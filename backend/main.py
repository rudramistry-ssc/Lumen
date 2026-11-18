"""Image extraction, session chat and local speech; also serves the original UI."""
import logging
import os
import time
import urllib.request
from pathlib import Path
from contextlib import asynccontextmanager

from typing import Literal
from uuid import UUID

from fastapi import FastAPI, Form, HTTPException, UploadFile, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from signspeak_ocr import analyze_image
from signspeak_ocr.errors import ConfigError, VlmConnectionError, VlmResponseError
from signspeak_ocr.chat import answer_question
from config import get_settings
from sessions import SessionStore
from local_speech import speech_status, synthesize, transcribe, warm_speech

@asynccontextmanager
async def lifespan(app):
    await run_in_threadpool(warm_speech)
    yield


app = FastAPI(title="Lumen image reader", lifespan=lifespan)
LOG = logging.getLogger("uvicorn.error")
# Long enough for the model container to restart llama-server on the CPU.
MODEL_RESTART_WAIT_SECONDS = float(os.getenv("LUMEN_MODEL_RESTART_WAIT_SECONDS", "300"))
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
sessions = SessionStore()


@app.middleware("http")
async def current_frontend(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.endswith((".js", ".html")):
        response.headers["Cache-Control"] = "no-store"
    return response


class Confidence(BaseModel):
    text: int | None = Field(ge=0, le=100, strict=True)
    summary: int | None = Field(ge=0, le=100, strict=True)
    method: Literal["model_estimate"] = "model_estimate"


class Extraction(BaseModel):
    session_id: str
    text: str
    summary: str
    language: Literal["en", "fr", "mixed", "none"]
    summary_language: Literal["en", "fr"]
    confidence: Confidence


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    session_id: UUID
    message: str = Field(min_length=1, max_length=4000)
    language: Literal["en", "fr"] = "en"
    context_text: str = Field(default="", max_length=20000)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/extract", response_model=Extraction)
async def extract(image: UploadFile, session_id: UUID | None = Form(None)):
    try:
        data = await image.read(MAX_UPLOAD_BYTES + 1)
    finally:
        await image.close()
    if not data:
        raise HTTPException(422, "Choose a nonempty image.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Choose an image smaller than 10 MB.")
    if not (image.content_type or "").startswith("image/"):
        raise HTTPException(415, "Choose an image file.")

    session = sessions.reserve(str(session_id) if session_id else None, len(data))
    try:
        return await process_image(data, session)
    except BaseException:
        sessions.delete(session.id)
        raise


def invalid_response(result):
    """True (and logged) when only the model's answer failed validation."""
    errors = [e for e in result["errors"] if e["code"] == "vlm_invalid_response"]
    for error in errors:
        # Fixed validation messages only; never the image text or model output.
        LOG.warning("Model answer rejected: %s", error["message"])
    # A truncated answer would be truncated again: do not repeat it.
    retryable = [e for e in errors if not e["message"].startswith("Model output was truncated")]
    return result["validation"]["overall_status"] == "failed" and bool(retryable)


def model_restarting(result):
    """True when the model server dropped the request (crashed/restarting)."""
    return any(e["code"] == "vlm_connection_failed" and e.get("details", {}).get("server_restarting")
               for e in result["errors"])


def wait_for_model(config, seconds=None):
    """After a model-server crash, wait until it serves again.

    The qwen container restarts llama-server itself and falls back to the CPU
    if the GPU keeps failing, so the request can then be repeated safely.
    """
    seconds = MODEL_RESTART_WAIT_SECONDS if seconds is None else seconds
    url = config.base_url.rstrip("/").removesuffix("/v1") + "/health"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + seconds
    LOG.warning("The local model server dropped a request; waiting for it to restart.")
    while time.monotonic() < deadline:
        try:
            with opener.open(url, timeout=5) as response:
                if response.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(3)
    return False


async def process_image(data, session):
    try:
        config = get_settings().vlm_config()
        # Keep the image exactly as sent to the model, for follow-up chat.
        result = await run_in_threadpool(analyze_image, data, vlm_config=config, keep_image_url=True)
        if model_restarting(result) and await run_in_threadpool(wait_for_model, config):
            result = await run_in_threadpool(analyze_image, data, vlm_config=config, keep_image_url=True)
        # Small local models occasionally return JSON that breaks the strict
        # contract (e.g. a no_text result with a language). Retry once; the
        # server reuses the cached image, so only generation time is repeated.
        if invalid_response(result):
            result = await run_in_threadpool(analyze_image, data, vlm_config=config, keep_image_url=True)
            invalid_response(result)
    except (ConfigError, ValidationError):
        raise HTTPException(503, "The model connection is not configured correctly.") from None
    if result["validation"]["overall_status"] == "failed":
        codes = {error["code"] for error in result["errors"]}
        if codes & {"invalid_input", "unsupported_image", "image_too_large"}:
            raise HTTPException(422, "This image could not be read. Choose a JPG, PNG or WebP image.")
        if "vlm_connection_failed" in codes:
            raise HTTPException(503, "Cannot reach the local model, or it took too long. Check the qwen container with: docker compose logs qwen")
        raise HTTPException(502, "The model could not process this image. Please try again.")
    image_url = result.pop("image_url")
    sessions.finish_upload(session, image_url, result)
    return {"session_id": session.id, "text": result["text"], "summary": result["summary"],
            "language": result["language"],
            "summary_language": "fr" if config.summary_language.lower().startswith("fr") else "en",
            "confidence": {**result["confidence"], "method": "model_estimate"}}


@app.post("/api/chat")
async def chat(question: Question):
    session = sessions.begin_chat(str(question.session_id))
    try:
        config = get_settings().vlm_config()

        def ask():
            return answer_question(
                config, image_url=session.image_url,
                text=session.text, summary=session.summary, uncertainties=session.uncertainties,
                history=list(session.history), question=question.message,
                language=question.language, edited_text=question.context_text,
            )

        try:
            answer = await run_in_threadpool(ask)
        except VlmConnectionError as error:
            # History is only updated after success, so repeating is safe.
            if not (error.details.get("server_restarting")
                    and await run_in_threadpool(wait_for_model, config)):
                raise
            answer = await run_in_threadpool(ask)
        sessions.finish_chat(session, question.message, answer)
        return {"reply": answer, "language": question.language}
    except (ConfigError, ValidationError):
        raise HTTPException(503, "The model connection is not configured correctly.") from None
    except VlmConnectionError as error:
        if error.details.get("http_status") == 400:
            raise HTTPException(422, "The model could not accept this context. Try a shorter question or a New session.") from None
        raise HTTPException(503, "Cannot reach the local model, or it took too long. Check the qwen container and try again.") from None
    except VlmResponseError:
        raise HTTPException(502, "The model could not finish an answer. Please try again.") from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    finally:
        sessions.release_chat(session)


@app.delete("/api/sessions/{session_id}", status_code=204)
def delete_session(session_id: UUID):
    sessions.delete(str(session_id))


class SpeechText(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=1200)
    language: Literal["en", "fr"] = "en"


@app.get("/api/speech/status")
def local_speech_status():
    return speech_status()


@app.post("/api/speech/transcribe")
async def speech_to_text(audio: UploadFile, language: Literal["en", "fr"] = Form("en")):
    try:
        data = await audio.read(12 * 1024 * 1024 + 1)
    finally:
        await audio.close()
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(413, "This recording is too large. Record a shorter question.")
    if not data:
        raise HTTPException(422, "No audio was recorded.")
    text = await run_in_threadpool(transcribe, data, language)
    return {"text": text, "language": language}


@app.post("/api/speech/synthesize")
async def text_to_speech(request: SpeechText):
    audio = await run_in_threadpool(synthesize, request.text, request.language)
    return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
