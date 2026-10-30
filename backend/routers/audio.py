"""Local transcript preparation plus the legacy stored-clip endpoint."""

import time
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from config import get_settings
from models.schemas import ClipOut, TranscriptionOut
from services import conversation_service, session_service, storage_service

router = APIRouter(tags=["audio"])


@router.post("/sessions/{session_id}/transcribe", response_model=TranscriptionOut)
async def transcribe_audio(
    session_id: str,
    file: UploadFile,
    language: Literal["auto", "en", "fr"] = Form("auto"),
):
    if session_service.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    limit = min(get_settings().max_audio_mb * 1024 * 1024, 8_000_000)
    data = await file.read(limit + 1)
    if not data:
        raise HTTPException(status_code=422, detail="Empty audio")
    if len(data) > limit:
        raise HTTPException(status_code=413, detail="Audio too large")
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if not content_type.startswith("audio/") or content_type not in storage_service.CLIP_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported audio format")
    return await run_in_threadpool(
        conversation_service.prepare_question, session_id, data, language
    )


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
