"""Typed errors with stable machine-readable codes for the JSON output."""

from __future__ import annotations

from typing import Any


class OcrError(Exception):
    """Base error. ``code`` is stable and appears in ``errors[].code``."""

    code = "ocr_error"
    recoverable = False

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self, stage: str) -> dict[str, Any]:
        record: dict[str, Any] = {
            "stage": stage,
            "code": self.code,
            "message": self.message,
            "recoverable": self.recoverable,
        }
        if self.details:
            record["details"] = self.details
        return record


class InputError(OcrError):
    code = "invalid_input"


class ImageTooLargeError(InputError):
    code = "image_too_large"


class UnsupportedImageError(InputError):
    code = "unsupported_image"


class ConfigError(OcrError):
    code = "invalid_config"


class TesseractNotFoundError(OcrError):
    code = "tesseract_not_found"


class TesseractLanguageError(OcrError):
    code = "tesseract_language_missing"


class TesseractExecutionError(OcrError):
    code = "tesseract_failed"


class TesseractTimeoutError(TesseractExecutionError):
    code = "tesseract_timeout"


class TsvParseError(OcrError):
    code = "tsv_invalid"
