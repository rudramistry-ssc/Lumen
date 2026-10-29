"""Pipeline configuration. Every value has a portable default; no HPC paths."""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlsplit

from .errors import ConfigError



@dataclass(frozen=True)
class VlmConfig:
    """Connection to any vision-capable OpenAI-compatible chat server.

    The model weights live on the server, never on the client. Environment
    variables are read when the config is constructed, not at import time.
    """

    base_url: str = field(default_factory=lambda: os.getenv(
        "SIGNSPEAK_VLM_BASE_URL", "http://127.0.0.1:18000/v1"))
    model: str = field(default_factory=lambda: os.getenv(
        "SIGNSPEAK_VLM_MODEL", "hackathon-llm"))
    api_key: str | None = field(default_factory=lambda: os.getenv(
        "SIGNSPEAK_VLM_API_KEY"), repr=False)
    timeout_seconds: float = 180.0
    max_tokens: int = 4096
    max_image_edge: int = 2560
    max_image_pixels: int = 4_000_000
    response_format: str = "json_schema"
    summary_language: str = "English"
    max_retries: int = 1

    def validate(self) -> None:
        try:
            url = urlsplit(self.base_url)
            port = url.port  # Validate an explicitly supplied port.
        except ValueError as error:
            raise ConfigError("Invalid VLM base URL") from error
        if (url.scheme not in {"http", "https"} or not url.hostname
                or url.username is not None or url.password is not None
                or url.query or url.fragment or any(c.isspace() for c in self.base_url)):
            raise ConfigError("VLM base URL must be HTTP(S), without credentials, query, or fragment")
        if port == 0:
            raise ConfigError("VLM port must be positive")
        if not self.model.strip() or any(c in self.model for c in "\r\n\0"):
            raise ConfigError("VLM model must be a nonempty served model name")
        if self.api_key and any(c in self.api_key for c in "\r\n\0"):
            raise ConfigError("VLM API key contains invalid characters")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ConfigError("VLM timeout must be finite and positive")
        for name, value in (("max_tokens", self.max_tokens),
                            ("max_image_edge", self.max_image_edge),
                            ("max_image_pixels", self.max_image_pixels)):
            if type(value) is not int or value <= 0:
                raise ConfigError(f"VLM {name} must be a positive integer")
        if type(self.max_retries) is not int or not 0 <= self.max_retries <= 3:
            raise ConfigError("VLM max_retries must be an integer in 0..3")
        if self.response_format not in {"json_schema", "json_object", "none"}:
            raise ConfigError("VLM response_format must be json_schema, json_object, or none")
        if (not self.summary_language.strip() or len(self.summary_language) > 80
                or any(c in self.summary_language for c in "\r\n\0")):
            raise ConfigError("Summary language must be a short, nonempty language name")

    def to_dict(self) -> dict[str, Any]:
        """Safe to put in a result; credentials are never serialized."""
        return {key: value for key, value in asdict(self).items() if key != "api_key"}
