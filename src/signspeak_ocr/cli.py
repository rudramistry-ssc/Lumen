"""Single-image extraction and model connection checks."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from . import __version__
from .analysis import analyze_image, render_report
from .config import VlmConfig
from .errors import OcrError
from .vlm import check_vlm


def add_vlm_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--vlm-base-url")
    parser.add_argument("--vlm-model")
    parser.add_argument("--vlm-timeout", type=float)
    parser.add_argument("--vlm-max-tokens", type=int)
    parser.add_argument("--vlm-max-image-edge", type=int)
    parser.add_argument("--vlm-max-image-pixels", type=int)
    parser.add_argument("--vlm-response-format", choices=("json_schema", "json_object", "none"))
    parser.add_argument("--summary-language")


def vlm_config_from_args(args: argparse.Namespace) -> VlmConfig:
    fields = {"vlm_base_url": "base_url", "vlm_model": "model",
              "vlm_timeout": "timeout_seconds", "vlm_max_tokens": "max_tokens",
              "vlm_max_image_edge": "max_image_edge", "vlm_max_image_pixels": "max_image_pixels",
              "vlm_response_format": "response_format", "summary_language": "summary_language"}
    return replace(VlmConfig(), **{target: getattr(args, source)
                   for source, target in fields.items() if getattr(args, source, None) is not None})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Extract image text and a summary using the HPC model")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    add_vlm_arguments(check)
    extract = sub.add_parser("extract")
    extract.add_argument("image", type=Path)
    extract.add_argument("-o", "--output", type=Path)
    extract.add_argument("--format", choices=("text", "json"), default="text")
    extract.add_argument("--debug", action="store_true")
    add_vlm_arguments(extract)
    args = parser.parse_args(argv)
    try:
        config = vlm_config_from_args(args)
        if args.command == "check":
            check_vlm(config)
            print("Model connection ready.")
            return 0
        if args.output and args.output.resolve() == args.image.resolve():
            parser.error("Output must not overwrite the image")
        result = analyze_image(args.image, vlm_config=config, include_debug=args.debug)
        text = json.dumps(result, ensure_ascii=False, indent=2) if args.format == "json" else render_report(result)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text + "\n", encoding="utf-8")
        else:
            sys.stdout.buffer.write((text + "\n").encode("utf-8"))
        for error in result["errors"]:
            print(error["message"], file=sys.stderr)
        return 1 if result["validation"]["overall_status"] == "failed" else 0
    except OcrError as error:
        print(error.message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
