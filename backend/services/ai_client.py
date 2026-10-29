"""The only file that knows the AI service's URL and endpoints.

Contract:
  POST /v1/ocr   multipart file                -> { "text": ... }
  POST /v1/tts   { text, voice }               -> audio/mpeg bytes
  POST /v1/stt   multipart file                -> { "text": ... }
  POST /v1/reply { message, context, history } -> { "reply": ... }
"""

import httpx
from fastapi import HTTPException

from config import get_settings


def _client() -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        base_url=settings.ai_base_url.rstrip("/"),
        timeout=settings.ai_timeout_seconds,
    )


def _map_error(exc: Exception) -> HTTPException:
    # Turn transport failures into status codes the frontend can handle.
    if isinstance(exc, httpx.TimeoutException):
        return HTTPException(status_code=504, detail="AI service timed out")
    if isinstance(exc, httpx.HTTPStatusError):
        return HTTPException(
            status_code=502,
            detail=f"AI service error ({exc.response.status_code})",
        )
    return HTTPException(status_code=503, detail="AI service unreachable")


async def ocr(data: bytes, filename: str, content_type: str) -> dict:
    # Raw image bytes in, extracted text out. Image formats are the AI's problem.
    try:
        async with _client() as client:
            response = await client.post(
                "/v1/ocr",
                files={"file": (filename, data, content_type)},
            )
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise _map_error(exc) from exc


async def tts(text: str) -> bytes:
    # Text in, mp3 bytes out. The voice is configured once in config.py.
    try:
        async with _client() as client:
            response = await client.post(
                "/v1/tts",
                json={"text": text, "voice": get_settings().tts_voice},
            )
            response.raise_for_status()
            return response.content
    except httpx.HTTPError as exc:
        raise _map_error(exc) from exc


async def stt(data: bytes, filename: str, content_type: str) -> str:
    # Recorded clip in, transcript out (used only by the chat route).
    try:
        async with _client() as client:
            response = await client.post(
                "/v1/stt",
                files={"file": (filename, data, content_type)},
            )
            response.raise_for_status()
            return (response.json().get("text") or "").strip()
    except (httpx.HTTPError, ValueError) as exc:
        raise _map_error(exc) from exc


async def reply(message: str, context: str, history: list[dict]) -> str:
    # context = OCR text from the scan, history = earlier chat turns.
    try:
        async with _client() as client:
            response = await client.post(
                "/v1/reply",
                json={"message": message, "context": context, "history": history},
            )
            response.raise_for_status()
            return (response.json().get("reply") or "").strip()
    except (httpx.HTTPError, ValueError) as exc:
        raise _map_error(exc) from exc
