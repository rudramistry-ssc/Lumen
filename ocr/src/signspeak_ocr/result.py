"""Build the structured JSON result from parsed OCR and mapped geometry."""

from __future__ import annotations

import re
from typing import Any

from .config import PipelineConfig
from .geometry import TransformChain, union_box
from .language import aggregate_languages, detect_line_language
from .tsv import TsvDocument, Word, confidence_summary

SCHEMA_VERSION = "signspeak-ocr-1.0"
_DIGIT = re.compile(r"\d")


def _word_flags(word: Word, config: PipelineConfig) -> list[str]:
    flags = list(word.flags)
    if word.confidence is not None and word.confidence < config.low_confidence_threshold:
        flags.append("low_confidence")
    return flags


def _region_flags(summary: dict[str, Any], config: PipelineConfig) -> list[str]:
    flags: list[str] = []
    mean = summary.get("mean")
    low = summary.get("low_conf_fraction")
    if mean is None:
        flags.append("confidence_unavailable")
    elif mean < config.region_low_mean_confidence:
        flags.append("low_mean_confidence")
    if low is not None and low > config.region_many_low_conf_fraction:
        flags.append("many_low_conf_words")
    return flags


def build_text_content(
    document: TsvDocument,
    chain: TransformChain,
    config: PipelineConfig,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    """Regions (one per Tesseract block), reading order, numeric index, text."""

    to_reference = chain.working_to_reference()
    regions: list[dict[str, Any]] = []
    numeric_values: list[dict[str, Any]] = []
    language_weights: list[tuple[str, int]] = []
    line_heights: list[float] = []
    counters = {"P": 0, "L": 0, "W": 0, "N": 0}

    def next_id(prefix: str) -> str:
        counters[prefix] += 1
        return f"{prefix}{counters[prefix]}"

    for region_index, block in enumerate(document.blocks, start=1):
        region_id = f"R{region_index}"
        block_words = list(block.iter_words())
        paragraphs_out: list[dict[str, Any]] = []
        lines_out: list[dict[str, Any]] = []
        paragraph_texts: list[str] = []
        region_language: list[tuple[str, int]] = []
        for paragraph in block.paragraphs:
            paragraph_id = next_id("P")
            paragraph_line_ids: list[str] = []
            paragraph_lines: list[str] = []
            for line in paragraph.lines:
                line_id = next_id("L")
                line_box = line.word_bbox or line.bbox
                line_heights.append(line_box[3] - line_box[1])
                words_out: list[dict[str, Any]] = []
                for word in line.words:
                    word_id = next_id("W")
                    flags = _word_flags(word, config)
                    word_record = {
                        "id": word_id,
                        "text": word.text,
                        **chain.map_box_to_reference(word.bbox, to_reference).to_dict(),
                        "confidence": None if word.confidence is None else round(word.confidence, 2),
                        "flags": flags,
                    }
                    words_out.append(word_record)
                    if _DIGIT.search(word.text):
                        numeric_values.append({
                            "id": next_id("N"),
                            "raw": word.text,
                            "word_id": word_id,
                            "line_id": line_id,
                            "region_id": region_id,
                            "bbox": word_record["bbox"],
                            "confidence": word_record["confidence"],
                            "status": "single_read_unverified",
                            "flags": [flag for flag in flags if flag == "low_confidence"],
                        })
                line_text = line.text
                language = detect_line_language(line_text)
                characters = len(line_text.replace(" ", ""))
                region_language.append((language["code"], characters))
                language_weights.append((language["code"], characters))
                summary = confidence_summary(line.words, config.low_confidence_threshold)
                lines_out.append({
                    "id": line_id,
                    "paragraph_id": paragraph_id,
                    "text": line_text,
                    **chain.map_box_to_reference(line_box, to_reference).to_dict(),
                    "confidence": summary,
                    "language": language,
                    "flags": ["contains_low_confidence_words"]
                    if any("low_confidence" in w["flags"] for w in words_out) else [],
                    "words": words_out,
                })
                paragraph_line_ids.append(line_id)
                paragraph_lines.append(line_text)
            paragraph_box = union_box(
                (line.word_bbox or line.bbox) for line in paragraph.lines
            )
            paragraphs_out.append({
                "id": paragraph_id,
                **chain.map_box_to_reference(paragraph_box, to_reference).to_dict(),
                "line_ids": paragraph_line_ids,
            })
            paragraph_texts.append("\n".join(paragraph_lines))

        region_box = union_box(word.bbox for word in block_words)
        summary = confidence_summary(block_words, config.low_confidence_threshold)
        region_language_summary = aggregate_languages(region_language)
        regions.append({
            "id": region_id,
            "type": "text_block",
            "reading_order": region_index,
            **chain.map_box_to_reference(region_box, to_reference).to_dict(),
            "text": "\n\n".join(paragraph_texts),
            "language": region_language_summary["primary"],
            "confidence": summary,
            "status": "ok",
            "coverage": "complete",
            "classification": {"source": "tesseract_layout", "evidence": ["tesseract_block"]},
            "provenance": {**provenance, **getattr(block, "provenance", {})},
            "flags": _region_flags(summary, config),
            "paragraphs": paragraphs_out,
            "lines": lines_out,
        })

    full_text = "\n\n".join(region["text"] for region in regions)
    return {
        "regions": regions,
        "numeric_values": numeric_values,
        "language": aggregate_languages(language_weights),
        "line_heights": line_heights,
        "text": full_text,
        "reading_order": {
            "source": "tesseract_layout",
            "confidence": "unverified",
            "sequence": [region["id"] for region in regions],
        },
    }


def render_text_view(regions: list[dict[str, Any]], low_threshold: float) -> str:
    """Deterministic agent-facing rendering; uncertain words are marked."""

    parts: list[str] = []
    for region in regions:
        mean = region["confidence"].get("mean")
        header = f"[{region['id']} {region['type']} conf={'?' if mean is None else round(mean)}"
        if region["flags"]:
            header += " flags=" + ",".join(region["flags"])
        lines = []
        for line in region["lines"]:
            tokens = []
            for word in line["words"]:
                confidence = word["confidence"]
                uncertain = confidence is None or confidence < low_threshold
                tokens.append(f"{word['text']}⟨?⟩" if uncertain else word["text"])
            lines.append(" ".join(tokens))
        parts.append(header + "]\n" + "\n".join(lines))
    return "\n\n".join(parts)


def peak_memory_mb() -> dict[str, float | None]:
    """Peak resident memory of this process and of finished children (Tesseract)."""

    try:
        import resource
        import sys

        divisor = 1024.0 * 1024.0 if sys.platform == "darwin" else 1024.0
        self_peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / divisor
        child_peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / divisor
        return {"process_peak_rss_mb": round(self_peak, 1), "children_peak_rss_mb": round(child_peak, 1)}
    except (ImportError, AttributeError, ValueError):
        pass
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        if ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
            return {"process_peak_rss_mb": round(counters.PeakWorkingSetSize / 1048576, 1),
                    "children_peak_rss_mb": None}
    except (AttributeError, OSError):
        pass
    return {"process_peak_rss_mb": None, "children_peak_rss_mb": None}
