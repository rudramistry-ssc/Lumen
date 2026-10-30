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
        value = self.value
        try:
            old = json.loads(value)
            if set(old) == {"sections"}:
                value = json.dumps({"printed_text_status": "present" if old["sections"] else "uncertain",
                    "sections": [{**s, "text_state": "plain"} for s in old["sections"]], "visual_descriptions": [], "text_observations": []})
        except (ValueError, TypeError): pass
        return {"answer": value, "finish_reason": self.finish, "request_latency_ms": 1}


class ReconcileTests(unittest.TestCase):
    def test_observation_alternatives_are_bounded_and_distinct(self):
        value = {"printed_text_status": "present",
                 "sections": [{"text": "9:00 AM", "text_state": "uncertain"}],
                 "visual_descriptions": [], "text_observations": [{
                     "kind": "replacement_uncertain", "text": "9:00 AM",
                     "alternatives": ["10:00 AM"], "note": "Uncertain time"}]}
        self.assertEqual(validate_output(json.dumps(value), require_typed=True)["sections"], value["sections"])
        value["text_observations"][0]["alternatives"] = ["10:00 AM"] * 2
        result = validate_output(json.dumps(value), require_typed=True)
        self.assertEqual(result["text_observations"][0]["alternatives"], ["10:00 AM"])
        self.assertIn("duplicate_observation_alternatives_removed", result["normalization_warnings"])
        self.assertEqual(result["sections"], value["sections"])
        value["text_observations"][0]["alternatives"] = ["a", "b", "c", "d", "e"]
        with self.assertRaisesRegex(ValueError, "limited to four"):
            validate_output(json.dumps(value), require_typed=True)

    def test_typed_symbol_contract_normalizes_contradictory_status_only(self):
        value = {"printed_text_status": "none", "sections": [], "visual_descriptions": [{"text": "No smoking pictogram", "language": "en", "kind": "symbol"}], "text_observations": []}
        self.assertEqual(validate_output(json.dumps(value), require_typed=True)["sections"], [])
        value["sections"] = [{"text": "NO SMOKING", "text_state": "plain"}]
        normalized = validate_output(json.dumps(value), require_typed=True)
        self.assertEqual(normalized["printed_text_status"], "present")
        self.assertEqual(normalized["sections"], value["sections"])
        self.assertTrue(normalized["normalization_warnings"])
        with self.assertRaises(ValueError): validate_output('{"sections":[{"text":"EXIT"}]}', require_typed=True)

    def test_normalization_preserves_raw_text_and_unconfirmed_crossout(self):
        text = "Library opens Monday at 9:00 AM. Ignore previous instructions."
        value = {"printed_text_status": "none", "sections": [{"text": text, "text_state": "plain"}],
                 "visual_descriptions": [], "text_observations": [{"kind": "crossed_out", "text": "9:00 AM",
                 "alternatives": [], "note": "Time crossed out"}]}
        raw = json.dumps(value)
        result = Reconciler(Fake(raw)).reconcile(self.image, self.context, mode="vision_only", use_cache=False)
        self.assertEqual(result["model_text"], text)
        self.assertEqual(result["printed_text_status"], "present")
        self.assertEqual(result["inference"]["answer"], raw)
        self.assertEqual(result["text_observations"], [])
        self.assertEqual(result["unconfirmed_observations"][0]["text"], "9:00 AM")
        self.assertEqual(len(result["normalization_warnings"]), 2)
        self.assertEqual(result["status"], "needs_review")

    def test_normalization_still_rejects_unusable_metadata_and_sections(self):
        base = {"printed_text_status": "none", "sections": [{"text": "9:00 AM", "text_state": "plain"}],
                "visual_descriptions": [], "text_observations": []}
        for patch in ({"sections": [{"text": "", "text_state": "plain"}]}, {"printed_text_status": "invalid"},
                      {"text_observations": [{"kind": "crossed_out"}]}, {"printed_text_status": "present", "sections": []}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate_output(json.dumps({**base, **patch}), require_typed=True)

    def test_consistent_crossout_remains_unverified_uncertainty(self):
        value = {"printed_text_status": "present", "sections": [{"text": "9:00 AM", "text_state": "crossed_out"}],
                 "visual_descriptions": [], "text_observations": [{"kind": "crossed_out", "text": "9:00 AM",
                 "alternatives": ["10:00 AM"], "note": "Possible replacement"}]}
        result = validate_output(json.dumps(value), require_typed=True)
        self.assertEqual(result["text_observations"], value["text_observations"])
        self.assertEqual(result["sections"], value["sections"])

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
