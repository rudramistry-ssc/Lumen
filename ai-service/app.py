"""The AI service: OCR, text to speech, speech to text and chat answers.

The backend is its only client (see backend/services/ai_client.py):
  POST /v1/ocr   multipart file                          -> { text, language, confidence }
  POST /v1/tts   { text, voice?, language? }             -> audio/wav bytes
  POST /v1/stt   multipart file                          -> 501, not set up (see README)
  POST /v1/reply { message, context, history, language? } -> { reply }
"""

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

import llm
import tts
from config import get_settings
from signspeak_ocr import PipelineConfig, PreprocessConfig, extract_image
from signspeak_ocr.tesseract import get_tesseract_info

app = FastAPI(title="CanAI Team E AI service")

# Same settings as the team's ocr/service.py, so both give the same text.
OCR_CONFIG = PipelineConfig(preprocessing=PreprocessConfig(enabled=get_settings().ocr_preprocess))


def _confidence(result: dict) -> float | None:
    # Mean word confidence (0-100 from Tesseract), weighted by region length, as 0-1.
    pairs = [
        (region["confidence"].get("mean"), len(region.get("text", "")))
        for region in result.get("regions", [])
        if isinstance(region.get("confidence"), dict)
    ]
    pairs = [(mean, size) for mean, size in pairs if mean is not None and size]
    total = sum(size for _, size in pairs)
    if not total:
        return None
    return round(sum(mean * size for mean, size in pairs) / total / 100, 3)


@app.post("/v1/ocr")
def ocr(file: UploadFile):
    # Plain `def`: OCR is slow CPU work, so FastAPI runs it in a worker thread.
    result = extract_image(file.file.read(), OCR_CONFIG, file_name=file.filename)
    if result["validation"]["overall_status"] == "failed":
        raise HTTPException(status_code=422, detail=result["errors"])

    language = result["language"]["primary"]
    return {
        "text": result["text"],
        "language": "" if language == "unknown" else language,
        "confidence": _confidence(result),
    }


class TtsIn(BaseModel):
    text: str
    voice: str | None = None      # sent by the backend; voices are picked by language here
    language: str = "en"


@app.post("/v1/tts")
def text_to_speech(body: TtsIn):
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="Empty text")
    try:
        audio = tts.synthesize(body.text, body.language)
    except tts.TtsError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=audio, media_type="audio/wav")


@app.post("/v1/stt")
def speech_to_text(file: UploadFile):
    # The frontend uses the browser's speech recognition, so nothing calls this yet.
    raise HTTPException(
        status_code=501,
        detail="Speech to text is not set up. Add Whisper here for offline voice input.",
    )


class ReplyIn(BaseModel):
    message: str
    context: str = ""
    history: list[dict] = []
    language: str = "en"


@app.post("/v1/reply")
async def reply(body: ReplyIn):
    try:
        answer = await llm.reply(body.message, body.context, body.history, body.language)
    except llm.LlmError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"reply": answer}


@app.get("/healthz")
async def healthz():
    # One place to see which parts work on this computer.
    try:
        # Raises if Tesseract or the eng/fra language data are missing.
        info = get_tesseract_info(OCR_CONFIG.tesseract)
        ocr_status = {"ok": True, "detail": f"tesseract {info.version}"}
    except Exception as exc:  # noqa: BLE001 - report, don't crash the health check
        ocr_status = {"ok": False, "detail": str(exc)}
    return {
        "status": "ok",
        "ocr": ocr_status,
        "llm": await llm.status(),
        "tts": {"ok": tts.engine() is not None, "detail": tts.engine() or "no speech engine found"},
        "stt": {"ok": False, "detail": "not set up (browser speech recognition is used)"},
    }
