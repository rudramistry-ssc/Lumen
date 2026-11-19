import importlib.util
import json
import sys
from pathlib import Path

import pytest

from conftest import completion

OCR_DIR = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, OCR_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_batch_continues_after_failure_and_saves_diagnostics(model_server, model_answer, image_bytes, tmp_path, monkeypatch):
    url, replies, requests = model_server
    replies.extend([(200, completion(model_answer), {}), (401, {}, {}),
                    (200, completion(model_answer), {})])
    folder = tmp_path / "images"
    folder.mkdir()
    for name in ("a.png", "b.PNG", "c.png"):
        (folder / name).write_bytes(image_bytes)
    (folder / "notes.txt").write_text("not an image", encoding="utf-8")
    output = tmp_path / "out.txt"
    json_dir = tmp_path / "results"
    monkeypatch.setattr(sys, "argv", ["run_test_images.py", "--input-dir", str(folder),
                        "-o", str(output), "--vlm-base-url", url, "--json-dir", str(json_dir)])
    assert load_script("run_test_images").main() == 1
    report = output.read_text(encoding="utf-8")
    assert len(requests) == 3
    assert report.count("Extracted text:") == 3
    assert report.count("Summary of the image:") == 3
    assert "SUMMARY: 2 ok, 0 partial, 1 failed" in report
    assert json.loads((json_dir / "b.PNG.json").read_text())["errors"][0]["code"] == "vlm_connection_failed"


def test_batch_does_not_overwrite_input(image_bytes, tmp_path, monkeypatch):
    image = tmp_path / "photo.png"
    image.write_bytes(image_bytes)
    monkeypatch.setattr(sys, "argv", ["run_test_images.py", "--input-dir", str(tmp_path), "-o", str(image)])
    with pytest.raises(SystemExit) as error:
        load_script("run_test_images").main()
    assert error.value.code == 2
    assert image.read_bytes() == image_bytes
