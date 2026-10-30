"""Own one native CPU server; explicit local files, health check, no downloads."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import time

from .client import InferenceError, LocalLLM
from .models import MODELS, check, model_path

REVISION = "52d6c8ffea26cc873ac5ad116f8631268d7eb503"
MODEL_REPO = "Qwen/Qwen3-VL-2B-Instruct-GGUF"
FILES = {
    "Qwen3VL-2B-Instruct-Q4_K_M.gguf": (1107409952, "089d75c52f4b7ffc56ba998ffc50aae89fcafc755f9e7208aacca281dca6c2ae"),
    "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf": (445053216, "f9a68fabba69c3b81e153367b2c7521030b0fa8bb0de400c9599c8e6725f9c82"),
}


def default_model_dir():
    return Path.home() / ".cache/huggingface/hub/models--Qwen--Qwen3-VL-2B-Instruct-GGUF/snapshots" / REVISION


def verify_file(path):
    path = Path(path).resolve(strict=True)
    for item in MODELS.values():
        if path.name == item["filename"]:
            return check(path, item)
    if path.name not in FILES:
        raise ValueError("Unknown model filename; this verifier pins the official Qwen3-VL-2B pair")
    size, expected = FILES[path.name]
    if path.stat().st_size != size:
        raise ValueError(f"Unexpected size for {path.name}")
    with path.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    if digest != expected:
        raise ValueError(f"SHA256 mismatch for {path.name}")
    return {"name": path.name, "bytes": size, "sha256": digest,
            "repository": MODEL_REPO, "revision": REVISION}


def memory_status():
    if os.name != "nt":
        return {"total_ram_bytes": None, "available_ram_bytes": None}
    class Status(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(n, ctypes.c_ulonglong) for n in (
            "total", "available", "page_total", "page_available", "virtual_total", "virtual_available", "extended")]
    status = Status()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return {"total_ram_bytes": None, "available_ram_bytes": None}
    return {"total_ram_bytes": status.total, "available_ram_bytes": status.available}


def process_memory(process):
    if os.name != "nt":
        return {"working_set_bytes": None, "peak_working_set_bytes": None}
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [(n, ctypes.c_size_t) for n in (
            "peak_working", "working", "peak_paged", "paged", "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    ok = ctypes.windll.psapi.GetProcessMemoryInfo(wintypes.HANDLE(int(process._handle)), ctypes.byref(counters), counters.cb)
    return {"working_set_bytes": counters.working if ok else None,
            "peak_working_set_bytes": counters.peak_working if ok else None}


class Server:
    def __init__(self, *, binary=None, model=None, projector=None, threads=4, context_size=4096,
                 port=8091, runtime="llm/runtime", startup_timeout=180, model_key="vl"):
        default_binary = shutil.which("llama-server") or shutil.which("llama-server.exe") or str(Path.home() / "tools/llama-cpp/llama-server.exe")
        self.binary = Path(binary or os.getenv("SIGNSPEAK_LLAMA_SERVER", default_binary)).resolve()
        self.model = Path(model or os.getenv("SIGNSPEAK_LLM_MODEL", str(model_path(model_key)))).resolve()
        self.projector = Path(projector).resolve() if projector else None
        if threads < 1 or context_size < 512 or not 1 <= port <= 65535:
            raise ValueError("Invalid threads, context size or port")
        self.threads, self.context_size, self.port = threads, context_size, port
        self.runtime = Path(runtime).resolve()
        self.startup_timeout = startup_timeout
        self.process = None
        self._log = None

    def __enter__(self):
        if not self.binary.is_file():
            raise FileNotFoundError(f"llama-server not found: {self.binary}; pass --binary")
        artifacts = [verify_file(self.model)]
        if self.projector:
            artifacts.append(verify_file(self.projector))
        # Refuse to attach to or terminate any unrelated listener.
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", self.port)) == 0:
                raise InferenceError(f"Port {self.port} is in use; choose another --port")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        version = subprocess.run([str(self.binary), "--version"], capture_output=True, text=True, creationflags=flags, timeout=20, check=True)
        command = [str(self.binary), "-m", str(self.model), "--host", "127.0.0.1", "--port", str(self.port),
                   "-c", str(self.context_size), "-t", str(self.threads), "-tb", str(self.threads),
                   "-ngl", "0", "--device", "none", "--parallel", "1", "--jinja", "--offline",
                   "--no-context-shift", "--batch-size", "256", "--ubatch-size", "128", "--alias", "signspeak",
                   "--reasoning", "off", "--chat-template-kwargs", '{"enable_thinking":false}']
        if self.projector:
            command += ["--mmproj", str(self.projector), "--no-mmproj-offload"]
        else:
            command += ["--no-mmproj"]
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.log_path = self.runtime / f"server-{time.time_ns()}.log"
        self._log = self.log_path.open("wb")
        before = memory_status()
        started = time.perf_counter()
        try:
            self.process = subprocess.Popen(command, stdout=self._log, stderr=subprocess.STDOUT, creationflags=flags)
            client = LocalLLM(f"http://127.0.0.1:{self.port}", timeout=2)
            while time.perf_counter() - started < self.startup_timeout:
                if self.process.poll() is not None:
                    raise InferenceError(f"llama.cpp exited ({self.process.returncode}); see {self.log_path}")
                try:
                    if client.health().get("status") == "ok":
                        break
                except InferenceError:
                    pass
                time.sleep(.2)
            else:
                raise InferenceError(f"Server startup timed out; see {self.log_path}")
            self.metadata = {"version": (version.stdout + version.stderr).strip(), "artifacts": artifacts,
                             "command": command, "startup_ms": round((time.perf_counter() - started) * 1000, 2),
                             "memory_before": before, "memory_at_ready": process_memory(self.process),
                             "log": str(self.log_path)}
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        if self._log:
            self._log.close()
