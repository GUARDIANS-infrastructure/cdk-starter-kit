import os.path

from aws_cdk import (
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_ssm as ssm,
    aws_elasticloadbalancing as elb,
    aws_certificatemanager as acm,
    aws_route53 as route53,
    aws_route53_targets as targets,
    aws_s3_assets as assets,
    Size,
    Stack,
)
from constructs import Construct

EC2_ITYPE: str = "t2.medium"
EBS_GB: int = 100
REMS_LISTEN: int = 3000
HOSTED_ZONE: str = "test.biocommons.org.au"
S3_ASSETS: str = "hgi-rems-assets"
REMS_DOMAIN: str = f"rems.{HOSTED_ZONE}"


class GdiStarterKitStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # VPC
        vpc = ec2.Vpc(self, "VPC", max_azs=2, nat_gateways=1)

        # Security Group for EC2
        ec2_security_group = ec2.SecurityGroup(
            self,
            "EC2SecurityGroup",
            vpc=vpc,
            security_group_name="rems-ec2-sg",
            description=f"Allow traffic on port {REMS_LISTEN}",
            allow_all_outbound=True,
        )
        ec2_security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(REMS_LISTEN),
            f"Allow traffic on port {REMS_LISTEN}",
        )

        # IAM Role for SSM
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

        # EC2 Instance
        instance = ec2.Instance(
            self,
            "RemsInstance",
            instance_type=ec2.InstanceType(EC2_ITYPE),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            vpc=vpc,
            security_group=ec2_security_group,
            role=role,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda", volume=ec2.BlockDeviceVolume.ebs(EBS_GB)
                )
            ],
        )

        # SSM Parameter to store instance ID
        ssm.StringParameter(
            self,
            "RemsInstanceId",
            parameter_name="/Rems/InstanceId",
            string_value=instance.instance_id,
        )

        # To request a certificate that gets automatically approved based on DNS
        # (i.e. proof that we own the domain), look up the current HostedZone and
        # reference it in the from_dns() validation call when creating the cert:

        # Route 53 Hosted Zone
        hosted_zone = route53.HostedZone.from_lookup(
            self, "HostedZone", domain_name=HOSTED_ZONE
        )

        # TLS certificate
        certificate = acm.Certificate(
            self,
            "TLSCertificate",
            domain_name=REMS_DOMAIN,
            validation=acm.CertificateValidation.from_dns(hosted_zone),
        )

        # Classic Load Balancer
        # We use a load balancer — even though we've only got a single EC2
        # instance behind it — for the convenience of being able to attach
        # our ACM-issued TLS certificate here instead of having to deploy
        # it manually on instances. And we use a Classic LB because the
        # latest Application LBs require you to have the extra layer of
        # an AutoScaling group as the target rather than bare instances.
        load_balancer = elb.LoadBalancer(
            self,
            "RemsELB",
            vpc=vpc,
            internet_facing=True,
            health_check=elb.HealthCheck(port=REMS_LISTEN),
            listeners=[
                elb.LoadBalancerListener(external_port=80, internal_port=REMS_LISTEN),
                elb.LoadBalancerListener(
                    external_port=443,
                    internal_port=REMS_LISTEN,
                    ssl_certificate_arn=certificate.certificate_arn,
                ),
            ],
        )
        load_balancer.add_target(elb.InstanceTarget(instance))

        # Route 53 A Record for the Load Balancer
        route53.ARecord(
            self,
            "AliasRecord",
            zone=hosted_zone,
            target=route53.RecordTarget.from_alias(
                targets.ClassicLoadBalancerTarget(load_balancer)
            ),
            record_name=REMS_DOMAIN,
        )
