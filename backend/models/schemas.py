"""Response shapes returned by the API (requests are plain forms/files)."""

from pydantic import BaseModel, Field, JsonValue


class SessionOut(BaseModel):
    session_id: str
    text: str          # OCR result; empty until an image is uploaded
    language: str      # e.g. "en"; empty until OCR detects something
    created_at: str
    document_id: str | None = None
    document_status: str | None = None


class ScanOut(BaseModel):
    session_id: str
    text: str          # what the AI service read from the image
    language: str      # detected language tag (shown in the UI)
    audio_url: str     # relative, e.g. /v1/media/<id>.mp3; "" while TTS is off
    ms: int            # total OCR + TTS time, handy during the demo
    document_id: str | None = None
    status: str | None = None
    selected_method: str | None = None
    printed_text_status: str | None = None
    sections: list[dict[str, JsonValue]] = Field(default_factory=list)
    visual_descriptions: list[dict[str, JsonValue]] = Field(default_factory=list)
    text_observations: list[dict[str, JsonValue]] = Field(default_factory=list)
    warnings: list[JsonValue] = Field(default_factory=list)
    ocr_comparison: dict[str, JsonValue] | None = None
    guardrails: dict[str, JsonValue] | None = None
    cache_hit: bool = False
    execution_this_call: dict[str, int] = Field(default_factory=dict)


class DocumentOut(BaseModel):
    session_id: str
    document: dict[str, JsonValue]


class ClipOut(BaseModel):
    session_id: str
    clip_id: str       # generated filename, e.g. <32 hex>.webm
    audio_url: str     # /v1/media/<clip_id>, playable in the UI
    bytes: int         # stored size
    content_type: str  # what the browser sent, e.g. audio/webm
    ms: int            # time spent storing, shown in the demo


class ChatOut(BaseModel):
    transcript: str    # what the user said (STT) or typed
    reply: str         # answer, grounded in the scanned text
    audio_url: str     # spoken version of the reply
    status: str | None = None
    language: str | None = None
    guardrails: dict[str, JsonValue] | None = None
    warnings: list[JsonValue] = Field(default_factory=list)
    errors: list[dict[str, JsonValue]] = Field(default_factory=list)
    timings: dict[str, JsonValue] = Field(default_factory=dict)
    history_turns: int | None = None


class ReadOut(BaseModel):
    audio_url: str
    metadata: dict[str, JsonValue]
