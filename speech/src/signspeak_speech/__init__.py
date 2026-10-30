"""Offline document read-aloud; no services, audio hardware or LLM calls."""
from .engine import MissingVoiceError, PiperSpeech, SpeechError, SpeechResult, UnsupportedLanguageError

__all__ = ["PiperSpeech", "SpeechResult", "SpeechError", "MissingVoiceError", "UnsupportedLanguageError"]
