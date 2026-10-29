"""Structural invariants of a result. Used by the pipeline and the tests."""

from __future__ import annotations

from typing import Any

from .result import SCHEMA_VERSION

_TOLERANCE = 0.51


def _check_geometry(item: dict[str, Any], size: tuple[int, int], where: str, problems: list[str]) -> None:
    width, height = size
    bbox = item.get("bbox")
    if not (isinstance(bbox, list) and len(bbox) == 4):
        problems.append(f"{where}: missing bbox")
        return
    x0, y0, x1, y1 = bbox
    if not (-_TOLERANCE <= x0 <= x1 <= width + _TOLERANCE and -_TOLERANCE <= y0 <= y1 <= height + _TOLERANCE):
        problems.append(f"{where}: bbox {bbox} outside reference image {width}x{height}")
    polygon = item.get("polygon")
    if not (isinstance(polygon, list) and len(polygon) == 4):
        problems.append(f"{where}: missing polygon")
    norm = item.get("bbox_norm")
    if not (isinstance(norm, list) and len(norm) == 4 and all(0.0 <= v <= 1.0 for v in norm)):
        problems.append(f"{where}: invalid bbox_norm {norm}")


def validate_result(result: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if result.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"unexpected schema_version {result.get('schema_version')!r}")
    size_value = (result.get("input") or {}).get("oriented_size")
    regions = result.get("regions") or []
    if not size_value:
        if regions:
            problems.append("regions present without input.oriented_size")
        return problems
    size = (int(size_value[0]), int(size_value[1]))
    ids: set[str] = set()
    word_ids: set[str] = set()

    def register(identifier: Any, where: str) -> None:
        if not isinstance(identifier, str) or not identifier:
            problems.append(f"{where}: missing id")
        elif identifier in ids:
            problems.append(f"{where}: duplicate id {identifier}")
        else:
            ids.add(identifier)

    for region in regions:
        register(region.get("id"), "region")
        _check_geometry(region, size, f"region {region.get('id')}", problems)
        line_ids = set()
        for paragraph in region.get("paragraphs") or []:
            register(paragraph.get("id"), "paragraph")
            _check_geometry(paragraph, size, f"paragraph {paragraph.get('id')}", problems)
        for line in region.get("lines") or []:
            register(line.get("id"), "line")
            line_ids.add(line.get("id"))
            _check_geometry(line, size, f"line {line.get('id')}", problems)
            words = line.get("words") or []
            if not words:
                problems.append(f"line {line.get('id')}: no words")
            if line.get("text") != " ".join(word.get("text", "") for word in words):
                problems.append(f"line {line.get('id')}: text differs from its words")
            for word in words:
                register(word.get("id"), "word")
                word_ids.add(word.get("id"))
                _check_geometry(word, size, f"word {word.get('id')}", problems)
                confidence = word.get("confidence")
                if confidence is not None and not 0 <= confidence <= 100:
                    problems.append(f"word {word.get('id')}: confidence {confidence} outside 0-100")
        for paragraph in region.get("paragraphs") or []:
            for line_id in paragraph.get("line_ids") or []:
                if line_id not in line_ids:
                    problems.append(f"paragraph {paragraph.get('id')}: unknown line {line_id}")

    region_ids = {region.get("id") for region in regions}
    sequence = (result.get("reading_order") or {}).get("sequence") or []
    if sorted(sequence) != sorted(region_ids) or len(sequence) != len(set(sequence)):
        problems.append("reading_order.sequence must list every region exactly once")
    for value in result.get("numeric_values") or []:
        register(value.get("id"), "numeric_value")
        if value.get("word_id") not in word_ids:
            problems.append(f"numeric_value {value.get('id')}: unknown word {value.get('word_id')}")
    return problems
