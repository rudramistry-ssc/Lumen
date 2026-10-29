"""Reads/writes generated audio on disk. Filenames are random and validated."""

import re
import uuid
from pathlib import Path

from config import get_settings

# Only names this service generated may be served back (blocks ../ tricks).
SAFE_AUDIO_NAME = re.compile(r"^[0-9a-f]{32}\.(mp3|webm|ogg|wav|m4a)$")

MEDIA_TYPES = {
    ".mp3": "audio/mpeg",
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
}

# Browsers record to different containers: Chrome/Edge use WebM, Firefox Ogg,
# Safari MP4. Map the upload's Content-Type to the extension we store.
CLIP_EXTENSIONS = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
}


def _write(data: bytes, ext: str) -> str:
    # Returns just the filename; the caller builds the /v1/media/... URL.
    name = f"{uuid.uuid4().hex}{ext}"
    path = Path(get_settings().media_dir) / name
    path.write_bytes(data)
    return name


def save_audio(data: bytes) -> str:
    # Generated speech (TTS). Always mp3.
    return _write(data, ".mp3")


def clip_extension(content_type: str, filename: str = "") -> str | None:
    # Content-Type wins; the filename is a fallback for clients that send
    # application/octet-stream. None means "unsupported", which becomes a 415.
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype in CLIP_EXTENSIONS:
        return CLIP_EXTENSIONS[ctype]
    suffix = Path(filename or "").suffix.lower()
    return suffix if suffix in MEDIA_TYPES else None


def save_clip(data: bytes, ext: str) -> str:
    # A recording uploaded by the browser, kept for playback and later STT.
    return _write(data, ext)


def audio_path(name: str) -> Path | None:
    # None means "not ours / doesn't exist", which the route turns into a 404.
    if not SAFE_AUDIO_NAME.match(name):
        return None
    path = Path(get_settings().media_dir) / name
    return path if path.is_file() else None


def media_type(name: str) -> str:
    return MEDIA_TYPES.get(Path(name).suffix.lower(), "application/octet-stream")
