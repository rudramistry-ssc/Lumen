"""Container setup and Qwen lifecycle; never invoked by request handlers."""

import argparse
import json
import os
from pathlib import Path
from urllib.request import ProxyHandler, build_opener


def provision() -> None:
    from signspeak_llm.server import FILES, MODEL_REPO, REVISION, verify_file
    from signspeak_speech.voices import provision as provision_voice
    from signspeak_stt.provision import MODEL, download

    for variable in ("SIGNSPEAK_LLM_MODEL", "SIGNSPEAK_LLM_PROJECTOR"):
        target = Path(os.environ[variable])
        size, digest = FILES[target.name]
        print(f"Checking/downloading {target.name}...", flush=True)
        download(
            f"https://huggingface.co/{MODEL_REPO}/resolve/{REVISION}/{target.name}",
            target, {"bytes": size, "sha256": digest},
        )
        verify_file(target)
    target = Path(os.environ["SIGNSPEAK_WHISPER_MODEL"])
    print(f"Checking/downloading {target.name}...", flush=True)
    download(
        f"https://huggingface.co/{MODEL['repository']}/resolve/{MODEL['revision']}/{MODEL['filename']}",
        target, MODEL,
    )
    for language in ("en", "fr"):
        print(f"Checking/downloading Piper {language}...", flush=True)
        provision_voice(language)
    print("All pinned models verified. Existing files require no network access.", flush=True)


def serve() -> None:
    from signspeak_llm.server import verify_file

    model = os.environ["SIGNSPEAK_LLM_MODEL"]
    projector = os.environ["SIGNSPEAK_LLM_PROJECTOR"]
    verify_file(model)
    verify_file(projector)
    threads = int(os.getenv("SIGNSPEAK_THREADS", "4"))
    if threads < 1:
        raise ValueError("SIGNSPEAK_THREADS must be positive")
    binary = os.environ["SIGNSPEAK_LLAMA_SERVER"]
    # The package's development launcher binds localhost. Compose needs 0.0.0.0;
    # keep its CPU, single-slot, offline and vision flags without altering it.
    command = [
        binary, "-m", model, "--mmproj", projector,
        "--host", "0.0.0.0", "--port", "8091", "-c", "8192",
        "-t", str(threads), "-tb", str(threads), "-ngl", "0",
        "--device", "none", "--parallel", "1", "--jinja", "--offline",
        "--no-context-shift", "--batch-size", "256", "--ubatch-size", "128",
        "--alias", "signspeak", "--reasoning", "off",
        "--chat-template-kwargs", '{"enable_thinking":false}', "--no-mmproj-offload",
    ]
    os.execv(binary, command)


def health(url: str) -> None:
    with build_opener(ProxyHandler({})).open(url, timeout=3) as response:
        result = json.load(response)
    if result.get("status") != "ok":
        raise RuntimeError(f"Service is not ready: {url}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("provision", "serve", "health"))
    parser.add_argument("url", nargs="?")
    args = parser.parse_args()
    if args.action == "health":
        if not args.url:
            parser.error("health requires a URL")
        health(args.url)
    elif args.action == "provision":
        provision()
    else:
        serve()
