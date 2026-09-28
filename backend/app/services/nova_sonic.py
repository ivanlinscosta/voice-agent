import asyncio
import base64
import contextlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Awaitable, Callable

from aws_sdk_bedrock_runtime.client import (
    AsyncBedrockRuntimeClient,
    InvokeModelWithBidirectionalStreamOperationInput,
)
from aws_sdk_bedrock_runtime.config import AsyncBedrockRuntimeConfig
from aws_sdk_bedrock_runtime.models import (
    BidirectionalInputPayloadPart,
    InvokeModelWithBidirectionalStreamInputChunk,
)
from smithy_aws_core.identity import IdentityChain
from smithy_aws_core.identity.components import AWSCredentialsIdentity
from smithy_http.aio.crt import AWSCRTHTTPClient

from app.config import settings
from app.observability import (
    conversation_duration_seconds,
    get_logger,
    nova_connection_errors,
    nova_session_renewals,
    nova_to_browser_latency_ms,
    time_to_first_audio_ms,
)

logger = get_logger(__name__)


class NovaEventType(StrEnum):
    SESSION_START = "sessionStart"
    PROMPT_START = "promptStart"
    CONTENT_START = "contentStart"
    AUDIO_INPUT = "audioInput"
    TEXT_INPUT = "textInput"
    CONTENT_END = "contentEnd"
    PROMPT_END = "promptEnd"
    SESSION_END = "sessionEnd"


class NovaOutputEventType(StrEnum):
    COMPLETION_START = "completionStart"
    CONTENT_START = "contentStart"
    TEXT_OUTPUT = "textOutput"
    AUDIO_OUTPUT = "audioOutput"
    CONTENT_END = "contentEnd"
    COMPLETION_END = "completionEnd"


@dataclass
class AudioBuffer:
    chunks: list[bytes] = field(default_factory=list)
    total_bytes: int = 0

    def add(self, chunk: bytes) -> None:
        self.chunks.append(chunk)
        self.total_bytes += len(chunk)

    def get_all(self) -> bytes:
        return b"".join(self.chunks)

    def clear(self) -> None:
        self.chunks.clear()
        self.total_bytes = 0


@dataclass
class NovaSession:
    session_id: str
    prompt_name: str
    content_name: str
    audio_content_name: str
    created_at: float = field(default_factory=time.time)
    is_active: bool = True
    first_audio_received: bool = False
    audio_buffer: AudioBuffer = field(default_factory=AudioBuffer)
    chat_history: list[dict] = field(default_factory=list)

    def elapsed_seconds(self) -> float:
        return time.time() - self.created_at

    def should_renew(self) -> bool:
        return (
            self.elapsed_seconds() >= settings.nova_session_renewal_threshold_seconds
            and self.is_active
        )


class NovaSonicService:
    def __init__(
        self,
        on_text_output: Callable[[str, str], Awaitable[None]] | None = None,
        on_audio_output: Callable[[bytes], Awaitable[None]] | None = None,
        on_user_transcript: Callable[[str], Awaitable[None]] | None = None,
        on_error: Callable[[str], Awaitable[None]] | None = None,
        on_session_renewed: Callable[[str], Awaitable[None]] | None = None,
        on_turn_end: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.client: AsyncBedrockRuntimeClient | None = None
        self.stream: Any = None
        self.current_session: NovaSession | None = None
        self.previous_session: NovaSession | None = None
        self.is_streaming = False
        self.barge_in_detected = False
        self.first_audio_timestamp: float | None = None

        self.on_text_output = on_text_output
        self.on_audio_output = on_audio_output
        self.on_user_transcript = on_user_transcript
        self.on_error = on_error
        self.on_session_renewed = on_session_renewed
        self.on_turn_end = on_turn_end

        self._response_task: asyncio.Task | None = None
        self._renewal_task: asyncio.Task | None = None
        self._audio_send_task: asyncio.Task | None = None
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue(
            maxsize=settings.audio_queue_max_frames
        )
        self._assistant_text_parts: list[str] = []

    async def _initialize_client(self) -> None:
        identity_chain = await IdentityChain.create(AWSCredentialsIdentity)
        config = await AsyncBedrockRuntimeConfig.resolve(
            endpoint_uri=f"https://bedrock-runtime.{settings.aws_region}.amazonaws.com",
            region=settings.aws_region,
            aws_credentials_identity_resolver=identity_chain,
            transport=AWSCRTHTTPClient(),
        )
        self.client = AsyncBedrockRuntimeClient(config=config)

    async def start_session(self, chat_history: list[dict] | None = None) -> str:
        if not self.client:
            await self._initialize_client()

        session_id = str(uuid.uuid4())
        prompt_name = str(uuid.uuid4())
        content_name = str(uuid.uuid4())
        audio_content_name = str(uuid.uuid4())

        self.current_session = NovaSession(
            session_id=session_id,
            prompt_name=prompt_name,
            content_name=content_name,
            audio_content_name=audio_content_name,
        )
        if chat_history:
            self.current_session.chat_history = list(chat_history)
        self._assistant_text_parts = []

        self.stream = await self.client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id=settings.nova_model_id)
        )
        self.is_streaming = True

        await self._send_session_start()
        await self._send_prompt_start()
        await self._send_system_prompt()
        await self._send_chat_history()

        self._response_task = asyncio.create_task(self._process_responses())
        self._renewal_task = asyncio.create_task(self._monitor_session_renewal())

        logger.info("nova_session_started", session_id=session_id, prompt_name=prompt_name)
        return session_id

    async def _send_session_start(self) -> None:
        event = {
            "event": {
                "sessionStart": {
                    "inferenceConfiguration": {
                        "maxTokens": settings.nova_max_tokens,
                        "topP": settings.nova_top_p,
                        "temperature": settings.nova_temperature,
                    },
                    "turnDetectionConfiguration": {
                        "endpointingSensitivity": "HIGH"
                    }
                }
            }
        }
        await self._send_event(event)

    async def _send_prompt_start(self) -> None:
        assert self.current_session
        event = {
            "event": {
                "promptStart": {
                    "promptName": self.current_session.prompt_name,
                    "textOutputConfiguration": {"mediaType": "text/plain"},
                    "audioOutputConfiguration": {
                        "mediaType": "audio/lpcm",
                        "sampleRateHertz": settings.output_sample_rate,
                        "sampleSizeBits": 16,
                        "channelCount": settings.audio_channels,
                        "voiceId": "matthew",
                        "encoding": "base64",
                        "audioType": "SPEECH"
                    },
                    "toolUseOutputConfiguration": {"mediaType": "application/json"},
                    "toolConfiguration": {"tools": []}
                }
            }
        }
        await self._send_event(event)

    async def _send_system_prompt(self) -> None:
        assert self.current_session
        content_start = {
            "event": {
                "contentStart": {
                    "promptName": self.current_session.prompt_name,
                    "contentName": self.current_session.content_name,
                    "type": "TEXT",
                    "interactive": False,
                    "role": "SYSTEM",
                    "textInputConfiguration": {"mediaType": "text/plain"}
                }
            }
        }
        text_input = {
            "event": {
                "textInput": {
                    "promptName": self.current_session.prompt_name,
                    "contentName": self.current_session.content_name,
                    "content": settings.voice_system_prompt
                }
            }
        }
        content_end = {
            "event": {
                "contentEnd": {
                    "promptName": self.current_session.prompt_name,
                    "contentName": self.current_session.content_name
                }
            }
        }
        for event in [content_start, text_input, content_end]:
            await self._send_event(event)

    async def _send_chat_history(self) -> None:
        assert self.current_session
        for msg in self.current_session.chat_history:
            role = msg.get("role", "USER")
            content = msg.get("content", "")
            if not content:
                continue
            content_name = str(uuid.uuid4())
            content_start = {
                "event": {
                    "contentStart": {
                        "promptName": self.current_session.prompt_name,
                        "contentName": content_name,
                        "type": "TEXT",
                        "role": role.upper(),
                        "interactive": False,
                        "textInputConfiguration": {"mediaType": "text/plain"},
                    }
                }
            }
            text_input = {
                "event": {
                    "textInput": {
                        "promptName": self.current_session.prompt_name,
                        "contentName": content_name,
                        "content": content,
                    }
                }
            }
            content_end = {
                "event": {
                    "contentEnd": {
                        "promptName": self.current_session.prompt_name,
                        "contentName": content_name,
                    }
                }
            }
            for event in (content_start, text_input, content_end):
                await self._send_event(event)

    async def start_audio_input(self) -> None:
        assert self.current_session
        event = {
            "event": {
                "contentStart": {
                    "promptName": self.current_session.prompt_name,
                    "contentName": self.current_session.audio_content_name,
                    "type": "AUDIO",
                    "interactive": True,
                    "role": "USER",
                    "audioInputConfiguration": {
                        "mediaType": "audio/lpcm",
                        "sampleRateHertz": settings.input_sample_rate,
                        "sampleSizeBits": 16,
                        "channelCount": settings.audio_channels,
                        "audioType": "SPEECH",
                        "encoding": "base64"
                    }
                }
            }
        }
        await self._send_event(event)
        self._audio_send_task = asyncio.create_task(self._send_audio_loop())

    async def _send_audio_loop(self) -> None:
        while self.is_streaming and self.current_session and self.current_session.is_active:
            try:
                audio_chunk = await asyncio.wait_for(self._audio_queue.get(), timeout=0.1)
                await self.send_audio_chunk(audio_chunk)
            except TimeoutError:
                continue
            except Exception as e:
                logger.exception("audio_send_error", error=str(e))
                break

    async def send_audio_chunk(self, audio_bytes: bytes) -> None:
        if not self.current_session or not self.current_session.is_active:
            return

        blob = base64.b64encode(audio_bytes).decode("utf-8")
        event = {
            "event": {
                "audioInput": {
                    "promptName": self.current_session.prompt_name,
                    "contentName": self.current_session.audio_content_name,
                    "content": blob
                }
            }
        }
        await self._send_event(event)
        audio_frames_sent = getattr(self, "_audio_frames_sent", 0) + 1
        self._audio_frames_sent = audio_frames_sent
        if audio_frames_sent == 1 or audio_frames_sent % 100 == 0:
            logger.info(
                "audio_input_sent",
                session_id=self.current_session.session_id,
                frames=audio_frames_sent,
                last_bytes=len(audio_bytes),
            )

    async def send_text(self, text: str) -> None:
        if not text.strip():
            return
        if not self.current_session or not self.current_session.is_active or not self.is_streaming:
            return

        content_name = str(uuid.uuid4())
        content_start = {
            "event": {
                "contentStart": {
                    "promptName": self.current_session.prompt_name,
                    "contentName": content_name,
                    "type": "TEXT",
                    "role": "USER",
                    "interactive": True,
                    "textInputConfiguration": {"mediaType": "text/plain"},
                }
            }
        }
        text_input = {
            "event": {
                "textInput": {
                    "promptName": self.current_session.prompt_name,
                    "contentName": content_name,
                    "content": text,
                }
            }
        }
        content_end = {
            "event": {
                "contentEnd": {
                    "promptName": self.current_session.prompt_name,
                    "contentName": content_name,
                }
            }
        }

        for event in (content_start, text_input, content_end):
            await self._send_event(event)
        await self.add_to_chat_history("USER", text)

    async def end_audio_input(self) -> None:
        if not self.current_session:
            return
        event = {
            "event": {
                "contentEnd": {
                    "promptName": self.current_session.prompt_name,
                    "contentName": self.current_session.audio_content_name
                }
            }
        }
        await self._send_event(event)

    async def end_session(self, *, cancel_renewal: bool = True) -> None:
        if not self.current_session:
            return

        self.current_session.is_active = False
        self.is_streaming = False

        if self._audio_send_task:
            self._audio_send_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._audio_send_task
            self._audio_send_task = None

        await self.end_audio_input()

        event = {
            "event": {
                "promptEnd": {
                    "promptName": self.current_session.prompt_name
                }
            }
        }
        await self._send_event(event)

        event = {"event": {"sessionEnd": {}}}
        await self._send_event(event)

        if self.stream:
            await self.stream.input_stream.close()
            self.stream = None

        if self._response_task:
            self._response_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._response_task
            self._response_task = None

        if (
            cancel_renewal
            and self._renewal_task
            and self._renewal_task is not asyncio.current_task()
        ):
            self._renewal_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._renewal_task
        self._renewal_task = None

        duration = self.current_session.elapsed_seconds()
        conversation_duration_seconds.observe(duration)

        logger.info(
            "nova_session_ended",
            session_id=self.current_session.session_id,
            duration_seconds=duration,
        )
        self.current_session = None

    async def renew_session(self) -> str:
        logger.info(
            "nova_session_renewal_started",
            old_session_id=self.current_session.session_id if self.current_session else None,
        )

        old_session = self.current_session
        self.previous_session = old_session
        old_session_id = old_session.session_id if old_session else None
        history = list(old_session.chat_history) if old_session else []

        await self.end_session(cancel_renewal=False)
        await asyncio.sleep(0.3)

        new_session_id = await self.start_session(chat_history=history)
        await self.start_audio_input()

        nova_session_renewals.inc()

        if self.on_session_renewed:
            await self.on_session_renewed(new_session_id)

        logger.info(
            "nova_session_renewal_completed",
            old_session_id=old_session_id,
            new_session_id=new_session_id,
        )
        return new_session_id

    async def _monitor_session_renewal(self) -> None:
        while self.is_streaming and self.current_session:
            if self.current_session.should_renew():
                logger.info("session_renewal_triggered", session_id=self.current_session.session_id)
                await self.renew_session()
                break
            await asyncio.sleep(10)

    async def _send_event(self, event: dict) -> None:
        if not self.stream:
            return
        event_json = json.dumps(event)
        chunk = InvokeModelWithBidirectionalStreamInputChunk(
            value=BidirectionalInputPayloadPart(bytes_=event_json.encode("utf-8"))
        )
        await self.stream.input_stream.send(chunk)

    async def _process_responses(self) -> None:
        try:
            _, output_stream = await self.stream.await_output()
            async for event in output_stream:
                if not self.is_streaming:
                    break
                if event is None:
                    continue
                payload = getattr(event, "value", event)
                response_bytes = getattr(payload, "bytes_", None)
                if response_bytes:
                    await self._handle_response(response_bytes.decode("utf-8"))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Bedrock modeled errors often stringify to ""; keep type for diagnosis.
            logger.exception(
                "response_processing_error",
                error=str(e),
                error_type=type(e).__name__,
                error_repr=repr(e),
            )
            if self.on_error:
                await self.on_error(f"{type(e).__name__}: {e}" if str(e) else type(e).__name__)
            nova_connection_errors.inc()

    async def _handle_response(self, response_data: str) -> None:
        try:
            json_data = json.loads(response_data)
        except json.JSONDecodeError:
            return

        if "event" not in json_data:
            return

        event = json_data["event"]

        event_name = next(iter(event), "")
        if event_name:
            logger.info(
                "nova_event",
                session_id=self.current_session.session_id if self.current_session else None,
                nova_event=event_name,
            )

        if NovaOutputEventType.COMPLETION_START.value in event:
            self._handle_completion_start(event[NovaOutputEventType.COMPLETION_START.value])
        elif NovaOutputEventType.CONTENT_START.value in event:
            self._handle_content_start(event[NovaOutputEventType.CONTENT_START.value])
        elif NovaOutputEventType.TEXT_OUTPUT.value in event:
            await self._handle_text_output_event(event[NovaOutputEventType.TEXT_OUTPUT.value])
        elif NovaOutputEventType.AUDIO_OUTPUT.value in event:
            await self._handle_audio_output_event(event[NovaOutputEventType.AUDIO_OUTPUT.value])
        elif NovaOutputEventType.CONTENT_END.value in event:
            self._handle_content_end(event[NovaOutputEventType.CONTENT_END.value])
        elif NovaOutputEventType.COMPLETION_END.value in event:
            await self._handle_completion_end(event[NovaOutputEventType.COMPLETION_END.value])

    def _handle_completion_start(self, completion: dict) -> None:
        logger.debug(
            "completion_start",
            session_id=completion.get("sessionId"),
            prompt_name=completion.get("promptName"),
        )

    def _handle_content_start(self, content_start: dict) -> None:
        content_type = content_start.get("type")
        role = content_start.get("role")

        if content_type == "TEXT" and role == "USER":
            logger.debug("user_transcript_start", content_id=content_start.get("contentId"))
            return

        if (
            content_type == "AUDIO"
            and role == "ASSISTANT"
            and self.current_session
            and not self.current_session.first_audio_received
        ):
            self.current_session.first_audio_received = True
            self.first_audio_timestamp = time.time()
            time_to_first_audio_ms.observe(0)

    async def _handle_text_output_event(self, text_output: dict) -> None:
        content = text_output.get("content", "")
        role = text_output.get("role")

        if content == '{ "interrupted" : true }':
            self.barge_in_detected = True
            logger.info("barge_in_detected")
            if self.on_error:
                await self.on_error("interrupted")
            return

        if role == "USER" and self.on_user_transcript:
            await self.on_user_transcript(content)
        elif role == "ASSISTANT":
            self._assistant_text_parts.append(content)
            if self.on_text_output:
                await self.on_text_output(content, text_output.get("contentId", ""))

    async def _handle_audio_output_event(self, audio_output: dict) -> None:
        content = audio_output.get("content", "")
        if not content or not self.on_audio_output:
            return

        audio_bytes = base64.b64decode(content)
        await self.on_audio_output(audio_bytes)

        if self.first_audio_timestamp:
            elapsed_ms = (time.time() - self.first_audio_timestamp) * 1000
            nova_to_browser_latency_ms.observe(elapsed_ms)
            self.first_audio_timestamp = None

    def _handle_content_end(self, content_end: dict) -> None:
        if content_end.get("stopReason") == "INTERRUPTED":
            self.barge_in_detected = True
            logger.info("content_interrupted")

    async def _handle_completion_end(self, completion_end: dict) -> None:
        logger.debug("completion_end", stop_reason=completion_end.get("stopReason"))
        if self._assistant_text_parts and self.current_session:
            await self.add_to_chat_history("ASSISTANT", "".join(self._assistant_text_parts))
        self._assistant_text_parts = []
        if self.on_turn_end:
            await self.on_turn_end()

    def queue_audio(self, audio_bytes: bytes) -> None:
        try:
            self._audio_queue.put_nowait(audio_bytes)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                self._audio_queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                self._audio_queue.put_nowait(audio_bytes)
            logger.warning("audio_queue_full_dropped_oldest")

    def get_barge_in_status(self) -> bool:
        status = self.barge_in_detected
        self.barge_in_detected = False
        return status

    async def add_to_chat_history(self, role: str, content: str) -> None:
        if not self.current_session or not content:
            return
        self.current_session.chat_history.append({
            "role": role.upper(),
            "content": content,
        })
