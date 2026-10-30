"""Conservative deterministic handling of literal OCR numeric disagreements."""
from decimal import Decimal, InvalidOperation
import re


def _literal(value):
    return value if isinstance(value, str) else value.get("text", value.get("raw", "")) if isinstance(value, dict) else ""


def numeric_disputes(context):
    groups = []
    for conflict in context.get("numeric_conflicts") or []:
        values = [_literal(conflict)] + [_literal(a) for a in conflict.get("alternatives", [])]
        groups.append(values)
    for region in context.get("regions", []):
        for word in region.get("tentative_words", []):
            evidence = word.get("evidence") or {}
            if evidence.get("status") == "numeric_disagreement":
                groups.append([word.get("text", "")] + [_literal(a) for a in evidence.get("alternatives", [])])
    for value in context.get("numeric_values", []):
        evidence = value.get("evidence") or {}
        if value.get("status") == "numeric_disagreement" or evidence.get("status") == "numeric_disagreement":
            groups.append([value.get("raw", "")] + [_literal(a) for a in evidence.get("alternatives", [])])
    result, seen = [], set()
    for group in groups:
        literals = list(dict.fromkeys(v for v in group if v))
        identity = tuple(sorted(literals))
        if not literals or identity in seen:
            continue
        seen.add(identity)
        # Only a single separator and one/two fractional digits is interpreted
        # as a decimal. Thousands/grouping, units, signs, exponents or multiple
        # separators remain unresolved. We do NOT assert source punctuation.
        parsed = []
        for literal in literals:
            if re.fullmatch(r"[0-9]+[.,][0-9]{1,2}", literal):
                try:
                    parsed.append(Decimal(literal.replace(",", ".")))
                except InvalidOperation:
                    pass
        if len(literals) > 1 and len(parsed) == len(literals) and len(set(parsed)) == 1:
            kind = "decimal_punctuation_only"
        elif len(literals) > 1 and all(re.fullmatch(r"[0-9]+(?:[.,][0-9]{1,2})?", v) for v in literals):
            quantities = {Decimal(v.replace(",", ".")) for v in literals}
            kind = "different_quantities" if len(quantities) > 1 else "literal_format_only"
        else:
            kind = "unresolved_literal_or_unit_disagreement"
        result.append({"literal_readings": literals, "kind": kind, "verification": "not_performed"})
    return result


def numeric_notice(disputes, language):
    french = language == "fr"
    opening = ("La lecture OCR est contestée ; je ne peux pas confirmer le texte imprimé exact." if french else
               "The OCR reading is disputed; I cannot confirm the exact printed text.")
    parts = [opening]
    for conflict in disputes:
        parts.append(("Lectures littérales : " if french else "Literal readings: ") + " / ".join('"' + x + '"' for x in conflict["literal_readings"]) + ".")
        if conflict["kind"] == "decimal_punctuation_only":
            parts.append("Ces écritures représentent la même quantité si la virgule et le point sont des séparateurs décimaux ; la ponctuation imprimée reste incertaine." if french else
                         "These spellings represent the same quantity if comma and point are decimal separators; the printed punctuation remains uncertain.")
        elif conflict["kind"] == "different_quantities":
            parts.append("Les quantités diffèrent ; aucune n'est sélectionnée." if french else
                         "The quantities differ; neither is selected.")
        else:
            parts.append("La quantité ou l'unité reste indéterminée." if french else "The quantity or unit remains unresolved.")
    parts.append("Vérifiez l'image ou fournissez une photo plus nette." if french else "Check the image or provide a clearer photo.")
    return " ".join(parts)
