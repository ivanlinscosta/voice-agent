# Architecture Decision Records

## ADR-001: Use Nova 2 Sonic Speech-to-Speech (not Transcribe + LLM + Polly)

**Date**: 2024
**Status**: Accepted

**Context**: Need real-time voice conversation with low latency.

**Decision**: Use Amazon Nova 2 Sonic native speech-to-speech via `InvokeModelWithBidirectionalStream`.

**Reasoning**:
- True streaming: audio in → audio out without intermediate text
- Lower latency: ~500ms vs 2-3s for cascaded pipeline
- Natural turn-taking: built-in barge-in/interruption handling
- Simpler architecture: single model, single API call
- Cost effective: single model pricing vs three services

**Consequences**:
- Limited to us-east-1 region (Nova 2 Sonic availability)
- 8-minute session limit requires renewal logic
- Less control over ASR/TTS separately

---

## ADR-002: AudioWorklet over ScriptProcessorNode

**Date**: 2024
**Status**: Accepted

**Context**: Need low-latency audio capture and playback in browser.

**Decision**: Use AudioWorklet API with ScriptProcessorNode fallback.

**Reasoning**:
- AudioWorklet runs on audio thread (not main thread) → no jitter
- ScriptProcessorNode deprecated but needed for WebView/iOS Safari compatibility
- Worklets enable resampling in-worklet (16kHz↔44.1/48kHz)
- Transferable ArrayBuffers avoid copy overhead

**Consequences**:
- Requires COOP/COEP headers for SharedArrayBuffer (if used)
- More complex than MediaRecorder API
- Must handle AudioContext suspension (autoplay policy)

---

## ADR-003: WebSocket Binary Frames (not base64 JSON)

**Date**: 2024
**Status**: Accepted

**Context**: Streaming audio between browser and backend.

**Decision**: Use WebSocket binary frames for audio, JSON for control messages.

**Reasoning**:
- 33% smaller than base64 encoding
- Lower CPU (no encode/decode)
- Native browser support for ArrayBuffer/Blob
- Backend can forward directly to Bedrock

**Consequences**:
- Must handle mixed text/binary messages
- Debugging harder (can't read in network tab easily)
- Proxy/load balancer must support binary WebSocket frames

---

## ADR-004: ECS Fargate over Lambda for Backend

**Date**: 2024
**Status**: Accepted

**Context**: Backend needs persistent WebSocket connections and Bedrock bidirectional stream.

**Decision**: Use ECS Fargate with Application Load Balancer.

**Reasoning**:
- Lambda: 15-min max, no persistent connections, cold starts
- Fargate: Long-running tasks, WebSocket support, no cold starts
- ALB: Native WebSocket support, health checks, auto-scaling
- Fargate Spot available for cost savings

**Consequences**:
- Higher baseline cost (~$15/month minimum vs near-zero for Lambda)
- More infrastructure to manage
- Container build/deploy pipeline needed

---

## ADR-005: CloudFront + S3 (OAC) for Frontend Hosting

**Date**: 2024
**Status**: Accepted

**Context**: Serve React SPA with HTTPS, custom domain, WAF.

**Decision**: CloudFront distribution with S3 origin using Origin Access Control.

**Reasoning**:
- S3 bucket stays private (Block Public Access)
- OAC more secure than legacy OAI
- CloudFront provides HTTPS, caching, WAF integration
- Single domain for frontend + API + WebSocket
- Price Class All for global low latency

**Consequences**:
- Cache invalidation needed on deploy (~$0.005 per 1000 paths)
- 404→200 rewrite for SPA routing
- Additional CloudFront cost vs S3 static website hosting

---

## ADR-006: Session Renewal at 6 Minutes (not 8)

**Date**: 2024
**Status**: Accepted

**Context**: Nova 2 Sonic sessions expire at ~8 minutes.

**Decision**: Start renewal process at 6 minutes (configurable threshold).

**Reasoning**:
- 2-minute buffer for renewal process
- Renewal requires: detect assistant speech → buffer user audio → create new session → transfer history
- Buffer size: 10 seconds of user audio during transition
- Prevents conversation dropping mid-sentence

**Consequences**:
- Slightly more Nova sessions (more cost)
- Complexity in chat history transfer
- Must handle renewal failures gracefully

---

## ADR-007: Least-Privilege IAM for ECS Task Role

**Date**: 2024
**Status**: Accepted

**Context**: Backend needs Bedrock access only.

**Decision**: Task Role with only `bedrock:InvokeModelWithBidirectionalStream` on Nova 2 Sonic ARN.

**Reasoning**:
- Security best practice
- No AdministratorAccess or broad Bedrock permissions
- Separate Execution Role for ECR/CloudWatch
- Conditions on resource tags for Secrets Manager

**Consequences**:
- Must update policy if model ARN changes
- Cannot use other Bedrock models without policy update

---

## ADR-008: Structured JSON Logging + Prometheus Metrics

**Date**: 2024
**Status**: Accepted

**Context**: Need observability for production voice application.

**Decision**: structlog for JSON logs, prometheus_client for custom metrics.

**Reasoning**:
- JSON logs: parseable by CloudWatch Logs Insights
- Custom metrics: business KPIs (sessions, latency, errors)
- Prometheus format: standard, works with CloudWatch/Prometheus/Grafana
- OpenTelemetry ready for distributed tracing

**Consequences**:
- Additional dependencies
- Metrics endpoint at `/metrics` (exposed via ALB)
- Need to filter sensitive data from logs

---

## ADR-009: WAF on CloudFront (not ALB)

**Date**: 2024
**Status**: Accepted

**Context**: Protect public endpoints from abuse.

**Decision**: Attach WAF Web ACL to CloudFront distribution.

**Reasoning**:
- Protects both frontend and API/WebSocket at edge
- Rate limiting at edge (before ALB/ECS)
- AWS Managed Rules for common attacks
- Single WAF for all origins

**Consequences**:
- WAF pricing: $5/month per Web ACL + $1/million requests
- Rule tuning needed for false positives
- CloudFront WAF has slight feature differences from Regional WAF

---

## ADR-010: Cognito for Authentication (Configurable)

**Date**: 2024
**Status**: Accepted

**Context**: Public endpoint needs access control.

**Decision**: Amazon Cognito User Pool with JWT validation, but make it configurable for dev.

**Reasoning**:
- Managed auth with MFA, social providers, custom flows
- JWT validation in backend (no session state)
- Works with ALB authentication (if needed)
- Can disable for local development

**Consequences**:
- Additional infrastructure (User Pool, Client, Domain)
- Token refresh handling in frontend
- Cognito pricing: 50k MAU free, then $0.0055/MAU