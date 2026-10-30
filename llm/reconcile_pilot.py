"""Three-way pilot; default inputs are SYNTHETIC, never real-photo validation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import time

from signspeak_llm import LocalLLM, Reconciler
from signspeak_llm.reconciliation_checks import critical_literals
from signspeak_llm.server import Server, default_model_dir, memory_status, process_memory

ROOT = Path(__file__).resolve().parent


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def default_manifest():
    benchmark = ROOT.parent / "ocr/eval/benchmark"
    items = json.loads((benchmark / "manifest.json").read_text(encoding="utf-8"))
    return [{"id": item["id"], "image": str(benchmark / item["image"]), "sha256": item["sha256"],
             "origin": "synthetic", "expected_text": item["text"],
             "expected_reading_order": [line for line in item["text"].splitlines() if line],
             "reference_review": "Existing synthetic ground truth visually inspected against these three images; not independent human photo annotation."}
            for name in ("bilingual_shadow", "columns_photo", "nutrition_photo")
            for item in items if item["id"] == name]


def distance(a, b):
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        row = [i]
        for j, right in enumerate(b, 1):
            row.append(min(row[-1] + 1, previous[j] + 1, previous[j-1] + (left != right)))
        previous = row
    return previous[-1]


def accuracy(expected, actual):
    from collections import Counter
    import unicodedata
    normalize = lambda text: " ".join(unicodedata.normalize("NFC", text).split())
    a, b = normalize(expected), normalize(actual)
    return {"cer": distance(a, b) / max(1, len(a)), "wer": distance(a.split(), b.split()) / max(1, len(a.split())),
            "critical_reference": critical_literals(expected), "critical_output": critical_literals(actual),
            "critical_literals_missing_or_changed": list((Counter(critical_literals(expected)) - Counter(critical_literals(actual))).elements()),
            "critical_literals_added_or_changed": list((Counter(critical_literals(actual)) - Counter(critical_literals(expected))).elements()),
            "policy": "NFC + collapsed whitespace for CER/WER; case/accents/punctuation retained. Critical literal differences need manual classification, not all are quantity errors."}


def run(manifest_path=None, output=None, repeats=2):
    from signspeak_ocr import PipelineConfig, PreprocessConfig, extract_image
    from signspeak_ocr.integration import adapt_result
    if repeats < 1:
        raise ValueError("repeats must be positive")
    if manifest_path:
        manifest_path = Path(manifest_path).resolve()
        items = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in items:
            item["image"] = str((manifest_path.parent / item["image"]).resolve())
    else:
        items = default_manifest()
    output = Path(output) if output else ROOT / "runtime/reconciliation-pilot" / str(time.time_ns())
    if output.exists():
        raise FileExistsError("Use a new output directory to preserve earlier results")
    output.mkdir(parents=True)
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "manifest": items, "rows": [],
              "real_photo_validation": "pending" if any(i["origin"] == "synthetic" for i in items) else "pilot only",
              "platform": platform.platform(), "python": platform.python_version(), "logical_processors": os.cpu_count(),
              "memory_before": memory_status(), "method": "Same original bytes, preparation and server for both VLM modes. No application cache for measured requests. First request of each mode/image disables prompt reuse; immediate repeat enables it. OS file cache uncontrolled. Fallback text never substituted into model accuracy metrics.",
              "source_hashes": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sorted((ROOT / "src/signspeak_llm").glob("*.py"))}}
    sources = {}
    for item in items:
        image = Path(item["image"]).read_bytes()
        digest = hashlib.sha256(image).hexdigest()
        if digest != item["sha256"]:
            raise ValueError(f"Image hash mismatch: {item['id']}")
        cache = ROOT / "runtime/reconciliation-inputs" / (digest + ".json")
        if cache.exists():
            source = json.loads(cache.read_text(encoding="utf-8"))
        else:
            source = extract_image(image, PipelineConfig(preprocessing=PreprocessConfig(enabled=True)), file_name=Path(item["image"]).name)
            save(cache, source)
        if (source.get("input") or {}).get("sha256") != digest:
            raise ValueError("OCR image association is missing or invalid")
        views = adapt_result(source)
        save(output / "inputs" / (item["id"] + ".json"), {"ocr": source, "views": views})
        sources[item["id"]] = (image, views["llm_context"])
        report["rows"].append({"id": item["id"], "mode": "ocr_only", "text": source["text"],
                               "accuracy": accuracy(item["expected_text"], source["text"]),
                               "ocr_processing_ms": source.get("timings_ms", {}).get("total"),
                               "ocr_resources": source.get("resources"), "validation": source.get("validation")})
    projector = os.getenv("SIGNSPEAK_LLM_PROJECTOR", str(default_model_dir() / "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf"))
    with Server(projector=projector, model_key="vl") as server:
        report["server"] = server.metadata
        fingerprint = json.dumps({"version": server.metadata["version"], "artifacts": server.metadata["artifacts"],
                                  "command": server.metadata["command"]}, sort_keys=True)
        client = LocalLLM(max_tokens=768, timeout=240)
        reconciler = Reconciler(client, cache_dir=output / "cache", model_fingerprint=fingerprint)
        for index, item in enumerate(items):
            image, context = sources[item["id"]]
            # Alternate mode order to avoid always favoring one with warm hardware.
            modes = ("vision_only", "hybrid") if index % 2 == 0 else ("hybrid", "vision_only")
            for mode in modes:
                for repeat in range(repeats):
                    client.cache_prompt = bool(repeat)
                    result = reconciler.reconcile(image, context, mode=mode, use_cache=False)
                    model_text = result["model_text"]
                    row = {"id": item["id"], "mode": mode, "repetition": repeat,
                           "cache_prompt": client.cache_prompt, "result": result,
                           "accuracy": accuracy(item["expected_text"], model_text or ""),
                           "model_output_valid": model_text is not None, "memory": process_memory(server.process)}
                    report["rows"].append(row)
                    save(output / "report.json", report)
                    print(json.dumps({"id": item["id"], "mode": mode, "repeat": repeat, "status": result["status"],
                                      "model_text": model_text, "error": result.get("error"),
                                      "ms": result["processing_ms"], "accuracy": row["accuracy"]}, ensure_ascii=False), flush=True)
        report["memory_final"] = process_memory(server.process)
        # Exercise persistent reuse without a second model call: a successful
        # measured result is saved with the same key into this run's cache.
        successful = next((r["result"] for r in report["rows"] if r.get("model_output_valid") and r["mode"] == "hybrid"), None)
        if successful:
            save(output / "cache" / (successful["cache_key"] + ".json"), successful)
    if successful:
        original = next(item for item in items if sources[item["id"]][1].get("source") == successful["source"]["ocr"])
        image, context = sources[original["id"]]
        reused = reconciler.reconcile(image, context)
        report["cache_reuse_after_server_shutdown"] = {"cache_hit": reused["cache_hit"], "status": reused["status"],
                                                       "cache_lookup_ms": reused.get("cache_lookup_ms")}
    report["completed_utc"] = datetime.now(timezone.utc).isoformat()
    save(output / "report.json", report)
    print("Saved " + str(output / "report.json"), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, help="JSON list: id,image,sha256,origin,expected_text,expected_reading_order")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    run(args.manifest, args.output, args.repeats)
