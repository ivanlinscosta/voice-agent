import asyncio
import base64
import contextlib
import json
import time
import uuid
from typing import Any, Awaitable, Callable

import websockets

from app.config import settings
from app.observability import (
    conversation_duration_seconds,
    gemini_connection_errors,
    get_logger,
)

logger = get_logger(__name__)


class GeminiLiveService:
    def __init__(
        self,
        on_text_output: Callable[[str, str], Awaitable[None]] | None = None,
        on_audio_output: Callable[[bytes], Awaitable[None]] | None = None,
        on_user_transcript: Callable[[str], Awaitable[None]] | None = None,
        on_error: Callable[[str], Awaitable[None]] | None = None,
        on_session_renewed: Callable[[str], Awaitable[None]] | None = None,
        on_turn_end: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.ws: Any = None
        self.session_id: str | None = None
        self.created_at: float = 0.0
        self.is_streaming: bool = False
        self.chat_history: list[dict] = []

        self.on_text_output = on_text_output
        self.on_audio_output = on_audio_output
        self.on_user_transcript = on_user_transcript
        self.on_error = on_error
        self.on_session_renewed = on_session_renewed
        self.on_turn_end = on_turn_end

        self._response_task: asyncio.Task | None = None
        self._audio_send_task: asyncio.Task | None = None
        self._turn_content_id: str | None = None
        self._user_transcript_parts: list[str] = []
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue(
            maxsize=settings.audio_queue_max_frames
        )
        self._audio_frames_sent = 0

    async def start_session(self, chat_history: list[dict] | None = None) -> str:
        if not settings.gemini_api_key:
            gemini_connection_errors.inc()
            logger.error("gemini_api_key_missing")
            raise ValueError("GEMINI_API_KEY is not configured")

        self.session_id = str(uuid.uuid4())
        self.created_at = time.time()
        self.chat_history = list(chat_history) if chat_history else []

        url = f"{settings.gemini_ws_endpoint}?key={settings.gemini_api_key}"
        try:
            self.ws = await websockets.connect(url, max_size=None)
        except Exception as e:
            gemini_connection_errors.inc()
            logger.exception("gemini_connection_failed", error=str(e))
            raise

        self.is_streaming = True

        setup_msg = {
            "setup": {
                "model": settings.gemini_model_id,
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {
                            "prebuiltVoiceConfig": {
                                "voiceName": settings.gemini_voice_name
                            }
                        }
                    },
                    "temperature": settings.gemini_temperature,
                },
                "systemInstruction": {
                    "parts": [{"text": settings.voice_system_prompt}]
                },
                "inputAudioTranscription": {},
                "outputAudioTranscription": {},
            }
        }

        try:
            await self.ws.send(json.dumps(setup_msg))
            setup_response = json.loads(await self.ws.recv())
        except Exception:
            await self._close_ws()
            self.is_streaming = False
            gemini_connection_errors.inc()
            logger.exception("gemini_setup_failed", model=settings.gemini_model_id)
            raise

        if "error" in setup_response:
            await self._close_ws()
            self.is_streaming = False
            gemini_connection_errors.inc()
            error = setup_response["error"]
            logger.error("gemini_setup_rejected", model=settings.gemini_model_id, error=error)
            raise RuntimeError(f"Gemini Live setup failed: {error.get('message', error)}")

        if "setupComplete" not in setup_response:
            await self._close_ws()
            self.is_streaming = False
            gemini_connection_errors.inc()
            raise RuntimeError(
                f"Unexpected Gemini Live setup response: {setup_response}"
            )

        logger.info(
            "gemini_setup_completed",
            session_id=self.session_id,
            model=settings.gemini_model_id,
        )

        if self.chat_history:
            await self._send_initial_chat_history()

        self._response_task = asyncio.create_task(self._process_responses())
        logger.info("gemini_session_started", session_id=self.session_id)
        return self.session_id

    async def _send_initial_chat_history(self) -> None:
        turns = []
        for msg in self.chat_history:
            content = msg.get("content", "")
            if not content:
                continue
            role = "user" if msg.get("role", "USER").upper() == "USER" else "model"
            turns.append({
                "role": role,
                "parts": [{"text": content}],
            })
        if turns:
            history_msg = {
                "clientContent": {
                    "turns": turns,
                    "turnComplete": True,
                }
            }
            await self.ws.send(json.dumps(history_msg))

    async def start_audio_input(self) -> None:
        self._audio_send_task = asyncio.create_task(self._send_audio_loop())

    def queue_audio(self, audio_bytes: bytes) -> None:
        try:
            self._audio_queue.put_nowait(audio_bytes)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                self._audio_queue.get_nowait()
            self._audio_queue.put_nowait(audio_bytes)

    async def _send_audio_loop(self) -> None:
        while self.is_streaming and self.ws:
            try:
                audio_chunk = await asyncio.wait_for(self._audio_queue.get(), timeout=0.1)
                await self.send_audio_chunk(audio_chunk)
            except TimeoutError:
                continue
            except Exception as e:
                logger.exception("gemini_audio_send_error", error=str(e))
                break

    async def send_audio_chunk(self, audio_bytes: bytes) -> None:
        if not self.ws or not self.is_streaming:
            return

        blob = base64.b64encode(audio_bytes).decode("utf-8")
        payload = {
            "realtimeInput": {
                "mediaChunks": [
                    {
                        "mimeType": f"audio/pcm;rate={settings.input_sample_rate}",
                        "data": blob,
                    }
                ]
            }
        }
        await self.ws.send(json.dumps(payload))
        self._audio_frames_sent += 1
        if self._audio_frames_sent == 1 or self._audio_frames_sent % 100 == 0:
            logger.info(
                "gemini_audio_input_sent",
                session_id=self.session_id,
                frames=self._audio_frames_sent,
                last_bytes=len(audio_bytes),
            )

    async def send_text(self, text: str) -> None:
        if not text.strip():
            return
        if not self.ws or not self.is_streaming:
            return

        payload = {
            "clientContent": {
                "turns": [{"role": "user", "parts": [{"text": text}]}],
                "turnComplete": True,
            }
        }
        await self.ws.send(json.dumps(payload))
        await self.add_to_chat_history("USER", text)

    async def _process_responses(self) -> None:
        try:
            async for raw_message in self.ws:
                if not self.is_streaming:
                    break
                try:
                    data = json.loads(raw_message)
                    await self._handle_gemini_message(data)
                except json.JSONDecodeError:
                    logger.warning("gemini_invalid_json", raw=str(raw_message)[:100])
        except websockets.ConnectionClosed as e:
            logger.info("gemini_connection_closed", code=e.code, reason=e.reason)
        except Exception as e:
            gemini_connection_errors.inc()
            logger.exception("gemini_receive_error", error=str(e))
            if self.on_error:
                await self.on_error(str(e))

    async def _handle_gemini_message(self, data: dict) -> None:
        server_content = data.get("serverContent")
        if not server_content:
            return

        if server_content.get("interrupted") and self.on_error:
            await self.on_error("interrupted")

        await self._handle_model_audio(server_content.get("modelTurn"))
        await self._handle_transcriptions(server_content)

        if server_content.get("turnComplete"):
            await self._flush_user_transcript()
            self._turn_content_id = None
            if self.on_turn_end:
                await self.on_turn_end()

    async def _handle_model_audio(self, model_turn: dict | None) -> None:
        if not model_turn or not self.on_audio_output:
            return
        for part in model_turn.get("parts", []):
            inline_data = part.get("inlineData")
            if not inline_data:
                continue
            audio_b64 = inline_data.get("data")
            if audio_b64:
                await self.on_audio_output(base64.b64decode(audio_b64))

    async def _handle_transcriptions(self, server_content: dict) -> None:
        output_transcription = server_content.get("outputTranscription")
        if output_transcription:
            text = output_transcription.get("text")
            if text and self.on_text_output:
                await self.on_text_output(text, self._next_content_id())

        input_transcription = server_content.get("inputTranscription")
        if input_transcription:
            text = input_transcription.get("text")
            if text:
                self._user_transcript_parts.append(text)

    async def _flush_user_transcript(self) -> None:
        if not self._user_transcript_parts:
            return
        text = " ".join("".join(self._user_transcript_parts).split())
        self._user_transcript_parts.clear()
        if text and self.on_user_transcript:
            await self.on_user_transcript(text)

    def _next_content_id(self) -> str:
        if self._turn_content_id is None:
            self._turn_content_id = str(uuid.uuid4())
        return self._turn_content_id

    async def add_to_chat_history(self, role: str, text: str) -> None:
        self.chat_history.append({"role": role, "content": text})

    async def end_session(self) -> None:
        self.is_streaming = False
        self._turn_content_id = None
        self._user_transcript_parts.clear()

        while not self._audio_queue.empty():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._audio_queue.get_nowait()

        if self._audio_send_task:
            self._audio_send_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._audio_send_task
            self._audio_send_task = None

        if self._response_task:
            self._response_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._response_task
            self._response_task = None

        if self.ws:
            await self._close_ws()

        if self.created_at > 0:
            duration = time.time() - self.created_at
            conversation_duration_seconds.observe(duration)
            logger.info(
                "gemini_session_ended",
                session_id=self.session_id,
                duration_seconds=duration,
            )

    async def _close_ws(self) -> None:
        if self.ws:
            with contextlib.suppress(Exception):
                await self.ws.close()
            self.ws = None
