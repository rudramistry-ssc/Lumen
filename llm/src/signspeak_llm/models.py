"""Pinned artifacts; provisioning is explicit and separate from offline serving."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import urllib.request

MODELS = {
    "vl": {"repository": "Qwen/Qwen3-VL-2B-Instruct-GGUF", "revision": "52d6c8ffea26cc873ac5ad116f8631268d7eb503",
           "filename": "Qwen3VL-2B-Instruct-Q4_K_M.gguf", "bytes": 1107409952,
           "sha256": "089d75c52f4b7ffc56ba998ffc50aae89fcafc755f9e7208aacca281dca6c2ae", "license": "Apache-2.0"},
    "text": {"repository": "unsloth/Qwen3-1.7B-GGUF", "revision": "d7f544eead698dbd1f15126ef60b45a1e1933222",
             "filename": "Qwen3-1.7B-Q4_K_M.gguf", "bytes": 1107409472,
             "sha256": "b139949c5bd74937ad8ed8c8cf3d9ffb1e99c866c823204dc42c0d91fa181897", "license": "Apache-2.0"},
}


def model_path(key):
    item = MODELS[key]
    hf = Path(os.getenv("HF_HUB_CACHE", str(Path.home() / ".cache/huggingface/hub")))
    snapshot = hf / ("models--" + item["repository"].replace("/", "--")) / "snapshots" / item["revision"] / item["filename"]
    if snapshot.is_file():
        return snapshot
    cache = Path(os.getenv("SIGNSPEAK_MODEL_CACHE", str(Path.home() / ".cache/signspeak/models")))
    return cache / key / item["revision"] / item["filename"]


def check(path, item):
    path = Path(path)
    if path.stat().st_size != item["bytes"]:
        raise ValueError(f"Unexpected size: {path}")
    with path.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    if digest != item["sha256"]:
        raise ValueError(f"SHA256 mismatch: {path}")
    return {**item, "verified_sha256": digest}


def provision(key):
    """Download missing pinned file once. TLS verification is never disabled."""
    item, path = MODELS[key], model_path(key)
    if path.exists():
        check(path, item)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".gguf.part")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset < item["bytes"]:
        url = f"https://huggingface.co/{item['repository']}/resolve/{item['revision']}/{item['filename']}"
        request = urllib.request.Request(url, headers={"Range": f"bytes={offset}-"} if offset else {})
        with urllib.request.urlopen(request, timeout=60) as response:
            if offset and response.status == 206:
                if not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                    raise ValueError("Unexpected partial-download offset")
                mode = "ab"
            else:
                mode = "wb"
            with partial.open(mode) as file:
                while chunk := response.read(1024 * 1024):
                    file.write(chunk)
    check(partial, item)
    partial.replace(path)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="One-time model provisioning; not used by normal inference")
    parser.add_argument("model", choices=MODELS)
    args = parser.parse_args()
    print(provision(args.model))
