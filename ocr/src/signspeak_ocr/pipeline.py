"""End-to-end Phase 1 pipeline: ingest -> quality -> Tesseract -> parse -> JSON."""

from __future__ import annotations

import platform
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

import numpy
import PIL

from . import __version__
from .config import PipelineConfig
from .errors import OcrError
from .evidence import attach_evidence
from .ingest import load_image
from .refine import refine
from .quality import assess_image, text_metrics
from .result import SCHEMA_VERSION, build_text_content, peak_memory_mb, render_text_view
from .tesseract import get_tesseract_info, run_tesseract_tsv
from .tsv import parse_tsv
from .validate import validate_result

T = TypeVar("T")

_NOT_IMPLEMENTED = {"status": "skipped", "reason": "not_implemented_in_phase_1"}
_ATTENTION_FLAGS = {"low_mean_confidence", "many_low_conf_words", "confidence_unavailable"}


class _StageRunner:
    def __init__(self) -> None:
        self.stages: dict[str, dict[str, Any]] = {}
        self.errors: list[dict[str, Any]] = []

    def run(self, name: str, function: Callable[[], T]) -> tuple[bool, T | None]:
        started = time.perf_counter()
        try:
            value = function()
        except OcrError as error:
            self._finish(name, started, "failed", error.code)
            self.errors.append(error.to_dict(name))
            return False, None
        except Exception as error:  # noqa: BLE001 - an unexpected bug must not lose partial results
            self._finish(name, started, "failed", "internal_error")
            self.errors.append({
                "stage": name,
                "code": "internal_error",
                "message": f"{type(error).__name__}: {error}",
                "recoverable": False,
            })
            return False, None
        self._finish(name, started, "ok", None)
        return True, value

    def _finish(self, name: str, started: float, status: str, code: str | None) -> None:
        record: dict[str, Any] = {
            "status": status,
            "duration_ms": round((time.perf_counter() - started) * 1000.0, 1),
        }
        if code:
            record["error_code"] = code
        self.stages[name] = record


def _skeleton(config: PipelineConfig) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "pipeline_version": __version__,
        "run_id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input": None,
        "engines": {
            "python": platform.python_version(),
            "platform": platform.platform(terse=True),
            "pillow": PIL.__version__,
            "numpy": numpy.__version__,
            "tesseract": None,
        },
        "config": config.to_dict(),
        "quality": None,
        "preprocessing": None,
        "language": {"primary": "unknown", "distribution": []},
        "regions": [],
        "reading_order": {"source": None, "confidence": None, "sequence": []},
        "text": "",
        "text_view": "",
        "tables": [],
        "forms": {"fields": [], "checkboxes": [], **_NOT_IMPLEMENTED},
        "visuals": [],
        "numeric_values": [],
        "tsv_summary": None,
        "validation": None,
        "stages": {},
        "timings_ms": {},
        "resources": {},
        "warnings": [],
        "errors": [],
    }


def extract_image(
    source: str | Path | bytes,
    config: PipelineConfig | None = None,
    *,
    file_name: str | None = None,
    include_debug: bool = False,
) -> dict[str, Any]:
    """Run OCR on one image and return the structured result (never raises for
    image or engine problems; those are reported in ``errors``)."""

    config = config or PipelineConfig()
    config.validate()
    started = time.perf_counter()
    result = _skeleton(config)
    runner = _StageRunner()
    warnings: list[str] = []
    debug: dict[str, Any] = {}

    ok, loaded = runner.run("ingest", lambda: load_image(source, config.ingest, file_name=file_name))
    if ok and loaded is not None:
        result["input"] = loaded.metadata
        warnings.extend(loaded.warnings)
        result["preprocessing"] = {
            "reference_space": "oriented_original",
            "working_size": list(loaded.working.size),
            "transforms": loaded.chain.to_dict(),
            "variants": [{"id": "original", "operations": [], "used_for": "full_image_ocr"}],
        }

        quality_ok, quality = runner.run("quality", lambda: assess_image(loaded.working, config.quality))
        if quality_ok:
            result["quality"] = quality

        engine_ok, info = runner.run("tesseract_engine", lambda: get_tesseract_info(config.tesseract))
        if engine_ok and info is not None:
            result["engines"]["tesseract"] = {
                "version": info.version,
                "cmd": info.cmd,
                "tessdata_dir": info.tessdata_dir,
                "languages_requested": list(config.tesseract.languages),
                "languages_available": list(info.languages),
            }
            ocr_ok, run = runner.run("ocr", lambda: run_tesseract_tsv(loaded.working, config.tesseract, info))
            if ocr_ok and run is not None:
                result["engines"]["tesseract"]["command"] = run.command
                if run.stderr_lines:
                    result["engines"]["tesseract"]["stderr"] = run.stderr_lines
                if include_debug:
                    debug["raw_tsv"] = run.tsv
                parse_ok, document = runner.run("parse", lambda: parse_tsv(run.tsv))
                if parse_ok and document is not None:
                    selected_variant = "original"
                    selection = None
                    if config.preprocessing.enabled:
                        refined_ok, refined = runner.run(
                            "preprocess_candidates",
                            lambda: refine(loaded.working, result["quality"], document, run, config, info),
                        )
                        if refined_ok and refined is not None:
                            document, run, selection, notes = refined
                            selected_variant = selection["selected"]
                            result["preprocessing"]["selection"] = selection
                            result["preprocessing"]["variants"].extend(selection["attempts"])
                            warnings.extend(notes)
                            result["engines"]["tesseract"]["command"] = run.command
                            if include_debug:
                                debug["selected_raw_tsv"] = run.tsv
                    warnings.extend(document.warnings)
                    provenance = {
                        "engine": "tesseract",
                        "engine_version": info.version,
                        "languages": list(config.tesseract.languages),
                        "psm": config.tesseract.psm,
                        "oem": config.tesseract.oem,
                        "variant": selected_variant,
                        "stage": "full_image_ocr",
                    }
                    assemble_ok, content = runner.run(
                        "assemble", lambda: build_text_content(document, loaded.chain, config, provenance)
                    )
                    if assemble_ok and content is not None:
                        result.update({
                            "regions": content["regions"],
                            "numeric_values": content["numeric_values"],
                            "language": content["language"],
                            "text": content["text"],
                            "reading_order": content["reading_order"],
                        })
                        result["text_view"] = render_text_view(content["regions"], config.low_confidence_threshold)
                        if selection is not None and selection.get('reading_order'):
                            result['reading_order'].update({key:value for key,value in selection['reading_order'].items() if key!='columns'})
                        if selection is not None:
                            attach_evidence(result, selection, loaded.chain, config.low_confidence_threshold)
                        if result["quality"] is not None:
                            metrics = text_metrics(content["line_heights"], config.quality)
                            result["quality"]["text_metrics"] = metrics
                            result["quality"]["reasons"] = result["quality"]["reasons"] + metrics["reasons"]
                            if metrics["reasons"] and result["quality"]["assessment"] == "good":
                                result["quality"]["assessment"] = "fair"
                        result["tsv_summary"] = {
                            "rows": document.row_count,
                            "word_rows": document.word_row_count,
                            "empty_word_rows": document.empty_word_rows,
                            "malformed_rows": document.malformed_rows,
                        }

    for name in ("table_detection", "form_extraction", "visual_detection", "numeric_verification"):
        runner.stages[name] = dict(_NOT_IMPLEMENTED)

    result["warnings"] = list(dict.fromkeys(warnings))
    result["errors"] = runner.errors
    result["stages"] = runner.stages
    result["validation"] = _validation(result, runner)
    problems = validate_result(result)
    if problems:
        result["validation"]["schema_problems"] = problems
        if result["validation"]["overall_status"] == "ok":
            result["validation"]["overall_status"] = "partial"
    if include_debug:
        result["debug"] = debug
    result["timings_ms"] = {
        name: stage["duration_ms"] for name, stage in runner.stages.items() if "duration_ms" in stage
    }
    result["timings_ms"]["total"] = round((time.perf_counter() - started) * 1000.0, 1)
    result["resources"] = peak_memory_mb()
    return result


def _validation(result: dict[str, Any], runner: _StageRunner) -> dict[str, Any]:
    essential = ("ingest", "tesseract_engine", "ocr", "parse", "assemble")
    essential_ok = all(runner.stages.get(name, {}).get("status") == "ok" for name in essential)
    any_failed = any(stage.get("status") == "failed" for stage in runner.stages.values())
    word_count = sum(len(line["words"]) for region in result["regions"] for line in region["lines"])
    warnings: list[str] = []
    if not essential_ok:
        status, text_coverage = "failed", "missing"
    else:
        status = "partial" if any_failed else "ok"
        text_coverage = "complete" if word_count else "unknown"
        if not word_count:
            warnings.append("no_text_detected")
    requires_attention: list[dict[str, Any]] = []
    for region in result["regions"]:
        for flag in region["flags"]:
            if flag in _ATTENTION_FLAGS:
                requires_attention.append({"ref": region["id"], "reason": flag})
    for value in result["numeric_values"]:
        if "low_confidence" in value["flags"]:
            requires_attention.append({"ref": value["id"], "reason": "numeric_low_confidence"})
    evidence = result.get("evidence", {})
    for word_id in evidence.get("uncertain_word_ids", []):
        requires_attention.append({"ref": word_id, "reason": "ocr_evidence_uncertain"})
    if evidence.get("numeric_conflicts"):
        requires_attention.append({"ref": "evidence", "reason": "numeric_disagreement"})
    if evidence.get("uncertain_word_ids") or evidence.get("numeric_conflicts"):
        text_coverage = "unknown"
        if status == "ok":
            status = "partial"
    return {
        "overall_status": status,
        "coverage": {"text": text_coverage, "tables": "not_assessed", "visuals": "not_assessed"},
        "word_count": word_count,
        "numeric_verification": "not_performed",
        "warnings": warnings,
        "requires_attention": requires_attention,
    }
