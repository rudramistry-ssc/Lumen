"""Actual offline components: image->OCR->saved session->Qwen->WAV, then recorded speech."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import socket
import sys
import time
from urllib.parse import urlsplit
import wave

from common import ROOT, native, sha256, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocr-python", type=Path)
    parser.add_argument("--image", type=Path, default=ROOT/"ocr/eval/benchmark/images/english_clean.png")
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--confirmed-question", help="Explicit previously reviewed submission; never inferred from raw STT")
    parser.add_argument("--language", choices=["en", "fr"], default="en")
    parser.add_argument("--question", default="When does the library reopen?")
    parser.add_argument("--start-server", action="store_true", help="Explicitly own ONE local existing Server for the whole smoke test")
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--ocr-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.ocr_worker:
        try:
            from signspeak_ocr import extract_image
            from signspeak_ocr.integration import adapt_result
            started = time.perf_counter()
            source = extract_image(args.image.read_bytes())
            if source["validation"]["overall_status"] == "failed": raise RuntimeError(str(source.get("errors")))
            write_json(args.worker_output, {"source": source, "views": adapt_result(source)})
            print(json.dumps({"status": "pass", "seconds": time.perf_counter()-started, "warnings": source.get("warnings", []), "errors": source.get("errors", [])})); return 0
        except Exception as exc:
            print(json.dumps({"status": "fail", "error": str(exc)})); return 1
    directory = ROOT/"handoff/runtime"/f"smoke-{time.time_ns()}"
    output = directory/"results.json"
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "passed": False, "steps": [],
              "verification": "not_performed; step success is execution only, review answers and audio",
              "downloads": "never performed", "reconciliation": "not invoked"}
    def step(name, function):
        started = time.perf_counter()
        try:
            data = function()
            report["steps"].append({"name": name, "status": "pass", "seconds": round(time.perf_counter()-started, 4), "details": data})
            write_json(output, report)
            return data
        except Exception as exc:
            report["steps"].append({"name": name, "status": "fail", "seconds": round(time.perf_counter()-started, 4), "error": str(exc)})
            write_json(output, report)
            raise
    try:
        if not args.audio or not args.confirmed_question or not args.confirmed_question.strip():
            raise ValueError("Supply --audio authorized.wav and --confirmed-question with explicit reviewed text. No automatic confirmation or synthetic fallback.")
        # Do not provision or substitute anything. The checker uses existing verifiers.
        from check import run_checks
        preflight = run_checks(args.ocr_python, service=not args.start_server)
        write_json(directory/"readiness.json", preflight)
        if not preflight["ready"]:
            failures = [f"{x['name']}: {x.get('message')}. {x.get('action')}" for x in preflight["checks"] if x["required"] and x["status"] != "pass"]
            raise RuntimeError("Preflight failed: " + "; ".join(failures))
        from signspeak_llm import LocalLLM
        from signspeak_llm.server import Server
        from signspeak_voice import DocumentSession, VoiceConversation
        from signspeak_stt.engine import wav_info
        step("prerecorded_input", lambda: {"path": str(args.audio), "sha256": sha256(args.audio), "duration_seconds": wav_info(args.audio.read_bytes())[0],
             "confirmation": "explicit CLI text; replay of previously authorized recording, not new microphone capture"})
        source_hash = sha256(args.image)
        ocr_output = directory/"document.json"
        def extract():
            command = [args.ocr_python or sys.executable, "-B", Path(__file__), "--ocr-worker", "--image", args.image, "--worker-output", ocr_output]
            result = native(command, timeout=180)
            try: data = json.loads(result.stdout)
            except ValueError: raise RuntimeError("OCR interpreter failed: " + (result.stderr or result.stdout)[-700:])
            if result.returncode: raise RuntimeError(data.get("error", "OCR failed"))
            return data
        step("image_ocr_and_save", extract)
        session = DocumentSession.from_file(ocr_output)
        snapshot_hash = sha256(ocr_output)
        report["document"] = {"image_sha256": source_hash, "context_sha256": session.context_sha256,
                              "text": session.document["views"]["llm_context"]["selected_text"], "session_file": str(ocr_output)}
        with ExitStack() as stack:
            if args.start_server:
                server = stack.enter_context(Server(port=args.port, runtime=directory/"server"))
                report["server_startup_seconds"] = server.metadata["startup_ms"]/1000
                client = LocalLLM(f"http://127.0.0.1:{args.port}")
            else: client = LocalLLM()
            step("qwen_service", lambda: {"url": client.base_url, "health": client.health()})
            # Refuse Python network connections except this configured local service.
            origin = urlsplit(client.base_url)
            addresses = {x[4][0] for x in socket.getaddrinfo(origin.hostname, origin.port or 80)}
            def audit(event, arguments):
                if event == "socket.connect":
                    target = arguments[1]
                    if not isinstance(target, tuple) or target[0] not in addresses or target[1] != (origin.port or 80):
                        raise PermissionError("Offline smoke test blocks connections outside the configured Qwen origin")
            sys.addaudithook(audit)
            report["offline_check"] = "Python socket guard allows only configured Qwen origin; native processes not OS-network-traced. Qwen launcher uses --offline."
            voice = VoiceConversation(llm=client)
            def answer(name, text, prepared=None):
                result = voice.answer_question(session, text, language=args.language, prepared=prepared)
                audio = result.pop("wav_bytes")
                if result["status"] != "ok": raise RuntimeError(json.dumps({"answer": result["answer"], "errors": result["errors"]}))
                path = directory/f"{name}.wav"
                path.write_bytes(audio)
                with wave.open(io.BytesIO(audio), "rb") as wav:
                    if wav.getnframes() == 0 or (wav.getnchannels(), wav.getsampwidth()) != (1, 2): raise ValueError("Invalid Piper WAV")
                    duration = wav.getnframes()/wav.getframerate()
                return {"question": text, "answer": result["answer"], "wav": str(path), "audio_seconds": duration,
                        "timings": result["timings"], "warnings": result["warnings"], "speech": result["speech"],
                        "history_turns": result["history_turns"], "context_sha256": result["context_sha256"]}
            step("typed_qwen_piper", lambda: answer("typed-answer", args.question))
            def prepare():
                value = voice.prepare_question(args.audio.read_bytes(), args.language)
                if value["status"] != "ready_for_review":
                    raise RuntimeError("No reviewable speech; Qwen not called for this recording: " + json.dumps(value))
                return value
            prepared = step("stt_review", prepare)
            step("confirmed_spoken_qwen_piper", lambda: answer("spoken-answer", args.confirmed_question, prepared))
            step("preserved_document_and_history", lambda: preserved(session, args.image, source_hash, ocr_output, snapshot_hash, directory))
            report["passed"] = True
            write_json(directory/"readiness-running.json", run_checks(args.ocr_python)) if not args.start_server or args.port == 8091 else None
        write_json(output, report)
    except Exception as exc:
        report["passed"] = False
        report["error"] = str(exc); write_json(output, report)
    print(json.dumps({"passed": report["passed"], "report": str(output), "error": report.get("error")}, ensure_ascii=True))
    return 0 if report["passed"] else 1


def preserved(session, image, image_hash, source, source_hash, directory):
    if sha256(image) != image_hash or sha256(source) != source_hash: raise ValueError("Source image/document cache changed")
    if len(session.history) != 4: raise ValueError("Expected shared two-turn typed/spoken history")
    write_json(directory/"session.json", {"session_id": session.session_id, "context_sha256": session.context_sha256, "history": session.history})
    return {"unchanged": True, "history_turns": 2, "ocr_calls": 1, "reconciliation_calls": 0}


if __name__ == "__main__": raise SystemExit(main())
