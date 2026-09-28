import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.websockets import WebSocketState

from app.config import settings
from app.observability import (
    active_websocket_connections,
    get_logger,
    mic_to_backend_latency_ms,
    voice_sessions_completed,
    voice_sessions_failed,
    voice_sessions_started,
)
from app.services import GeminiLiveService, NovaSonicService

logger = get_logger(__name__)

router = APIRouter()

VoiceService = GeminiLiveService | NovaSonicService
TextOutputHandler = Callable[[str, str], Awaitable[None]]
AudioOutputHandler = Callable[[bytes], Awaitable[None]]
TranscriptHandler = Callable[[str], Awaitable[None]]
ErrorHandler = Callable[[str], Awaitable[None]]
SessionRenewedHandler = Callable[[str], Awaitable[None]]
TurnEndHandler = Callable[[], Awaitable[None]]

GEMINI_MODEL_ALIASES = ("gemini", "gemini-live")


def normalize_model(model: str | None) -> str:
    return (
        "gemini-live"
        if (model or "").strip().lower() in GEMINI_MODEL_ALIASES
        else "nova-sonic"
    )


@dataclass
class VoiceSession:
    session_id: str
    websocket: WebSocket
    service: VoiceService
    model: str = "nova-sonic"
    created_at: float = field(default_factory=time.time)
    is_active: bool = True
    last_activity: float = field(default_factory=time.time)
    audio_frames_received: int = 0
    audio_bytes_received: int = 0
    audio_frames_sent: int = 0

    @property
    def nova_service(self) -> VoiceService:
        return self.service


class ConnectionManager:
    def __init__(self) -> None:
        self.active_sessions: dict[str, VoiceSession] = {}

    def _create_service(self, model: str, session_id: str) -> VoiceService:
        normalized = normalize_model(model)
        if normalized == "gemini-live":
            return GeminiLiveService(
                on_text_output=self._handle_text_output(session_id),
                on_audio_output=self._handle_audio_output(session_id),
                on_user_transcript=self._handle_user_transcript(session_id),
                on_error=self._handle_error(session_id),
                on_session_renewed=self._handle_session_renewed(session_id),
                on_turn_end=self._handle_turn_end(session_id),
            )
        return NovaSonicService(
            on_text_output=self._handle_text_output(session_id),
            on_audio_output=self._handle_audio_output(session_id),
            on_user_transcript=self._handle_user_transcript(session_id),
            on_error=self._handle_error(session_id),
            on_session_renewed=self._handle_session_renewed(session_id),
            on_turn_end=self._handle_turn_end(session_id),
        )

    async def connect(
        self,
        websocket: WebSocket,
        token: str | None = None,
        model: str = "nova-sonic",
    ) -> VoiceSession:
        await websocket.accept()

        if settings.app_env != "dev" and not token:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )

        session_id = str(uuid.uuid4())
        normalized_model = normalize_model(model)
        service = self._create_service(model, session_id)

        voice_session = VoiceSession(
            session_id=session_id,
            websocket=websocket,
            service=service,
            model=normalized_model,
        )

        self.active_sessions[session_id] = voice_session
        active_websocket_connections.inc()
        voice_sessions_started.inc()

        try:
            await service.start_session()
            await service.start_audio_input()
        except Exception as e:
            self.active_sessions.pop(session_id, None)
            active_websocket_connections.dec()
            voice_sessions_failed.inc()
            logger.exception("session_start_failed", session_id=session_id, error=str(e))
            await websocket.send_json({
                "type": "error",
                "message": str(e),
            })
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
            raise

        await websocket.send_json({
            "type": "session_started",
            "session_id": session_id,
            "model": normalized_model,
        })

        logger.info(
            "websocket_connected",
            session_id=session_id,
            model=normalized_model,
            total_connections=len(self.active_sessions),
        )
        return voice_session

    def _handle_text_output(self, session_id: str) -> TextOutputHandler:
        async def handler(text: str, content_id: str) -> None:
            session = self.active_sessions.get(session_id)
            if session and session.websocket.client_state == WebSocketState.CONNECTED:
                await session.websocket.send_json({
                    "type": "assistant_transcript",
                    "text": text,
                    "content_id": content_id,
                })
        return handler

    def _handle_audio_output(self, session_id: str) -> AudioOutputHandler:
        async def handler(audio_bytes: bytes) -> None:
            session = self.active_sessions.get(session_id)
            if session and session.websocket.client_state == WebSocketState.CONNECTED:
                await session.websocket.send_bytes(audio_bytes)
        return handler

    def _handle_user_transcript(self, session_id: str) -> TranscriptHandler:
        async def handler(text: str) -> None:
            session = self.active_sessions.get(session_id)
            if session and session.websocket.client_state == WebSocketState.CONNECTED:
                await session.websocket.send_json({
                    "type": "user_transcript",
                    "text": text,
                })
                await session.service.add_to_chat_history("USER", text)
        return handler

    def _handle_error(self, session_id: str) -> ErrorHandler:
        async def handler(message: str) -> None:
            session = self.active_sessions.get(session_id)
            if session and session.websocket.client_state == WebSocketState.CONNECTED:
                if message == "interrupted":
                    await session.websocket.send_json({"type": "interrupted"})
                else:
                    await session.websocket.send_json({
                        "type": "error",
                        "message": message,
                    })
        return handler

    def _handle_session_renewed(self, session_id: str) -> SessionRenewedHandler:
        async def handler(new_session_id: str) -> None:
            session = self.active_sessions.get(session_id)
            if session and session.websocket.client_state == WebSocketState.CONNECTED:
                await session.websocket.send_json({
                    "type": "session_renewed",
                    "session_id": new_session_id,
                })
        return handler

    def _handle_turn_end(self, session_id: str) -> TurnEndHandler:
        async def handler() -> None:
            session = self.active_sessions.get(session_id)
            if session and session.websocket.client_state == WebSocketState.CONNECTED:
                await session.websocket.send_json({"type": "assistant_turn_end"})
        return handler

    async def disconnect(self, session_id: str) -> None:
        session = self.active_sessions.pop(session_id, None)
        if session:
            session.is_active = False
            await session.service.end_session()
            active_websocket_connections.dec()
            voice_sessions_completed.inc()
            logger.info(
                "websocket_disconnected",
                session_id=session_id,
                total_connections=len(self.active_sessions),
            )

    async def handle_message(self, session_id: str, message: str | bytes) -> None:
        session = self.active_sessions.get(session_id)
        if not session or not session.is_active:
            return

        session.last_activity = time.time()

        if isinstance(message, bytes):
            start = time.perf_counter()
            session.service.queue_audio(message)
            session.audio_frames_received += 1
            session.audio_bytes_received += len(message)
            if session.audio_frames_received == 1 or session.audio_frames_received % 100 == 0:
                logger.info(
                    "audio_frame_received",
                    session_id=session.session_id,
                    frames=session.audio_frames_received,
                    total_bytes=session.audio_bytes_received,
                    last_bytes=len(message),
                )
            mic_to_backend_latency_ms.observe((time.perf_counter() - start) * 1000)
        else:
            try:
                data = json.loads(message)
                await self._handle_control_message(session, data)
            except json.JSONDecodeError:
                logger.warning("invalid_json_message", session_id=session_id)

    async def _handle_control_message(self, session: VoiceSession, data: dict) -> None:
        msg_type = data.get("type")

        if msg_type == "stop_session":
            await self.disconnect(session.session_id)
        elif msg_type == "ping":
            await session.websocket.send_json({"type": "pong"})
        elif msg_type == "message":
            text = data.get("text")
            if not isinstance(text, str) or not text.strip():
                await session.websocket.send_json({"type": "error", "message": "Empty message"})
                return
            await session.service.send_text(text)
        else:
            logger.warning("unknown_message_type", session_id=session.session_id, type=msg_type)

    async def cleanup_stale_sessions(self, max_age_seconds: int = 300) -> None:
        now = time.time()
        stale_sessions = [
            sid
            for sid, session in self.active_sessions.items()
            if now - session.last_activity > max_age_seconds
        ]
        for sid in stale_sessions:
            logger.info("cleanup_stale_session", session_id=sid)
            await self.disconnect(sid)


manager = ConnectionManager()


@router.websocket("/ws/voice")
async def websocket_voice(
    websocket: WebSocket,
    token: str | None = Query(None),
    model: str | None = Query("nova-sonic"),
) -> None:
    session = await manager.connect(websocket, token=token, model=model or "nova-sonic")
    session_id = session.session_id

    try:
        while True:
            message = await websocket.receive()
            if "bytes" in message:
                await manager.handle_message(session_id, message["bytes"])
            elif "text" in message:
                await manager.handle_message(session_id, message["text"])
    except WebSocketDisconnect:
        logger.info("websocket_disconnect", session_id=session_id)
    except Exception as e:
        logger.exception("websocket_error", session_id=session_id, error=str(e))
        voice_sessions_failed.inc()
    finally:
        await manager.disconnect(session_id)


@router.get("/models")
async def list_models() -> dict:
    return {
        "models": [
            {
                "id": "nova-sonic",
                "name": "Amazon Nova 2 Sonic",
                "provider": "AWS Bedrock",
                "description": "Streaming bidirecional de voz na AWS",
                "available": True,
            },
            {
                "id": "gemini-live",
                "name": "Google Gemini Live",
                "provider": "Google Gemini",
                "description": "Multimodal Live API com suporte nativo a áudio",
                "available": bool(settings.gemini_api_key),
            },
        ]
    }


@router.get("/health")
async def health_check() -> dict:
    return {
        "status": "ok",
        "active_connections": len(manager.active_sessions),
        "timestamp": time.time(),
    }


async def get_manager() -> ConnectionManager:
    return manager
