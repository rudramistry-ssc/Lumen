"""All AI service settings. Every field can be overridden by an env var with
the same name in uppercase (e.g. LLM_MODEL)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Any OpenAI-compatible chat API. Default is a local Ollama; for vLLM on
    # the HPC node use e.g. http://<node>:8000/v1.
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "llama3.2:3b"
    llm_api_key: str = "ollama"            # Ollama ignores it; vLLM may need one
    llm_timeout_seconds: float = 120.0
    llm_max_tokens: int = 300              # replies are read aloud, keep them short

    # Run OCR a second time on cleaned-up images when the first read is poor.
    ocr_preprocess: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
