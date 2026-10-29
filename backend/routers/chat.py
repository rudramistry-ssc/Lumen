"""One conversation turn: user audio/text in, spoken answer out."""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from models.schemas import ChatOut
from services import ai_client, session_service, storage_service

router = APIRouter(tags=["chat"])


@router.post("/sessions/{session_id}/chat", response_model=ChatOut)
async def chat(
    session_id: str,
    message: str | None = Form(None),
    audio: UploadFile | None = File(None),
):
    session = session_service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Two ways in: typed text or a recorded clip (browser sends audio/webm).
    transcript = (message or "").strip()
    if audio is not None:
        data = await audio.read()
        if not data:
            raise HTTPException(status_code=422, detail="Empty audio")
        transcript = await ai_client.stt(
            data,
            audio.filename or "audio.webm",
            audio.content_type or "audio/webm",
        )
    if not transcript:
        raise HTTPException(status_code=422, detail="Provide 'message' or 'audio'")

    # Send prior turns plus the OCR text so the answer stays about this scan.
    history = session_service.recent_messages(session_id)
    session_service.add_message(session_id, "user", transcript)

    answer = await ai_client.reply(transcript, session["text"], history)
    if not answer:
        raise HTTPException(status_code=502, detail="AI service returned an empty reply")
    session_service.add_message(session_id, "assistant", answer)

    # Same TTS path as the scan, so the client always gets an mp3 URL.
    voice = await ai_client.tts(answer)
    name = storage_service.save_audio(voice)

    return {
        "transcript": transcript,
        "reply": answer,
        "audio_url": f"/v1/media/{name}",
    }
