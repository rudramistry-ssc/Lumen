"""Explicit, pinned artifact provisioning, independent of normal inference."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import urllib.request
import zipfile

RUNTIME = {"tag": "b5454", "version": "1.9.5", "commit": "d1be6fde11ac6e0407606b4e42fe72d34add8037",
           "filename": "whisper-bin-x64.zip", "bytes": 8928640,
           "sha256": "6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb",
           "url": "https://github.com/ggml-org/whisper.cpp/releases/download/b5454/whisper-bin-x64.zip", "license": "MIT"}
MODEL = {"repository": "ggerganov/whisper.cpp", "revision": "5359861c739e955e79d9a303bcbc70fb988958b1",
         "filename": "ggml-base.bin", "bytes": 147951465,
         "sha256": "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe", "license": "MIT"}


def cache_root():
    return Path(os.getenv("SIGNSPEAK_STT_CACHE", str(Path.home() / ".cache/signspeak/stt")))


def model_path():
    explicit = os.getenv("SIGNSPEAK_WHISPER_MODEL")
    if explicit:
        return Path(explicit)
    hf = Path(os.getenv("HF_HUB_CACHE", str(Path.home() / ".cache/huggingface/hub")))
    candidate = hf / "models--ggerganov--whisper.cpp/snapshots" / MODEL["revision"] / MODEL["filename"]
    if candidate.is_file():
        return candidate
    return cache_root() / "models" / MODEL["revision"] / MODEL["filename"]


def executable(kind="cli"):
    key = "SIGNSPEAK_WHISPER_SERVER" if kind == "server" else "SIGNSPEAK_WHISPER_CLI"
    explicit = os.getenv(key)
    name = "whisper-server" if kind == "server" else "whisper-cli"
    if explicit:
        return Path(explicit)
    found = shutil.which(name) or shutil.which(name + ".exe")
    if found:
        return Path(found)
    directory = cache_root() / "runtime" / RUNTIME["tag"]
    matches = list(directory.rglob(name + ".exe")) if directory.exists() else []
    return matches[0] if matches else directory / (name + (".exe" if os.name == "nt" else ""))


def verify(path, artifact):
    path = Path(path)
    if path.stat().st_size != artifact["bytes"]:
        raise ValueError(f"Unexpected file size: {path}")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != artifact["sha256"]:
        raise ValueError(f"SHA256 mismatch: {path}")
    return digest


def download(url, path, artifact):
    if path.exists():
        verify(path, artifact)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset < artifact["bytes"]:
        request = urllib.request.Request(url, headers={"Range": f"bytes={offset}-"} if offset else {})
        with urllib.request.urlopen(request, timeout=60) as response:
            append = offset and response.status == 206
            if append and not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                raise ValueError("Unexpected partial-download range")
            with partial.open("ab" if append else "wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
    verify(partial, artifact)
    partial.replace(path)


def provision():
    if os.name != "nt":
        # Docker/Linux uses the native CPU binary built by the container team.
        target = model_path()
        url = f"https://huggingface.co/{MODEL['repository']}/resolve/{MODEL['revision']}/{MODEL['filename']}"
        download(url, target, MODEL)
        return {"model": str(target), "model_artifact": MODEL, "cli": str(executable()),
                "runtime_note": "Build the pinned whisper.cpp source natively; no Windows archive downloaded."}
    archive = cache_root() / "downloads" / RUNTIME["filename"]
    download(RUNTIME["url"], archive, RUNTIME)
    directory = cache_root() / "runtime" / RUNTIME["tag"]
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / "installed.json"
    if not marker.exists():
        with zipfile.ZipFile(archive) as zipped:
            for member in zipped.infolist():
                target = (directory / member.filename).resolve()
                if directory.resolve() not in target.parents and target != directory.resolve():
                    raise ValueError("Unsafe runtime archive path")
            zipped.extractall(directory)
        hashes = {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in directory.rglob("*") if p.is_file()}
        marker.write_text(json.dumps({"runtime": RUNTIME, "files": hashes}, indent=2), encoding="utf-8")
    target = model_path()
    url = f"https://huggingface.co/{MODEL['repository']}/resolve/{MODEL['revision']}/{MODEL['filename']}"
    download(url, target, MODEL)
    return {"runtime_directory": str(directory), "cli": str(executable()), "server": str(executable("server")),
            "model": str(target), "runtime": RUNTIME, "model_artifact": MODEL}


if __name__ == "__main__":
    print(json.dumps(provision(), indent=2))
