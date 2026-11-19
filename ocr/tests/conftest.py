"""Tests use a local fake model server; no weights, downloads, or GPU needed."""

import io
import json
import os
import sys
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# The app pre-loads the real model at startup; tests use a fake server instead.
os.environ["LUMEN_WARM_MODEL"] = "0"


@pytest.fixture
def image_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (320, 240), "white").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def model_answer():
    return {"extracted_text": "Livraison reportée\n16 h 15", "summary": "A delivery notice with a revised arrival time.",
            "language": "fr", "text_confidence": 96, "summary_confidence": 91}


def completion(answer, *, finish_reason="stop"):
    return {"model": "test-vision", "choices": [{"finish_reason": finish_reason,
            "message": {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 30}}


class Streamed(list):
    """A reply sent as a server-sent event stream, like llama.cpp with "stream": true."""


def streamed(content, *, size=3, finish_reason="stop"):
    """Stream ``content`` (a string, or an answer dict as JSON) a few characters at a time."""
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    events = [{"choices": [{"index": 0, "delta": {"content": content[i:i + size]}, "finish_reason": None}]}
              for i in range(0, len(content), size)]
    if finish_reason:
        events.append({"model": "test-vision", "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
                       "usage": {"prompt_tokens": 20, "completion_tokens": 30}})
    return Streamed(events)


@pytest.fixture
def model_server():
    replies = deque()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def handle_request(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            requests.append({"path": self.path, "authorization": self.headers.get("Authorization"),
                             "body": json.loads(body) if body else None})
            status, payload, headers = replies.popleft() if replies else (500, {"error": "no test reply"}, {})
            if isinstance(payload, Streamed):
                data = "".join(f"data: {json.dumps(event, ensure_ascii=False)}\n\n" for event in payload)
                data = (data + "data: [DONE]\n\n").encode("utf-8")
                content_type = "text/event-stream"
            else:
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                content_type = "application/json"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        do_GET = handle_request
        do_POST = handle_request

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", replies, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
