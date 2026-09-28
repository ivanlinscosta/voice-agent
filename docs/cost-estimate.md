# Cost Estimate (USD, us-east-1, August 2025 pricing)

## Monthly Cost Breakdown

### Always-On Costs (incurred even with zero conversations)

| Component | Dev (1 NAT, 1 task) | Prod (2 NAT, 2 tasks) |
|-----------|---------------------|----------------------|
| **NAT Gateway** | $32.40 (1 × $0.045/hr × 720h) | $64.80 (2 × $0.045/hr × 720h) |
| **ALB** | $18.00 ($0.0225/hr × 720h) | $18.00 ($0.0225/hr × 720h) |
| **ALB LCU** | ~$5.00 (estimated) | ~$10.00 (estimated) |
| **ECS Fargate** | $14.60 (1 task × 0.5 vCPU/1GB × $0.04048/hr × 720h) | $29.20 (2 tasks) |
| **CloudWatch Logs** | $5.00 (5 GB ingestion + storage) | $15.00 (15 GB) |
| **CloudWatch Metrics** | $1.00 (10 custom metrics) | $3.00 (30 custom metrics) |
| **ECR** | $0.10 (1 GB storage) | $0.10 |
| **CloudFront** | $0.50 (first 10 TB free, then $0.085/GB) | $2.00 |
| **S3** | $0.05 (frontend assets) | $0.10 |
| **WAF** | $5.00 (1 Web ACL + 1M requests) | $5.00 |
| **Route 53** | $0.50 (hosted zone) | $0.50 |
| **Total Fixed** | **~$82.15/month** | **~$147.70/month** |

### Per-Conversation Costs (Nova 2 Sonic)

| Usage Level | Minutes/Month | Nova Cost | Data Transfer | Total Variable |
|-------------|---------------|-----------|---------------|----------------|
| **Low** | 500 min | $3.75 | $0.50 | **~$4.25** |
| **Moderate** | 5,000 min | $37.50 | $5.00 | **~$42.50** |
| **High** | 50,000 min | $375.00 | $50.00 | **~$425.00** |

**Nova 2 Sonic Pricing**: $0.0045 per minute (speech-to-speech)

### Total Monthly Estimates

| Usage Level | Dev Environment | Prod Environment |
|-------------|-----------------|------------------|
| **Low** (500 min) | **~$86** | **~$152** |
| **Moderate** (5,000 min) | **~$125** | **~$190** |
| **High** (50,000 min) | **~$507** | **~$573** |

## Cost Drivers

### Highest Fixed Costs
1. **NAT Gateway** - $32.40/month per gateway (major fixed cost)
2. **ALB** - $18.00/month base + LCU charges
3. **ECS Fargate** - Scales with task count and size

### Highest Variable Costs
1. **Nova 2 Sonic** - $0.0045/minute (primary variable cost)
2. **Data Transfer** - $0.01/GB (CloudFront + ALB)
3. **CloudWatch Logs** - $0.50/GB ingestion

## Cost Optimization

### For Development
- Use 1 NAT Gateway (save $32.40/month)
- Set ECS desired_count=1 (save $14.60/month)
- Reduce CloudWatch retention to 1 week
- Disable WAF in dev (save $5/month)
- **Estimated dev minimum: ~$40/month**

### For Production
- Use Fargate Spot (up to 70% savings on compute)
- Enable CloudFront caching for static assets
- Use CloudWatch Logs Insights sparingly
- Set up budget alarms at 80% of expected spend

### Nova 2 Sonic Optimization
- Keep conversations focused (shorter = cheaper)
- Use session renewal efficiently (avoids new session overhead)
- Monitor `time_to_first_audio_ms` - high latency may indicate retry loops

## Budget Alarm Example

```bash
# Create budget alarm at $100/month
aws budgets create-budget --account-id $ACCOUNT_ID --budget '{
  "BudgetName": "nova-voice-agent-monthly",
  "BudgetLimit": {"Amount": "100", "Unit": "USD"},
  "TimeUnit": "MONTHLY",
  "BudgetType": "COST",
  "CostFilters": {"TagKeyValue": ["Project$nova-voice-agent"]}
}'
```

## Pricing References

- [AWS Fargate Pricing](https://aws.amazon.com/fargate/pricing/)
- [ALB Pricing](https://aws.amazon.com/elasticloadbalancing/pricing/)
- [NAT Gateway Pricing](https://aws.amazon.com/vpc/pricing/)
- [CloudFront Pricing](https://aws.amazon.com/cloudfront/pricing/)
- [CloudWatch Pricing](https://aws.amazon.com/cloudwatch/pricing/)
- [Bedrock Pricing](https://aws.amazon.com/bedrock/pricing/)
- [WAF Pricing](https://aws.amazon.com/waf/pricing/)
- [S3 Pricing](https://aws.amazon.com/s3/pricing/)
- [ECR Pricing](https://aws.amazon.com/ecr/pricing/)

*Prices subject to change. Always verify current pricing in AWS Console before making financial decisions.*