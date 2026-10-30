"""Public, manually written listening fixtures. No private documents or LLMs."""
CASES = [
    {"id": "english-notice", "segments": [{"text": "The library is closed on Monday. It reopens Tuesday at 9:00 AM.", "language": "en"}]},
    {"id": "french-notice", "segments": [{"text": "La bibliothèque est fermée lundi. Elle rouvre mardi à 9 h 00.", "language": "fr"}]},
    {"id": "bilingual-notice", "segments": [
        {"text": "The library reopens Tuesday at 9:00 AM.", "language": "en"},
        {"text": "La bibliothèque rouvre mardi à 9 h 00.", "language": "fr"}]},
    {"id": "dates-and-times", "segments": [
        {"text": "Your appointment is on 2026-11-03 at 9:00 AM. Please bring your ID.", "language": "en"},
        {"text": "Votre rendez-vous est le 2026-11-03 à 14 h 30. Veuillez apporter votre carte d'identité.", "language": "fr"}]},
    {"id": "prices-and-decimals", "segments": [
        {"text": "Admission is $12.50. The discount is 10%. The package weighs 1.5 kg.", "language": "en"},
        {"text": "L'entrée coûte 12,50 $. La réduction est de 10 %. Le paquet pèse 1,5 kg.", "language": "fr"}]},
    {"id": "nutrition-label", "segments": [
        {"text": "Nutrition Facts. Per 125 g. Calories 120. Fat 1.5 g, 2%. Sodium 230 mg, 10%.", "language": "en"},
        {"text": "Valeur nutritive. Pour 125 g. Calories 120. Lipides 1,5 g, 2 %. Sodium 230 mg, 10 %.", "language": "fr"}]},
    {"id": "numeric-disagreement", "speech_view": {
        "requires_attention": True,
        "numeric_conflicts": [{"text": "1,5", "alternatives": ["1.5"]}],
        "notices": [{"text": "Warning: the printed decimal separator is uncertain. Check the original label before relying on this reading.", "language": "en"}],
        "segments": [{"id": "R1:L1", "text": "Fat 1.5 g per serving.", "language": "en", "bbox": [0, 0, 100, 30], "confidence": 42,
                      "warnings": [{"text": "This is an uncertain OCR reading.", "language": "en", "word_ids": ["W2"]}]}]}},
    {"id": "reconciled-review", "reconciled": {"status": "needs_review", "requires_review": True,
        "sections": [{"text": "Admission $12.50."}, {"text": "Entrée 12,50 $."}],
        "comparison": {"numeric_disagreements": {"ocr_literals_missing_or_changed": ["$12.00"], "model_literals_introduced_or_changed": ["$12.50"]}}},
        "section_languages": ["en", "fr"]},
]


def synthesize_case(engine, case):
    if "speech_view" in case:
        return engine.synthesize_view(case["speech_view"])
    if "reconciled" in case:
        return engine.synthesize_reconciled(case["reconciled"], section_languages=case["section_languages"])
    return engine.synthesize_segments(case["segments"])
