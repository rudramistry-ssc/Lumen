"""Literal comparisons flag review items, not proof of hallucination or truth."""
from collections import Counter
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
import re
import unicodedata

from .grounding import numeric_disputes

_UNIT = r"(?:mcg|µg|μg|mg|kg|g|mL|ml|L|l|cl|dl|kcal|cal|kJ|kj|cm|mmHg|mm|km|oz|lb|IU|°C|°F|%|AM|PM|am|pm|[$€£])"
_CRITICAL = re.compile(
    r"[$€£]?\s*[+\-−]?(?:\d{1,2}\s*h\s*\d{2}|\d+(?:[.,:/\-]\d+)*)(?:\s*" + _UNIT + r")?(?![\w])"
    r"|\b[A-Za-z]+\d+[A-Za-z0-9]*\b", re.UNICODE)


def critical_literals(text):
    """Keep punctuation, dates, time, currency and units literal; no locale guess."""
    return [m.group().strip() for m in _CRITICAL.finditer(unicodedata.normalize("NFC", text))]


def _decimal(literal):
    match = re.fullmatch(r"([$€£]?)\s*(\d+(?:[.,]\d{1,2})?)\s*([A-Za-zµμ%$€£]*)", literal)
    if not match:
        return None
    try:
        return (Decimal(match[2].replace(",", ".")), match[1], match[3])
    except InvalidOperation:
        return None


def compare_transcription(context, text):
    source = context["selected_text"]
    ocr, model = critical_literals(source), critical_literals(text)
    removed = list((Counter(ocr) - Counter(model)).elements())
    introduced = list((Counter(model) - Counter(ocr)).elements())
    variants = [{"ocr": old, "model": new, "kind": "possible_decimal_or_spacing_variant",
                 "verification": "not_performed"}
                for old in removed for new in introduced
                if _decimal(old) is not None and _decimal(old) == _decimal(new)]
    changes = []
    a, b = source.split(), text.split()
    for kind, i, j, k, l in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if kind != "equal":
            changes.append({"kind": kind, "ocr_text": " ".join(a[i:j]), "model_text": " ".join(b[k:l]),
                            "verification": "not_performed"})
    # Bag differences do not mistake moved text for missing text; genuine OCR
    # garbage removal can still be a useful correction, so all are review items.
    omitted_words = list((Counter(a) - Counter(b)).elements())
    added_words = list((Counter(b) - Counter(a)).elements())
    return {"ocr_numeric_observations": ocr, "model_numeric_observations": model,
            "numeric_disagreements": {"ocr_literals_missing_or_changed": removed,
                                      "model_literals_introduced_or_changed": introduced,
                                      "possible_representation_changes": variants},
            "source_numeric_conflicts": context.get("numeric_conflicts") or [],
            "source_numeric_disputes": numeric_disputes(context),
            "omissions": omitted_words, "unsupported_additions": added_words,
            "uncertain_corrections": changes,
            "interpretation": "Differences from OCR are unverified review candidates, not confirmed hallucinations or corrections. Reordering may appear in sequence differences."}
