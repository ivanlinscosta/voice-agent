import base64
import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.websocket import ConnectionManager, VoiceSession
from app.main import app
from app.services.gemini_live import GeminiLiveService
from app.services.nova_sonic import NovaSession, NovaSonicService


class TestGeminiLiveService:
    def test_init(self) -> None:
        service = GeminiLiveService()
        assert not service.is_streaming
        assert service.session_id is None
        assert service.chat_history == []

    @pytest.mark.asyncio
    async def test_start_session_missing_api_key(self) -> None:
        with patch("app.services.gemini_live.settings.gemini_api_key", None):
            service = GeminiLiveService()
            with pytest.raises(ValueError, match="GEMINI_API_KEY is not configured"):
                await service.start_session()

    @pytest.mark.asyncio
    async def test_start_session_success(self) -> None:
        mock_ws = AsyncMock()
        mock_ws.recv.return_value = json.dumps({"setupComplete": {}})
        mock_ws.send = AsyncMock()
        mock_ws.__aiter__.return_value = []

        with (
            patch("app.services.gemini_live.settings.gemini_api_key", "test-key"),
            patch("websockets.connect", new=AsyncMock(return_value=mock_ws)),
        ):
            service = GeminiLiveService()
            session_id = await service.start_session([{"role": "user", "content": "olá"}])

            assert service.is_streaming
            assert session_id is not None
            assert mock_ws.send.call_count == 2
            await service.end_session()

    @pytest.mark.asyncio
    async def test_start_session_setup_error(self) -> None:
        mock_ws = AsyncMock()
        mock_ws.recv.return_value = json.dumps(
            {"error": {"code": 404, "message": "model not found"}}
        )

        with (
            patch("app.services.gemini_live.settings.gemini_api_key", "test-key"),
            patch("websockets.connect", new=AsyncMock(return_value=mock_ws)),
        ):
            service = GeminiLiveService()
            with pytest.raises(RuntimeError, match="model not found"):
                await service.start_session()

            assert not service.is_streaming
            assert service.ws is None
            mock_ws.close.assert_awaited()

    @pytest.mark.asyncio
    async def test_start_session_unexpected_setup_response(self) -> None:
        mock_ws = AsyncMock()
        mock_ws.recv.return_value = json.dumps({"serverContent": {}})

        with (
            patch("app.services.gemini_live.settings.gemini_api_key", "test-key"),
            patch("websockets.connect", new=AsyncMock(return_value=mock_ws)),
        ):
            service = GeminiLiveService()
            with pytest.raises(RuntimeError, match="Unexpected Gemini Live setup response"):
                await service.start_session()

            assert not service.is_streaming
            assert service.ws is None

    @pytest.mark.asyncio
    async def test_audio_queue_and_send(self) -> None:
        mock_ws = AsyncMock()
        service = GeminiLiveService()
        service.ws = mock_ws
        service.is_streaming = True

        service.queue_audio(b"pcm-data")
        assert service._audio_queue.qsize() == 1

        await service.send_audio_chunk(b"chunk-bytes")
        assert mock_ws.send.called
        sent_payload = json.loads(mock_ws.send.call_args[0][0])
        assert "realtimeInput" in sent_payload
        assert len(sent_payload["realtimeInput"]["mediaChunks"]) == 1
        expected_data = base64.b64encode(b"chunk-bytes").decode()
        assert sent_payload["realtimeInput"]["mediaChunks"][0]["data"] == expected_data

    @pytest.mark.asyncio
    async def test_send_text_sends_client_content_and_appends_history(self) -> None:
        mock_ws = AsyncMock()
        service = GeminiLiveService()
        service.ws = mock_ws
        service.is_streaming = True

        await service.send_text("oi")

        mock_ws.send.assert_awaited_once()
        sent_payload = json.loads(mock_ws.send.await_args.args[0])
        assert sent_payload == {
            "clientContent": {
                "turns": [{"role": "user", "parts": [{"text": "oi"}]}],
                "turnComplete": True,
            }
        }
        assert service.chat_history == [{"role": "USER", "content": "oi"}]

    @pytest.mark.asyncio
    async def test_send_text_ignores_empty_text(self) -> None:
        mock_ws = AsyncMock()
        service = GeminiLiveService()
        service.ws = mock_ws
        service.is_streaming = True

        await service.send_text("   ")

        mock_ws.send.assert_not_awaited()
        assert service.chat_history == []

    @pytest.mark.asyncio
    async def test_handle_gemini_message_model_turn(self) -> None:
        audio_mock = AsyncMock()
        text_mock = AsyncMock()
        turn_end_mock = AsyncMock()

        service = GeminiLiveService(
            on_audio_output=audio_mock,
            on_text_output=text_mock,
            on_turn_end=turn_end_mock,
        )

        test_pcm = b"\x01\x02\x03\x04"
        test_msg = {
            "serverContent": {
                "modelTurn": {
                    "parts": [
                        {"inlineData": {"data": base64.b64encode(test_pcm).decode()}},
                    ]
                },
                "outputTranscription": {"text": "ola mundo"},
                "turnComplete": True,
            }
        }
        await service._handle_gemini_message(test_msg)

        audio_mock.assert_awaited_once_with(test_pcm)
        text_mock.assert_awaited_once()
        text_arg, content_id_arg = text_mock.await_args[0]
        assert text_arg == "ola mundo"
        assert content_id_arg
        turn_end_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_model_turn_text_parts_are_ignored(self) -> None:
        text_mock = AsyncMock()

        service = GeminiLiveService(on_text_output=text_mock)

        await service._handle_gemini_message(
            {
                "serverContent": {
                    "modelTurn": {
                        "parts": [{"text": "**Confirming Linguistic Output** reasoning leak"}]
                    }
                }
            }
        )

        text_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_content_id_is_stable_within_turn(self) -> None:
        service = GeminiLiveService(on_text_output=AsyncMock())

        await service._handle_gemini_message(
            {"serverContent": {"outputTranscription": {"text": "Ola, "}}}
        )
        first_id = service._turn_content_id
        await service._handle_gemini_message(
            {"serverContent": {"outputTranscription": {"text": "mundo!"}}}
        )
        assert service._turn_content_id == first_id

        await service._handle_gemini_message({"serverContent": {"turnComplete": True}})
        assert service._turn_content_id is None

    @pytest.mark.asyncio
    async def test_handle_gemini_message_interrupted_and_transcripts(self) -> None:
        text_mock = AsyncMock()
        user_transcript_mock = AsyncMock()
        error_mock = AsyncMock()

        service = GeminiLiveService(
            on_text_output=text_mock,
            on_user_transcript=user_transcript_mock,
            on_error=error_mock,
        )

        test_msg = {
            "serverContent": {
                "interrupted": True,
                "inputTranscription": {"text": "Pergunta do aluno"},
                "outputTranscription": {"text": "Transcrição do professor"},
            }
        }
        await service._handle_gemini_message(test_msg)

        error_mock.assert_awaited_once_with("interrupted")
        text_mock.assert_awaited_once()
        text_arg, content_id_arg = text_mock.await_args[0]
        assert text_arg == "Transcrição do professor"
        assert content_id_arg
        user_transcript_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_user_transcript_is_emitted_once_per_turn(self) -> None:
        user_transcript_mock = AsyncMock()
        service = GeminiLiveService(on_user_transcript=user_transcript_mock)

        fragments = (
            "O", "i", " profe", "ssor", ",", " qual", " é", " ", " a ca", "pital do Brasil?",
        )
        for fragment in fragments:
            await service._handle_gemini_message(
                {"serverContent": {"inputTranscription": {"text": fragment}}}
            )

        user_transcript_mock.assert_not_awaited()

        await service._handle_gemini_message({"serverContent": {"turnComplete": True}})
        user_transcript_mock.assert_awaited_once_with("Oi professor, qual é a capital do Brasil?")

        await service._handle_gemini_message(
            {"serverContent": {"inputTranscription": {"text": "Outra pergunta"}}}
        )
        await service._handle_gemini_message({"serverContent": {"turnComplete": True}})
        assert user_transcript_mock.await_count == 2
        assert user_transcript_mock.await_args[0][0] == "Outra pergunta"

    @pytest.mark.asyncio
    async def test_chat_history_and_end_session(self) -> None:
        mock_ws = AsyncMock()
        service = GeminiLiveService()
        service.ws = mock_ws
        service.is_streaming = True

        await service.add_to_chat_history("user", "oi")
        assert service.chat_history == [{"role": "user", "content": "oi"}]

        await service.end_session()
        assert not service.is_streaming
        assert service.ws is None


class TestConnectionManagerModelSelection:
    def test_create_service_nova(self) -> None:
        manager = ConnectionManager()
        service = manager._create_service("nova-sonic", "test-sid")
        assert isinstance(service, NovaSonicService)

    def test_create_service_gemini(self) -> None:
        manager = ConnectionManager()
        service = manager._create_service("gemini-live", "test-sid")
        assert isinstance(service, GeminiLiveService)

    def test_create_service_gemini_alias(self) -> None:
        manager = ConnectionManager()
        service = manager._create_service("gemini", "test-sid")
        assert isinstance(service, GeminiLiveService)

    @pytest.mark.asyncio
    async def test_handle_control_message_routes_text_message(self) -> None:
        manager = ConnectionManager()
        websocket = AsyncMock()
        service = AsyncMock()
        session = VoiceSession(session_id="test-sid", websocket=websocket, service=service)

        await manager._handle_control_message(session, {"type": "message", "text": "oi"})

        service.send_text.assert_awaited_once_with("oi")
        websocket.send_json.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_control_message_rejects_empty_text(self) -> None:
        manager = ConnectionManager()
        websocket = AsyncMock()
        service = AsyncMock()
        session = VoiceSession(session_id="test-sid", websocket=websocket, service=service)

        await manager._handle_control_message(session, {"type": "message", "text": "  "})

        service.send_text.assert_not_awaited()
        websocket.send_json.assert_awaited_once_with({"type": "error", "message": "Empty message"})


class TestNovaSonicService:
    @pytest.mark.asyncio
    async def test_send_text_emits_expected_event_sequence(self) -> None:
        service = NovaSonicService()
        service.current_session = NovaSession(
            session_id="session-id",
            prompt_name="prompt-id",
            content_name="system-content-id",
            audio_content_name="audio-content-id",
        )
        service.is_streaming = True
        service._send_event = AsyncMock()

        await service.send_text("oi")

        assert service._send_event.await_count == 3
        content_start = service._send_event.await_args_list[0].args[0]
        text_input = service._send_event.await_args_list[1].args[0]
        content_end = service._send_event.await_args_list[2].args[0]

        assert content_start["event"]["contentStart"]["role"] == "USER"
        assert content_start["event"]["contentStart"]["interactive"] is True
        assert content_start["event"]["contentStart"]["type"] == "TEXT"
        assert content_start["event"]["contentStart"]["textInputConfiguration"] == {
            "mediaType": "text/plain"
        }
        assert text_input["event"]["textInput"]["content"] == "oi"

        content_name = content_start["event"]["contentStart"]["contentName"]
        assert text_input["event"]["textInput"]["contentName"] == content_name
        assert content_end["event"]["contentEnd"]["contentName"] == content_name
        assert service.current_session.chat_history == [{"role": "USER", "content": "oi"}]


class TestModelsEndpoint:
    @pytest.mark.asyncio
    async def test_get_models_list(self) -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/models")
            assert response.status_code == 200
            data = response.json()
            assert "models" in data
            model_ids = [m["id"] for m in data["models"]]
            assert "nova-sonic" in model_ids
            assert "gemini-live" in model_ids
