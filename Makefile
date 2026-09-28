.PHONY: install dev test build deploy deploy-frontend destroy clean help

AWS_REGION ?= us-east-1
CDK_DEFAULT_REGION ?= us-east-1
CDK_DEFAULT_ACCOUNT ?= $(shell aws sts get-caller-identity --query Account --output text)
FRONTEND_BUCKET ?= nova-voice-agent-frontend-dev-$(CDK_DEFAULT_ACCOUNT)
CLOUDFRONT_DIST_ID ?= E2K2B8FTSXFZM5

help:
	@echo "Available commands:"
	@echo "  make install     - Install all dependencies"
	@echo "  make dev         - Start local development environment"
	@echo "  make test        - Run all tests"
	@echo "  make build       - Build Docker images"
	@echo "  make deploy      - Deploy to AWS"
	@echo "  make deploy-frontend - Rebuild + sync frontend to S3 + CloudFront invalidation"
	@echo "  make destroy     - Destroy AWS resources (requires confirmation)"
	@echo "  make clean       - Clean build artifacts"
	@echo "  make logs        - View ECS logs"
	@echo "  make status      - Check deployment status"

install:
	@echo "Installing backend dependencies..."
	cd backend && pip install -e ".[dev]"
	@echo "Installing frontend dependencies..."
	cd frontend && npm ci
	@echo "Installing CDK dependencies..."
	cd infra && pip install -r requirements.txt

dev:
	@echo "Starting development environment..."
	docker-compose up --build

test:
	@echo "Running backend tests..."
	cd backend && python -m pytest -v --tb=short
	@echo "Running frontend lint..."
	cd frontend && npm run lint
	@echo "Running frontend unit tests..."
	cd frontend && npm run test

build:
	@echo "Building backend image..."
	docker build -t nova-voice-agent-backend:latest ./backend
	@echo "Building frontend image..."
	docker build -t nova-voice-agent-frontend:latest ./frontend

deploy: build
	@echo "Deploying to AWS..."
	@echo "Account: $(CDK_DEFAULT_ACCOUNT)"
	@echo "Region: $(CDK_DEFAULT_REGION)"
	cd infra && cdk deploy --all --require-approval never

deploy-frontend:
	@echo "Building frontend..."
	cd frontend && npm run build
	@echo "Syncing to S3 with cache headers..."
	aws s3 sync frontend/dist/ s3://$(FRONTEND_BUCKET) --delete \
		--cache-control "public,max-age=31536000,immutable" \
		--exclude "index.html" \
		--exclude "capture-worklet.js" \
		--exclude "playback-worklet.js"
	aws s3 cp frontend/dist/index.html s3://$(FRONTEND_BUCKET)/index.html \
		--cache-control "no-cache, no-store, must-revalidate" \
		--content-type "text/html; charset=utf-8" \
		--metadata-directive REPLACE
	aws s3 cp frontend/dist/capture-worklet.js s3://$(FRONTEND_BUCKET)/capture-worklet.js \
		--cache-control "no-cache" --content-type "application/javascript" --metadata-directive REPLACE
	aws s3 cp frontend/dist/playback-worklet.js s3://$(FRONTEND_BUCKET)/playback-worklet.js \
		--cache-control "no-cache" --content-type "application/javascript" --metadata-directive REPLACE
	aws cloudfront create-invalidation --distribution-id $(CLOUDFRONT_DIST_ID) --paths "/*"

destroy:
	@echo "WARNING: This will destroy ALL resources created by this project!"
	@echo "Type 'YES' to confirm:"
	@read -r confirm && [ "$$confirm" = "YES" ] || (echo "Aborted." && exit 1)
	cd infra && cdk destroy --all --force

clean:
	@echo "Cleaning build artifacts..."
	rm -rf backend/__pycache__ backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache
	rm -rf frontend/dist frontend/node_modules
	rm -rf infra/cdk.out
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

logs:
	aws logs tail /ecs/nova-voice-agent-dev --follow --region $(AWS_REGION)

status:
	@echo "Checking ECS service status..."
	aws ecs describe-services --cluster nova-voice-agent-cluster-dev --services nova-voice-agent-backend-dev --region $(AWS_REGION) --query 'services[0].{Status:status,Running:runningCount,Desired:desiredCount}' --output table
	@echo ""
	@echo "Checking ALB health..."
	aws elbv2 describe-target-health --target-group-arn $(shell aws elbv2 describe-target-groups --names nova-voice-agent-tg-dev --region $(AWS_REGION) --query 'TargetGroups[0].TargetGroupArn' --output text) --region $(AWS_REGION) --query 'TargetHealthDescriptions[].{Target:Target.Id,Health:TargetHealth.State}' --output table

cdk-synth:
	cd infra && cdk synth

cdk-diff:
	cd infra && cdk diff

cdk-bootstrap:
	cdk bootstrap aws://$(CDK_DEFAULT_ACCOUNT)/$(CDK_DEFAULT_REGION)

backend-shell:
	docker-compose exec backend bash

frontend-shell:
	docker-compose exec frontend sh

lint:
	cd backend && ruff check .
	cd frontend && npm run lint

format:
	cd backend && ruff format .
	cd frontend && npx prettier --write .
