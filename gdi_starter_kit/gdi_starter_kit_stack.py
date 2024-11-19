import os.path

from aws_cdk import (
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_ssm as ssm,
    aws_elasticloadbalancingv2 as elbv2,
    aws_elasticloadbalancingv2_targets as elbv2_targets,
    aws_certificatemanager as acm,
    aws_route53 as route53,
    aws_route53_targets as targets,
    aws_secretsmanager as secretsmanager,
    Stack,
)
from constructs import Construct

EC2_ITYPE: str = "t2.medium"
EBS_GB: int = 100
REMS_LISTEN: int = 3000


class GdiStarterKitStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # get runtime context - this can be specified in various places
        # https://docs.aws.amazon.com/cdk/v2/guide/context.html#context_construct
        # e.g.
        # * cdk deploy --context key=value
        # * in the context key of the project cdk.json file
        # * in the context key of the ~/.cdk.json file

        # Domain of a hosted zone you own and want to deploy to
        hz_domain = self.node.get_context("hz_domain")
        # Name of the secret in AWS Secrets Manager that stores OIDC RP config
        rems_oidc_sec_name = self.node.get_context("rems_oidc_sec_name")
        # Domain component to prefix to hz_domain to generate the public URL
        rems_domain_prefix = self.node.try_get_context("rems_domain_prefix") or "rems"
        rems_domain = f"{rems_domain_prefix}.{hz_domain}"
        rems_url = f"https://{rems_domain}/"  # <- requires trailing slash

        # SSM Parameters
        param_rems_oidc_sec_name = ssm.StringParameter(
            self,
            "RemsOidcSecName",
            parameter_name="/Rems/OidcSecName",
            string_value=rems_oidc_sec_name,
        )

        # AWS Secrets Manager Secrets
        oidc_sec = secretsmanager.Secret.from_secret_name_v2(
            self, "oidc_sec", rems_oidc_sec_name
        )

        # VPC
        vpc = ec2.Vpc(self, "VPC", max_azs=2, nat_gateways=1)

        # Security group for ALB
        alb_sg = ec2.SecurityGroup(
            self,
            "AlbSecurityGroup",
            vpc=vpc,
            description="Allow HTTPS access to ALB",
            allow_all_outbound=True,
        )
        alb_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), "Allow HTTPS")

        # Security group for EC2 instance
        ec2_sg = ec2.SecurityGroup(
            self,
            "Ec2SecurityGroup",
            vpc=vpc,
            description=f"Allow traffic from ALB on port {REMS_LISTEN}",
            allow_all_outbound=True,
        )
        ec2_sg.add_ingress_rule(
            alb_sg,
            ec2.Port.tcp(REMS_LISTEN),
            f"Allow ALB to access EC2 on port {REMS_LISTEN}",
        )

        # IAM Role with Systems Manager policy
        role = iam.Role(
            self,
            "RemsInstanceSSM",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
        )
        role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "AmazonSSMManagedInstanceCore"
            )
        )
        oidc_sec.grant_read(role)

        # EC2 Instance
        instance = ec2.Instance(
            self,
            "RemsInstance",
            instance_type=ec2.InstanceType(EC2_ITYPE),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_group=ec2_sg,
            role=role,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda", volume=ec2.BlockDeviceVolume.ebs(EBS_GB)
                )
            ],
            user_data=config_rems_host(
                param_rems_oidc_sec_name.parameter_name, rems_url
            ),
        )

        # To request a certificate that gets automatically approved based on DNS
        # (i.e. proof that we own the domain), look up the current HostedZone and
        # reference it in the from_dns() validation call when creating the cert:

        # Route 53 Hosted Zone
        hosted_zone = route53.HostedZone.from_lookup(
            self, "HostedZone", domain_name=hz_domain
        )

        # TLS certificate for the subdomain
        rems_cert = acm.Certificate(
            self,
            "RemsTLSCertificate",
            domain_name=rems_domain,
            validation=acm.CertificateValidation.from_dns(hosted_zone),
        )

        # Application Load Balancer
        alb = elbv2.ApplicationLoadBalancer(
            self, "GDI-ALB", vpc=vpc, internet_facing=True, security_group=alb_sg
        )

        # Add an HTTPS listener for TLS traffic
        listener = alb.add_listener(
            "HttpsListener", port=443, certificates=[rems_cert], open=True
        )

        # Create a target group for REMS
        atg_rems = elbv2.ApplicationTargetGroup(
            self,
            "RemsTargetGroup",
            vpc=vpc,
            port=REMS_LISTEN,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[
                elbv2_targets.InstanceIdTarget(instance.instance_id, port=REMS_LISTEN)
            ],
            health_check=elbv2.HealthCheck(port=f"{REMS_LISTEN}"),
        )

        # Add a default action (target group) to the listener
        listener.add_target_groups("DefaultTargetGroup", target_groups=[atg_rems])

        # Add a routing rule for the domain
        listener.add_target_groups(
            "RemsDomainRule",
            priority=1,
            conditions=[elbv2.ListenerCondition.host_headers([rems_domain])],
            target_groups=[atg_rems],
        )

        # Route 53 A Record for the Load Balancer
        route53.ARecord(
            self,
            "RemsAliasRecord",
            zone=hosted_zone,
            record_name=rems_domain,
            target=route53.RecordTarget.from_alias(targets.LoadBalancerTarget(alb)),
        )


def config_rems_host(param_rems_oidc_sec_name: str, rems_url: str) -> ec2.UserData:
    """
    As a prerequisite, the named AWS Secrets Manager entry (type: other) must
    exist and be configured with 3 key-value pairs:
        - 'oidc-metadata-url'
        - 'oidc-client-id'
        - 'oidc-client-secret'
    Passing only the secret name to the instance via SSM is for security.
    This is a bit clunky but avoids unwrapping secrets at CDK synthesis time.
    """
    user_data = ec2.UserData.for_linux()
    user_data.add_commands(
        # install necessaries
        r"""dnf update -y""",
        r"""dnf install -y git docker pwgen""",
        r"""systemctl enable docker""",
        r"""systemctl start docker""",
        r"""curl -L https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m) -o /usr/local/bin/docker-compose""",
        r"""chmod +x /usr/local/bin/docker-compose""",
        # install authlib for generate_jwks.py
        r"""curl -O https://bootstrap.pypa.io/get-pip.py""",
        r"""python3 get-pip.py""",
        r"""pip install authlib""",
        # clone the REMS repo
        r"""cd /opt""",
        r"""git clone https://github.com/GUARDIANS-infrastructure/starter-kit-rems""",
        r"""cd starter-kit-rems/""",
        # generate keys
        r"""python3 generate_jwks.py""",
        # fetch secrets and other deployment config; set as env vars.
        rf"""oidc_sec_name=$(aws ssm get-parameter --name "{param_rems_oidc_sec_name}" --query Parameter.Value --output text)""",
        r"oidc_config=$(aws secretsmanager get-secret-value --secret-id $oidc_sec_name --query SecretString --output text | jq .)",
        r"""export OIDC_METADATA_URL=$(jq -r '."oidc-metadata-url"' <<< $oidc_config)""",
        r"""export OIDC_CLIENT_ID=$(jq -r '."oidc-client-id"' <<< $oidc_config)""",
        r"""export OIDC_CLIENT_SECRET=$(jq -r '."oidc-client-secret"' <<< $oidc_config)""",
        r"""export DB_NAME=remsdb""",
        r"""export DB_USER=rems""",
        r"""export DB_PASSWORD=$(pwgen)""",
        rf"""export PUBLIC_URL={rems_url}""",
        # configure the application
        r"""for cfgfile in config.edn docker-compose.yml; do""",
        r"""	tmpfile=$(mktemp)""",
        r"""	\cp -f --preserve=all --attributes-only $cfgfile $tmpfile""",
        r"""	envsubst < $cfgfile > $tmpfile""",
        r"""	\mv -f $tmpfile $cfgfile""",
        r"""done""",
        # start the first time
        r"""docker-compose up -d db""",
        r"""docker-compose run --rm -e CMD="migrate" app""",
        r"""docker-compose up -d app""",
    )
    return user_data
