"""Run with PYTHONPATH=llm/src, or install this package separately."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

from .client import InferenceError, LocalLLM
from .server import Server, default_model_dir
from .reconcile import Reconciler


def main():
    parser = argparse.ArgumentParser(description="SignSpeak local inference")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Start an owned CPU server; Ctrl+C stops only this process")
    serve.add_argument("--binary")
    serve.add_argument("--model")
    serve.add_argument("--projector", help="Optional local Q8 projector; omit for OCR-only chat")
    serve.add_argument("--vision", action="store_true", default=True, help="Default: load the cached Qwen vision projector")
    serve.add_argument("--text-only", dest="vision", action="store_false", help="Explicit legacy/evaluation mode; cannot process normal uploads")
    serve.add_argument("--threads", type=int, default=4)
    serve.add_argument("--context-size", type=int, default=8192)
    serve.add_argument("--port", type=int, default=8091)
    ask = sub.add_parser("ask", help="Answer from a completed selected-document JSON; never reanalyzes the image")
    ask.add_argument("context", type=Path)
    ask.add_argument("question")
    ask.add_argument("--history", type=Path)
    ask.add_argument("--language", choices=["auto", "en", "fr"], default="auto")
    ask.add_argument("--url")
    ask.add_argument("--context-size", type=int, default=8192)
    ask.add_argument("--allow-legacy-ocr", action="store_true")
    ask.add_argument("--allow-ocr-fallback", action="store_true")
    ask.add_argument("--max-tokens", type=int, default=192)
    reconcile = sub.add_parser("reconcile", help="Transcribe image + saved adapter evidence; cache the separate result")
    reconcile.add_argument("image", type=Path)
    reconcile.add_argument("context", type=Path)
    reconcile.add_argument("--output", type=Path, required=True)
    reconcile.add_argument("--url")
    reconcile.add_argument("--cache-dir", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "serve":
            projector = args.projector
            if args.vision and not projector:
                projector = os.getenv("SIGNSPEAK_LLM_PROJECTOR", str(default_model_dir() / "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf"))
            with Server(binary=args.binary, model=args.model, projector=projector,
                        threads=args.threads, context_size=args.context_size, port=args.port) as server:
                print(json.dumps(server.metadata, indent=2), flush=True)
                print(f"Ready at http://127.0.0.1:{args.port}. Ctrl+C stops this server.", flush=True)
                while server.process.poll() is None:
                    time.sleep(.5)
                raise InferenceError(f"Server exited: {server.process.returncode}; see {server.log_path}")
        elif args.command == "reconcile":
            if args.output.resolve() in {args.context.resolve(), args.image.resolve()}:
                raise ValueError("Reconciliation output must be separate from the source image and OCR/view JSON")
            context = json.loads(args.context.read_text(encoding="utf-8-sig"))
            if isinstance(context.get("views"), dict):
                context = context["views"]
            context = context.get("llm_context", context)
            client = LocalLLM(args.url, max_tokens=768, timeout=240)
            result = Reconciler(client, cache_dir=args.cache_dir).reconcile(args.image.read_bytes(), context)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{result['status']}: {args.output}")
            return 2 if result["status"] == "fallback" else 0
        else:
            context = json.loads(args.context.read_text(encoding="utf-8-sig"))
            if "selected_views" in context:
                if context.get("status") == "ocr_unreviewed_fallback" and not args.allow_ocr_fallback:
                    raise ValueError("Unreviewed OCR fallback requires explicit --allow-ocr-fallback")
                context = context["selected_views"]["llm_context"]
            elif args.allow_legacy_ocr:
                context = context.get("llm_context", context)
            else:
                raise ValueError("Use a completed DocumentProcessor JSON; OCR-only Q&A requires explicit --allow-legacy-ocr")
            history = json.loads(args.history.read_text(encoding="utf-8-sig")) if args.history else []
            result = LocalLLM(args.url, context_size=args.context_size, max_tokens=args.max_tokens).answer(
                context, args.question, history, language=args.language)
            sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    except KeyboardInterrupt:
        return 0
    except (InferenceError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
