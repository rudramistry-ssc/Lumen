"""Run with PYTHONPATH=llm/src, or install this package separately."""
import argparse
import json
from pathlib import Path
import sys
import time

from .client import InferenceError, LocalLLM
from .server import Server


def main():
    parser = argparse.ArgumentParser(description="SignSpeak local inference")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Start an owned CPU server; Ctrl+C stops only this process")
    serve.add_argument("--binary")
    serve.add_argument("--model")
    serve.add_argument("--projector", help="Optional local Q8 projector; omit for OCR-only chat")
    serve.add_argument("--threads", type=int, default=4)
    serve.add_argument("--context-size", type=int, default=4096)
    serve.add_argument("--port", type=int, default=8091)
    ask = sub.add_parser("ask", help="Answer from a saved adapter view; never runs OCR")
    ask.add_argument("context", type=Path)
    ask.add_argument("question")
    ask.add_argument("--history", type=Path)
    ask.add_argument("--language", choices=["auto", "en", "fr"], default="auto")
    ask.add_argument("--url")
    ask.add_argument("--context-size", type=int, default=4096)
    ask.add_argument("--max-tokens", type=int, default=192)
    args = parser.parse_args()
    try:
        if args.command == "serve":
            with Server(binary=args.binary, model=args.model, projector=args.projector,
                        threads=args.threads, context_size=args.context_size, port=args.port) as server:
                print(json.dumps(server.metadata, indent=2), flush=True)
                print(f"Ready at http://127.0.0.1:{args.port}. Ctrl+C stops this server.", flush=True)
                while server.process.poll() is None:
                    time.sleep(.5)
                raise InferenceError(f"Server exited: {server.process.returncode}; see {server.log_path}")
        else:
            context = json.loads(args.context.read_text(encoding="utf-8-sig"))
            context = context.get("llm_context", context)
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
