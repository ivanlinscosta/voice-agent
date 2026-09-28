#!/usr/bin/env python3
import os
import aws_cdk as cdk
from stacks.network_stack import NetworkStack
from stacks.ecr_stack import EcrStack
from stacks.backend_stack import BackendStack
from stacks.frontend_stack import FrontendStack
from stacks.observability_stack import ObservabilityStack

app = cdk.App()

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT") or os.environ.get("AWS_ACCOUNT_ID"),
    region=os.environ.get("CDK_DEFAULT_REGION") or os.environ.get("AWS_REGION", "us-east-1"),
)

project_name = "nova-voice-agent"
env_name = os.environ.get("APP_ENV", "dev")

tags = {
    "Project": project_name,
    "Environment": env_name,
    "ManagedBy": "CDK",
}

network_stack = NetworkStack(
    app,
    f"{project_name}-network-{env_name}",
    env=env,
    project_name=project_name,
    env_name=env_name,
    tags=tags,
)

observability_stack = ObservabilityStack(
    app,
    f"{project_name}-observability-{env_name}",
    env=env,
    project_name=project_name,
    env_name=env_name,
    tags=tags,
)

ecr_stack = EcrStack(
    app,
    f"{project_name}-ecr-{env_name}",
    env=env,
    project_name=project_name,
    env_name=env_name,
    tags=tags,
)

backend_stack = BackendStack(
    app,
    f"{project_name}-backend-{env_name}",
    env=env,
    project_name=project_name,
    env_name=env_name,
    vpc=network_stack.vpc,
    ecs_sg=network_stack.ecs_sg,
    alb=network_stack.alb,
    listener=network_stack.listener,
    target_group=network_stack.target_group,
    repository=ecr_stack.repository,
    log_group=observability_stack.log_group,
    tags=tags,
)

frontend_stack = FrontendStack(
    app,
    f"{project_name}-frontend-{env_name}",
    env=env,
    project_name=project_name,
    env_name=env_name,
    distribution=backend_stack.distribution,
    bucket=backend_stack.bucket,
    tags=tags,
)

for stack in [network_stack, observability_stack, ecr_stack, backend_stack, frontend_stack]:
    for key, value in tags.items():
        cdk.Tags.of(stack).add(key, value)

app.synth()