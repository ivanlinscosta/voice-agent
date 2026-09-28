# Architecture

## Overview

```
┌─────────────────┐     HTTPS/WSS      ┌──────────────────┐
│   Browser       │ ◄─────────────────► │   CloudFront     │
│   (React +      │                     │   (CDN + WAF)    │
│   AudioWorklet) │                     └────────┬─────────┘
└─────────────────┘                              │
                                                 │ /* → S3
                                                 │ /api/*, /ws/* → ALB
                                                 ▼
                                        ┌──────────────────┐
                                        │   ALB            │
                                        │   (HTTPS/WSS)    │
                                        └────────┬─────────┘
                                                 │
                                                 ▼
                                        ┌──────────────────┐
                                        │   ECS Fargate    │
                                        │   (FastAPI)      │
                                        └────────┬─────────┘
                                                 │
                                                 ▼
                                        ┌──────────────────┐
                                        │   Bedrock        │
                                        │   Runtime        │
                                        └────────┬─────────┘
                                                 │
                                                 ▼
                                        ┌──────────────────┐
                                        │   Nova 2 Sonic   │
                                        │   (Speech-to-    │
                                        │    Speech)       │
                                        └──────────────────┘
```

## Components

### Frontend (React + TypeScript + Vite)
- Single-page application served via CloudFront + S3
- AudioWorklet for low-latency audio capture (16kHz PCM16) and playback (24kHz PCM16)
- WebSocket connection to backend for real-time streaming
- Visual indicators: connection status, volume meter, transcript history

### Backend (FastAPI + Python 3.12)
- WebSocket server at `/ws/voice`
- Manages Nova Sonic bidirectional stream
- Handles session lifecycle, renewal, barge-in
- Health check at `/health`, metrics at `/metrics`

### Infrastructure (AWS CDK v2)
- **VPC**: 2 AZs, public + private subnets, NAT Gateway (1 for dev, 2 for prod)
- **ALB**: Public, HTTPS termination, WebSocket support (idle timeout 300s)
- **ECS Fargate**: Backend service with auto-scaling (CPU/Memory)
- **ECR**: Docker image repository
- **CloudFront**: CDN with WAF, OAC for S3 origin
- **S3**: Frontend hosting (private, accessed via OAC)
- **CloudWatch**: Logs, metrics, dashboards, alarms
- **IAM**: Least-privilege roles for ECS execution and task

## Data Flow

1. User opens frontend → loads from CloudFront
2. User clicks "Iniciar conversa" → requests microphone permission
3. Frontend creates AudioContext (16kHz capture, 24kHz playback)
4. WebSocket connects to `/ws/voice` via CloudFront → ALB → ECS
5. Backend starts Nova Sonic session (sessionStart → promptStart → system prompt)
6. Microphone audio → AudioWorklet (resample to 16kHz) → WebSocket binary frames → Backend
6. Backend → Bedrock bidirectional stream → Nova 2 Sonic
7. Nova responses → Backend → WebSocket (text transcripts + binary audio) → Frontend
8. Frontend AudioWorklet plays 24kHz audio chunks in real-time
9. User can interrupt (barge-in) → Nova sends `{"interrupted": true}` → Frontend clears playback queue

## Session Renewal

Nova 2 Sonic sessions have ~8 minute limit. Backend implements transparent renewal:
- At 6 minutes (configurable), monitor for assistant speech
- When assistant starts speaking, buffer user audio for 10 seconds
- Create new Nova session with chat history + buffered audio
- Seamless handoff without user interaction

## Security

- No AWS credentials in frontend
- ECS Task Role with only `bedrock:InvokeModelWithBidirectionalStream` permission
- WAF on CloudFront (rate limiting, common rule sets)
- Cognito authentication ready (configurable)
- Private subnets for ECS, no direct internet access