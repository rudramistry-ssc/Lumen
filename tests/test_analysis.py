import io

from PIL import Image

from conftest import completion
from signspeak_ocr import VlmConfig, analyze_image, render_report
from signspeak_ocr.cli import main


def test_one_image_returns_text_and_summary(model_server, model_answer, image_bytes):
    url, replies, requests = model_server
    replies.append((200, completion(model_answer), {}))
    result = analyze_image(image_bytes, vlm_config=VlmConfig(base_url=url))
    assert len(requests) == 1
    assert result["text"] == model_answer["extracted_text"]
    assert result["summary"] == model_answer["summary"]
    assert result["validation"]["overall_status"] == "ok"
    assert render_report(result).startswith("Extracted text:\n")


def test_symbol_only_image_returns_summary(model_server, image_bytes):
    url, replies, _ = model_server
    replies.append((200, completion({"extracted_text": "", "summary": "A left-pointing exit sign.",
                                   "text_status": "no_text", "uncertainties": []}), {}))
    result = analyze_image(image_bytes, vlm_config=VlmConfig(base_url=url))
    assert result["validation"]["overall_status"] == "ok"
    assert result["text"] == ""
    assert "left-pointing" in render_report(result)


def test_unreadable_text_keeps_summary(model_server, image_bytes):
    url, replies, _ = model_server
    replies.append((200, completion({"extracted_text": "", "summary": "A blurred notice.",
                                   "text_status": "unreadable", "uncertainties": []}), {}))
    result = analyze_image(image_bytes, vlm_config=VlmConfig(base_url=url))
    assert result["validation"]["overall_status"] == "partial"
    assert result["summary"] == "A blurred notice."


def test_exif_orientation_before_model(model_server, model_answer):
    url, replies, _ = model_server
    replies.append((200, completion(model_answer), {}))
    data = io.BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (40, 20), "red").save(data, format="JPEG", exif=exif)
    result = analyze_image(data.getvalue(), vlm_config=VlmConfig(base_url=url), include_debug=True)
    assert result["input"]["oriented_size"] == [20, 40]
    assert result["model_response"]["provenance"]["image_size_sent"] == [20, 40]


def test_invalid_input_does_not_contact_model(model_server):
    url, _, requests = model_server
    result = analyze_image(b"not an image", vlm_config=VlmConfig(base_url=url))
    assert result["validation"]["overall_status"] == "failed"
    assert not requests


def test_cli_report(model_server, model_answer, image_bytes, tmp_path):
    url, replies, _ = model_server
    replies.append((200, completion(model_answer), {}))
    image = tmp_path / "notice.png"
    image.write_bytes(image_bytes)
    output = tmp_path / "out.txt"
    assert main(["extract", str(image), "--vlm-base-url", url, "-o", str(output)]) == 0
    assert model_answer["extracted_text"] in output.read_text(encoding="utf-8")
    assert "Summary of the image:" in output.read_text(encoding="utf-8")


def test_cli_failure(model_server, image_bytes, tmp_path):
    url, replies, _ = model_server
    replies.append((401, {}, {}))
    image = tmp_path / "notice.png"
    image.write_bytes(image_bytes)
    assert main(["extract", str(image), "--vlm-base-url", url, "-o", str(tmp_path / "out.txt")]) == 1
