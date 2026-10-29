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
from signspeak_ocr.vlm import analyze_with_vlm, check_vlm, encode_image, parse_analysis


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
    encoded = content[1]["image_url"]["url"].split(",", 1)[1]
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
        assert image.size == (200, 100)
        assert image.getpixel((0, 0)) == (255, 0, 0)
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
    assert parse_analysis("```json\n" + json.dumps(model_answer, ensure_ascii=False) + "\n```") == model_answer


@pytest.mark.parametrize("update", [
    {"summary": ""}, {"summary": 123}, {"uncertainties": "none"}, {"uncertainties": [1]},
    {"text_status": "invented"}, {"text_status": "no_text"}, {"extracted_text": ""},
    {"extra": "not in the schema"},
])
def test_invalid_contract_is_rejected(model_answer, update):
    with pytest.raises(VlmResponseError):
        parse_analysis(json.dumps({**model_answer, **update}))


@pytest.mark.parametrize("content", ["not JSON", "[]", '{"summary": NaN}', '{"summary": "unfinished'])
def test_invalid_json_is_rejected(content):
    with pytest.raises(VlmResponseError):
        parse_analysis(content)


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
    with pytest.raises(VlmConnectionError, match="SSH tunnel"):
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
