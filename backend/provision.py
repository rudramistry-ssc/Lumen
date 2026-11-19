"""One-time model setup for the Docker `models` service; never called by requests.

Downloads every pinned file once (resumable), verifies its size and SHA256, and
prebuilds the optimized Kokoro graph, so the app and model containers can mount
the volume read-only and run fully offline afterwards. Existing files are checked
without network access. A verified file is not re-hashed while its size and
modification time are unchanged (recorded in .verified.json).

    LUMEN_MODEL_SIZE=2B   (default) Qwen3-VL-2B-Instruct, Q4_K_M + F16 projector
    LUMEN_MODEL_SIZE=8B   Qwen3-VL-8B-Instruct, Q4_K_M + F16 projector

The F16 vision projector encodes an image ~35% faster than Q8_0 on a GPU.
"""
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

MODELS = Path(os.getenv("LUMEN_MODELS_DIR", "/models"))
HF = "https://huggingface.co/{repo}/resolve/{revision}/{name}"
KOKORO = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/"

QWEN = {
    "2B": ("Qwen/Qwen3-VL-2B-Instruct-GGUF", "52d6c8ffea26cc873ac5ad116f8631268d7eb503", {
        "Qwen3VL-2B-Instruct-Q4_K_M.gguf":
            (1107409952, "089d75c52f4b7ffc56ba998ffc50aae89fcafc755f9e7208aacca281dca6c2ae"),
        "mmproj-Qwen3VL-2B-Instruct-F16.gguf":
            (819394848, "c3d5afbef5287953acd57b4043d2269456e5761a4eaccb3b71b062996970aea5"),
    }),
    "8B": ("Qwen/Qwen3-VL-8B-Instruct-GGUF", "f982a07559d4a2f6c8744d840bf6fccab30eea96", {
        "Qwen3VL-8B-Instruct-Q4_K_M.gguf":
            (5027784800, "67d1659bfe71b89d50b45a4ad1a9e5b997e5bb16ce5da66a6a6167abd569e9e2"),
        "mmproj-Qwen3VL-8B-Instruct-F16.gguf":
            (1159029824, "ca524100ebf825c9a870db1c580d03879e0da0ab2541697e2458e64891cf9d38"),
    }),
}

# Same speech files and digests as the HPC version's setup_speech.py downloads.
WHISPER = ("Systran/faster-whisper-base", "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66", {
    "config.json": (2309, "56a6d8110d311f19c8f0471e562832c7527f146b567275bfca59fcf7c184da9a"),
    "model.bin": (145217532, "d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9"),
    "tokenizer.json": (2203239, "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab"),
    "vocabulary.txt": (459861, "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913"),
})
KOKORO_FILES = {
    "kokoro-v1.0.onnx": (325505369, "beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a"),
    "voices-v1.0.bin": (28214398, "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"),
}


def artifacts(size):
    repo, revision, files = QWEN[size]
    for name, (length, digest) in files.items():
        yield MODELS / "qwen" / name, HF.format(repo=repo, revision=revision, name=name), length, digest
    repo, revision, files = WHISPER
    for name, (length, digest) in files.items():
        yield MODELS / "whisper-base" / name, HF.format(repo=repo, revision=revision, name=name), length, digest
    for name, (length, digest) in KOKORO_FILES.items():
        yield MODELS / "kokoro" / name, KOKORO + name, length, digest


class Verified:
    """Remembers files already hashed, keyed by path, size and modification time."""

    def __init__(self):
        self.path = MODELS / ".verified.json"
        try:
            self.entries = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.entries = {}

    def _key(self, path):
        stat = path.stat()
        return [stat.st_size, stat.st_mtime_ns]

    def known(self, path, digest):
        entry = self.entries.get(str(path))
        return entry == [*self._key(path), digest]

    def remember(self, path, digest):
        self.entries[str(path)] = [*self._key(path), digest]
        temporary = self.path.with_suffix(".part")
        temporary.write_text(json.dumps(self.entries, indent=1), encoding="utf-8")
        temporary.replace(self.path)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check(path, length, digest):
    if path.stat().st_size != length:
        raise ValueError(f"Unexpected size for {path.name}; delete it and run setup again.")
    if sha256(path) != digest:
        raise ValueError(f"SHA256 mismatch for {path.name}; delete it and run setup again.")


def download(url, target, length, digest):
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > length:
        partial.unlink()
        offset = 0
    if offset < length:
        request = urllib.request.Request(url, headers={"Range": f"bytes={offset}-"} if offset else {})
        with urllib.request.urlopen(request, timeout=60) as response:
            append = bool(offset) and response.status == 206
            if append and not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                raise ValueError("Unexpected partial-download range")
            done, shown, started = (offset if append else 0), 0, time.monotonic()
            with partial.open("ab" if append else "wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    done += len(chunk)
                    if done - shown >= 100 * 1024 * 1024 or done == length:
                        shown = done
                        rate = (done - offset) / max(time.monotonic() - started, 1e-3) / 1e6
                        print(f"  {target.name}: {done / 1e6:,.0f} / {length / 1e6:,.0f} MB"
                              f" ({rate:.1f} MB/s)", flush=True)
    check(partial, length, digest)
    partial.replace(target)


def main():
    size = os.getenv("LUMEN_MODEL_SIZE", "2B").upper()
    if size not in QWEN:
        sys.exit(f"LUMEN_MODEL_SIZE must be one of {', '.join(QWEN)}, not {size!r}.")
    verified = Verified()
    for target, url, length, digest in artifacts(size):
        if target.exists():
            if not verified.known(target, digest):
                print(f"Verifying {target.relative_to(MODELS)}...", flush=True)
                check(target, length, digest)
        else:
            print(f"Downloading {target.relative_to(MODELS)} ({length / 1e6:,.0f} MB)...", flush=True)
            download(url, target, length, digest)
        verified.remember(target, digest)

    # Prebuild the loop-free Kokoro graph (same weights, FP32) on the writable volume.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from speech_acceleration import optimized_model
    print("Preparing the optimized Kokoro voice graph...", flush=True)
    optimized_model(MODELS / "kokoro" / "kokoro-v1.0.onnx")
    print(f"All models verified (Qwen3-VL-{size}). Later starts need no network access.", flush=True)


if __name__ == "__main__":
    main()
