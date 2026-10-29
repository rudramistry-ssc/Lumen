"""Exercise the actual HTTP upload -> OCR -> model HTTP boundary."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import completion

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CanAI_Team_E-feature-frontend" / "backend"))
from main import app
from config import Settings


@pytest.fixture
def client(model_server):
    url, _, _ = model_server
    app.dependency_overrides.clear()
    import main
    previous = main.get_settings
    main.get_settings = lambda: Settings(base_url=url, model="test-vision", api_key="test-secret")
    try:
        with TestClient(app) as connection:
            yield connection
    finally:
        main.get_settings = previous


def test_upload_reaches_model_and_returns_only_requested_fields(client, model_server, model_answer, image_bytes):
    _, replies, requests = model_server
    replies.append((200, completion(model_answer), {}))
    response = client.post("/api/extract", files={"image": ("photo.png", image_bytes, "image/png")})
    assert response.status_code == 200
    assert response.json() == {"text": model_answer["extracted_text"], "summary": model_answer["summary"]}
    assert len(requests) == 1
    assert requests[0]["path"] == "/v1/chat/completions"
    assert requests[0]["authorization"] == "Bearer test-secret"
    assert "test-secret" not in response.text


def test_symbol_only_upload_is_successful(client, model_server, image_bytes):
    _, replies, _ = model_server
    replies.append((200, completion({"extracted_text": "", "summary": "A no-entry symbol.",
                                   "text_status": "no_text", "uncertainties": []}), {}))
    response = client.post("/api/extract", files={"image": ("symbol.png", image_bytes, "image/png")})
    assert response.status_code == 200
    assert response.json() == {"text": "", "summary": "A no-entry symbol."}


@pytest.mark.parametrize("data,mime,status", [
    (b"", "image/png", 422),
    (b"not an image", "image/png", 422),
    (b"text", "text/plain", 415),
    (b"x" * (10 * 1024 * 1024 + 1), "image/png", 413),
])
def test_bad_upload_does_not_contact_model(client, model_server, data, mime, status):
    response = client.post("/api/extract", files={"image": ("bad.png", data, mime)})
    assert response.status_code == status
    assert not model_server[2]


def test_model_failure_has_actionable_error(client, model_server, image_bytes):
    model_server[1].append((401, {"error": "private server detail"}, {}))
    response = client.post("/api/extract", files={"image": ("photo.png", image_bytes, "image/png")})
    assert response.status_code == 503
    assert "SSH tunnel" in response.json()["detail"]
    assert "private server detail" not in response.text


def test_truncated_response_is_not_displayed_as_success(client, model_server, model_answer, image_bytes):
    model_server[1].append((200, completion(model_answer, finish_reason="length"), {}))
    response = client.post("/api/extract", files={"image": ("photo.png", image_bytes, "image/png")})
    assert response.status_code == 502


def test_local_page_and_assets_are_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="extracted-text"' in response.text
    for path in ("/styles.css", "/api.js", "/app.js"):
        assert client.get(path).status_code == 200


def test_env_file_settings_are_independent_of_working_directory(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("SIGNSPEAK_VLM_BASE_URL=http://127.0.0.1:18001/v1\nSIGNSPEAK_VLM_MODEL=custom-8b\nSIGNSPEAK_VLM_API_KEY=private-key\n", encoding="utf-8")
    for key in ("SIGNSPEAK_VLM_BASE_URL", "SIGNSPEAK_VLM_MODEL", "SIGNSPEAK_VLM_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path.parent)
    settings = Settings(_env_file=env)
    config = settings.vlm_config()
    assert config.base_url == "http://127.0.0.1:18001/v1"
    assert config.model == "custom-8b"
    assert config.api_key == "private-key"
