"""Readiness inventory: no downloads, model inference or service startup."""
import argparse
from dataclasses import asdict
import importlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time

from common import ROOT, native, sha256, worker, write_json


def dependencies(ocr=False):
    # Read existing project manifests, not a second requirements/download system.
    import tomllib
    requirements = []
    if ocr:
        requirements = tomllib.loads((ROOT/"ocr/pyproject.toml").read_text())["project"]["dependencies"]
    else:
        requirements = [line.strip() for line in (ROOT/"speech/requirements.txt").read_text().splitlines() if line.strip() and not line.startswith("#")]
    versions, problems = {}, []
    for spec in requirements:
        match = re.fullmatch(r"([\w.-]+)(>=|==)([\d.]+)", spec)
        if not match: raise ValueError(f"Update checker for unsupported requirement syntax: {spec}")
        name, operator, wanted = match.groups()
        try: actual = metadata.version(name)
        except metadata.PackageNotFoundError: problems.append(f"Missing {spec}"); continue
        versions[name] = actual
        numbers = lambda value: tuple(int(x) for x in re.match(r"[\d.]+", value)[0].strip('.').split('.'))
        if (operator == "==" and actual != wanted) or (operator == ">=" and numbers(actual) < numbers(wanted)):
            problems.append(f"Installed {name}=={actual}; requires {spec}")
    if sys.version_info < (3, 11): problems.append("Python >=3.11 required")
    for module in (("numpy", "PIL", "cv2", "signspeak_ocr", "signspeak_llm") if ocr else ("piper", "onnxruntime", "signspeak_llm", "signspeak_stt", "signspeak_voice")):
        try: importlib.import_module(module)
        except Exception as exc: problems.append(f"Cannot import {module}: {exc}")
    return {"interpreter": sys.executable, "python": sys.version.split()[0], "versions": versions, "problems": problems}


def ocr_inventory():
    dep = dependencies(ocr=True)
    if dep["problems"]: raise RuntimeError("; ".join(dep["problems"]))
    from signspeak_ocr import TesseractConfig
    from signspeak_ocr.tesseract import get_tesseract_info
    info = get_tesseract_info(TesseractConfig())
    if int(info.version.split('.')[0]) < 4: raise RuntimeError("Tesseract >=4 required for LSTM OEM 1")
    output = native([info.cmd, *(["--tessdata-dir", info.tessdata_dir] if info.tessdata_dir else []), "--list-langs"])
    match = re.search(r'in "([^"]+)"', output.stdout+output.stderr)
    directory = Path(info.tessdata_dir or match[1]) if info.tessdata_dir or match else None
    files = []
    for language in ("eng", "fra"):
        path = directory/f"{language}.traineddata" if directory else None
        files.append({"file": str(path) if path else f"{language}.traineddata", "sha256": sha256(path) if path and path.is_file() else None,
                      "provenance": "locally installed Tesseract data; no source revision pinned in repository"})
    return {"dependencies": dep, "tesseract": asdict(info), "traineddata": files,
            "opencv_available": importlib.util.find_spec("cv2") is not None}


def writable(path):
    path = Path(path).expanduser()
    # Existing persistent models can be mounted read-only. Probe the nearest
    # existing parent for nonexistent directories without creating cache trees.
    probe = path
    while not probe.exists() and probe != probe.parent: probe = probe.parent
    with tempfile.TemporaryFile(dir=probe) as stream: stream.write(b"signspeak-readiness"); stream.flush()
    return {"requested": str(path), "tested_existing_directory": str(probe)}


def run_checks(ocr_python=None, *, service=True):
    from signspeak_llm.server import Server, default_model_dir, verify_file
    from signspeak_llm.client import LocalLLM
    from signspeak_speech.voices import VOICES, voice_directory, verify
    from signspeak_stt.provision import MODEL, RUNTIME, model_path, executable, cache_root, verify as verify_stt
    checks = []
    def check(name, action, remedy, *, required=True):
        started = time.perf_counter()
        try:
            data = action()
            checks.append({"name": name, "status": "pass", "details": data, "seconds": round(time.perf_counter()-started, 3), "required": required})
        except Exception as exc:
            checks.append({"name": name, "status": "fail" if required else "warning", "message": str(exc), "action": remedy, "required": required})
    def python_check():
        data = dependencies()
        if data["problems"]: raise RuntimeError("; ".join(data["problems"]))
        return data
    check("python_voice_dependencies", python_check, "Use a consuming environment with speech/requirements.txt and the five local packages. Existing speech/.venv is suitable for voice-only calls.")
    check("ocr", lambda: worker(ocr_python or os.getenv("SIGNSPEAK_DOCUMENT_PYTHON") or sys.executable, "ocr"), "Install ./ocr[preprocess] and ./llm in the chosen upload worker environment; install Tesseract with eng/fra or set SIGNSPEAK_TESSERACT_CMD/SIGNSPEAK_TESSDATA_DIR. See ocr/README.md.")
    server = Server(runtime=ROOT/"handoff/runtime")
    check("qwen_model", lambda: {"path": str(server.model), **verify_file(server.model)}, "Set SIGNSPEAK_LLM_MODEL or run: python llm/src/signspeak_llm/models.py vl (explicit first-install download).")
    projector = Path(os.getenv("SIGNSPEAK_LLM_PROJECTOR", str(default_model_dir()/"mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf")))
    check("qwen_projector", lambda: {"path": str(projector), **verify_file(projector)}, "Provision the exact pinned Q8 projector described in llm/README.md; set SIGNSPEAK_LLM_PROJECTOR. models.py vl downloads only the language model.")
    def runtime(path, args, expected):
        output = native([path, *args])
        text = output.stdout+output.stderr
        if expected.lower() not in text.lower(): raise RuntimeError(f"Executable failed probe ({output.returncode}): {text[-500:]}")
        return {"path": str(path), "probe": text[:250].strip()}
    check("llama_cpp_executable", lambda: runtime(server.binary, ["--version"], "version"), "Set SIGNSPEAK_LLAMA_SERVER to a compatible native llama-server with its shared libraries; reuse llm/README.md build 11904 / source 5cd62ffee guidance.")
    for language, item in VOICES.items():
        def voice(item=item, language=language):
            directory = voice_directory(language)
            return {"name": item["name"], "revision": item["revision"], "path": str(directory),
                    "files": [{"filename": f["filename"], "sha256": verify(directory/f["filename"], f)} for f in item["files"]]}
        check(f"piper_{language}", voice, f"Run in the consuming Piper environment: python -m signspeak_speech provision {language}; respect SIGNSPEAK_VOICE_DIR.")
    check("whisper_executable", lambda: runtime(executable(), ["--help"], "--language"), "Run python stt/src/signspeak_stt/provision.py on Windows, or build the pinned native Linux whisper-cli; set SIGNSPEAK_WHISPER_CLI.")
    check("whisper_model", lambda: {"path": str(model_path()), "revision": MODEL["revision"], "sha256": verify_stt(model_path(), MODEL)}, "Run python stt/src/signspeak_stt/provision.py explicitly; set SIGNSPEAK_WHISPER_MODEL for a persistent model mount.")
    for name, path in [("temporary_storage", tempfile.gettempdir()), ("handoff_outputs", ROOT/"handoff"),
                       ("document_cache", os.getenv("SIGNSPEAK_DOCUMENT_CACHE", str(Path.home()/".cache/signspeak/documents"))),
                       ("whisper_cache", cache_root()), ("qwen_cache", server.model.parent),
                       *[(f"piper_{lang}_cache", voice_directory(lang)) for lang in VOICES]]:
        check(name, lambda path=path: writable(path), "Configure writable temp/output locations. Model directories may be read-only after provisioning; use a writable mount only during first install.", required=name in ("temporary_storage", "handoff_outputs", "document_cache"))
    ffmpeg = os.getenv("SIGNSPEAK_FFMPEG") or shutil.which("ffmpeg")
    check("optional_ffmpeg", lambda: runtime(ffmpeg or "ffmpeg", ["-version"], "ffmpeg"), "Install a native FFmpeg build and set SIGNSPEAK_FFMPEG only if accepting WebM/Opus; canonical WAV needs none.", required=False)
    if service:
        def healthy():
            client = LocalLLM(timeout=3)
            data = client.health()
            if data.get("status") != "ok": raise RuntimeError(f"Service is not healthy: {data}")
            props = client.json_request("/props")
            if not (props.get("modalities") or {}).get("vision"):
                raise RuntimeError("Qwen is responding but vision is disabled. Restart the shared server once with --vision --context-size 8192.")
            if Path(props.get("model_path", "")).name != server.model.name:
                raise RuntimeError("Running server model does not match the configured pinned Qwen VL filename")
            context_size = props.get("default_generation_settings", {}).get("n_ctx")
            if not isinstance(context_size, int) or context_size < 8192:
                raise RuntimeError("Default accuracy-first upload needs an 8192-token server slot; restart once with --context-size 8192")
            return {"url": client.base_url, "health": data, "context_size": props.get("default_generation_settings", {}).get("n_ctx"),
                    "vision_enabled": True, "model_path": props["model_path"],
                    "note": "Health/capability checks are not semantic answer verification; run smoke test."}
        check("qwen_service", healthy, "Start once: python -m signspeak_llm serve --vision --context-size 8192 --threads 4. Set SIGNSPEAK_LLM_URL to that trusted local/container origin.")
    return {"ready": all(x["status"] == "pass" for x in checks if x["required"]), "interpreter": sys.executable,
            "checks": checks, "downloads": "never performed", "service_checked": service}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocr-python", type=Path)
    parser.add_argument("--json", type=Path, help="Optional report path under handoff/")
    parser.add_argument("--worker", choices=["ocr"], help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.worker:
            print(json.dumps(ocr_inventory(), ensure_ascii=True)); return 0
        report = run_checks(args.ocr_python)
        if args.json:
            if ROOT/"handoff" not in args.json.resolve().parents: raise ValueError("Report must stay under handoff/")
            write_json(args.json, report)
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0 if report["ready"] else 1
    except Exception as exc:
        print(json.dumps({"ready": False, "error": str(exc), "action": "Use Python >=3.11 and the documented environment; no downloads were attempted."}))
        return 1


if __name__ == "__main__": raise SystemExit(main())
