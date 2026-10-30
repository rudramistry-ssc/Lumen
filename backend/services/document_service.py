"""Bridge image uploads to the bounded, vision-first AI processor."""

import io
import logging
import threading
from functools import lru_cache
from typing import TYPE_CHECKING, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, JsonValue, TypeAdapter
from starlette.concurrency import run_in_threadpool

from config import get_settings
from models.schemas import ScanOut
from services import session_service

logger = logging.getLogger(__name__)
inference_slot = threading.BoundedSemaphore(1)
_json_document = TypeAdapter(dict[str, JsonValue])

if TYPE_CHECKING:
    from signspeak_llm import DocumentProcessor


class DisplayView(BaseModel):
    text: str
    sections: list[dict[str, JsonValue]]


class SpeechView(BaseModel):
    text: str
    segments: list[dict[str, JsonValue]]


class SelectedViews(BaseModel):
    display: DisplayView
    speech: SpeechView
    llm_context: dict[str, JsonValue]


class ProcessorResult(BaseModel):
    status: Literal[
        "needs_review", "ocr_unreviewed_fallback", "processing_failed", "deadline_exceeded"
    ]
    document_id: str | None = None
    text: str = ""
    selected_views: SelectedViews | None = None
    selected_method: str | None = None
    printed_text_status: str | None = None
    visual_descriptions: list[dict[str, JsonValue]] = Field(default_factory=list)
    text_observations: list[dict[str, JsonValue]] = Field(default_factory=list)
    warnings: list[JsonValue] = Field(default_factory=list)
    ocr_comparison: dict[str, JsonValue] | None = None
    guardrails: dict[str, JsonValue] | None = None
    cache_hit: bool = False
    execution_this_call: dict[str, int] = Field(default_factory=dict)


@lru_cache
def get_processor() -> "DocumentProcessor":
    from signspeak_llm import DocumentProcessor, LocalLLM, Reconciler

    settings = get_settings()
    return DocumentProcessor(
        reconciler=Reconciler(
            LocalLLM(
                base_url=settings.signspeak_llm_url,
                context_size=8192,
                max_tokens=1536,
                timeout=480,
            ),
            max_edge=2048,
        ),
        cache_dir=settings.document_cache_dir,
        processing_timeout_seconds=settings.document_timeout_seconds,
    )


def _validate_image(data: bytes) -> None:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > get_settings().max_image_pixels:
                raise HTTPException(status_code=413, detail="Image dimensions too large")
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Invalid or unsupported image") from exc
    except Image.DecompressionBombError as exc:
        raise HTTPException(status_code=413, detail="Image dimensions too large") from exc


def _process_document(session_id: str, data: bytes) -> ScanOut:
    if not inference_slot.acquire(blocking=False):
        raise HTTPException(
            status_code=503,
            detail="AI processing is busy. Please retry when it finishes.",
            headers={"Retry-After": "5"},
        )
    try:
        try:
            _validate_image(data)
            processor = get_processor()
        except ImportError as exc:
            logger.exception("Document processing dependencies are missing")
            raise HTTPException(
                status_code=503,
                detail="Document processing is not installed. See backend/README.md.",
            ) from exc
        try:
            document = _json_document.validate_python(processor.process(data))
            result = ProcessorResult.model_validate(document)
        except TimeoutError as exc:
            logger.exception("Document processor exceeded its deadline")
            raise HTTPException(status_code=504, detail="Document processing timed out") from exc
        except (OSError, ValueError) as exc:
            logger.exception("Document processor failed; no automatic retry was attempted")
            raise HTTPException(
                status_code=502,
                detail="Document processing failed. Inspect backend logs and the document cache.",
            ) from exc

        if result.status in ("processing_failed", "deadline_exceeded"):
            session_service.set_session_document(session_id, document, "", "")
            raise HTTPException(
                status_code=504 if result.status == "deadline_exceeded" else 502,
                detail={
                    "message": "No completed vision document was returned.",
                    "status": result.status,
                    "stage": document.get("stage"),
                    "error": document.get("error"),
                    "warnings": result.warnings,
                },
            )

        views = result.selected_views
        if (
            not result.document_id
            or views is None
            or result.text != views.display.text
            or result.text != views.speech.text
            or result.text != views.llm_context.get("selected_text")
            or document.get("schema_version") != "signspeak-selected-document-2"
        ):
            logger.error("Document processor returned inconsistent selected views")
            raise HTTPException(status_code=502, detail="Invalid selected document result")

        languages: set[str] = set()
        for item in [*views.speech.segments, *result.visual_descriptions]:
            code = item.get("language")
            if isinstance(code, str) and code in ("en", "fr"):
                languages.add(code)
        language = "mixed" if len(languages) == 2 else next(iter(languages), "")
        response = ScanOut(
            session_id=session_id,
            text=views.display.text,
            language=language,
            audio_url="",
            ms=0,
            document_id=result.document_id,
            status=result.status,
            selected_method=result.selected_method,
            printed_text_status=result.printed_text_status,
            sections=views.display.sections,
            visual_descriptions=result.visual_descriptions,
            text_observations=result.text_observations,
            warnings=result.warnings,
            ocr_comparison=result.ocr_comparison,
            guardrails=result.guardrails,
            cache_hit=result.cache_hit,
            execution_this_call=result.execution_this_call,
        )
        session_service.set_session_document(session_id, document, response.text, response.language)
        return response
    finally:
        inference_slot.release()


async def process_document(session_id: str, data: bytes) -> ScanOut:
    # Keep inference off the event loop; the processor owns its worker deadline.
    return await run_in_threadpool(_process_document, session_id, data)
