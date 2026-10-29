"""Wall-clock worker boundary. Only the owned worker tree is terminated."""
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import math
import time


def stop_tree(process, timeout):
    end = time.monotonic()+timeout
    if process.poll() is not None: return {"worker_stopped": True, "tree_termination": "already_exited"}
    if os.name == "nt":
        # taskkill targets this freshly-created worker and its OCR children,
        # never the independently-running llama.cpp service.
        try:
            killed = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True, timeout=max(.05, timeout), creationflags=subprocess.CREATE_NO_WINDOW)
            tree = "confirmed" if killed.returncode == 0 else "not_confirmed"
        except (OSError, subprocess.TimeoutExpired): tree = "not_confirmed"
        if process.poll() is None: process.kill()
    else:
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        tree = "confirmed"
    try: process.wait(timeout=max(.001, end-time.monotonic()))
    except subprocess.TimeoutExpired: return {"worker_stopped": False, "tree_termination": tree}
    return {"worker_stopped": True, "tree_termination": tree,
            "inference_cancellation": "owned HTTP connections closed; native server cancellation is disconnect-driven",
            "shared_server_stopped": False}


def run_bounded(command, payload, *, seconds, env=None):
    """A total deadline includes process startup, IO, work and cleanup reserve.

    A pathological OS that refuses to terminate a process is reported, not claimed
    successfully cancelled. There is no retry, service restart or late cache writer.
    """
    started = time.monotonic()
    if not math.isfinite(seconds) or seconds <= 0: raise ValueError("Deadline must be finite and positive")
    cleanup = min(3.0, seconds/2)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, start_new_session=os.name != "nt", creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except OSError as exc: return {"ok": False, "error": str(exc), "elapsed_seconds": time.monotonic()-started}
    remaining = seconds-(time.monotonic()-started)-cleanup
    expired, cancelled = threading.Event(), threading.Event()
    cancellation = {"worker_stopped": False, "tree_termination": "not_confirmed", "shared_server_stopped": False}
    once = threading.Lock()
    def expire():
        if not once.acquire(blocking=False): return
        expired.set()
        cancellation.update(stop_tree(process, max(.001, seconds-(time.monotonic()-started))))
        cancelled.set()
    # A watchdog is essential on Windows: communicate() can block writing stdin
    # before its own timeout wait starts. Killing the worker also unblocks pipes.
    timer = threading.Timer(max(0, remaining), expire)
    timer.daemon = True
    timer.start()
    try:
        stdout, stderr = process.communicate(data, timeout=max(.001, seconds-(time.monotonic()-started)))
        if expired.is_set():
            cancelled.wait(max(0, seconds-(time.monotonic()-started)))
            return {"ok": False, "deadline_exceeded": True, "cancellation": dict(cancellation),
                    "elapsed_seconds": time.monotonic()-started, "error": "Upload exceeded its total wall-clock processing deadline"}
        if process.returncode:
            return {"ok": False, "error": stderr.decode("utf-8", "replace")[-1000:] or stdout.decode("utf-8", "replace")[-1000:],
                    "elapsed_seconds": time.monotonic()-started}
        return {"ok": True, "stdout": stdout, "elapsed_seconds": time.monotonic()-started}
    except subprocess.TimeoutExpired:
        expire()
        cancelled.wait(max(0, seconds-(time.monotonic()-started)))
        return {"ok": False, "deadline_exceeded": True, "cancellation": dict(cancellation),
                "elapsed_seconds": time.monotonic()-started, "error": "Upload exceeded its total wall-clock processing deadline"}
    except BaseException:
        expire()
        raise
    finally: timer.cancel()
