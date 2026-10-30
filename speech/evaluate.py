"""Generate playable fixtures and measure cold/warm CPU synthesis, not quality."""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import time
import urllib.request
import wave

from examples import CASES, synthesize_case

ROOT = Path(__file__).resolve().parent


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def memory():
    if os.name != "nt":
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
        return {"working_set_bytes": None, "peak_working_set_bytes": peak}
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [(name, ctypes.c_size_t) for name in (
            "peak_working", "working", "peak_paged", "paged", "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]
    counter = Counters()
    counter.cb = ctypes.sizeof(counter)
    ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    ctypes.windll.psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    ok = ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counter), counter.cb)
    return {"working_set_bytes": counter.working if ok else None, "peak_working_set_bytes": counter.peak_working if ok else None}


def offline_guard():
    def blocked(*args, **kwargs):
        raise RuntimeError("Network disabled during synthesis evaluation")
    socket.socket.connect = blocked
    urllib.request.urlopen = blocked


def inspect_audio(data):
    import numpy as np
    with wave.open(io.BytesIO(data), "rb") as wav:
        rate, channels, width, count = wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getnframes()
        pcm = np.frombuffer(wav.readframes(count), dtype="<i2")
    assert (rate, channels, width) == (22050, 1, 2) and count > 0
    peak = int(np.abs(pcm.astype(np.int32)).max())
    assert peak > 0
    return {"duration_seconds": count / rate, "frames": count, "sample_rate": rate, "peak_pcm": peak,
            "sha256": hashlib.sha256(data).hexdigest(), "pronunciation_review": "pending manual listening"}


def worker(language, output):
    offline_guard()
    started = time.perf_counter()
    from signspeak_speech import PiperSpeech
    engine = PiperSpeech()
    case = CASES[0 if language == "en" else 1]
    result = synthesize_case(engine, case)
    result.write_wav(output / f"cold-{language}.wav")
    report = {"language": language, "startup_and_first_synthesis_ms": (time.perf_counter() - started) * 1000,
              "synthesis": result.metadata, "audio": inspect_audio(result.wav_bytes), "memory": memory()}
    save(output / f"cold-{language}.json", report)


def run(output):
    output = Path(output) if output else ROOT / "runtime" / ("evaluation-" + str(time.time_ns()))
    if output.exists():
        raise FileExistsError("Use a new output directory; previous examples are preserved")
    output.mkdir(parents=True)
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
              "platform": platform.platform(), "logical_processors": os.cpu_count(), "cold": [], "rows": [],
              "dependencies": {name: importlib.metadata.version(name) for name in ("piper-tts", "onnxruntime", "numpy", "pathvalidate")},
              "method": "Cold = new Python process, OS file cache uncontrolled. Main engine reused across two syntheses per fixture. Voice hashing/import/load included in first call. CPU only; Python socket connections blocked and ONNX telemetry disabled. No listening score assigned."}
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8")
    for language in ("en", "fr"):
        started = time.perf_counter()
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", language, "--output", str(output)],
                       env=env, check=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        cold = json.loads((output / f"cold-{language}.json").read_text(encoding="utf-8"))
        cold["process_wall_ms"] = (time.perf_counter() - started) * 1000
        report["cold"].append(cold)
        print(f"Cold {language}: {cold['process_wall_ms']:.0f} ms", flush=True)
    offline_guard()
    from signspeak_speech import PiperSpeech
    from signspeak_speech.voices import VOICES
    engine = PiperSpeech()
    report["voices"] = VOICES
    for case in CASES:
        for repeat in range(2):
            result = synthesize_case(engine, case)
            audio = inspect_audio(result.wav_bytes)
            if repeat == 0:
                result.write_wav(output / (case["id"] + ".wav"))
                save(output / (case["id"] + ".json"), result.metadata)
            row = {"id": case["id"], "repeat": repeat, "synthesis": result.metadata, "audio": audio, "memory": memory()}
            report["rows"].append(row)
            save(output / "report.json", report)
            print(f"{case['id']} repeat={repeat}: {result.metadata['processing_ms']:.0f} ms, {audio['duration_seconds']:.2f} s audio", flush=True)
    report["error_cases"] = []
    for tag in (None, "unknown", "mixed", "de"):
        try:
            engine.synthesize("A readable sentence.", tag)
            raise AssertionError("Unsupported language unexpectedly accepted")
        except Exception as exc:
            from signspeak_speech import UnsupportedLanguageError
            if not isinstance(exc, UnsupportedLanguageError):
                raise
            report["error_cases"].append({"language": tag, "error": str(exc), "expected": True})
    report["final_memory"] = memory()
    report["completed_utc"] = datetime.now(timezone.utc).isoformat()
    save(output / "report.json", report)
    print("Saved " + str(output / "report.json"), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=["en", "fr"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.output)
    else:
        run(args.output)
