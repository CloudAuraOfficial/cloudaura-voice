from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LiveKit
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    livekit_sip_host: str = "sip.livekit.cloud"

    # Deepgram
    deepgram_api_key: str

    # OpenAI
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"

    # ElevenLabs
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    elevenlabs_model_id: str = "eleven_turbo_v2_5"

    # TTS provider: "openai" or "elevenlabs"
    tts_provider: str = "openai"

    # Telnyx
    telnyx_api_key: str = ""
    telnyx_phone_number: str = ""
    telnyx_assistant_id: str = ""

    # Twilio (legacy — kept for backwards compatibility during migration)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # Airtable
    airtable_api_key: str
    airtable_base_id: str
    airtable_table_name: str = "Interactions"

    # Application
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    environment: str = "development"
    public_base_url: str = "http://localhost:8000"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
