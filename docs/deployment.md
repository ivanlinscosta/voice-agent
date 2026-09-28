# Deployment Guide

## Prerequisites

1. AWS CLI configured with appropriate permissions
2. Node.js 20+ and npm
3. Python 3.12+
4. Docker
5. AWS CDK v2 (`npm install -g aws-cdk`)
6. Bedrock model access for `amazon.nova-2-sonic-v1:0` in us-east-1

## Enable Bedrock Model Access

1. Go to AWS Bedrock Console → Model access
2. Request access to "Amazon Nova 2 Sonic"
3. Wait for approval (usually instant for Nova models)

## Local Development

```bash
# Clone repository
cd voice-agent

# Install dependencies
make install

# Configure environment
cp .env.example .env
# Edit .env with your values

# Start local development (requires AWS credentials)
make dev

# Frontend: http://localhost:5173
# Backend:  http://localhost:8000
# WebSocket: ws://localhost:8000/ws/voice
```

## AWS Deployment

### 1. Bootstrap CDK (first time only)

```bash
cdk bootstrap aws://ACCOUNT-ID/us-east-1
# Or use Makefile:
make cdk-bootstrap
```

### 2. Deploy

```bash
# Full deployment
make deploy

# Or step by step:
cd infra
cdk deploy --all
```

### 3. Verify Deployment

```bash
# Check ECS service status
make status

# View logs
make logs

# Get frontend URL
aws cloudformation describe-stacks --stack-name nova-voice-agent-frontend-dev --query 'Stacks[0].Outputs[?OutputKey==`FrontendURL`].OutputValue' --output text
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| AWS_REGION | AWS region | us-east-1 |
| NOVA_MODEL_ID | Bedrock model ID | amazon.nova-2-sonic-v1:0 |
| APP_ENV | Environment (dev/prod) | dev |
| LOG_LEVEL | Log level | INFO |
| VOICE_SYSTEM_PROMPT | System prompt for Nova | (Portuguese prompt) |
| INPUT_SAMPLE_RATE | Audio input sample rate | 16000 |
| OUTPUT_SAMPLE_RATE | Audio output sample rate | 24000 |
| NOVA_TEMPERATURE | Model temperature | 0.7 |

### Production Settings

For production, update these in `.env` or CDK context:

```bash
APP_ENV=prod
# CDK will use 2 NAT Gateways, desired_count=2 for ECS
```

## Frontend Deployment

The frontend is automatically built and deployed to S3 via CDK. To manually deploy:

```bash
cd frontend
npm run build
aws s3 sync dist/ s3://nova-voice-agent-frontend-{env}-{account} --delete
aws cloudfront create-invalidation --distribution-id {dist-id} --paths "/*"
```

## Updating Backend

```bash
# Build and push new image
cd backend
docker build -t nova-voice-agent-backend:latest .
docker tag nova-voice-agent-backend:latest {account}.dkr.ecr.{region}.amazonaws.com/nova-voice-agent-backend-{env}:latest
docker push {account}.dkr.ecr.{region}.amazonaws.com/nova-voice-agent-backend-{env}:latest

# Force new deployment
aws ecs update-service --cluster nova-voice-agent-cluster-{env} --service nova-voice-agent-backend-{env} --force-new-deployment
```

## Monitoring

### CloudWatch Dashboards

- Dashboard: `nova-voice-agent-{env}`
- Key metrics: active connections, session counts, latency percentiles, Nova errors

### Alarms

- ECS CPU > 80% for 3 periods
- ALB 5xx errors > 10 in 5 minutes
- ECS running tasks < 1 for 3 periods

### Logs

```bash
# Follow backend logs
aws logs tail /ecs/nova-voice-agent-backend-{env} --follow

# Query logs
aws logs filter-log-events --log-group-name /ecs/nova-voice-agent-backend-{env} --filter-pattern "ERROR"
```

## Troubleshooting Deployment

### CDK Deploy Fails

1. Check CloudFormation events: `aws cloudformation describe-stack-events --stack-name {stack-name}`
2. Common issues:
   - Insufficient permissions → Add required IAM policies
   - Resource limits → Request quota increase
   - VPC CIDR conflicts → Use different CIDR

### ECS Service Not Starting

1. Check task logs: `make logs`
2. Common issues:
   - Image pull failure → Check ECR permissions
   - Health check failing → Verify `/health` endpoint
   - Bedrock access denied → Verify model access in console

### Frontend Not Loading

1. Check CloudFront distribution status
2. Verify S3 bucket has objects
3. Check OAC configuration
4. Verify cache behaviors for `/api/*` and `/ws/*`

## Rollback

```bash
# Rollback ECS service
aws ecs update-service --cluster nova-voice-agent-cluster-{env} --service nova-voice-agent-backend-{env} --task-definition {previous-task-def-arn}

# Rollback CloudFront
aws cloudfront create-invalidation --distribution-id {dist-id} --paths "/*"
```

## Destroy

```bash
# Requires explicit confirmation
make destroy

# Or manually:
cd infra
cdk destroy --all --force
```