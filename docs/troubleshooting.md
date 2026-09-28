# Troubleshooting Guide

## Audio Issues

### Microphone Not Working

**Symptoms**: No audio input, "Ouvindo" status but no transcripts

**Causes & Solutions**:
1. **Browser permissions**: Check site settings → Microphone → Allow
2. **HTTPS required**: AudioWorklet requires secure context (HTTPS or localhost)
3. **Wrong sample rate**: Ensure AudioContext created with `sampleRate: 16000`
4. **AudioContext suspended**: Call `audioContext.resume()` after user interaction

### No Audio Output

**Symptoms**: Transcripts appear but no sound

**Causes & Solutions**:
1. **AudioContext suspended**: Browser auto-play policy - must resume after user gesture
2. **Sample rate mismatch**: Playback AudioContext must be 24000 Hz
3. **Worklet not loaded**: Check network tab for `playback-worklet.js` 404
4. **Ring buffer empty**: Check WebSocket binary frames arriving

### Choppy/Delayed Audio

**Symptoms**: Audio cuts out, high latency, robotic sound

**Causes & Solutions**:
1. **Network latency**: Check CloudFront edge location proximity
2. **Buffer underrun**: Increase `bufferSeconds` in playback worklet (default 10s)
3. **Frame size too large**: Reduce frame duration (30ms recommended)
4. **CPU throttling**: Check ECS CPU utilization

## Connection Issues

### WebSocket Fails to Connect

**Symptoms**: "Conectando..." stuck, then "Erro"

**Causes & Solutions**:
1. **Wrong WebSocket URL**: Check `VITE_WS_URL` environment variable
2. **ALB idle timeout**: Must be 300+ seconds for long conversations
3. **CloudFront WebSocket support**: Verify cache behaviors for `/ws/*` have caching disabled
4. **Cognito token expired**: Re-authenticate to get fresh token

### Frequent Disconnections

**Symptoms**: Session drops after 30-60 seconds

**Causes & Solutions**:
1. **ALB idle timeout**: Increase to 300s (default 60s)
2. **ECS health check failing**: Ensure `/health` returns 200 OK quickly
3. **Nova session expired**: Check session renewal logic (6 min threshold)
4. **Network instability**: Implement client-side reconnection with backoff

## Nova Sonic Issues

### "Model not found" or Access Denied

**Symptoms**: Backend logs show Bedrock access errors

**Solutions**:
1. Verify model access in Bedrock Console → Model access
2. Check IAM Task Role has `bedrock:InvokeModelWithBidirectionalStream` permission
3. Confirm region is `us-east-1` (Nova 2 Sonic only available there)

### Session Not Renewing

**Symptoms**: Conversation dies after ~8 minutes

**Solutions**:
1. Check `NOVA_SESSION_RENEWAL_THRESHOLD_SECONDS` (default 360 = 6 min)
2. Verify renewal task is running in backend
3. Check logs for "session_renewal_triggered" and "nova_session_renewal_completed"

### High Latency

**Symptoms**: >2 second delay between speaking and hearing response

**Optimization**:
1. Use CloudFront edge cache for frontend (already configured)
2. Ensure ALB and ECS in same AZ (use `az` placement strategy)
3. Monitor metrics: `time_to_first_audio_ms`, `backend_to_bedrock_latency_ms`
4. Consider provisioned concurrency for Bedrock (if available)

## Infrastructure Issues

### CDK Deploy Fails

**Error**: "Resource already exists"
```bash
# Check if resource was created outside CDK
aws cloudformation list-stack-resources --stack-name {stack-name}
# Or delete manually and re-deploy
```

**Error**: "Insufficient permissions"
```bash
# Required permissions for deployment:
# - CloudFormation, EC2, ECS, ECR, ELBv2, CloudFront, S3, IAM, Logs, WAF, ACM, Route53
# Use AdministratorAccess for initial setup, then scope down
```

### ECS Tasks Not Starting

**Check**:
```bash
# Describe service
aws ecs describe-services --cluster nova-voice-agent-cluster-dev --services nova-voice-agent-backend-dev

# Check task definition
aws ecs describe-task-definition --task-definition nova-voice-agent-backend-dev

# Check task logs
aws logs tail /ecs/nova-voice-agent-backend-dev --follow
```

### CloudFront 403/404

**Causes**:
1. OAC not configured correctly → Verify bucket policy allows CloudFront OAC
2. Default root object not set → Should be `index.html`
3. Cache behavior mismatch → Check `/api/*` and `/ws/*` point to ALB origin

## Debugging Commands

### Backend Logs
```bash
# Follow logs
make logs

# Filter for errors
aws logs filter-log-events --log-group-name /ecs/nova-voice-agent-backend-dev --filter-pattern "ERROR"

# Filter for session events
aws logs filter-log-events --log-group-name /ecs/nova-voice-agent-backend-dev --filter-pattern "session"
```

### Network Connectivity
```bash
# Test ALB health
curl -v https://{alb-dns}/health

# Test WebSocket
wscat -c wss://{cloudfront-domain}/ws/voice

# Check DNS
dig {cloudfront-domain}
```

### Metrics
```bash
# Get custom metrics
aws cloudwatch get-metric-statistics \
  --namespace nova-voice-agent/dev \
  --metric-name active_websocket_connections \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 --statistics Average
```

## Common Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| `Microphone access denied` | Browser permission | Allow in site settings |
| `AudioContext suspended` | Auto-play policy | Call `resume()` after user click |
| `WebSocket connection failed` | Network/Config | Check ALB, CloudFront, Security Groups |
| `Bedrock AccessDenied` | IAM/Model access | Enable model access, fix Task Role |
| `Session renewal failed` | Timeout/Logic | Check renewal threshold, logs |
| `ECS task stopped` | Health check fail | Fix `/health` endpoint, increase start period |

## Getting Help

1. Check CloudWatch Logs for detailed error messages
2. Review CloudWatch Metrics for system health
3. Enable debug logging: `LOG_LEVEL=DEBUG`
4. Check AWS Service Health Dashboard for regional issues