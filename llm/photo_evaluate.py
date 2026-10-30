"""Private real-photo pilot: actual upload pipeline, no unreviewed accuracy scores."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import time
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT/name/"src") for name in ("llm", "ocr", "speech", "stt", "voice")]+[str(ROOT/"voice")]
from PIL import Image
from signspeak_llm import DocumentProcessor, LocalLLM, Reconciler
from signspeak_llm.server import Server, default_model_dir
from signspeak_llm.reconciliation_checks import compare_transcription
from signspeak_voice import DocumentSession
from signspeak_speech.engine import plan_segments
from eval.monitor import CombinedMemory


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def digest(path):
    with path.open("rb") as stream: return hashlib.file_digest(stream, "sha256").hexdigest()


class CountClient(LocalLLM):
    def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs); self.visual_calls = self.text_calls = 0
    def complete(self, messages, **kwargs):
        if any(isinstance(m.get("content"), list) for m in messages): self.visual_calls += 1
        else: self.text_calls += 1
        return super().complete(messages, **kwargs)


class ProgressReconciler(Reconciler):
    def reconcile(self, image_bytes, context, **kwargs):
        mode, started = kwargs["mode"], time.perf_counter()
        print(f"  {mode}: processing", flush=True)
        result = super().reconcile(image_bytes, context, **kwargs)
        print(f"  {mode}: {result['status']} in {time.perf_counter()-started:.1f}s", flush=True)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--start-server", action="store_true")
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--server-pid", type=int)
    parser.add_argument("--skip-qa", action="store_true", help="Skip redundant per-image model Q&A; contract checks still run")
    parser.add_argument("--max-edge", type=int, default=2048, choices=[768, 1024, 1280, 2048])
    args = parser.parse_args()
    paths = sorted(p for p in args.images.iterdir() if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"})
    if not paths: parser.error("No supported images found")
    output = (args.output or ROOT/"llm/runtime/photo-evaluation"/str(time.time_ns())).resolve()
    if ROOT/"llm/runtime" not in output.parents: parser.error("Outputs must remain under Git-ignored llm/runtime/")
    report_path = output/"report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {
        "started_utc": datetime.now(timezone.utc).isoformat(), "source_directory": str(args.images.resolve()),
        "reference_status": "pending manual verification; CER/WER not computed", "rows": [],
        "method": "One OCR + independent vision + hybrid per image; shared vision-enabled local Qwen server. Source hashes checked before/after. No model downloads. Q&A uses only selected text/sections/warnings.",
        "memory_method": "Sample simultaneous working sets of Python/OCR and Qwen, not sum of separate peaks; shared pages can be counted twice; native processes not network-traced."}
    manifests = []
    for index, path in enumerate(paths, 1):
        sha = digest(path)
        with Image.open(path) as image: size = list(image.size)
        identifier = f"{index:02d}-{path.stem.replace(' ', '_')}-{sha[:8]}"
        manifests.append({"id": identifier, "path": str(path.resolve()), "name": path.name, "sha256": sha, "size": size})
        reference = output/"references"/(identifier+".json")
        if not reference.exists():
            save(reference, {"image": str(path.resolve()), "sha256": sha, "review_status": "pending",
                "reviewer": "", "reviewed_at": "", "exact_transcription": "", "no_printed_text": None,
                "ordered_sections": [], "languages": [], "critical_values_and_label_relationships": [],
                "crossed_out_or_corrected_text": [], "redacted_or_unreadable_regions": [],
                "symbol_only_observations_separate_from_printed_text": [], "notes": "",
                "instructions": "Inspect original image. Enter only visible text, preserve language, accents, punctuation, columns and label/value relationships. Mark unreadable/redacted text without inventing it. Model/OCR output is not ground truth. Mark reviewed only after manual checking; empty text needs explicit no_printed_text=true."})
    save(output/"images.json", manifests)
    from signspeak_ocr import extract_image
    counts = {"ocr": 0}
    def extract(*a, **kw): counts["ocr"] += 1; return extract_image(*a, **kw)
    with ExitStack() as stack:
        server, pid = None, args.server_pid
        if args.start_server:
            projector = os.getenv("SIGNSPEAK_LLM_PROJECTOR", str(default_model_dir()/"mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf"))
            server = stack.enter_context(Server(projector=projector, context_size=8192, port=args.port, runtime=output/"server"))
            pid = server.process.pid; report["server"] = server.metadata
        url = f"http://127.0.0.1:{args.port}" if server else None
        image_client = CountClient(url, context_size=8192, max_tokens=1536, timeout=480)
        qa = CountClient(url, context_size=8192, max_tokens=192, timeout=180)
        report["server_capabilities"] = image_client.json_request("/props").get("modalities")
        completed = {row["id"] for row in report["rows"]}
        for item in manifests:
            if item["id"] in completed: continue
            print(f"[{len(report['rows'])+1}/{len(paths)}] {item['name']}", flush=True)
            folder, path = output/"images"/item["id"], Path(item["path"])
            edge = args.max_edge
            # A checkpoint may have saved a completed document before its Q&A.
            # Recover its ORIGINAL processing profile, never repeat visual work.
            saved = folder/"document.json"
            if saved.exists():
                old = json.loads(saved.read_text(encoding="utf-8"))
                old_evidence = json.loads(Path(old["evidence_ref"]).read_text(encoding="utf-8"))
                edge = old_evidence["configuration"]["max_edge"]
            processor = DocumentProcessor(reconciler=ProgressReconciler(image_client, max_edge=edge), ocr=extract, cache_dir=output/"documents")
            row = {**item, "status": "error", "reference_status": "pending; no accuracy score", "warnings": []}
            started, before = time.perf_counter(), (counts["ocr"], image_client.visual_calls, qa.text_calls)
            memory = None
            try:
                with CombinedMemory(pid) as memory:
                    doc = processor.process(path.read_bytes())
                    elapsed_upload = time.perf_counter()-started
                    row["upload_seconds"] = doc["processing_seconds"] if doc["cache_hit"] else elapsed_upload
                    row["cache_hit_on_first_access"] = doc["cache_hit"]
                    row["image_max_edge"] = edge
                    row["document_id"], row["status"], row["selected_method"] = doc["document_id"], doc["status"], doc["selected_method"]
                    save(folder/"document.json", doc)
                    evidence = json.loads(Path(doc["evidence_ref"]).read_text(encoding="utf-8"))
                    texts = {"ocr_only": evidence["original_views"]["llm_context"]["selected_text"],
                             **{mode: r.get("model_text") for mode,r in evidence["readings"].items()}, "final": doc["text"]}
                    for mode, text in texts.items():
                        name = "final-OCR-FALLBACK" if mode == "final" and doc["status"] == "ocr_unreviewed_fallback" else mode
                        (folder).mkdir(parents=True, exist_ok=True)
                        (folder/(name+".txt")).write_text(text if text is not None else "[No complete valid model reading; inspect evidence.json error]", encoding="utf-8")
                    row["texts"] = texts
                    row["model_status"] = {mode: {"status": r["status"], "processing_ms": r.get("processing_ms"), "error": r.get("error")}
                                            for mode,r in evidence["readings"].items()}
                    row["warnings"], row["evidence_ref"] = doc["warnings"], doc["evidence_ref"]
                    row["method_differences"] = {mode: compare_transcription(evidence["original_views"]["llm_context"], text)
                        for mode,text in texts.items() if mode != "ocr_only" and text is not None}
                    # Cache reuse must add NO OCR or image requests.
                    calls = (counts["ocr"], image_client.visual_calls)
                    repeated = processor.process(path.read_bytes())
                    assert repeated["cache_hit"] and calls == (counts["ocr"], image_client.visual_calls)
                    row["cache_reuse_without_analysis"] = True
                    row["consumer_checks"] = {"display_matches_final": doc["selected_views"]["display"]["text"] == doc["text"],
                                              "speech_text_matches_final": doc["selected_views"]["speech"]["text"] == doc["text"]}
                    segments = doc["selected_views"]["speech"]["segments"]
                    plan = plan_segments(segments, default_language="en") if segments else []
                    content = " ".join(part["text"] for part in plan if part["kind"] == "content")
                    normalize_speech = lambda text: " ".join(re.sub(r"\s+[/|]\s+", " ", unicodedata.normalize("NFC", text)).split())
                    row["consumer_checks"]["piper_content_plan_matches_final"] = normalize_speech(content) == normalize_speech(doc["text"])
                    row["piper_comparison_policy"] = "Preserve wording/values; normalize NFC/whitespace and language-switch slash/pipe separators only"
                    if doc["status"] == "ocr_unreviewed_fallback":
                        row["qa"] = {"status": "blocked", "reason": "Explicit unreviewed OCR fallback is not a normal interpreted session"}
                    else:
                        session = DocumentSession.from_document(doc)
                        context = session.document["views"]["llm_context"]
                        row["consumer_checks"]["qa_context_matches_final"] = context["selected_text"] == doc["text"]
                        stable = session.context_sha256
                        turns, history = [], []
                        if args.skip_qa:
                            messages = qa.messages(context, "Question", [], "en")
                            assert all(isinstance(m["content"], str) for m in messages)
                            row["consumer_checks"]["qa_context_stable"] = session.context_sha256 == stable
                            row["qa"] = {"status": "contract_only", "reason": "Repeated model Q&A skipped for speed; existing real-engine/lifecycle tests cover history reuse", "context_sha256": stable}
                        for question in ("What information is available in this document? Do not invent unreadable details.",
                                         "Which parts of that reading are uncertain?"):
                            if args.skip_qa: break
                            prior_turns = len(history)//2
                            response = qa.answer(context, question, history=history, language="en")
                            history.extend([{"role": "user", "content": question}, {"role": "assistant", "content": response["answer"]}])
                            turns.append({"question": question, "answer": response["answer"], "warnings": response["warnings"],
                                          "total_latency_ms": response["total_latency_ms"], "prior_history_turns": prior_turns})
                        if turns:
                            row["qa"] = {"status": "completed", "turns": turns, "context_sha256": stable, "history": history}
                            row["consumer_checks"]["followup_has_prior_turn"] = turns[1]["prior_history_turns"] == 1
                        row["consumer_checks"]["qa_context_stable"] = session.context_sha256 == stable
                        assert calls == (counts["ocr"], image_client.visual_calls)
                row["processing_and_qa_seconds"] = time.perf_counter()-started
                row["memory"] = memory.report
            except Exception as exc: row["error"] = str(exc)
            row["processing_and_qa_seconds"] = time.perf_counter()-started
            if memory is not None: row["memory"] = memory.report
            row["ocr_calls"] = counts["ocr"]-before[0]
            row["visual_calls"] = image_client.visual_calls-before[1]
            row["qa_text_requests"] = qa.text_calls-before[2]
            row["original_unchanged"] = digest(path) == item["sha256"]
            save(folder/"result.json", row)
            report["rows"].append(row); save(report_path, report)
            print(f"  saved: {row['status']}, {time.perf_counter()-started:.1f}s", flush=True)
    report["completed_utc"] = datetime.now(timezone.utc).isoformat()
    report["all_originals_unchanged"] = all(digest(Path(i["path"])) == i["sha256"] for i in manifests)
    save(report_path, report)
    print("Report:", report_path, flush=True)


if __name__ == "__main__": main()
