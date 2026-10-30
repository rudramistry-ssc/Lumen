"""Default OCR + independent vision upload; filename retained for compatibility."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import time
from common import ROOT, native, sha256, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocr-python", type=Path)
    parser.add_argument("--image", type=Path, default=ROOT/"ocr/eval/benchmark/images/english_clean.png")
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--confirmed-question")
    parser.add_argument("--language", choices=["en", "fr"], default="en")
    parser.add_argument("--question", default="On which day does the library reopen?")
    parser.add_argument("--start-server", action="store_true")
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--url", help=argparse.SUPPRESS)
    args = parser.parse_args()
    from signspeak_llm import DocumentProcessor, LocalLLM, Reconciler
    class CountingClient(LocalLLM):
        def __init__(self, *a, **kw): super().__init__(*a, **kw); self.visual = self.text = 0
        def complete(self, messages, **kwargs):
            if any(isinstance(m.get("content"), list) for m in messages): self.visual += 1
            else: self.text += 1
            return super().complete(messages, **kwargs)
    if args.worker:
        client = LocalLLM(args.url, context_size=8192, max_tokens=1536, timeout=480)
        processor = DocumentProcessor(reconciler=Reconciler(client, max_edge=2048), cache_dir=ROOT/"handoff/runtime/documents")
        document = processor.process(args.image.read_bytes())
        if "selected_views" not in document: raise RuntimeError(json.dumps(document))
        counts = document["execution_this_call"]
        cached = processor.process(args.image.read_bytes())
        assert cached["cache_hit"] and cached["execution_this_call"] == {"ocr": 0, "vision": 0, "hybrid": 0}
        assert counts == ({"ocr": 0, "vision": 0, "hybrid": 0} if document["cache_hit"] else {"ocr": 1, "vision": 1, "hybrid": 0})
        write_json(args.output, document)
        print(json.dumps({"ocr_calls": counts["ocr"], "visual_calls": counts["vision"], "hybrid_calls": counts["hybrid"], "cached_read_added_calls": 0,
                          "status": document["status"], "cache_hit_on_first_access": document["cache_hit"], "processing_seconds": document["processing_seconds"]}))
        return 0
    directory = ROOT/"handoff/runtime"/f"hybrid-smoke-{time.time_ns()}"
    output = directory/"results.json"
    report = {"passed": False, "steps": [], "real_photo_validation": "pending; generated image fixture",
              "downloads": "none", "analysis_policy": "OCR once + independent vision once; no hybrid or question-time visual analysis"}
    def step(name, call):
        started = time.perf_counter()
        try:
            data = call(); report["steps"].append({"name": name, "status": "pass", "seconds": time.perf_counter()-started, "details": data})
            write_json(output, report); return data
        except Exception as exc:
            report["steps"].append({"name": name, "status": "fail", "error": str(exc)}); raise
    try:
        if not args.audio or not args.confirmed_question: raise ValueError("Provide authorized --audio and explicit --confirmed-question")
        from check import run_checks
        preflight = run_checks(args.ocr_python, service=not args.start_server)
        write_json(directory/"readiness.json", preflight)
        if not preflight["ready"]: raise RuntimeError("Readiness failed; see readiness.json. No model downloads attempted.")
        from signspeak_llm.server import Server, default_model_dir
        from signspeak_voice import DocumentSession, VoiceConversation
        from signspeak_speech import PiperSpeech
        sys.path.insert(0, str(ROOT/"voice"))
        from eval.monitor import CombinedMemory
        with ExitStack() as stack:
            server = None
            if args.start_server:
                projector = os.getenv("SIGNSPEAK_LLM_PROJECTOR", str(default_model_dir()/"mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf"))
                server = stack.enter_context(Server(projector=projector, context_size=8192, port=args.port, runtime=directory/"server"))
            client = CountingClient(f"http://127.0.0.1:{args.port}" if server else None, context_size=8192)
            report["props"] = client.json_request("/props")
            if server: report["server"] = server.metadata
            with CombinedMemory(server.process.pid if server else None) as monitor:
                document_file = directory/"document.json"
                def upload():
                    command = [args.ocr_python or sys.executable, "-B", __file__, "--worker", "--image", args.image, "--output", document_file, "--url", client.base_url]
                    result = native(command, timeout=1000)
                    if result.returncode: raise RuntimeError((result.stderr or result.stdout)[-2000:])
                    return json.loads(result.stdout)
                step("upload_and_cache_reuse", upload)
                doc = json.loads(document_file.read_text(encoding="utf-8"))
                session = DocumentSession.from_document(doc)
                context_hash, document_hash = session.context_sha256, sha256(document_file)
                tts = PiperSpeech()
                def read_aloud():
                    assert doc["text"] == doc["selected_views"]["display"]["text"]
                    audio = tts.synthesize_view(doc["selected_views"]["speech"], default_language=args.language)
                    planned = " ".join(x["text"] for x in audio.metadata["segments"] if x["kind"] == "content")
                    assert " ".join(doc["text"].split()) == " ".join(planned.split())
                    audio.write_wav(directory/"document-read-aloud.wav")
                    return {"selected_text": doc["text"], "method": doc["selected_method"], "wav": str(directory/"document-read-aloud.wav")}
                step("display_and_piper_selected_document", read_aloud)
                voice = VoiceConversation(llm=client, speech=tts)
                def answer(name, question, prepared=None):
                    result = voice.answer_question(session, question, language=args.language, prepared=prepared)
                    audio = result.pop("wav_bytes")
                    if result["status"] != "ok": raise RuntimeError(str(result["errors"]))
                    (directory/f"{name}.wav").write_bytes(audio)
                    assert result["context_sha256"] == context_hash and client.visual == 0
                    return {"question": question, "answer": result["answer"], "timings": result["timings"], "warnings": result["warnings"],
                            "context_sha256": result["context_sha256"], "history_turns": result["history_turns"]}
                step("first_qa_selected_context", lambda: answer("first-answer", args.question))
                step("typed_followup_text_only", lambda: answer("followup-answer", "And at what time?"))
                prepared = step("stt_confirmation", lambda: voice.prepare_question(args.audio.read_bytes(), args.language))
                step("spoken_question_text_only", lambda: answer("spoken-answer", args.confirmed_question, prepared))
                assert session.context_sha256 == context_hash and document_hash == sha256(document_file)
                second_session = DocumentSession.from_file(document_file)
                assert second_session.history == [] and second_session.session_id != session.session_id
                report.update(context_stable=True, history_turns=len(session.history)//2, fresh_session_history_empty=True,
                              question_requests={"text": client.text, "visual": client.visual}, document_id=doc["document_id"],
                              final_method=doc["selected_method"], final_text=doc["text"], warnings=doc["warnings"])
            report["combined_memory"] = monitor.report
        report["passed"] = True
    except Exception as exc: report["error"] = str(exc)
    write_json(output, report)
    print(json.dumps({"passed": report["passed"], "report": str(output), "error": report.get("error")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
