"""Replay the existing three-way pilot through selection; no OCR/model requests."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT/"src"), str(ROOT.parent/"ocr/src")]
from signspeak_llm.document import build_document
from reconcile_pilot import accuracy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT/"reconciliation-pilot-results.json")
    parser.add_argument("--output", type=Path, default=ROOT/"document-selection-results.json")
    args = parser.parse_args()
    previous = json.loads(args.input.read_text(encoding="utf-8"))
    report = {"method": "Selection-only replay of first recorded complete outputs; no tuning, new model inference or real-photo validation.",
              "source": str(args.input), "real_photo_validation": "pending", "rows": []}
    for item in previous["manifest"]:
        rows = [r for r in previous["rows"] if r["id"] == item["id"]]
        ocr = next(r for r in rows if r["mode"] == "ocr_only")
        readings = {}
        for mode in ("vision_only", "hybrid"):
            row = next(r for r in rows if r["mode"] == mode)
            raw = row.get("raw_model_json")
            try: sections = json.loads(raw)["sections"] if isinstance(raw, str) else raw["sections"]
            except (ValueError, KeyError, TypeError): sections = [{"text": row["model_text"]}] if row.get("model_text") else []
            readings[mode] = {**row, "sections": sections}
        context = {"selected_text": ocr["text"], "regions": [{"id": "R1", "text": ocr["text"]}]}
        selected = build_document(context, readings, item["id"])
        scores = {"ocr_only": accuracy(item["expected_text"], ocr["text"]),
                  **{mode: accuracy(item["expected_text"], reading.get("model_text") or "") for mode, reading in readings.items()},
                  "selected": accuracy(item["expected_text"], selected["text"])}
        missing = list((Counter(item["expected_text"].split())-Counter(selected["text"].split())).elements())
        added = list((Counter(selected["text"].split())-Counter(item["expected_text"].split())).elements())
        normalize = lambda text: " ".join(text.split())
        positions = [normalize(selected["text"]).find(normalize(line)) for line in item["expected_reading_order"]]
        report["rows"].append({"id": item["id"], "origin": item["origin"], "selected_method": selected["selected_method"],
            "selection_reason": selected["selection_reason"], "text": selected["text"], "accuracy": scores,
            "omitted_reference_tokens": missing, "added_tokens_not_in_reference": added,
            "reference_passages_in_order": all(p >= 0 for p in positions) and positions == sorted(positions),
            "order_check_limit": "Exact reference passage matching; failures may be spelling/punctuation errors, not proven order errors."})
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__": main()
