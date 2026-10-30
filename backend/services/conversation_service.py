"""Use the AI team's selected document and guarded Q&A without reprocessing."""

import logging
from functools import lru_cache
from typing import TYPE_CHECKING

from fastapi import HTTPException

from config import get_settings
from models.schemas import ChatOut, ReadOut
from services import document_service, session_service, storage_service

if TYPE_CHECKING:
    from signspeak_voice import DocumentSession, VoiceConversation

logger = logging.getLogger(__name__)


@lru_cache
def get_conversation() -> "VoiceConversation":
    from signspeak_llm import LocalLLM
    from signspeak_speech import PiperSpeech
    from signspeak_voice import VoiceConversation

    return VoiceConversation(
        llm=LocalLLM(base_url=get_settings().signspeak_llm_url, context_size=8192),
        speech=PiperSpeech(),
    )


def _session(session_id: str) -> "DocumentSession":
    from signspeak_voice import DocumentSession

    document = session_service.get_document(session_id)
    if document is None:
        raise HTTPException(status_code=409, detail="Upload an image before asking or reading.")
    if document.get("status") != "needs_review":
        raise HTTPException(
            status_code=409,
            detail="A selected vision document is required. OCR fallback is not used for Q&A.",
        )
    try:
        selected = DocumentSession.from_document(document)
        snapshot = selected.document
        return DocumentSession(
            snapshot["views"],
            records=snapshot["records"],
            session_id=session_id,
            history=session_service.conversation_history(session_id),
        )
    except ValueError as exc:
        logger.exception("Saved document or conversation cannot be restored")
        raise HTTPException(status_code=409, detail="Saved document or history is invalid.") from exc


def _acquire() -> None:
    if not document_service.inference_slot.acquire(blocking=False):
        raise HTTPException(
            status_code=503,
            detail="AI processing is busy. Please retry when it finishes.",
            headers={"Retry-After": "5"},
        )


def read_document(session_id: str, language: str, include_visual_descriptions: bool) -> ReadOut:
    _acquire()
    try:
        try:
            from signspeak_speech import SpeechError
        except ImportError as exc:
            logger.exception("Speech dependencies are missing")
            raise HTTPException(status_code=503, detail="Install backend/requirements-ai.txt first.") from exc
        try:
            session = _session(session_id)
            audio = get_conversation().read_document(
                session,
                language=language,
                include_visual_descriptions=include_visual_descriptions,
            )
            if not audio.wav_bytes:
                raise SpeechError("Piper returned no audio")
            name = storage_service.save_wav(audio.wav_bytes)
            return ReadOut(audio_url=f"/v1/media/{name}", metadata=audio.metadata)
        except (SpeechError, ImportError, OSError, ValueError) as exc:
            logger.exception("Document read-aloud failed")
            raise HTTPException(
                status_code=503,
                detail="Read-aloud failed. Check Piper dependencies, voice models and media storage.",
            ) from exc
    finally:
        document_service.inference_slot.release()


def answer_question(session_id: str, message: str, language: str) -> ChatOut:
    _acquire()
    try:
        try:
            session = _session(session_id)
            result = get_conversation().answer_question(session, message, language=language)
        except ImportError as exc:
            logger.exception("Conversation dependencies are missing")
            raise HTTPException(status_code=503, detail="Install backend/requirements-ai.txt first.") from exc
        if result["status"] == "error":
            logger.error("Document Q&A failed: %s", result["errors"])
            raise HTTPException(
                status_code=502,
                detail={"message": "Document Q&A failed. Check the local Qwen server.",
                        "errors": result["errors"]},
            )

        blocked = result["status"] == "blocked" or result.get("guardrails", {}).get("blocked")
        audio_url = ""
        if not blocked:
            session_service.add_turn(session_id, result["question"], result["answer"])
            if result["wav_bytes"]:
                try:
                    name = storage_service.save_wav(result["wav_bytes"])
                    audio_url = f"/v1/media/{name}"
                except OSError as exc:
                    logger.exception("Answer saved but speech file could not be written")
                    result["status"] = "text_only"
                    result["errors"].append({"stage": "media", "message": str(exc)})
            if result["errors"]:
                logger.warning("Answer returned with audio errors: %s", result["errors"])
        return ChatOut(
            transcript=message, reply=result["answer"], audio_url=audio_url,
            status=result["status"], language=language,
            guardrails=result.get("guardrails"), warnings=result["warnings"],
            errors=result["errors"], timings=result["timings"],
            history_turns=result["history_turns"],
        )
    finally:
        document_service.inference_slot.release()
