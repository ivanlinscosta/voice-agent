from functools import lru_cache
from typing import Optional
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # AWS
    aws_region: str = Field(default="us-east-1", validation_alias="AWS_REGION")
    aws_account_id: str = Field(default="", validation_alias="AWS_ACCOUNT_ID")

    # Nova 2 Sonic
    nova_model_id: str = Field(default="amazon.nova-2-sonic-v1:0", validation_alias="NOVA_MODEL_ID")
    voice_system_prompt: str = Field(
        default=(
            "Você é um professor virtual da educação básica brasileira, especializado no Ensino Fundamental "
            "(1º ao 9º ano) e no Ensino Médio.\n"
            "Responda SOMENTE sobre conteúdos escolares dessas etapas (BNCC): Matemática, Língua Portuguesa, "
            "Ciências, História, Geografia, Inglês, Literatura, Física, Química, Biologia, Filosofia, Sociologia "
            "e afins.\n"
            "Você pode: revisar e explicar conteúdos; aplicar testes, quiz e exercícios (uma questão por vez, "
            "aguardando a resposta); corrigir respostas com feedback claro; sugerir estudos e resumos; adaptar a "
            "linguagem à idade do aluno.\n"
            "Se o aluno pedir algo fora da educação básica, recuse com educação e redirecione para os estudos. "
            "Não resolva tarefas de forma irresponsável: explique o método e dê um exemplo parecido.\n"
            "Fale em português brasileiro, de forma natural para voz: frases curtas, sem listas longas, sem "
            "markdown e sem emojis. Não seja excessivamente longo, a menos que peçam detalhes."
        ),
        validation_alias="VOICE_SYSTEM_PROMPT",
    )
    nova_temperature: float = Field(default=0.7, validation_alias="NOVA_TEMPERATURE")
    nova_top_p: float = Field(default=0.9, validation_alias="NOVA_TOP_P")
    nova_max_tokens: int = Field(default=1024, validation_alias="NOVA_MAX_TOKENS")

    gemini_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    )
    gemini_model_id: str = Field(
        default="models/gemini-2.5-flash-native-audio-latest",
        validation_alias="GEMINI_MODEL_ID",
    )
    gemini_voice_name: str = Field(
        default="Puck",
        validation_alias="GEMINI_VOICE_NAME",
    )
    gemini_temperature: float = Field(
        default=0.7,
        validation_alias="GEMINI_TEMPERATURE",
    )
    gemini_ws_endpoint: str = Field(
        default="wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent",
        validation_alias="GEMINI_WS_ENDPOINT",
    )

    # Audio
    input_sample_rate: int = Field(default=16000, validation_alias="INPUT_SAMPLE_RATE")
    output_sample_rate: int = Field(default=24000, validation_alias="OUTPUT_SAMPLE_RATE")
    audio_chunk_size: int = Field(default=512, validation_alias="AUDIO_CHUNK_SIZE")
    audio_channels: int = Field(default=1, validation_alias="AUDIO_CHANNELS")

    # Session
    nova_session_max_duration_seconds: int = Field(default=480, validation_alias="NOVA_SESSION_MAX_DURATION_SECONDS")
    nova_session_renewal_threshold_seconds: int = Field(default=360, validation_alias="NOVA_SESSION_RENEWAL_THRESHOLD_SECONDS")
    nova_audio_buffer_seconds: int = Field(default=10, validation_alias="NOVA_AUDIO_BUFFER_SECONDS")
    audio_queue_max_frames: int = Field(default=200, validation_alias="AUDIO_QUEUE_MAX_FRAMES")

    # Application
    app_env: str = Field(default="dev", validation_alias="APP_ENV")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    log_format: str = Field(default="json", validation_alias="LOG_FORMAT")

    # Cognito
    cognito_user_pool_id: Optional[str] = Field(default=None, validation_alias="COGNITO_USER_POOL_ID")
    cognito_client_id: Optional[str] = Field(default=None, validation_alias="COGNITO_CLIENT_ID")
    cognito_domain: Optional[str] = Field(default=None, validation_alias="COGNITO_DOMAIN")

    # Frontend URLs (set after deployment)
    vite_api_url: Optional[str] = Field(default=None, validation_alias="VITE_API_URL")
    vite_ws_url: Optional[str] = Field(default=None, validation_alias="VITE_WS_URL")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()