import base64
import io
import json
from dataclasses import replace
from urllib.error import URLError

import pytest
from PIL import Image

from conftest import completion
from signspeak_ocr import VlmConfig
from signspeak_ocr.errors import ConfigError, VlmConnectionError, VlmResponseError
from signspeak_ocr.vlm import SYSTEM_PROMPT, analyze_with_vlm, check_vlm, encode_image, parse_analysis, warm_up


def test_request_uses_configured_model_image_and_secret(model_server, model_answer):
    url, replies, requests = model_server
    replies.append((200, completion(model_answer), {}))
    config = VlmConfig(base_url=url, model="a-different-vision-model", api_key="test-secret")
    result = analyze_with_vlm(Image.new("RGB", (200, 100), "red"), config)
    request = requests[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["authorization"] == "Bearer test-secret"
    assert request["body"]["model"] == "a-different-vision-model"
    assert request["body"]["temperature"] == 0
    assert request["body"]["response_format"]["json_schema"]["strict"] is True
    content = request["body"]["messages"][1]["content"]
    header, encoded = content[1]["image_url"]["url"].split(",", 1)
    assert header == "data:image/jpeg;base64"
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
        assert image.size == (200, 100)
        # Color is preserved (high-quality JPEG, no chroma subsampling).
        assert all(abs(a - b) <= 3 for a, b in zip(image.getpixel((0, 0)), (255, 0, 0)))
    assert result["extracted_text"] == model_answer["extracted_text"]
    assert "test-secret" not in json.dumps(result)
    assert "test-secret" not in json.dumps(config.to_dict())
    assert "test-secret" not in repr(config)
    assert "raw_response" not in result


@pytest.mark.parametrize("mode,expected", [("json_schema", "json_schema"), ("json_object", "json_object"), ("none", None)])
def test_response_format_is_configurable(model_server, model_answer, mode, expected):
    url, replies, requests = model_server
    replies.append((200, completion(model_answer), {}))
    analyze_with_vlm(Image.new("RGB", (20, 20)), VlmConfig(base_url=url, response_format=mode))
    assert requests[0]["body"].get("response_format", {}).get("type") == expected


def test_image_resize_preserves_ratio_and_pixel_budget():
    _, size = encode_image(Image.new("RGB", (1200, 600)),
                          VlmConfig(max_image_edge=1000, max_image_pixels=125000))
    assert size == [500, 250]


def test_fenced_json_and_unicode(model_answer):
    assert parse_analysis("```json\n" + json.dumps(model_answer, ensure_ascii=False) + "\n```") == {
        "extracted_text": "Livraison reportée\n16 h 15", "summary": model_answer["summary"],
        "text_status": "readable", "language": "fr", "confidence": {"text": 96, "summary": 91}}


@pytest.mark.parametrize("field", ["text_confidence", "summary_confidence"])
@pytest.mark.parametrize("value", [True, "95%", 0.95, -1, 101, {}, {"text": 95}, float("nan")])
def test_invalid_confidence_is_never_exposed_as_a_percentage(model_answer, field, value):
    with pytest.raises(VlmResponseError):
        parse_analysis(json.dumps({**model_answer, field: value}))


@pytest.mark.parametrize("text,summary", [(0, 100), (100, 0), (None, None)])
def test_confidence_boundaries_and_unavailable_estimates(model_answer, text, summary):
    answer = {**model_answer, "text_confidence": text, "summary_confidence": summary}
    assert parse_analysis(json.dumps(answer))["confidence"] == {"text": text, "summary": summary}


@pytest.mark.parametrize("text", ["←\n\n→\n\n\n", " - • ", "→ ⚠"])
def test_symbols_only_count_as_no_text(model_answer, text):
    result = parse_analysis(json.dumps({**model_answer, "extracted_text": text}))
    assert (result["text_status"], result["extracted_text"], result["language"]) == ("no_text", "", "none")
    assert result["confidence"]["text"] is None


@pytest.mark.parametrize("text", ["[illegible]", "[illegible] [occluded]\n…", " [ILLEGIBLE] - "])
def test_unreadable_text_has_no_transcription_confidence(model_answer, text):
    result = parse_analysis(json.dumps({**model_answer, "extracted_text": text}))
    assert result["text_status"] == "unreadable"
    assert result["confidence"] == {"text": None, "summary": 91}


def test_contradictions_of_a_text_free_image_are_corrected_not_retried(model_answer):
    # A small model sometimes gives a language and a text confidence with no
    # text; rejecting that would cost a whole second model run.
    result = parse_analysis(json.dumps({**model_answer, "extracted_text": "  \n"}))
    assert result == {"extracted_text": "", "summary": model_answer["summary"], "text_status": "no_text",
                      "language": "none", "confidence": {"text": None, "summary": 91}}


def test_text_with_an_illegible_part_is_still_readable(model_answer):
    result = parse_analysis(json.dumps({**model_answer, "extracted_text": "Closed [illegible] today"}))
    assert result["text_status"] == "readable"
    assert result["confidence"]["text"] == 96


@pytest.mark.parametrize("update", [
    {"summary": ""}, {"summary": "  "}, {"summary": 123}, {"extracted_text": None},
    {"uncertainties": []}, {"text_status": "readable"}, {"confidence": {"text": 1, "summary": 1}},
    {"extra": "not in the schema"},
    {"language": "Spanish"}, {"language": ["en", "fr"]}, {"language": None},
])
def test_invalid_contract_is_rejected(model_answer, update):
    with pytest.raises(VlmResponseError):
        parse_analysis(json.dumps({**model_answer, **update}))


@pytest.mark.parametrize("content", ["not JSON", "[]", '{"summary": NaN}', '{"summary": "unfinished'])
def test_invalid_json_is_rejected(content):
    with pytest.raises(VlmResponseError):
        parse_analysis(content)


@pytest.mark.parametrize("field", ["extracted_text", "summary", "language", "text_confidence", "summary_confidence"])
def test_every_field_is_required(model_answer, field):
    with pytest.raises(VlmResponseError):
        parse_analysis(json.dumps({k: v for k, v in model_answer.items() if k != field}))


def test_request_is_cacheable_and_bounded(model_server, model_answer):
    url, replies, requests = model_server
    replies.append((200, completion(model_answer), {}))
    result = analyze_with_vlm(Image.new("RGB", (4000, 3000)), VlmConfig(base_url=url), keep_conversation=True)
    body = requests[0]["body"]
    assert body["cache_prompt"] is True
    assert body["max_tokens"] == 768
    assert body["temperature"] == 0 and body["dry_multiplier"] > 0  # no greedy repetition loops
    assert body["messages"][0]["content"] == SYSTEM_PROMPT
    width, height = result["provenance"]["image_size_sent"]
    assert width * height <= 500_000 and width / height == pytest.approx(4 / 3, rel=0.01)
    # Chat repeats this exact turn so the server reuses the encoded image.
    assert result["conversation"] == [body["messages"][1], {"role": "assistant", "content": json.dumps(model_answer, ensure_ascii=False)}]


def test_warm_up_sends_one_small_image_per_orientation(model_server, model_answer):
    url, replies, requests = model_server
    replies.extend([(200, completion(model_answer), {})] * 2)
    warm_up(VlmConfig(base_url=url))
    assert len(requests) == 2
    sizes = []
    for request in requests:
        body = request["body"]
        assert body["max_tokens"] == 1 and body["messages"][0]["content"] == SYSTEM_PROMPT
        encoded = body["messages"][1]["content"][1]["image_url"]["url"].split(",", 1)[1]
        with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
            sizes.append(image.size)
    assert sizes[0] == sizes[1][::-1] and sizes[0][0] > sizes[0][1]


def test_truncated_reply_is_not_success(model_server, model_answer):
    url, replies, _ = model_server
    replies.append((200, completion(model_answer, finish_reason="length"), {}))
    with pytest.raises(VlmResponseError, match="truncated"):
        analyze_with_vlm(Image.new("RGB", (20, 20)), VlmConfig(base_url=url))


def test_retry_only_transient_http_failure(model_server, model_answer, monkeypatch):
    url, replies, requests = model_server
    monkeypatch.setattr("signspeak_ocr.vlm.time.sleep", lambda _: None)
    replies.extend([(503, {"error": "warming up"}, {}), (200, completion(model_answer), {})])
    analyze_with_vlm(Image.new("RGB", (20, 20)), VlmConfig(base_url=url))
    assert len(requests) == 2


def test_auth_failure_does_not_retry_or_echo_body(model_server):
    url, replies, requests = model_server
    replies.append((401, {"error": "private-server-detail"}, {}))
    with pytest.raises(VlmConnectionError, match="401") as error:
        check_vlm(VlmConfig(base_url=url))
    assert len(requests) == 1
    assert "private-server-detail" not in str(error.value)


def test_redirect_is_not_followed(model_server):
    url, replies, requests = model_server
    replies.append((307, {}, {"Location": url + "/elsewhere"}))
    with pytest.raises(VlmConnectionError, match="307"):
        check_vlm(VlmConfig(base_url=url, api_key="secret"))
    assert len(requests) == 1


def test_connection_failure_has_actionable_message(monkeypatch):
    class Offline:
        def open(self, *args, **kwargs):
            raise URLError("connection refused")
    monkeypatch.setattr("signspeak_ocr.vlm.build_opener", lambda *_: Offline())
    with pytest.raises(VlmConnectionError, match="local model container"):
        check_vlm(VlmConfig())


def test_check_verifies_model_alias(model_server):
    url, replies, _ = model_server
    replies.append((200, {"data": [{"id": "other-model"}]}, {}))
    with pytest.raises(VlmConnectionError, match="not served"):
        check_vlm(VlmConfig(base_url=url, model="wanted-model"))


@pytest.mark.parametrize("changes", [
    {"base_url": "file:///tmp/model"}, {"base_url": "http://user:pass@localhost/v1"},
    {"base_url": "http://localhost:bad/v1"}, {"base_url": "http://localhost/v1?key=secret"},
    {"timeout_seconds": float("nan")}, {"max_tokens": 0}, {"max_retries": 5},
    {"model": ""}, {"api_key": "key\nInjected: value"},
])
def test_bad_config_is_rejected(changes):
    with pytest.raises(ConfigError):
        replace(VlmConfig(), **changes).validate()


def test_environment_is_read_at_construction(monkeypatch):
    monkeypatch.setenv("SIGNSPEAK_VLM_MODEL", "new-model")
    monkeypatch.setenv("SIGNSPEAK_VLM_BASE_URL", "http://127.0.0.1:9000/v1")
    assert VlmConfig().model == "new-model"
    assert VlmConfig().base_url.endswith(":9000/v1")
