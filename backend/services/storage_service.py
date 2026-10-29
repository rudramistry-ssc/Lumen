"""Reads/writes generated mp3s on disk. Filenames are random and validated."""

import re
import uuid
from pathlib import Path

from config import get_settings

# Only names this service generated may be served back (blocks ../ tricks).
SAFE_AUDIO_NAME = re.compile(r"^[0-9a-f]{32}\.mp3$")


def save_audio(data: bytes) -> str:
    # Returns just the filename; the caller builds the /v1/media/... URL.
    name = f"{uuid.uuid4().hex}.mp3"
    path = Path(get_settings().media_dir) / name
    path.write_bytes(data)
    return name


def audio_path(name: str) -> Path | None:
    # None means "not ours / doesn't exist", which the route turns into a 404.
    if not SAFE_AUDIO_NAME.match(name):
        return None
    path = Path(get_settings().media_dir) / name
    return path if path.is_file() else None
