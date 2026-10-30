import argparse
import json
from pathlib import Path
import sys

from . import PiperSpeech, SpeechError


def main():
    parser = argparse.ArgumentParser(description="SignSpeak offline Piper speech; no audio device or model server")
    sub = parser.add_subparsers(dest="command", required=True)
    download = sub.add_parser("provision", help="One-time explicit download of the pinned voices")
    download.add_argument("languages", nargs="*", choices=["en", "fr"], default=["en", "fr"])
    download.add_argument("--voice-dir", type=Path)
    speak = sub.add_parser("synthesize", help="Write a local WAV and metadata JSON")
    inputs = speak.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--text", help="Literal text; UTF-8 input files are preferable in older PowerShell")
    inputs.add_argument("--text-file", type=Path)
    inputs.add_argument("--speech-view", type=Path, help="Saved adapter speech view, or adapter views object")
    inputs.add_argument("--reconciled", type=Path)
    speak.add_argument("--language", help="Required for plain text or a single-language reconciliation")
    speak.add_argument("--section-languages", nargs="*", help="Explicit languages for ordered reconciliation sections")
    speak.add_argument("--default-language", help="Explicit caller choice for missing/unknown segment tags")
    speak.add_argument("--voice-dir", type=Path)
    speak.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "provision":
            from .voices import provision
            for language in args.languages:
                print(provision(language, args.voice_dir))
            return 0
        sources = [p.resolve() for p in (args.text_file, args.speech_view, args.reconciled) if p]
        metadata_path = args.output.with_suffix(".json")
        if args.output.suffix.lower() != ".wav" or args.output.resolve() in sources or metadata_path.resolve() in sources:
            raise ValueError("Use a separate .wav output path; source files must not be overwritten")
        engine = PiperSpeech(voice_dir=args.voice_dir)
        if args.speech_view:
            view = json.loads(args.speech_view.read_text(encoding="utf-8-sig"))
            if "views" in view:
                view = view["views"]
            result = engine.synthesize_view(view.get("speech", view), default_language=args.default_language)
        elif args.reconciled:
            result = engine.synthesize_reconciled(json.loads(args.reconciled.read_text(encoding="utf-8-sig")),
                                                  language=args.language, section_languages=args.section_languages)
        else:
            text = args.text if args.text is not None else args.text_file.read_text(encoding="utf-8-sig")
            result = engine.synthesize(text, args.language)
        result.write_wav(args.output)
        metadata_path.write_text(json.dumps(result.metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {args.output} ({result.metadata['audio_duration_seconds']:.2f} s audio)")
        return 0
    except (SpeechError, ValueError, OSError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
