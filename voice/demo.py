"""English speech -> typed follow-up -> French speech, existing cached OCR only."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import wave

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT/f"{name}/src") for name in ("voice", "llm", "speech", "stt")]
from signspeak_voice import DocumentSession, VoiceConversation
from signspeak_llm import LocalLLM
from signspeak_llm.server import Server
from signspeak_speech import PiperSpeech
from signspeak_stt import WhisperSTT
from eval.monitor import CombinedMemory


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--views", type=Path, required=True, help="Completed DocumentProcessor document.json; not original OCR views")
    parser.add_argument("--english", type=Path)
    parser.add_argument("--french", type=Path)
    parser.add_argument("--scripted-confirmation", action="store_true", help="Known synthetic questions only; not human review")
    parser.add_argument("--start-server", action="store_true", help="Start ONE existing llama.cpp Server for this whole demo")
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--llama-pid", type=int, help="For combined RAM measurement when attaching to an existing server")
    args = parser.parse_args()
    if "selected_views" not in json.loads(args.views.read_text(encoding="utf-8")):
        parser.error("Use a completed interpreted document JSON; see handoff/smoke.py for the default upload path")
    if bool(args.english) != bool(args.french): parser.error("Provide both --english and --french")
    if args.scripted_confirmation and args.english: parser.error("Scripted confirmation only accepts generated synthetic fixtures")
    sys.stdout.reconfigure(encoding="utf-8")
    directory = ROOT/"voice/runtime"/f"demo-{time.time_ns()}"
    directory.mkdir(parents=True)
    if not args.english:
        # Separate process: fixture generation must not pre-load evaluated Piper.
        subprocess.run([sys.executable, str(ROOT/"voice/eval/prepare_synthetic.py"), str(directory/"questions")], check=True)
        args.english, args.french = directory/"questions/english.wav", directory/"questions/french.wav"
        kind = "synthetic Piper questions; not human microphone validation"
        warm_audio = directory/"questions/english-followup.wav"
    else:
        kind = "caller-supplied saved recordings; human provenance must be checked by caller"
        warm_audio = None
    original_hash = digest(args.views)
    session = DocumentSession.from_file(args.views)
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
              "python": platform.python_version(), "input_kind": kind, "views_file": str(args.views),
              "views_sha256_before": original_hash, "context_sha256": session.context_sha256,
              "document_text": session.document["views"]["llm_context"]["selected_text"],
              "turns": [], "method": "Local models only. No OCR/reconciliation calls. First interaction separately from follow-ups; OS cache uncontrolled. Review time separate from active processing."}
    output = directory/"results.json"
    def save(): output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with ExitStack() as stack:
        qwen_pid = args.llama_pid
        if args.start_server:
            from signspeak_llm.server import default_model_dir
            import os
            projector = os.getenv("SIGNSPEAK_LLM_PROJECTOR", str(default_model_dir()/"mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf"))
            server = stack.enter_context(Server(runtime=directory/"server", port=args.port, projector=projector, context_size=8192))
            qwen_pid = server.process.pid
            report["qwen_server"] = server.metadata
            client = LocalLLM(base_url=f"http://127.0.0.1:{args.port}", context_size=8192)
        else:
            client = LocalLLM(context_size=8192)
            client.health()
        report["qwen_url"] = client.base_url
        started = time.perf_counter()
        voice = VoiceConversation(stt=WhisperSTT(), llm=client, speech=PiperSpeech())
        report["adapter_initialization_seconds"] = time.perf_counter()-started
        cases = [("english", args.english, "en", "On which day does the library reopen?", "Tuesday; no other day"),
                 ("typed-followup", None, "en", "And at what time?", "9:00 AM, resolving the previous reopening question"),
                 ("french", args.french, "fr", "Quel jour la bibliothèque est-elle fermée ?", "Lundi, in French, from the English notice")]
        if warm_audio:
            cases.insert(2, ("spoken-followup", warm_audio, "en", "Can you repeat that time?", "9:00 AM, resolving the previous turn"))
        cases.append(("absent-fact", None, "en", "What is the library's phone number?", "Not provided; no invented phone number"))
        for index, (name, audio_path, language, reference, expected) in enumerate(cases):
            before_history = session.history
            with CombinedMemory(qwen_pid) as monitor:
                submitted = time.perf_counter()
                prepared = voice.prepare_question(audio_path.read_bytes(), language) if audio_path else None
                review_started = time.perf_counter()
                if prepared and prepared["status"] != "ready_for_review":
                    report["turns"].append({"id": name, "prepared": prepared, "status": "not_submitted"})
                    save(); print(name, "no reviewable question; Qwen not called", flush=True); continue
                if prepared:
                    print(name, "Whisper:", prepared["review_text"], flush=True)
                    if args.scripted_confirmation:
                        confirmed, review_kind = reference, "scripted confirmation of known synthetic question; no human review"
                    else:
                        correction = input("Review transcript. Enter to submit, type a correction, or /skip: ").strip()
                        if correction == "/skip":
                            report["turns"].append({"id": name, "status": "skipped_by_caller"}); save(); continue
                        confirmed, review_kind = correction or prepared["review_text"], "interactive caller confirmation"
                else: confirmed, review_kind = reference, "explicit typed follow-up"
                review_seconds = time.perf_counter()-review_started
                result = voice.answer_question(session, confirmed, language=language, prepared=prepared)
                elapsed = time.perf_counter()-submitted
                wav_bytes = result.pop("wav_bytes")
                if wav_bytes:
                    audio_output = directory/f"{name}-answer.wav"
                    audio_output.write_bytes(wav_bytes)
                    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
                        audio_check = {"sample_rate": wav.getframerate(), "channels": wav.getnchannels(),
                            "sample_width": wav.getsampwidth(), "frames": wav.getnframes(),
                            "duration_seconds": wav.getnframes()/wav.getframerate()}
                else: audio_output, audio_check = None, None
            turn = {"id": name, "state": "first interaction" if index == 0 else "warm follow-up; new language voice may load",
                    "audio_input": str(audio_path) if audio_path else None, "reference_question": reference,
                    "expected_answer": expected, "history_before": before_history, "history_after": session.history,
                    "review_kind": review_kind, "review_seconds": review_seconds,
                    "recorded_submission_to_response_seconds": elapsed, "result": result,
                    "wav_file": str(audio_output) if audio_output else None, "wav_check": audio_check,
                    "combined_memory": monitor.report}
            report["turns"].append(turn); save()
            print(name, result["status"], result["answer"], result["timings"], flush=True)
        report.update(views_sha256_after=digest(args.views), document_unchanged=original_hash == digest(args.views),
                      shared_history=session.history,
                      peak_simultaneous_working_set_mib=max((x.get("combined_memory", {}).get("peak_combined_working_set_mib", 0) for x in report["turns"]), default=0))
        save()
    print("Results:", output, flush=True)
    if any(x.get("result", {}).get("status") != "ok" for x in report["turns"]): raise SystemExit(1)


if __name__ == "__main__": main()
