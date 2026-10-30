from copy import deepcopy
import json
import unittest
from pathlib import Path
import ast

from signspeak_llm.context import compact_context, render_context
from signspeak_llm.grounding import numeric_disputes, numeric_notice


class ContextTests(unittest.TestCase):
    def test_original_question_suite_and_expectations_unchanged(self):
        root = Path(__file__).resolve().parents[1]
        def cases_ast(path):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            return ast.dump(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "cases"))
        self.assertEqual(cases_ast(root / "benchmark.py"), cases_ast(root / "baseline-phase3/benchmark.py"))
    def test_deployment_manifest_matches_runtime_pins(self):
        from signspeak_llm.models import MODELS
        manifest = json.loads((Path(__file__).resolve().parents[1] / "models.json").read_text())
        for name, item in MODELS.items():
            for key, value in item.items():
                self.assertEqual(manifest[name][key], value)
    def test_complete_order_and_alternatives_without_geometry(self):
        source = {"selected_text": "Second\n\nFirst", "reading_order": {"sequence": ["R2", "R1"]},
                  "regions": [{"id": "R1", "text": "First", "bbox": [0, 0, 1, 1]},
                              {"id": "R2", "text": "Second", "tentative_words": [{"id": "W1", "text": "1,5",
                               "bbox": [0, 0, 1, 1], "evidence": {"status": "numeric_disagreement", "alternatives": [{"text": "1.5", "bbox": [0, 0, 1, 1]}]}}]}],
                  "warnings": ["partial"], "numeric_conflicts": [{"text": "1,5", "alternatives": ["1.5"]}]}
        before = deepcopy(source)
        result = compact_context(source)
        self.assertEqual([r["text"] for r in result["regions"]], ["Second", "First"])
        self.assertNotIn('"bbox"', json.dumps(result))
        self.assertIn('"1.5"', json.dumps(result))
        self.assertEqual(source, before)

    def test_nonredundant_selected_text_is_retained(self):
        result = compact_context({"selected_text": "Other content", "regions": [{"id": "R1", "text": "Text"}]})
        self.assertEqual(result["selected_text"], "Other content")

    def test_decimal_punctuation_is_not_quantity_disagreement(self):
        def dispute(a, b):
            return numeric_disputes({"numeric_conflicts": [{"text": a, "alternatives": [b]}]})[0]
        self.assertEqual(dispute("1,5", "1.5")["kind"], "decimal_punctuation_only")
        self.assertEqual(dispute("1,5", "7.5")["kind"], "different_quantities")
        self.assertEqual(dispute("1,500", "1.500")["kind"], "unresolved_literal_or_unit_disagreement")
        self.assertEqual(dispute("5mg", "5g")["kind"], "unresolved_literal_or_unit_disagreement")
        notice = numeric_notice([dispute("1,5", "1.5")], "fr")
        self.assertIn('"1,5"', notice)
        self.assertIn('"1.5"', notice)
        self.assertIn("même quantité", notice)

    def test_missing_alternative_still_blocks_confirmation(self):
        result = numeric_disputes({"numeric_conflicts": [{"text": "12", "alternatives": []}]})
        self.assertEqual(result[0]["kind"], "unresolved_literal_or_unit_disagreement")


if __name__ == "__main__":
    unittest.main()
