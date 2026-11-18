"""One image -> vision model -> transcription and summary."""
from __future__ import annotations

import time
from pathlib import Path

from .config import VlmConfig
from .errors import OcrError, VlmResponseError
from .plain_text import plain_answer
from .ingest import load_image
from .vlm import analyze_with_vlm

ANALYSIS_SCHEMA_VERSION = "signspeak-analysis-1.1"


def analyze_image(
    source: str | Path | bytes,
    *,
    vlm_config: VlmConfig | None = None,
    include_debug: bool = False,
    keep_image_url: bool = False,
) -> dict:
    config = vlm_config or VlmConfig()
    config.validate()
    started = time.perf_counter()
    result = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "text": "", "summary": None, "text_status": "unknown", "language": "none",
        "confidence": {"text": None, "summary": None},
        "uncertainties": [], "input": None, "errors": [],
        "validation": {"overall_status": "failed"},
    }
    stage = "ingest"
    try:
        loaded = load_image(source)
        result["input"] = loaded.metadata
        stage = "vlm"
        vision = analyze_with_vlm(loaded.working, config, include_debug=include_debug,
                                  keep_image_url=keep_image_url)
        if keep_image_url:
            result["image_url"] = vision.pop("image_url")
        summary = plain_answer(vision["summary"])
        if not summary:
            raise VlmResponseError("Model returned no readable image summary")
        result.update(text=vision["extracted_text"], summary=summary,
                      text_status=vision["text_status"], language=vision["language"],
                      uncertainties=vision["uncertainties"], confidence=vision["confidence"])
        result["validation"]["overall_status"] = (
            "partial" if vision["uncertainties"] or vision["text_status"] == "unreadable" else "ok"
        )
        if include_debug:
            result["model_response"] = vision
    except OcrError as error:
        result["errors"].append(error.to_dict(stage))
    result["timings_ms"] = {"total": round((time.perf_counter() - started) * 1000, 1)}
    return result


def render_report(result: dict) -> str:
    text = result["text"] or (
        "[No visible text]" if result.get("text_status") == "no_text"
        else "[Text could not be extracted]"
    )
    return f"Extracted text:\n{text}\n\nSummary of the image:\n{result['summary'] or '[Unavailable]'}"
