"""Opt-in smoke test of the running Docker app (local model + local speech).

Start the app first (./start.sh or .\\start.ps1), then from the repo root:
    python tests/live_pipeline.py [http://127.0.0.1:8000]
Needs only httpx (pip install -r requirements-dev.txt).
"""
import io
from pathlib import Path
import sys
import time
import wave

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def main():
    # No client timeout: CPU-only inference can take several minutes per image.
    with httpx.Client(base_url=BASE_URL, timeout=None) as client:
        started = time.monotonic()
        response = client.post("/api/extract", files={"image": (
            "one.png", (ROOT / "ocr/test images/one.png").read_bytes(), "image/png")})
        assert response.status_code == 200, response.text
        result = response.json()
        key = result["session_id"]
        print("Local model extraction:", len(result["text"]), "text characters;", len(result["summary"]), "summary characters; language:", result["language"], flush=True)
        try:
            for question in ["Summarize this image in one sentence. For this conversation, call the image Cedar42.",
                             "What label did I ask you to use in my previous message? Repeat that label."]:
                reply = client.post("/api/chat", json={"session_id": key, "message": question})
                assert reply.status_code == 200, reply.text
                answer = reply.json()["reply"]
                assert "*" not in answer
                print("Local model answer:", answer, flush=True)
            assert "Cedar42" in answer
            for language, text in [("en", "What is the main message in this image?"),
                                   ("fr", "Bonjour, pouvez-vous expliquer cette image ?")]:
                audio = client.post("/api/speech/synthesize", json={"text": text, "language": language})
                assert audio.status_code == 200, audio.text
                with wave.open(io.BytesIO(audio.content)) as wav:
                    assert wav.getnframes() > wav.getframerate() / 2
                transcript = client.post("/api/speech/transcribe", data={"language": language},
                                         files={"audio": ("local.wav", audio.content, "audio/wav")})
                assert transcript.status_code == 200, transcript.text
                print("Local", language, "speech transcript:", transcript.json()["text"], flush=True)
                assert transcript.json()["text"].strip()
                if language == "en":
                    reply = client.post("/api/chat", json={"session_id": key, "message": transcript.json()["text"]})
                    assert reply.status_code == 200, reply.text
                    spoken = client.post("/api/speech/synthesize", json={"text": reply.json()["reply"][:1000], "language": "en"})
                    assert spoken.status_code == 200, spoken.text
                    print("Voice -> text -> local model answer -> local voice: passed", flush=True)
        finally:
            assert client.delete("/api/sessions/" + key).status_code == 204
        assert client.post("/api/chat", json={"session_id": key, "message": "Old session?"}).status_code == 404
        print("Session reset: passed. Total seconds:", round(time.monotonic() - started, 1), flush=True)

        for expected, path in [
            ("en", ROOT / "frontend/samples/sample-en.jpg"),
            ("fr", ROOT / "frontend/samples/sample-fr.jpg"),
            ("mixed", ROOT / "frontend/samples/sample-mixed.jpg"),
            ("none", ROOT / "ocr/test images/seven.png"),
        ]:
            mime = "image/png" if path.suffix == ".png" else "image/jpeg"
            response = client.post("/api/extract", files={"image": (path.name, path.read_bytes(), mime)})
            assert response.status_code == 200, response.text
            result = response.json()
            try:
                print("Document language:", path.name, "->", result["language"], flush=True)
                assert result["language"] == expected
                assert "*" not in result["summary"]
            finally:
                client.delete("/api/sessions/" + result["session_id"])


if __name__ == "__main__":
    main()
