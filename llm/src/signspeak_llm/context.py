"""Loss-aware compact evidence; no OCR mutation, retrieval or text filtering."""
from copy import deepcopy
import json

_GEOMETRY = {"bbox", "bbox_norm", "polygon", "provenance", "speech_segment_ids"}


def _without_geometry(value):
    if isinstance(value, dict):
        return {k: _without_geometry(v) for k, v in value.items() if k not in _GEOMETRY}
    if isinstance(value, list):
        return [_without_geometry(v) for v in value]
    return deepcopy(value)


def compact_context(source):
    """Keep all regions/text, literal alternatives and warnings, omit geometry.

    The selected text is omitted ONLY when reproduced exactly by region text in
    reading order. Any mismatch remains available as selected_text verbatim.
    """
    regions = source["regions"]
    ids = [r["id"] for r in regions]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate OCR region IDs")
    order = (source.get("reading_order") or {}).get("sequence", [])
    sequence = list(dict.fromkeys(i for i in order if i in ids))
    sequence.extend(i for i in ids if i not in sequence)
    by_id = {r["id"]: r for r in regions}
    result = {"verification": "not_performed", "reading_order": sequence,
              "regions": [{k: _without_geometry(by_id[i][k]) for k in (
                  "id", "text", "text_state", "language", "flags", "coverage", "tentative_words")
                  if k in by_id[i] and by_id[i][k] not in (None, [], "")} for i in sequence]}
    reconstructed = "\n\n".join(by_id[i].get("text", "") for i in sequence)
    if reconstructed != source["selected_text"]:
        result["selected_text"] = source["selected_text"]
    for key in ("numeric_values", "numeric_conflicts", "warnings", "errors", "validation", "language",
                "visual_descriptions", "text_observations", "ocr_discrepancies"):
        if source.get(key):
            result[key] = _without_geometry(source[key])
    if sequence != order:
        result["reading_order_notice"] = "Incomplete source order; remaining source regions appended without deleting text."
    return result


def render_context(source, mode):
    if mode not in {"full", "compact"}:
        raise ValueError("context_mode must be full or compact")
    view = source if mode == "full" else compact_context(source)
    return json.dumps(view, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
