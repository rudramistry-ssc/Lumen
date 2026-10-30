"""Local transcription; importing does not start processes or download models."""
from .engine import WhisperSTT, convert_audio, transcribe

__all__ = ["WhisperSTT", "transcribe", "convert_audio"]
