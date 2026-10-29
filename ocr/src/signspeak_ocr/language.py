"""Lightweight per-line English/French identification for short sign text.

Evidence: function words and common signage/label vocabulary, French
diacritics, French elisions (l', d', qu', ...) and English contractions.
Short or ambiguous text returns ``unknown``; bilingual lines ("Exit / Sortie")
return ``mixed``. Cognates shared by both languages are deliberately absent.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any, Iterable

ENGLISH_WORDS = frozenset("""
the and of to in for with at by from this that these those is are was were be been not no
your you yours we our it its they their there here what when where which who how please do does
did only all any each every or but if than then into onto over under after before between per
open closed hours entrance exit keep out push pull caution warning wet floor emergency
stairs elevator restroom washroom women men staff authorized parking free sale today daily facts
fat sugars sugar protein fiber serving servings amount ingredients contains
may made value total saturated trans cholesterol carbohydrate calcium iron vitamin
prohibited allowed smoking no-smoking welcome thank thanks close closes opens monday tuesday
wednesday thursday friday saturday sunday weekdays weekends right left use do not
""".split())

FRENCH_WORDS = frozenset("""
le la les un une des du de et à au aux en dans pour avec sur par ce cette ces est sont été être
ne pas vous votre vos nous notre nos il elle ils elles que qui quoi où quand comment
ou mais si donc sans sous entre après avant chaque tout tous toute toutes seulement svp merci
ouvert ouverte fermé fermée heures entrée sortie secours poussez tirez glissant
plancher urgence escalier ascenseur toilettes femmes hommes autorisé autorisée
stationnement gratuit solde aujourd'hui quotidienne valeur nutritive lipides glucides sucres
protéines fibres teneur ingrédients contient peut fabriqué saturés
cholestérol fer interdit permis fumer bienvenue lundi mardi mercredi jeudi vendredi
samedi dimanche droite gauche utiliser défense
""".split())

FRENCH_DIACRITICS = frozenset("àâæçéèêëîïôœùûüÿ")
_ELISION = re.compile(r"\b(?:[ldjmnstc]|qu|jusqu|lorsqu|puisqu)['’]\w", re.IGNORECASE)
_EN_CONTRACTION = re.compile(r"\w['’](?:s|t|re|ve|ll|d|m)\b", re.IGNORECASE)
_TOKEN = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?", re.UNICODE)
_SEGMENT_SPLIT = re.compile(r"\s+[/|]\s+|\s{3,}")


def _score(text: str) -> tuple[float, float, int]:
    normalized = unicodedata.normalize("NFC", text).casefold()
    tokens = _TOKEN.findall(normalized)
    en = fr = 0.0
    for token in tokens:
        bare = re.sub(r"^[ldjmnstc]['’]|^qu['’]", "", token)
        if token in ENGLISH_WORDS or bare in ENGLISH_WORDS:
            en += 1.0
        if token in FRENCH_WORDS or bare in FRENCH_WORDS:
            fr += 1.0
        if any(character in FRENCH_DIACRITICS for character in token):
            fr += 0.75
    fr += 1.0 * len(_ELISION.findall(normalized))
    # "it's" etc. Do not count French elisions (handled above) as English.
    en += 0.75 * sum(1 for m in _EN_CONTRACTION.finditer(normalized) if not _ELISION.search(m.group(0)))
    return en, fr, len(tokens)


def _decide(en: float, fr: float, tokens: int) -> dict[str, Any]:
    evidence = en + fr
    if tokens == 0 or evidence < 1.0:
        language = "unknown"
    elif en > 0 and fr > 0 and min(en, fr) / max(en, fr) >= 0.5:
        language = "mixed"
    elif en == fr:
        language = "unknown"
    else:
        language = "en" if en > fr else "fr"
    confidence = abs(en - fr) / evidence if evidence else 0.0
    return {
        "code": language,
        "confidence": round(confidence, 3),
        "scores": {"en": round(en, 2), "fr": round(fr, 2)},
        "tokens": tokens,
    }


def detect_line_language(text: str) -> dict[str, Any]:
    segments = [segment for segment in _SEGMENT_SPLIT.split(text) if segment.strip()]
    if len(segments) > 1:
        decisions = [_decide(*_score(segment)) for segment in segments]
        codes = {decision["code"] for decision in decisions} - {"unknown"}
        if codes == {"en", "fr"}:
            en = sum(decision["scores"]["en"] for decision in decisions)
            fr = sum(decision["scores"]["fr"] for decision in decisions)
            return {
                "code": "mixed",
                "confidence": round(min(d["confidence"] for d in decisions if d["code"] != "unknown"), 3),
                "scores": {"en": round(en, 2), "fr": round(fr, 2)},
                "tokens": sum(decision["tokens"] for decision in decisions),
                "segments": [
                    {"text": segment.strip(), "code": decision["code"]}
                    for segment, decision in zip(segments, decisions)
                ],
            }
    return _decide(*_score(text))


def aggregate_languages(items: Iterable[tuple[str, int]]) -> dict[str, Any]:
    """Character-weighted distribution of line language codes."""

    weights: Counter[str] = Counter()
    for code, characters in items:
        weights[code] += max(characters, 0)
    total = sum(weights.values())
    if not total:
        return {"primary": "unknown", "distribution": []}
    distribution = [
        {"code": code, "share": round(weight / total, 3)}
        for code, weight in weights.most_common()
    ]
    known = {code: weight for code, weight in weights.items() if code in {"en", "fr"}}
    mixed_share = weights.get("mixed", 0) / total
    if known.get("en", 0) and known.get("fr", 0) and min(known.values()) / total >= 0.2 or mixed_share >= 0.3:
        primary = "mixed"
    elif known:
        primary = max(known, key=known.get)
    else:
        primary = "unknown"
    return {"primary": primary, "distribution": distribution}
