"""Separate, opt-in synthetic visual check; never used by OCR chat routing."""
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw

from signspeak_llm import LocalLLM
from signspeak_llm.server import Server, default_model_dir, process_memory

ROOT = Path(__file__).resolve().parent


def run():
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "rows": [],
              "method": "Two deterministic 336x252 Pillow drawings without text. Ground truth from drawing commands. No remote images. First image request after fresh server; OS cache uncontrolled. Visual correctness needs human review; no claim of general vision accuracy."}
    output = ROOT / "runtime/vision.json"
    projector = default_model_dir() / "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf"
    with Server(projector=projector) as server:
        report["server"] = server.metadata
        client = LocalLLM(timeout=240, max_tokens=96)
        for shape, colour in (("circle", "red"), ("rectangle", "blue")):
            image = Image.new("RGB", (336, 252), "white")
            draw = ImageDraw.Draw(image)
            if shape == "circle":
                draw.ellipse((90, 48, 246, 204), fill=colour)
            else:
                draw.rectangle((50, 80, 286, 172), fill=colour)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            data = buffer.getvalue()
            image.save(ROOT / f"runtime/{colour}-{shape}.png")
            encoded = base64.b64encode(data).decode("ascii")
            for repeat in range(2):
                row = {"id": f"{colour}-{shape}", "repeat": repeat, "expected": f"One {colour} {shape} on white background.",
                       "image_sha256": hashlib.sha256(data).hexdigest(), "dimensions": list(image.size)}
                messages = [{"role": "system", "content": "Describe only visible image content. If unclear, say so. Answer briefly in English."},
                            {"role": "user", "content": [{"type": "text", "text": "What shape and colour are shown?"},
                                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + encoded}}]}]
                try:
                    row["result"] = client.complete(messages)
                except Exception as error:
                    row["error"] = f"{type(error).__name__}: {error}"
                row["memory"] = process_memory(server.process)
                report["rows"].append(row)
                output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps(row, ensure_ascii=False), flush=True)
        # Same question without the pixels or OCR text: no shape/colour is available.
        report["ocr_only_control"] = client.answer(
            {"selected_text": "", "regions": [], "verification": "not_performed",
             "source": {"run_id": "constructed-empty-ocr-shapes"}},
            "What shape and colour are shown?", language="en")
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ocr_only_control": report["ocr_only_control"]}, ensure_ascii=False), flush=True)
    return report


if __name__ == "__main__":
    run()
