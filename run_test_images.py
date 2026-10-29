"""Run the same single-image pipeline across the preserved test photos."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

OCR_DIR = Path(__file__).resolve().parent
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif", ".ppm", ".pgm", ".pbm", ".pnm", ".ico", ".jfif"}


def main() -> int:
    sys.path.insert(0, str(OCR_DIR / "src"))
    from signspeak_ocr import analyze_image, render_report
    from signspeak_ocr.cli import add_vlm_arguments, vlm_config_from_args
    from signspeak_ocr.errors import OcrError

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=OCR_DIR / "test images")
    parser.add_argument("-o", "--output", type=Path, default=OCR_DIR / "out.txt")
    parser.add_argument("--json-dir", type=Path)
    add_vlm_arguments(parser)
    args = parser.parse_args()
    if not args.input_dir.is_dir():
        parser.error("Input directory does not exist")
    images = sorted(p for p in args.input_dir.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS)
    if not images:
        parser.error("No images found")
    protected = {p.resolve() for p in images}
    destinations = [args.output]
    if args.json_dir:
        destinations += [args.json_dir / (str(p.relative_to(args.input_dir)) + ".json") for p in images]
    if any(p.resolve() in protected for p in destinations):
        parser.error("Output must not overwrite an image")
    try:
        config = vlm_config_from_args(args)
        config.validate()
    except OcrError as error:
        parser.error(error.message)
    counts = {"ok": 0, "partial": 0, "failed": 0}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as report:
        for image in images:
            name = str(image.relative_to(args.input_dir))
            try:
                result = analyze_image(image, vlm_config=config)
                status = result["validation"]["overall_status"]
                report.write(f"IMAGE: {name}\n{render_report(result)}\n\n")
                if args.json_dir:
                    target = args.json_dir / (name + ".json")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as error:
                status = "failed"
                report.write(f"IMAGE: {name}\nFailed: {error}\n\n")
            counts[status] += 1
            print(f"{name}: {status}", flush=True)
        report.write("SUMMARY: " + ", ".join(f"{count} {status}" for status, count in counts.items()) + "\n")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
