"""Command-line entry point: ``signspeak-ocr`` or ``python -m signspeak_ocr``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .config import IngestConfig, PipelineConfig, PreprocessConfig, TesseractConfig
from .errors import OcrError
from .pipeline import extract_image
from .tesseract import get_tesseract_info

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_INPUT = 3
EXIT_ENGINE = 4

_INPUT_CODES = {"invalid_input", "image_too_large", "unsupported_image"}
_ENGINE_CODES = {"tesseract_not_found", "tesseract_language_missing"}


def _tesseract_config(args: argparse.Namespace) -> TesseractConfig:
    return TesseractConfig(
        cmd=args.tesseract_cmd,
        tessdata_dir=args.tessdata_dir,
        languages=tuple(part for part in args.lang.split("+") if part),
        psm=getattr(args, "psm", 3),
        oem=getattr(args, "oem", 1),
        dpi=None if getattr(args, "dpi", 300) == 0 else getattr(args, "dpi", 300),
        timeout_seconds=getattr(args, "timeout", 120.0),
    )


def _add_engine_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lang", default="eng+fra", help="Tesseract languages (default: eng+fra)")
    parser.add_argument("--tesseract-cmd", help="Path to tesseract(.exe); default: SIGNSPEAK_TESSERACT_CMD or PATH")
    parser.add_argument("--tessdata-dir", help="tessdata folder; default: SIGNSPEAK_TESSDATA_DIR or Tesseract default")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="signspeak-ocr", description="SignSpeak classical OCR")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    extract = sub.add_parser("extract", help="OCR one image and emit structured JSON")
    extract.add_argument("image", type=Path)
    extract.add_argument("-o", "--output", type=Path, help="Write JSON here (default: stdout)")
    extract.add_argument("--format", choices=("json", "text"), default="json",
                         help="json: full result; text: agent text view only")
    extract.add_argument("--psm", type=int, default=3, help="Tesseract page segmentation mode (default 3)")
    extract.add_argument("--oem", type=int, default=1, choices=(0, 1, 2, 3))
    extract.add_argument("--dpi", type=int, default=300, help="DPI hint for Tesseract; 0 = none")
    extract.add_argument("--timeout", type=float, default=120.0, help="Tesseract timeout in seconds")
    extract.add_argument("--max-working-edge", type=int, default=IngestConfig().max_working_edge)
    extract.add_argument("--preprocess", action="store_true", help="Try one bounded diagnostic-driven OpenCV candidate")
    extract.add_argument("--compact", action="store_true", help="Single-line JSON")
    extract.add_argument("--debug", action="store_true", help="Include raw Tesseract TSV in the output")
    _add_engine_arguments(extract)

    check = sub.add_parser("check", help="Verify Tesseract installation and language data")
    _add_engine_arguments(check)
    return parser


def _exit_code(result: dict) -> int:
    if result["validation"]["overall_status"] != "failed":
        return EXIT_OK
    codes = {error["code"] for error in result["errors"]}
    if codes & _INPUT_CODES:
        return EXIT_INPUT
    if codes & _ENGINE_CODES:
        return EXIT_ENGINE
    return EXIT_FAILED


def _write(text: str, output: Path | None) -> None:
    if output is None:
        sys.stdout.buffer.write((text + "\n").encode("utf-8"))
        sys.stdout.flush()
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")


def _command_extract(args: argparse.Namespace) -> int:
    config = PipelineConfig(
        tesseract=_tesseract_config(args),
        ingest=IngestConfig(max_working_edge=args.max_working_edge),
        preprocessing=PreprocessConfig(enabled=args.preprocess),
    )
    try:
        result = extract_image(args.image, config, include_debug=args.debug)
    except OcrError as error:
        print(f"error: {error.message}", file=sys.stderr)
        return 2
    if args.format == "text":
        _write(result["text_view"], args.output)
    else:
        _write(json.dumps(result, ensure_ascii=False, indent=None if args.compact else 2), args.output)
    status = result["validation"]["overall_status"]
    for error in result["errors"]:
        print(f"{error['stage']}: {error['code']}: {error['message']}", file=sys.stderr)
    if status != "ok":
        print(f"overall_status: {status}", file=sys.stderr)
    return _exit_code(result)


def _command_check(args: argparse.Namespace) -> int:
    config = _tesseract_config(args)
    try:
        config.validate()
        info = get_tesseract_info(config)
    except OcrError as error:
        print(f"FAIL {error.code}: {error.message}", file=sys.stderr)
        return EXIT_ENGINE
    print(f"tesseract: {info.cmd}")
    print(f"version:   {info.version}")
    print(f"tessdata:  {info.tessdata_dir or '(tesseract default)'}")
    print(f"languages: {', '.join(info.languages)}")
    print(f"OK: requested languages available ({'+'.join(config.languages)})")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "check":
        return _command_check(args)
    return _command_extract(args)


if __name__ == "__main__":
    raise SystemExit(main())
