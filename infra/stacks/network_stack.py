import aws_cdk as cdk
from aws_cdk import (
    Stack,
    CfnOutput,
    Duration,
    aws_ec2 as ec2,
    aws_elasticloadbalancingv2 as elbv2,
    aws_route53 as route53,
)
from constructs import Construct


class NetworkStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        project_name: str,
        env_name: str,
        tags: dict,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        nat_gateways = 1 if env_name == "dev" else 2

        self.vpc = ec2.Vpc(
            self,
            "VPC",
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
            max_azs=2,
            nat_gateways=nat_gateways,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
            enable_dns_hostnames=True,
            enable_dns_support=True,
        )

        cdk.Tags.of(self.vpc).add("Name", f"{project_name}-vpc-{env_name}")

        self.alb_sg = ec2.SecurityGroup(
            self,
            "ALBSecurityGroup",
            vpc=self.vpc,
            description="Security group for ALB",
            allow_all_outbound=True,
        )
        self.alb_sg.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(80),
            "Allow HTTP from anywhere",
        )
        self.alb_sg.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(8080),
            "Allow WebSocket HTTP from anywhere",
        )

        self.ecs_sg = ec2.SecurityGroup(
            self,
            "ECSSecurityGroup",
            vpc=self.vpc,
            description="Security group for ECS tasks",
            allow_all_outbound=True,
        )
        self.ecs_sg.add_ingress_rule(
            self.alb_sg,
            ec2.Port.tcp(8000),
            "Allow traffic from ALB",
        )

        self.alb = elbv2.ApplicationLoadBalancer(
            self,
            "ALB",
            vpc=self.vpc,
            internet_facing=True,
            security_group=self.alb_sg,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            load_balancer_name=f"{project_name}-alb-{env_name}",
        )

        self.listener = self.alb.add_listener(
            "HTTPListener",
            port=80,
            protocol=elbv2.ApplicationProtocol.HTTP,
            default_action=elbv2.ListenerAction.fixed_response(
                404,
                content_type="application/json",
                message_body='{"error": "Not found"}',
            ),
        )

        self.target_group = elbv2.ApplicationTargetGroup(
            self,
            "TargetGroup",
            vpc=self.vpc,
            port=8000,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(
                path="/health",
                interval=Duration.seconds(30),
                timeout=Duration.seconds(10),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
            ),
            target_group_name=f"{project_name}-tg-{env_name}",
        )

        self.target_group.set_attribute("deregistration_delay.timeout_seconds", "60")
        self.target_group.set_attribute("stickiness.enabled", "false")

        self.listener.add_target_groups(
            "HealthTargetGroup",
            target_groups=[self.target_group],
            conditions=[elbv2.ListenerCondition.path_patterns(["/health"])],
            priority=5,
        )

        self.listener.add_target_groups(
            "APITargetGroup",
            target_groups=[self.target_group],
            conditions=[elbv2.ListenerCondition.path_patterns(["/api/*"])],
            priority=10,
        )

        self.listener.add_target_groups(
            "WSTargetGroup",
            target_groups=[self.target_group],
            conditions=[elbv2.ListenerCondition.path_patterns(["/ws/*"])],
            priority=15,
        )

        ws_listener = self.alb.add_listener(
            "WSListener",
            port=8080,
            protocol=elbv2.ApplicationProtocol.HTTP,
            default_action=elbv2.ListenerAction.forward([self.target_group]),
        )

        self.alb.set_attribute("idle_timeout.timeout_seconds", "600")

        CfnOutput(self, "VPCId", value=self.vpc.vpc_id, export_name=f"{project_name}-vpc-id")
        CfnOutput(self, "ALBDNSName", value=self.alb.load_balancer_dns_name, export_name=f"{project_name}-alb-dns")
        CfnOutput(self, "ALBArn", value=self.alb.load_balancer_arn, export_name=f"{project_name}-alb-arn")
        CfnOutput(self, "TargetGroupArn", value=self.target_group.target_group_arn, export_name=f"{project_name}-tg-arn")