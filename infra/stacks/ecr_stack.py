import aws_cdk as cdk
from aws_cdk import (
    Stack,
    CfnOutput,
    RemovalPolicy,
    aws_ecr as ecr,
)
from constructs import Construct


class EcrStack(Stack):
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

        self.repository = ecr.Repository(
            self,
            "ECRRepository",
            repository_name=f"{project_name}-backend-{env_name}",
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_images=False,
            image_scan_on_push=True,
        )

        CfnOutput(self, "RepositoryUri", value=self.repository.repository_uri, export_name=f"{project_name}-ecr-uri")
        CfnOutput(self, "RepositoryName", value=self.repository.repository_name, export_name=f"{project_name}-ecr-name")
        CfnOutput(self, "RepositoryArn", value=self.repository.repository_arn, export_name=f"{project_name}-ecr-arn")

        for key, value in tags.items():
            cdk.Tags.of(self).add(key, value)