"""Stable error codes for input and model failures."""
class OcrError(Exception):
    code = "ocr_error"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self, stage: str) -> dict:
        return {"stage": stage, "code": self.code, "message": self.message, **({"details": self.details} if self.details else {})}


class InputError(OcrError):
    code = "invalid_input"


class ImageTooLargeError(InputError):
    code = "image_too_large"


class UnsupportedImageError(InputError):
    code = "unsupported_image"


class ConfigError(OcrError):
    code = "invalid_config"


class VlmConnectionError(OcrError):
    code = "vlm_connection_failed"


class VlmResponseError(OcrError):
    code = "vlm_invalid_response"
