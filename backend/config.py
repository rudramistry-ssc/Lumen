"""All configuration lives here. Every field can be overridden by an env var
with the same name in uppercase (e.g. AI_BASE_URL)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Where the AI service runs. Compose overrides this with http://ai:8000.
    ai_base_url: str = "http://localhost:9000"
    ai_timeout_seconds: float = 120.0

    # Runtime files: sqlite database and generated mp3s. Compose points these at /data.
    db_path: str = "data/app.db"
    media_dir: str = "data/media"

    # "*" allows any origin; set a comma-separated list for the real frontend.
    cors_origins: str = "*"
    max_upload_mb: int = 15
    tts_voice: str = "en-US-AvaNeural"  # passed through to the AI service
    # Off until the AI service offers /v1/tts; scans then return text only.
    tts_enabled: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    # Cached so .env is read once, not on every request.
    return Settings()
