import aws_cdk as cdk
from aws_cdk import (
    Stack,
    CfnOutput,
    Duration,
    aws_logs as logs,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_sns as sns,
    aws_sns_subscriptions as subs,
)
from constructs import Construct


class ObservabilityStack(Stack):
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

        self.log_group = logs.LogGroup(
            self,
            "LogGroup",
            log_group_name=f"/ecs/{project_name}-{env_name}",
            retention=logs.RetentionDays.ONE_MONTH if env_name == "dev" else logs.RetentionDays.THREE_MONTHS,
            removal_policy=cdk.RemovalPolicy.DESTROY if env_name == "dev" else cdk.RemovalPolicy.RETAIN,
        )

        alarm_topic = sns.Topic(
            self,
            "AlarmTopic",
            topic_name=f"{project_name}-alarms-{env_name}",
            display_name=f"{project_name} Alarms ({env_name})",
        )

        alarm_topic.add_subscription(subs.EmailSubscription("alerts@example.com"))

        dashboard = cloudwatch.Dashboard(
            self,
            "Dashboard",
            dashboard_name=f"{project_name}-{env_name}",
            widgets=[
                [
                    cloudwatch.GraphWidget(
                        title="ECS Service Metrics",
                        left=[
                            cloudwatch.Metric(
                                namespace="AWS/ECS",
                                metric_name="CPUUtilization",
                                dimensions_map={"ClusterName": f"{project_name}-cluster-{env_name}", "ServiceName": f"{project_name}-backend-{env_name}"},
                                statistic="Average",
                                period=Duration.minutes(5),
                            ),
                            cloudwatch.Metric(
                                namespace="AWS/ECS",
                                metric_name="MemoryUtilization",
                                dimensions_map={"ClusterName": f"{project_name}-cluster-{env_name}", "ServiceName": f"{project_name}-backend-{env_name}"},
                                statistic="Average",
                                period=Duration.minutes(5),
                            ),
                        ],
                        width=12,
                        height=6,
                    ),
                    cloudwatch.GraphWidget(
                        title="ALB Metrics",
                        left=[
                            cloudwatch.Metric(
                                namespace="AWS/ApplicationELB",
                                metric_name="RequestCount",
                                dimensions_map={"LoadBalancer": f"{project_name}-alb-{env_name}"},
                                statistic="Sum",
                                period=Duration.minutes(5),
                            ),
                            cloudwatch.Metric(
                                namespace="AWS/ApplicationELB",
                                metric_name="TargetResponseTime",
                                dimensions_map={"LoadBalancer": f"{project_name}-alb-{env_name}"},
                                statistic="Average",
                                period=Duration.minutes(5),
                            ),
                        ],
                        width=12,
                        height=6,
                    ),
                ],
                [
                    cloudwatch.GraphWidget(
                        title="Voice Agent Custom Metrics",
                        left=[
                            cloudwatch.Metric(
                                namespace=f"{project_name}/{env_name}",
                                metric_name="active_websocket_connections",
                                statistic="Average",
                                period=Duration.minutes(1),
                            ),
                            cloudwatch.Metric(
                                namespace=f"{project_name}/{env_name}",
                                metric_name="voice_sessions_started",
                                statistic="Sum",
                                period=Duration.minutes(5),
                            ),
                            cloudwatch.Metric(
                                namespace=f"{project_name}/{env_name}",
                                metric_name="voice_sessions_completed",
                                statistic="Sum",
                                period=Duration.minutes(5),
                            ),
                            cloudwatch.Metric(
                                namespace=f"{project_name}/{env_name}",
                                metric_name="voice_sessions_failed",
                                statistic="Sum",
                                period=Duration.minutes(5),
                            ),
                        ],
                        width=12,
                        height=6,
                    ),
                    cloudwatch.GraphWidget(
                        title="Nova Sonic Metrics",
                        left=[
                            cloudwatch.Metric(
                                namespace=f"{project_name}/{env_name}",
                                metric_name="time_to_first_audio_ms",
                                statistic="Average",
                                period=Duration.minutes(5),
                            ),
                            cloudwatch.Metric(
                                namespace=f"{project_name}/{env_name}",
                                metric_name="nova_connection_errors",
                                statistic="Sum",
                                period=Duration.minutes(5),
                            ),
                            cloudwatch.Metric(
                                namespace=f"{project_name}/{env_name}",
                                metric_name="nova_session_renewals",
                                statistic="Sum",
                                period=Duration.minutes(5),
                            ),
                        ],
                        width=12,
                        height=6,
                    ),
                ],
            ],
        )

        ecs_cpu_alarm = cloudwatch.Alarm(
            self,
            "ECSCPUHighAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/ECS",
                metric_name="CPUUtilization",
                dimensions_map={"ClusterName": f"{project_name}-cluster-{env_name}", "ServiceName": f"{project_name}-backend-{env_name}"},
                statistic="Average",
                period=Duration.minutes(5),
            ),
            threshold=80,
            evaluation_periods=3,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            alarm_name=f"{project_name}-ecs-cpu-high-{env_name}",
            alarm_description="ECS CPU utilization is high",
        )
        ecs_cpu_alarm.add_alarm_action(cw_actions.SnsAction(alarm_topic))

        alb_5xx_alarm = cloudwatch.Alarm(
            self,
            "ALB5xxAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/ApplicationELB",
                metric_name="HTTPCode_Target_5XX_Count",
                dimensions_map={"LoadBalancer": f"{project_name}-alb-{env_name}"},
                statistic="Sum",
                period=Duration.minutes(5),
            ),
            threshold=10,
            evaluation_periods=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            alarm_name=f"{project_name}-alb-5xx-{env_name}",
            alarm_description="ALB returning 5xx errors",
        )
        alb_5xx_alarm.add_alarm_action(cw_actions.SnsAction(alarm_topic))

        ecs_unhealthy_alarm = cloudwatch.Alarm(
            self,
            "ECSUnhealthyAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/ECS",
                metric_name="RunningTaskCount",
                dimensions_map={"ClusterName": f"{project_name}-cluster-{env_name}", "ServiceName": f"{project_name}-backend-{env_name}"},
                statistic="Average",
                period=Duration.minutes(5),
            ),
            threshold=1,
            evaluation_periods=3,
            comparison_operator=cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
            alarm_name=f"{project_name}-ecs-unhealthy-{env_name}",
            alarm_description="ECS service has unhealthy tasks",
        )
        ecs_unhealthy_alarm.add_alarm_action(cw_actions.SnsAction(alarm_topic))

        CfnOutput(self, "LogGroupName", value=self.log_group.log_group_name, export_name=f"{project_name}-log-group")
        CfnOutput(self, "DashboardName", value=dashboard.dashboard_name, export_name=f"{project_name}-dashboard")