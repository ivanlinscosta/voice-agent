# WebSocket Protocol

## Endpoint

```
ws://{host}/api/ws/voice
```

Locally the Vite dev server proxies `/api` (HTTP + WebSocket upgrade) to the
FastAPI backend on port 8000, so the browser connects to
`ws://localhost:5173/api/ws/voice`.

## Authentication

For production, pass JWT token as query parameter:
```
wss://{domain}/api/ws/voice?token={jwt}
```

## Model Selection

Pass the provider as a query parameter:
```
ws://{host}/api/ws/voice?model=nova-sonic
ws://{host}/api/ws/voice?model=gemini-live
```

`model` defaults to `nova-sonic`. The accepted values are the `id` values
returned by `GET /api/models`. The active value is echoed back in
`session_started.model`.

## Message Types

### Client → Server

#### Message (typed text)
Send a text turn to the agent. The session must already be active (the server
starts it automatically on accept).
```json
{
  "type": "message",
  "text": "Explique fotosíntese"
}
```
- Empty or whitespace-only text is rejected with an `error` frame.
- The server does **not** echo the message; the client renders its own bubble.
- The reply arrives through the normal response events
  (`assistant_transcript` chunks, binary audio, `assistant_turn_end`).

#### Stop Session
```json
{
  "type": "stop_session"
}
```

#### Ping (keepalive)
```json
{
  "type": "ping"
}
```

Unknown `type` values are ignored and logged as a warning.

#### Audio Data (Binary)
Raw PCM16, 16kHz, mono audio frames. Sent as WebSocket binary frames (not base64).

### Server → Client

#### Session Started
Sent automatically right after the session is established.
```json
{
  "type": "session_started",
  "session_id": "uuid",
  "model": "nova-sonic"
}
```

#### User Transcript
```json
{
  "type": "user_transcript",
  "text": "Recognized speech text"
}
```

#### Assistant Transcript
```json
{
  "type": "assistant_transcript",
  "text": "Assistant response text",
  "content_id": "uuid"
}
```

#### Audio Chunk (Binary)
Raw PCM16, 24kHz, mono audio. Sent as WebSocket binary frames.

#### Interrupted (Barge-in)
```json
{
  "type": "interrupted"
}
```

#### Error
```json
{
  "type": "error",
  "message": "Error description"
}
```

#### Assistant Turn End
The agent finished its turn; the client should return to listening state.
```json
{
  "type": "assistant_turn_end"
}
```

#### Session Renewed
```json
{
  "type": "session_renewed",
  "session_id": "new-uuid"
}
```

#### Pong
```json
{
  "type": "pong"
}
```

## Connection Lifecycle

```
1. Client connects to WebSocket (?model=...)
2. Server accepts and starts the provider session (Nova Sonic or Gemini Live)
3. Server sends: {"type": "session_started", "session_id": "...", "model": "..."}
4. Client streams audio (binary frames) and/or typed text ({"type": "message"})
5. Server streams transcripts (JSON), audio (binary) and turn events back
6. Client can send {"type": "stop_session"} to end
7. Server closes connection
```

## Audio Format

| Direction | Format | Sample Rate | Channels | Bit Depth |
|-----------|--------|-------------|----------|-----------|
| Client → Server | PCM16 (little-endian) | 16,000 Hz | 1 (mono) | 16-bit |
| Server → Client | PCM16 (little-endian) | 24,000 Hz | 1 (mono) | 16-bit |

## Frame Size

Recommended frame size: 30ms at 16kHz = 480 samples = 960 bytes per frame.

## Error Handling

- Connection errors → Server sends `{"type": "error", "message": "..."}` then closes
- Client should implement exponential backoff reconnection (max 5 attempts)
- Session renewal is transparent - client receives `session_renewed` with new ID

## Example Flow

```
C: WS Connect
S: WS Accept
C: {"type": "start_session"}
S: {"type": "session_started", "session_id": "abc-123"}
C: [binary: 960 bytes PCM16 @ 16kHz]
C: [binary: 960 bytes PCM16 @ 16kHz]
S: {"type": "user_transcript", "text": "Olá"}
S: {"type": "assistant_transcript", "text": "Olá! Como posso ajudar?"}
S: [binary: 1440 bytes PCM16 @ 24kHz]
S: [binary: 1440 bytes PCM16 @ 24kHz]
C: {"type": "stop_session"}
S: Close
```