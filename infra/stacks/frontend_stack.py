from aws_cdk import (
    Stack,
    CfnOutput,
    RemovalPolicy,
    Size,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_cloudfront as cloudfront,
)
from constructs import Construct


class FrontendStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        project_name: str,
        env_name: str,
        distribution: cloudfront.Distribution,
        bucket: s3.Bucket,
        tags: dict,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        s3deploy.BucketDeployment(
            self,
            "FrontendDeployment",
            sources=[s3deploy.Source.asset("../frontend/dist")],
            destination_bucket=bucket,
            distribution=distribution,
            distribution_paths=["/*"],
            memory_limit=1024,
            ephemeral_storage_size=Size.mebibytes(512),
        )

        CfnOutput(self, "FrontendURL", value=f"https://{distribution.distribution_domain_name}", export_name=f"{project_name}-frontend-url")