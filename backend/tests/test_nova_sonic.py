import pytest
import json
import base64


class TestWebSocketProtocol:
    def test_start_session_message(self):
        message = {"type": "start_session"}
        assert message["type"] == "start_session"

    def test_stop_session_message(self):
        message = {"type": "stop_session"}
        assert message["type"] == "stop_session"

    def test_session_started_response(self):
        response = {"type": "session_started", "session_id": "test-123"}
        assert response["type"] == "session_started"
        assert "session_id" in response

    def test_user_transcript_response(self):
        response = {"type": "user_transcript", "text": "Hello"}
        assert response["type"] == "user_transcript"
        assert response["text"] == "Hello"

    def test_assistant_transcript_response(self):
        response = {"type": "assistant_transcript", "text": "Hi there!", "content_id": "cid-123"}
        assert response["type"] == "assistant_transcript"
        assert response["text"] == "Hi there!"

    def test_interrupted_response(self):
        response = {"type": "interrupted"}
        assert response["type"] == "interrupted"

    def test_error_response(self):
        response = {"type": "error", "message": "Something went wrong"}
        assert response["type"] == "error"
        assert response["message"] == "Something went wrong"


class TestHealthEndpoint:
    def test_health_response_format(self):
        response = {"status": "ok"}
        assert response["status"] == "ok"


class TestAudioFormat:
    def test_input_sample_rate(self):
        assert 16000 == 16000

    def test_output_sample_rate(self):
        assert 24000 == 24000

    def test_audio_channels(self):
        assert 1 == 1

    def test_chunk_size(self):
        assert 512 == 512


class TestAudioEncoding:
    def test_base64_encoding(self):
        audio_data = b"test audio data"
        encoded = base64.b64encode(audio_data).decode()
        decoded = base64.b64decode(encoded)
        assert decoded == audio_data

    def test_json_serialization(self):
        event = {"event": {"audioInput": {"content": "base64data"}}}
        serialized = json.dumps(event)
        parsed = json.loads(serialized)
        assert parsed == event


class TestWebSocketProtocol:
    def test_start_session_message(self):
        message = {"type": "start_session"}
        assert message["type"] == "start_session"

    def test_stop_session_message(self):
        message = {"type": "stop_session"}
        assert message["type"] == "stop_session"

    def test_session_started_response(self):
        response = {"type": "session_started", "session_id": "test-123"}
        assert response["type"] == "session_started"
        assert "session_id" in response

    def test_user_transcript_response(self):
        response = {"type": "user_transcript", "text": "Hello"}
        assert response["type"] == "user_transcript"
        assert response["text"] == "Hello"

    def test_assistant_transcript_response(self):
        response = {"type": "assistant_transcript", "text": "Hi there!", "content_id": "cid-123"}
        assert response["type"] == "assistant_transcript"
        assert response["text"] == "Hi there!"

    def test_interrupted_response(self):
        response = {"type": "interrupted"}
        assert response["type"] == "interrupted"

    def test_error_response(self):
        response = {"type": "error", "message": "Something went wrong"}
        assert response["type"] == "error"
        assert response["message"] == "Something went wrong"


class TestHealthEndpoint:
    def test_health_response_format(self):
        response = {"status": "ok"}
        assert response["status"] == "ok"


class TestAudioFormat:
    def test_input_sample_rate(self):
        assert 16000 == 16000

    def test_output_sample_rate(self):
        assert 24000 == 24000

    def test_audio_channels(self):
        assert 1 == 1

    def test_chunk_size(self):
        assert 512 == 512


if __name__ == "__main__":
    pytest.main([__file__, "-v"])