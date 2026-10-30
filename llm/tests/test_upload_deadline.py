"""Opt-in real OCR / simulated stalled HTTP test, never runs vision inference."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from signspeak_llm import DocumentProcessor, LocalLLM, Reconciler


@unittest.skipUnless(os.getenv("SIGNSPEAK_RUN_OCR_DEADLINE_TEST") == "1", "requires installed Tesseract and OCR preprocessing dependencies")
class UploadDeadlineTests(unittest.TestCase):
    def test_isolated_success_uses_independent_text_and_reuses_cache(self):
        requests = []
        reading = {"printed_text_status": "present", "sections": [{"text": "Independent vision text.", "text_state": "plain"}], "visual_descriptions": [], "text_observations": []}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def reply(self, value):
                data = json.dumps(value).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
            def do_GET(self): self.reply({"default_generation_settings": {"n_ctx": 8192}})
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/apply-template": return self.reply({"prompt": "test"})
                if self.path == "/tokenize": return self.reply({"tokens": [1]*100})
                requests.append(payload)
                chunk = {"choices": [{"delta": {"content": json.dumps(reading)}, "finish_reason": "stop"}]}
                data = ("data: "+json.dumps(chunk)+"\n\ndata: [DONE]\n\n").encode()
                self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        from signspeak_ocr import PipelineConfig, PreprocessConfig
        with tempfile.TemporaryDirectory() as directory:
            client = LocalLLM(f"http://127.0.0.1:{server.server_port}", context_size=8192)
            processor = DocumentProcessor(reconciler=Reconciler(client), cache_dir=directory,
                ocr_config=PipelineConfig(preprocessing=PreprocessConfig(enabled=True)), processing_timeout_seconds=30)
            image = (Path(__file__).resolve().parents[2]/"ocr/eval/benchmark/images/english_clean.png").read_bytes()
            result = processor.process(image)
            self.assertEqual(result.get("text"), "Independent vision text.", result)
            self.assertEqual(result["execution_this_call"], {"ocr": 1, "vision": 1, "hybrid": 0})
            task = requests[0]["messages"][1]["content"][0]["text"]
            self.assertNotIn("OCR evidence", task)
            self.assertNotIn("library", task.lower())
            cached = processor.process(image)
            self.assertTrue(cached["cache_hit"])
            self.assertEqual(cached["execution_this_call"], {"ocr": 0, "vision": 0, "hybrid": 0})
            self.assertEqual(len(requests), 1)

    def test_trickling_http_does_not_extend_upload_deadline(self):
        reached, disconnected, stop = threading.Event(), threading.Event(), threading.Event()
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self): self.reply({"default_generation_settings": {"n_ctx": 8192}})
            def reply(self, value):
                data = json.dumps(value).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/apply-template": return self.reply({"prompt": "test"})
                if self.path == "/tokenize": return self.reply({"tokens": [1]*100})
                calls.append(payload); reached.set()
                self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
                try:
                    while not stop.wait(.1): self.wfile.write(b": still processing\n\n"); self.wfile.flush()
                except (ConnectionError, OSError): disconnected.set()
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown); self.addCleanup(stop.set)
        with tempfile.TemporaryDirectory() as directory:
            client = LocalLLM(f"http://127.0.0.1:{server.server_port}", context_size=8192, timeout=60)
            processor = DocumentProcessor(reconciler=Reconciler(client), cache_dir=directory, processing_timeout_seconds=12)
            image = (Path(__file__).resolve().parents[2]/"ocr/eval/benchmark/images/english_clean.png").read_bytes()
            started = time.monotonic(); result = processor.process(image)
            self.assertTrue(reached.is_set(), result)
            self.assertEqual(result["status"], "deadline_exceeded", result)
            self.assertLess(time.monotonic()-started, 14)
            self.assertTrue(result["cancellation"]["worker_stopped"], result)
            self.assertTrue((Path(result["partial_evidence"])/"ocr.json").is_file())
            self.assertNotIn("selected_views", result)
            self.assertTrue(disconnected.wait(2), "Owned request socket was not closed")
            cached = processor.process(image)
            self.assertEqual(cached["status"], "deadline_exceeded")
            self.assertTrue(cached["cache_hit"])
            self.assertEqual(len(calls), 1)
            self.assertTrue(thread.is_alive(), "Shared service must survive cancellation")
