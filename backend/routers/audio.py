"""Microphone clips: store them now, transcribe them later.

The AI service has no /v1/stt yet, so this route deliberately stops at
"received and saved". It proves the browser can record and upload audio, and
gives the STT work a stable endpoint to hang off.
"""

import time

from fastapi import APIRouter, File, HTTPException, UploadFile

from config import get_settings
from models.schemas import ClipOut
from services import session_service, storage_service

router = APIRouter(tags=["audio"])


@router.post("/sessions/{session_id}/audio", response_model=ClipOut, status_code=201)
async def upload_audio(session_id: str, file: UploadFile):
    # A clip belongs to a session so it can later become a chat message.
    if session_service.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")

    data = await file.read()

    # Same cheap guards as image uploads, before anything touches the disk.
    if not data:
        raise HTTPException(status_code=422, detail="Empty audio")
    if len(data) > get_settings().max_audio_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio too large")
    if not (file.content_type or "").startswith("audio/"):
        raise HTTPException(status_code=415, detail="Expected audio")

    ext = storage_service.clip_extension(file.content_type, file.filename or "")
    if ext is None:
        raise HTTPException(status_code=415, detail="Unsupported audio format")

    started = time.perf_counter()
    name = storage_service.save_clip(data, ext)

    return {
        "session_id": session_id,
        "clip_id": name,
        "audio_url": f"/v1/media/{name}",
        "bytes": len(data),
        "content_type": file.content_type,
        "ms": int((time.perf_counter() - started) * 1000),
    }
