"""Start the whole app with one command: AI service, backend and frontend.

    python run.py              check everything, start all three, open the browser
    python run.py --check      only check that everything is installed
    python run.py --no-browser start without opening the browser

Works on macOS and Windows. Run it with the project's virtual environment
(see README.md). Press Ctrl+C to stop everything.
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORTS = {"ai": 9000, "backend": 8000, "frontend": 5500}
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "llama3.2:3b")


def say(status: str, message: str) -> None:
    # Plain ASCII so it prints the same in a Windows terminal.
    print(f"  [{status:^4}] {message}", flush=True)


def get_json(url: str, timeout: float = 3) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def port_free(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex((HOST, port)) != 0


def wait_for(url: str, seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if get_json(url, timeout=2) is not None:
            return True
        time.sleep(0.5)
    return False


# ---------- checks ----------

def check_python_packages() -> bool:
    missing = []
    for module in ("fastapi", "uvicorn", "httpx", "multipart", "pydantic_settings", "cv2", "signspeak_ocr"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    if missing:
        say("FAIL", f"Python packages missing: {', '.join(missing)}")
        say("", "Fix: activate the virtual environment, then: pip install -r requirements.txt")
        return False
    say("OK", f"Python {sys.version.split()[0]} with all packages")
    return True


def check_tesseract() -> bool:
    from signspeak_ocr import TesseractConfig
    from signspeak_ocr.tesseract import get_tesseract_info

    try:
        info = get_tesseract_info(TesseractConfig())
    except Exception as exc:  # noqa: BLE001 - any failure here means "not installed"
        say("FAIL", f"Tesseract OCR: {exc}")
        if sys.platform == "win32":
            say("", "Fix: install from https://github.com/UB-Mannheim/tesseract/wiki and tick French")
        else:
            say("", "Fix: brew install tesseract tesseract-lang")
        return False
    say("OK", f"Tesseract OCR {info.version} with English + French")
    return True


def ollama_running() -> dict | None:
    return get_json(f"{LLM_BASE_URL.rstrip('/')}/models")


def find_ollama() -> str | None:
    # PATH first, then where the official installers / downloads put it.
    candidates = [
        Path.home() / ".local" / "ollama" / "ollama",                       # macOS: release .tgz unpacked here
        Path("/Applications/Ollama.app/Contents/Resources/ollama"),         # macOS app
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",  # Windows installer
    ]
    found = shutil.which("ollama")
    if found:
        return found
    return next((str(c) for c in candidates if c.is_file()), None)


def check_llm(processes: list) -> bool:
    models = ollama_running()
    local_ollama = "localhost:11434" in LLM_BASE_URL or "127.0.0.1:11434" in LLM_BASE_URL
    ollama = find_ollama()
    if models is None and local_ollama and ollama:
        # Installed but not started (the Windows app usually starts it by itself).
        say("..", "Starting Ollama")
        processes.append(("ollama", subprocess.Popen(
            [ollama, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)))
        if wait_for(f"{LLM_BASE_URL.rstrip('/')}/models", 20):
            models = ollama_running()
    if models is None:
        say("FAIL", f"Language model server not reachable at {LLM_BASE_URL}")
        say("", "Fix: install Ollama from https://ollama.com (or: brew install ollama), then run this again")
        say("", "Without it, everything works except chat answers.")
        return False
    names = [m.get("id", "") for m in models.get("data", [])]
    if not any(n == LLM_MODEL or n.split(":")[0] == LLM_MODEL for n in names):
        say("FAIL", f"Model {LLM_MODEL} is not downloaded (have: {', '.join(names) or 'none'})")
        say("", f"Fix: {'ollama' if shutil.which('ollama') else (ollama or 'ollama')} pull {LLM_MODEL}")
        return False
    say("OK", f"Language model {LLM_MODEL}")
    return True


def check_tts() -> bool:
    sys.path.insert(0, str(ROOT / "ai-service"))
    import tts

    kind = tts.engine()
    if kind is None:
        say("WARN", "No speech engine for backend audio (the browser still reads aloud)")
        return False
    say("OK", f"Speech engine: {kind}")
    return True


def check_ports() -> bool:
    busy = [f"{name} ({port})" for name, port in PORTS.items() if not port_free(port)]
    if busy:
        say("FAIL", f"Ports already in use: {', '.join(busy)}")
        say("", "Is the app already running in another terminal? Stop it there (Ctrl+C), or close what uses the port.")
        return False
    say("OK", f"Ports {', '.join(str(p) for p in PORTS.values())} are free")
    return True


# ---------- start ----------

def start(name: str, args: list[str], cwd: Path, env: dict | None = None, quiet: bool = False) -> subprocess.Popen:
    # quiet: hide the static file server's one-line-per-request log.
    output = subprocess.DEVNULL if quiet else None
    return subprocess.Popen(args, cwd=cwd, env={**os.environ, **(env or {})}, stdout=output, stderr=output)


def stop_all(processes: list) -> None:
    for _, process in reversed(processes):
        if process.poll() is None:
            process.terminate()
    for _, process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="only check the setup, start nothing")
    parser.add_argument("--no-browser", action="store_true", help="don't open the browser")
    args = parser.parse_args()

    processes: list[tuple[str, subprocess.Popen]] = []
    print("\nChecking setup")
    if not check_python_packages():
        return 1
    ocr_ok = check_tesseract()
    llm_ok = check_llm(processes)
    tts_ok = check_tts()
    if args.check:
        stop_all(processes)
        return 0 if (ocr_ok and llm_ok) else 1
    if not check_ports():
        stop_all(processes)
        return 1
    if not ocr_ok:
        say("WARN", "Starting anyway: photos can't be read until Tesseract is installed")
    if not llm_ok:
        say("WARN", "Starting anyway: chat answers won't work until the model is ready")

    print("\nStarting")
    python = sys.executable
    uvicorn = [python, "-m", "uvicorn", "--host", HOST, "--log-level", "warning"]
    try:
        processes.append(("ai", start("ai", [*uvicorn, "--port", str(PORTS["ai"]), "app:app"], ROOT / "ai-service",
                                      {"LLM_BASE_URL": LLM_BASE_URL, "LLM_MODEL": LLM_MODEL})))
        processes.append(("backend", start("backend", [*uvicorn, "--port", str(PORTS["backend"]), "main:app"], ROOT / "backend",
                                           {"AI_BASE_URL": f"http://{HOST}:{PORTS['ai']}",
                                            "TTS_ENABLED": "true" if tts_ok else "false"})))
        processes.append(("frontend", start("frontend", [python, "-m", "http.server", str(PORTS["frontend"]), "--bind", HOST],
                                            ROOT / "frontend", quiet=True)))

        checks = [("AI service", f"http://{HOST}:{PORTS['ai']}/healthz"),
                  ("Backend", f"http://{HOST}:{PORTS['backend']}/healthz"),
                  ("Frontend", f"http://{HOST}:{PORTS['frontend']}/config.js")]
        for label, url in checks:
            if url.endswith(".js"):
                # http.server serves files, not JSON: just check it answers.
                ok = False
                deadline = time.time() + 15
                while time.time() < deadline and not ok:
                    try:
                        urllib.request.urlopen(url, timeout=2).close()
                        ok = True
                    except (urllib.error.URLError, OSError):
                        time.sleep(0.5)
            else:
                ok = wait_for(url, 30)
            say("OK" if ok else "FAIL", f"{label}  {url.rsplit('/', 1)[0]}")
            if not ok:
                say("", "It did not start; see the error printed above.")
                stop_all(processes)
                return 1

        app_url = f"http://localhost:{PORTS['frontend']}"
        print(f"\nLumen is running:  {app_url}")
        print(f"API docs:          http://localhost:{PORTS['backend']}/docs")
        print("Press Ctrl+C to stop.\n")
        if not args.no_browser:
            webbrowser.open(app_url)

        while True:
            for name, process in processes:
                if process.poll() is not None:
                    print(f"\n{name} stopped unexpectedly (exit code {process.returncode}). Stopping everything.")
                    return 1
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        return 0
    finally:
        stop_all(processes)


if __name__ == "__main__":
    sys.exit(main())
