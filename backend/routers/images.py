"""Scan pipeline: validate upload → OCR → (optional) TTS → store the mp3."""

import time

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse

from config import get_settings
from models.schemas import ScanOut
from services import ai_client, session_service, storage_service

router = APIRouter(tags=["images"])


@router.post("/sessions/{session_id}/images", response_model=ScanOut)
async def upload_image(session_id: str, file: UploadFile):
    # A scan belongs to a session so the follow-up chat has context.
    if session_service.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")

    data = await file.read()

    # Cheap guards before we spend time on the AI service.
    if not data:
        raise HTTPException(status_code=422, detail="Empty file")
    if len(data) > get_settings().max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large")
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=415, detail="Expected an image")

    started = time.perf_counter()

    # The AI side owns image handling (EXIF, HEIC, OCR); we forward raw bytes.
    result = await ai_client.ocr(data, file.filename or "upload", file.content_type)
    text = (result.get("text") or "").strip()
    language = (result.get("language") or result.get("lang") or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="No readable text found")

    # Speak the text back (once TTS is enabled), then remember it as the
    # session's document. An empty audio_url means "text only".
    audio_url = ""
    if get_settings().tts_enabled:
        audio = await ai_client.tts(text)
        audio_url = f"/v1/media/{storage_service.save_audio(audio)}"
    session_service.set_session_scan(session_id, text, language)

    return {
        "session_id": session_id,
        "text": text,
        "language": language,
        "audio_url": audio_url,
        "ms": int((time.perf_counter() - started) * 1000),
    }


@router.get("/media/{name}")
def get_media(name: str):
    # storage_service only accepts names it generated, so no path traversal.
    path = storage_service.audio_path(name)
    if path is None:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(
        path,
        media_type=storage_service.media_type(name),
        headers={"Cache-Control": "public, max-age=86400"},
    )
