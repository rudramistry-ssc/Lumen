"""Replay saved pilot outputs only. Fixture typing is NOT human ground truth."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
from signspeak_llm.document import build_vision_document

PILOT = Path(__file__).resolve().parents[1]/"runtime/photo-evaluation/user-ten-20261029"


@unittest.skipUnless(PILOT.is_dir(), "private pilot outputs not distributed")
class SavedPhotoTests(unittest.TestCase):
    def test_saved_vision_text_preserved_and_failed_vision_never_uses_hybrid(self):
        files = list(PILOT.rglob("*.json"))
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        count = 0
        for path in sorted((PILOT/"documents").glob("*/evidence.json")):
            evidence = json.loads(path.read_text(encoding="utf-8"))
            vision = deepcopy(evidence["readings"]["vision_only"])
            # Explicit replay fixture only: do NOT migrate caches or mark reviewed.
            # Literal/symbol classification is independently covered with typed fixtures.
            if vision.get("model_text"):
                vision.update(printed_text_status="present", visual_descriptions=[], text_observations=[])
                for section in vision["sections"]: section["text_state"] = "plain"
            doc = build_vision_document(evidence["original_views"]["llm_context"], vision, path.parent.name)
            if vision.get("model_text"):
                self.assertEqual(doc["text"], vision["model_text"])
                self.assertEqual(doc["selected_method"], "vision_only")
            else:
                self.assertEqual(doc["status"], "ocr_unreviewed_fallback")
                self.assertNotEqual(doc["selected_method"], "hybrid")
            for key, field in (("display", "text"), ("speech", "text"), ("llm_context", "selected_text")):
                self.assertEqual(doc["text"], doc["selected_views"][key][field])
            self.assertEqual(doc["verification"], "not_performed")
            count += 1
        self.assertGreater(count, 0)
        for path in (PILOT/"references").glob("*.json"):
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["review_status"], "pending")
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
