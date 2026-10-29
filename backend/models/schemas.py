"""Response shapes returned by the API (requests are plain forms/files)."""

from pydantic import BaseModel


class SessionOut(BaseModel):
    session_id: str
    text: str          # OCR result; empty until an image is uploaded
    language: str      # e.g. "en"; empty until OCR detects something
    created_at: str


class ScanOut(BaseModel):
    session_id: str
    text: str          # what the AI service read from the image
    language: str      # detected language tag (shown in the UI)
    confidence: float | None = None  # OCR confidence 0-1, if the AI service reports it
    audio_url: str     # relative, e.g. /v1/media/<id>.mp3 or .wav; "" while TTS is off
    ms: int            # total OCR + TTS time, handy during the demo


class ChatOut(BaseModel):
    transcript: str    # what the user said (STT) or typed
    reply: str         # answer, grounded in the scanned text
    audio_url: str     # spoken version of the reply; "" while TTS is off
