"""Start a local model with vLLM on an allocated GPU node.

Uses the active Python environment. Model paths, served name and GPU settings
are arguments/environment variables; no cluster-specific paths live in code.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path


def resolve_model(path: Path) -> Path:
    """Accept a model directory, HF snapshot, or HF cache entry with refs/main."""
    path = path.expanduser().resolve()
    reference = path / "refs" / "main"
    if reference.is_file():
        revision = reference.read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"[a-fA-F0-9]{40,64}", revision):
            raise ValueError("Model cache refs/main is not a valid snapshot revision")
        path = path / "snapshots" / revision
    if not (path / "config.json").is_file():
        raise ValueError(f"Model directory has no readable config.json: {path}")
    index = path / "model.safetensors.index.json"
    if index.is_file():
        data = json.loads(index.read_text(encoding="utf-8"))
        shards = set(data.get("weight_map", {}).values())
        if not shards:
            raise ValueError("Model weight index is empty")
        for shard in shards:
            if not (path / shard).is_file() or not os.access(path / shard, os.R_OK):
                raise ValueError(f"Missing or unreadable model shard: {shard}")
    elif not list(path.glob("*.safetensors")) and not list(path.glob("pytorch_model*.bin")):
        raise ValueError("No model weights found in the model directory")
    return path


def build_command(args: argparse.Namespace, model: Path) -> list[str]:
    command = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--model", str(model),
        "--served-model-name", args.served_model_name,
        "--host", args.host,
        "--port", str(args.port),
        "--dtype", args.dtype,
        "--tensor-parallel-size", str(args.tensor_parallel_size),
        "--gpu-memory-utilization", str(args.gpu_memory_utilization),
        "--max-model-len", str(args.max_model_len),
        "--max-num-seqs", str(args.max_num_seqs),
        "--limit-mm-per-prompt", json.dumps({"image": 1, "video": 0}),
        "--generation-config", "vllm",
    ]
    if args.mm_processor_kwargs is not None:
        command.extend(["--mm-processor-kwargs", args.mm_processor_kwargs])
    return command


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=os.getenv("SIGNSPEAK_MODEL_PATH"),
                        help="Local model directory or HF cache entry; also SIGNSPEAK_MODEL_PATH")
    parser.add_argument("--served-model-name", default=os.getenv("SIGNSPEAK_VLM_MODEL", "hackathon-llm"))
    parser.add_argument("--host", default="127.0.0.1", help="Bind address; use loopback with an SSH tunnel")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--dtype", choices=("auto", "bfloat16", "float16"), default="bfloat16")
    parser.add_argument("--tensor-parallel-size", type=int, default=1)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.90)
    parser.add_argument("--max-model-len", type=int, default=32768)
    parser.add_argument("--max-num-seqs", type=int, default=2)
    parser.add_argument("--mm-processor-kwargs", help="Optional model-specific JSON, e.g. pixel limits")
    parser.add_argument("--dry-run", action="store_true", help="Validate local files and print the launch command")
    args = parser.parse_args()
    if args.model is None:
        parser.error("Supply --model or set SIGNSPEAK_MODEL_PATH")
    if not 1 <= args.port <= 65535 or not 0 < args.gpu_memory_utilization <= 1:
        parser.error("Invalid port or GPU memory utilization")
    if min(args.tensor_parallel_size, args.max_model_len, args.max_num_seqs) <= 0:
        parser.error("GPU count, context length and sequence count must be positive")
    if not args.served_model_name.strip():
        parser.error("Served model name cannot be empty")
    try:
        model = resolve_model(args.model)
        if args.mm_processor_kwargs is not None:
            if not isinstance(json.loads(args.mm_processor_kwargs), dict):
                raise ValueError("--mm-processor-kwargs must be a JSON object")
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))
    command = build_command(args, model)
    print("Model directory:", model, flush=True)
    print("Launch:", shlex.join(command), flush=True)
    if args.dry_run:
        return 0
    api_key = os.getenv("SIGNSPEAK_VLM_API_KEY")
    if not api_key:
        parser.error("Set SIGNSPEAK_VLM_API_KEY; clients must use the same key")
    environment = dict(os.environ)
    environment["VLLM_API_KEY"] = api_key
    environment["HF_HUB_OFFLINE"] = "1"
    environment["TRANSFORMERS_OFFLINE"] = "1"
    # No automatic downloads, trust_remote_code, or global environment changes.
    try:
        return subprocess.call(command, env=environment)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
