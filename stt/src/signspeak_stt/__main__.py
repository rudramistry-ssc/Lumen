import argparse
import json
import sys
from pathlib import Path
from .engine import transcribe, convert_audio

parser = argparse.ArgumentParser(description="Local CPU transcription; no downloads")
parser.add_argument("audio", type=Path)
parser.add_argument("--language", choices=["auto", "en", "fr"], default="auto")
parser.add_argument("--convert", action="store_true", help="Explicitly convert using configured FFmpeg")
args = parser.parse_args()
try:
    with args.audio.open("rb") as stream: audio = stream.read(8_000_001)
    if args.convert: audio = convert_audio(audio)
    result = transcribe(audio, args.language)
except (OSError, ValueError) as exc:
    result = {"status": "error", "text": "", "error": str(exc)}
sys.stdout.reconfigure(encoding="utf-8")
print(json.dumps(result, indent=2, ensure_ascii=False))
raise SystemExit(1 if result["status"] == "error" else 0)
