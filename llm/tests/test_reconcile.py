from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from signspeak_llm import InferenceError, Reconciler
from signspeak_llm.reconcile import prepare_image, validate_output, transcription_evidence
from signspeak_llm.reconciliation_checks import compare_transcription


class Fake:
    base_url, model, max_tokens, context_size, thinking = "http://127.0.0.1:8091", "test", 768, 4096, False

    def __init__(self, value=None, error=None, finish="stop"):
        self.value, self.error, self.finish, self.calls = value, error, finish, 0

    def _count(self, messages):
        return 200

    def json_request(self, *args):
        return {"default_generation_settings": {"n_ctx": 4096}}

    def complete(self, messages, **kwargs):
        self.calls += 1
        self.messages = messages
        if self.error:
            raise self.error
        return {"answer": self.value, "finish_reason": self.finish, "request_latency_ms": 1}


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        output = io.BytesIO()
        Image.new("RGB", (32, 24), "white").save(output, format="PNG")
        self.image = output.getvalue()
        self.context = {"selected_text": "Sodium 230 mg. Price $12.50.", "source": {"run_id": "test"},
                        "regions": [{"id": "R1", "text": "Sodium 230 mg. Price $12.50."}]}

    def test_changes_flagged_source_untouched_and_cache_offline(self):
        source = deepcopy(self.context)
        client = Fake(json.dumps({"sections": [{"text": "Sodium 280 mg. Price $12.50."}]}))
        with tempfile.TemporaryDirectory() as directory:
            reconciler = Reconciler(client, cache_dir=directory)
            first = reconciler.reconcile(self.image, self.context)
            client.error = InferenceError("Server now offline")
            second = reconciler.reconcile(self.image, self.context)
            self.assertTrue(second["cache_hit"])
            self.assertEqual(client.calls, 1)
            self.assertIn("280 mg", first["comparison"]["numeric_disagreements"]["model_literals_introduced_or_changed"])
            self.assertTrue(first["requires_review"])
            self.assertEqual(first["sections"][0]["source_region_ids"], [])
            self.assertNotIn("bbox", first["sections"][0])
            self.assertEqual(source, self.context)
            self.context["selected_text"] += " New evidence."
            third = reconciler.reconcile(self.image, self.context)
            self.assertEqual(third["status"], "fallback")
            self.assertEqual(client.calls, 2)

    def test_timeout_invalid_json_and_truncation_fall_back(self):
        for client in (Fake(error=InferenceError("timeout")), Fake("not JSON"), Fake('{"sections":', finish="length")):
            with self.subTest(client=client):
                result = Reconciler(client).reconcile(self.image, self.context, use_cache=False)
                self.assertEqual(result["status"], "fallback")
                self.assertEqual(result["text"], self.context["selected_text"])
                self.assertIsNone(result["model_text"])

    def test_wrong_image_hash_and_invalid_image_do_not_generate(self):
        client = Fake()
        self.context["source"]["image_sha256"] = "wrong"
        result = Reconciler(client).reconcile(self.image, self.context, use_cache=False)
        self.assertEqual(result["status"], "fallback")
        self.assertEqual(client.calls, 0)
        del self.context["source"]["image_sha256"]
        result = Reconciler(client).reconcile(b"corrupt", self.context, use_cache=False)
        self.assertEqual(result["status"], "fallback")

    def test_prep_is_identical_in_both_modes_and_vision_gets_no_ocr(self):
        value = json.dumps({"sections": [{"text": "Readable text"}]} )
        client = Fake(value)
        reconciler = Reconciler(client)
        hybrid = reconciler.reconcile(self.image, self.context, use_cache=False)
        hybrid_image = client.messages[1]["content"][1]
        vision = reconciler.reconcile(self.image, self.context, mode="vision_only", use_cache=False)
        self.assertEqual(hybrid_image, client.messages[1]["content"][1])
        self.assertNotIn("Sodium", client.messages[1]["content"][0]["text"])
        self.assertEqual(hybrid["image_preparation"], vision["image_preparation"])

    def test_literals_include_sign_dates_units_and_decimal_variants(self):
        context = {"selected_text": "Dose -1.5 mg. Date 2030-02-14. Fat 1,5 g."}
        result = compare_transcription(context, "Dose 1.5 g. Date 2030-02-15. Fat 1.5 g.")
        numbers = result["numeric_disagreements"]
        self.assertIn("-1.5 mg", numbers["ocr_literals_missing_or_changed"])
        self.assertIn("2030-02-15", numbers["model_literals_introduced_or_changed"])
        self.assertTrue(numbers["possible_representation_changes"])

    def test_no_word_coordinates_or_verification_accepted_from_model(self):
        with self.assertRaises(ValueError):
            validate_output('{"sections":[{"text":"x","bbox":[0,0,1,1]}]}')
        with self.assertRaises(ValueError):
            validate_output('{"sections":[],"sections":[]}')

    def test_compact_transcription_evidence_preserves_literal_alternatives(self):
        self.context["regions"][0]["tentative_words"] = [{"id": "W1", "text": "230", "confidence": 22,
            "evidence": {"status": "numeric_disagreement", "alternatives": [{"text": "280", "confidence": 21}]}}]
        original = deepcopy(self.context)
        view = json.loads(transcription_evidence(self.context))
        word = view["regions"][0]["tentative_words"][0]
        self.assertEqual(word["alternatives"], ["280"])
        self.assertEqual(word["status"], "numeric_disagreement")
        self.assertNotIn("confidence", word)
        self.assertEqual(self.context, original)

    def test_concurrent_calls_share_one_generation_and_bad_cache_recovers(self):
        from concurrent.futures import ThreadPoolExecutor
        client = Fake(json.dumps({"sections": [{"text": self.context["selected_text"]}]}))
        with tempfile.TemporaryDirectory() as directory:
            reconciler = Reconciler(client, cache_dir=directory)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(reconciler.reconcile, self.image, self.context) for _ in range(2)]
                values = [f.result() for f in futures]
            self.assertEqual(client.calls, 1)
            self.assertEqual(sum(v["cache_hit"] for v in values), 1)
            path = next(Path(directory).glob("*.json"))
            path.write_text("[]", encoding="utf-8")
            recovered = reconciler.reconcile(self.image, self.context)
            self.assertEqual(client.calls, 2)
            self.assertIn("invalid_cache_entry_recomputed", recovered["warnings"])

    def test_cli_cannot_overwrite_source_json(self):
        import os
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "views.json"
            original = json.dumps(self.context)
            source.write_text(original, encoding="utf-8")
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
            completed = subprocess.run([sys.executable, "-m", "signspeak_llm", "reconcile", str(source),
                                        str(source), "--output", str(source)], env=env, capture_output=True, timeout=15)
            self.assertEqual(completed.returncode, 1)
            self.assertEqual(source.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
