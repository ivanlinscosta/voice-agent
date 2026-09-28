# Amazon Nova 2 Sonic Voice Agent

A production-ready real-time voice conversation application using Amazon Nova 2 Sonic on Amazon Bedrock with bidirectional streaming.

## Architecture Overview

```
Browser (React + AudioWorklet)
    ↓ HTTPS/WSS
CloudFront
    ├─ /* → S3 (Frontend)
    └─ /api/*, /ws/* → ALB → ECS Fargate (Python/FastAPI)
                                    ↓
                              Bedrock Runtime
                                    ↓
                              Nova 2 Sonic
```

## Prerequisites

- AWS Account with Bedrock access in `us-east-1`
- Nova 2 Sonic model access enabled in Bedrock
- Node.js 20+
- Python 3.12+
- Docker
- AWS CLI configured
- AWS CDK v2 (`npm install -g aws-cdk`)

## Quick Start

```bash
# Clone and setup
cd voice-agent

# Install dependencies
make install

# Configure environment
cp .env.example .env
# Edit .env with your values

# Local development
make dev

# Run tests
make test

# Deploy to AWS
make deploy

# Destroy resources
make destroy
```

## Project Structure

```
voice-agent/
├── backend/                 # FastAPI backend
│   ├── app/
│   │   ├── api/            # API routes and WebSocket
│   │   ├── services/       # Nova Sonic service
│   │   ├── models/         # Pydantic models
│   │   ├── observability/  # Logging, metrics, tracing
│   │   └── config.py       # Configuration
│   ├── tests/              # Unit tests
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/               # React + TypeScript + Vite
│   ├── src/
│   │   ├── components/     # React components
│   │   ├── hooks/          # Custom hooks
│   │   ├── services/       # WebSocket service
│   │   ├── audio/          # AudioWorklet processors
│   │   └── types/          # TypeScript types
│   ├── public/             # Static assets + worklets
│   ├── package.json
│   └── vite.config.ts
├── infra/                  # AWS CDK v2 (Python)
│   ├── app.py
│   ├── stacks/
│   │   ├── network_stack.py
│   │   ├── backend_stack.py
│   │   ├── frontend_stack.py
│   │   └── observability_stack.py
│   └── requirements.txt
├── scripts/                # Utility scripts
├── docs/                   # Documentation
├── docker-compose.yml
├── Makefile
├── .env.example
└── .gitignore
```

## Configuration

Key environment variables (see `.env.example`):

```bash
AWS_REGION=us-east-1
NOVA_MODEL_ID=amazon.nova-2-sonic-v1:0
VOICE_SYSTEM_PROMPT="You are a helpful voice assistant..."
INPUT_SAMPLE_RATE=16000
OUTPUT_SAMPLE_RATE=24000
NOVA_TEMPERATURE=0.7
```

## WebSocket Protocol

### Client → Server

| Type | Payload | Description |
|------|---------|-------------|
| `message` | `{text}` | Send a typed message to the agent |
| `stop_session` | `{}` | End voice session |
| `ping` | `{}` | Keepalive |
| Binary | PCM16 16kHz mono | Audio frames |

The provider is chosen at connect time via `?model=nova-sonic` or
`?model=gemini-live`; the session starts automatically on accept.

### Server → Client

| Type | Payload | Description |
|------|---------|-------------|
| `session_started` | `{session_id, model}` | Session established |
| `user_transcript` | `{text}` | User speech transcript |
| `assistant_transcript` | `{text, content_id}` | Assistant response transcript |
| `assistant_turn_end` | `{}` | Assistant finished its turn |
| `audio_chunk` | Binary | PCM 24kHz audio |
| `interrupted` | `{}` | Barge-in detected |
| `error` | `{message}` | Error occurred |
| `session_renewed` | `{session_id}` | Nova session renewed |

## Development

### Backend (port 8000)
```bash
cd backend
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

### Frontend (port 5173)
```bash
cd frontend
npm install
npm run dev
```

### Docker Compose
```bash
docker-compose up --build
```

## Deployment

```bash
# Bootstrap CDK (first time only)
cdk bootstrap aws://ACCOUNT-ID/us-east-1

# Deploy
make deploy

# View logs
aws logs tail /ecs/nova-voice-agent-backend --follow
```

## Cost Estimate (Monthly)

| Component | Low Usage | Moderate | High |
|-----------|-----------|----------|------|
| Nova 2 Sonic | ~$5 | ~$50 | ~$500 |
| ECS Fargate | ~$15 | ~$30 | ~$100 |
| ALB | ~$18 | ~$18 | ~$18 |
| NAT Gateway | ~$32 | ~$64 | ~$128 |
| CloudFront | ~$1 | ~$5 | ~$20 |
| CloudWatch | ~$5 | ~$15 | ~$50 |
| **Total** | **~$76** | **~$182** | **~$816** |

## Troubleshooting

- **Microphone not working**: Check browser permissions, HTTPS required
- **WebSocket connection fails**: Verify ALB idle timeout (300s), Cognito config
- **No audio output**: Check AudioWorklet loading, sample rate mismatch
- **Nova session errors**: Verify model access in Bedrock console
- **High latency**: Check network, consider CloudFront edge locations

## Security

- No AWS credentials in frontend
- IAM roles for ECS tasks (least privilege)
- Cognito authentication for API/WebSocket
- WAF on CloudFront
- Private subnets for ECS

## License

MIT