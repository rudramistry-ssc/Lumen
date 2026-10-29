"""Small offline human-speech pilot; run after prepare_fleurs.py."""
from array import array
import hashlib
import io
import json
from pathlib import Path
import platform
import random
import re
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.request
import uuid
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from signspeak_stt import WhisperSTT
from signspeak_stt.engine import windows_flags
from signspeak_stt.metrics import MemorySampler
from signspeak_stt.provision import executable, MODEL, RUNTIME

HERE = Path(__file__).parent


def tokens(text):
    text = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")
    return re.findall(r"[^\W_]+(?:'[^\W_]+)*", text)


def errors(reference, hypothesis):
    a, b = tokens(reference), tokens(hypothesis)
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        current = [i]
        for j, right in enumerate(b, 1):
            current.append(min(previous[j]+1, current[-1]+1, previous[j-1]+(left != right)))
        previous = current
    return {"edits": previous[-1], "reference_words": len(a), "wer": previous[-1]/len(a) if a else None}


def synthetic(kind, seconds=5):
    rng = random.Random(41)
    pcm = array("h", (0 if kind == "silence" else rng.randint(-2200, 2200) for _ in range(16000*seconds)))
    if sys.byteorder != "little": pcm.byteswap()
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed")); wav.writeframes(pcm.tobytes())
    return output.getvalue()


def persistent_benchmark(engine, samples):
    """Investigation only: native localhost server, owned process, no custom service."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    results = {"runs": [], "startup_seconds": None}
    with tempfile.TemporaryDirectory(prefix="signspeak-whisper-server-") as directory:
        command = [str(executable("server")), "-m", str(engine.model), "-ng", "-t", "4", "-l", "auto", "-sns",
                   "-mc", "0", "-bo", "5", "-bs", "5", "-nlp", "--host", "127.0.0.1", "--port", str(port)]
        started = time.perf_counter()
        with open(Path(directory)/"server.log", "wb") as log:
            process = subprocess.Popen(command, cwd=directory, stdout=log, stderr=log, creationflags=windows_flags())
            try:
                with MemorySampler(process) as memory:
                    while time.perf_counter()-started < 30:
                        if process.poll() is not None: raise RuntimeError("Native server exited during startup")
                        try:
                            with client.open(base+"/health", timeout=1) as response:
                                if response.status == 200: break
                        except OSError: time.sleep(.1)
                    else: raise TimeoutError("Native server startup timeout")
                    results["startup_seconds"] = time.perf_counter()-started
                    for sample in samples:
                        audio = (HERE/"data"/sample["file"]).read_bytes()
                        for repeat in range(3):
                            boundary = uuid.uuid4().hex
                            fields = {"language": "auto", "response_format": "verbose_json", "translate": "false",
                                      "temperature": "0", "temperature_inc": "0", "token_timestamps": "false", "max_context": "0"}
                            body = b""
                            for name, value in fields.items():
                                body += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
                            body += f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="input.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()+audio+f'\r\n--{boundary}--\r\n'.encode()
                            request = urllib.request.Request(base+"/inference", data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
                            before = time.perf_counter()
                            with client.open(request, timeout=120) as response: data = json.load(response)
                            results["runs"].append({"file": sample["file"], "repeat": repeat, "processing_seconds": time.perf_counter()-before, "response": data})
                    results["native_peak_working_set_mib"] = memory.peak/1048576
            finally:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
            results["native_timings_log"] = (Path(directory)/"server.log").read_text(encoding="utf-8", errors="replace")[-3000:]
    return results


def main():
    manifest = json.loads((HERE/"data/manifest.json").read_text(encoding="utf-8"))
    target = HERE / f"results-{time.time_ns()}.json"
    started = time.perf_counter()
    engine = WhisperSTT()
    report = {"platform": platform.platform(), "python": sys.version, "model": MODEL, "runtime": RUNTIME,
              "settings": {"threads": 4, "beam_size": 5, "best_of": 5, "temperature": 0, "temperature_increment": 0, "max_context": 0, "gpu": False},
              "engine_init_seconds": time.perf_counter()-started, "human": [], "controls": [], "repeated_cli": [],
              "reference_policy": "Published FLEURS reference; not manually listening-verified. WER casefolds NFKC, removes punctuation, retains accents and number spellings.",
              "cold_policy": "Fresh process/model context, OS file cache not cleared; first measured request is not machine-boot cold."}
    def save(): target.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for sample in manifest["samples"]:
        audio = (HERE/"data"/sample["file"]).read_bytes()
        if hashlib.sha256(audio).hexdigest() != sample["sha256"]: raise ValueError("Sample hash mismatch")
        result = engine.transcribe(audio)
        entry = {"file": sample["file"], "expected_language": sample["language"], "reference": sample["reference"],
                 "result": result, **errors(sample["reference"], result["text"])}
        entry["language_correct"] = result["language"] == sample["language"]
        entry["real_time_factor"] = result["processing_seconds"] / result["audio_seconds"] if result["audio_seconds"] else None
        report["human"].append(entry); save()
        print(sample["file"], result["status"], round(entry["wer"], 3), result["processing_seconds"], flush=True)
    selected = [manifest["samples"][0], manifest["samples"][6]]
    for sample in selected:
        audio = (HERE/"data"/sample["file"]).read_bytes()
        for language in ["auto", "auto", sample["language"]]:
            report["repeated_cli"].append({"file": sample["file"], "result": engine.transcribe(audio, language)})
            save()
    for kind in ["silence", "noise"]:
        audio = synthetic(kind)
        (HERE/"data"/f"synthetic-{kind}.wav").write_bytes(audio)
        report["controls"].append({"kind": "synthetic_"+kind, "expected_text": "", "result": engine.transcribe(audio)})
        save()
    for name, audio, language in [("empty", b"", "auto"), ("malformed", b"not a WAV", "auto"),
                                  ("truncated", (HERE/"data"/selected[0]["file"]).read_bytes()[:-40], "auto"),
                                  ("unsupported_language", synthetic("silence"), "de"),
                                  ("oversized", b"x"*8_000_001, "auto"), ("too_long", synthetic("silence", 61), "auto")]:
        report["controls"].append({"kind": name, "result": engine.transcribe(audio, language)})
        save()
    try: report["persistent_server"] = persistent_benchmark(engine, selected)
    except Exception as exc: report["persistent_server"] = {"error": str(exc)}
    report["summary"] = {}
    for language in ["en", "fr"]:
        entries = [x for x in report["human"] if x["expected_language"] == language]
        report["summary"][language] = {"samples": len(entries), "corpus_wer": sum(x["edits"] for x in entries)/sum(x["reference_words"] for x in entries),
            "language_correct": sum(x["language_correct"] for x in entries),
            "median_seconds": statistics.median(x["result"]["processing_seconds"] for x in entries),
            "median_rtf": statistics.median(x["real_time_factor"] for x in entries),
            "max_native_peak_working_set_mib": max(x["result"].get("native_peak_working_set_mib") or 0 for x in entries)}
    save()
    print(target, json.dumps(report["summary"], indent=2), flush=True)


if __name__ == "__main__": main()
