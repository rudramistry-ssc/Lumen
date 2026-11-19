"""Model settings, loaded from the environment (Docker Compose) or a repo-root .env."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from signspeak_ocr import VlmConfig

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_prefix="SIGNSPEAK_VLM_", extra="ignore"
    )
    # Docker Compose points this at the internal llama.cpp service (qwen:8091).
    base_url: str = "http://127.0.0.1:8091/v1"
    model: str = "lumen-local"
    api_key: str | None = None
    # Local CPU inference can take minutes for a large photo; GPUs are faster.
    timeout_seconds: float = 900.0
    # Image size sent to the model; the main speed/detail trade-off.
    max_image_pixels: int = 500_000

    def vlm_config(self) -> VlmConfig:
        return VlmConfig(base_url=self.base_url, model=self.model,
                         api_key=self.api_key, timeout_seconds=self.timeout_seconds,
                         max_image_pixels=self.max_image_pixels)


@lru_cache
def get_settings() -> Settings:
    return Settings()
