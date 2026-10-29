"""Explicit one-time provisioning; synthesis never downloads files."""
import argparse
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import urllib.request

VOICES = json.loads(files("signspeak_speech").joinpath("voices.json").read_text(encoding="utf-8"))


def voice_directory(language, root=None):
    item = VOICES[language]
    root = root or os.getenv("SIGNSPEAK_VOICE_DIR")
    if root:
        return Path(root) / item["name"]
    hf = Path(os.getenv("HF_HUB_CACHE", str(Path.home() / ".cache/huggingface/hub")))
    snapshot = hf / "models--rhasspy--piper-voices/snapshots" / item["revision"] / Path(item["files"][0]["path"]).parent
    if (snapshot / item["files"][0]["filename"]).is_file():
        return snapshot
    return Path.home() / ".cache/signspeak/voices" / item["revision"] / item["name"]


def verify(path, artifact):
    path = Path(path)
    if path.stat().st_size != artifact["bytes"]:
        raise ValueError(f"Unexpected file size: {path}")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != artifact["sha256"]:
        raise ValueError(f"SHA256 mismatch: {path}")
    return digest


def provision(language, root=None):
    item = VOICES[language]
    directory = voice_directory(language, root)
    directory.mkdir(parents=True, exist_ok=True)
    for artifact in item["files"]:
        path = directory / artifact["filename"]
        if path.exists():
            verify(path, artifact)
            continue
        partial = path.with_suffix(path.suffix + ".part")
        offset = partial.stat().st_size if partial.exists() else 0
        if offset < artifact["bytes"]:
            url = f"https://huggingface.co/{item['repository']}/resolve/{item['revision']}/{artifact['path']}"
            request = urllib.request.Request(url, headers={"Range": f"bytes={offset}-"} if offset else {})
            with urllib.request.urlopen(request, timeout=60) as response:
                append = offset and response.status == 206
                if append and not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                    raise ValueError("Unexpected download offset")
                with partial.open("ab" if append else "wb") as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
        verify(partial, artifact)
        partial.replace(path)
    return directory


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download only the two pinned Piper voices once, with checksum verification")
    parser.add_argument("languages", nargs="*", choices=["en", "fr"], default=["en", "fr"])
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    for language in args.languages:
        print(provision(language, args.directory), flush=True)
