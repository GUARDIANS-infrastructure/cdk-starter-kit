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
    Stack,
)
from constructs import Construct

EC2_ITYPE: str = "t2.medium"
EBS_GB: int = 100
REMS_LISTEN: int = 3000
HOSTED_ZONE: str = "test.biocommons.org.au"
REMS_DOMAIN: str = f"rems.{HOSTED_ZONE}"


class GdiStarterKitStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

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
            security_group=ec2_sg,
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

        # TLS certificate for the subdomain
        rems_cert = acm.Certificate(
            self,
            "RemsTLSCertificate",
            domain_name=REMS_DOMAIN,
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
        listener.add_target_groups("DefaultTargetGroup",
                                   target_groups=[atg_rems])

        # Add a routing rule for the domain
        listener.add_target_groups(
            "RemsDomainRule",
            priority=1,
            conditions=[elbv2.ListenerCondition.host_headers([REMS_DOMAIN])],
            target_groups=[atg_rems],
        )

        # Route 53 A Record for the Load Balancer
        route53.ARecord(
            self,
            "RemsAliasRecord",
            zone=hosted_zone,
            record_name=REMS_DOMAIN,
            target=route53.RecordTarget.from_alias(targets.LoadBalancerTarget(alb)),
        )
