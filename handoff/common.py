"""Shared stdlib-only handoff helpers; no provisioning or downloads."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT/name/"src") for name in ("ocr", "llm", "speech", "stt", "voice")]


def sha256(path):
    with Path(path).open("rb") as stream: return hashlib.file_digest(stream, "sha256").hexdigest()


def native(command, timeout=30):
    return subprocess.run([str(x) for x in command], capture_output=True, encoding="utf-8", errors="replace",
                          timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def worker(python, *args):
    result = native([python, "-B", ROOT/"handoff/check.py", "--worker", *args], timeout=180)
    try: data = json.loads(result.stdout)
    except ValueError: raise RuntimeError("Interpreter probe failed: " + (result.stderr or result.stdout)[-700:])
    if result.returncode: raise RuntimeError(data.get("error", "Interpreter probe failed"))
    return data


def write_json(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
