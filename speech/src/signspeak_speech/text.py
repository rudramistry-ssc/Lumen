"""Small speech-only expansions; never change source text or guess OCR values."""
from datetime import date
import re

_MONTHS = {
    "en": "January February March April May June July August September October November December".split(),
    "fr": "janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split(),
}
_UNITS = {
    "en": {"mg": "milligram", "g": "gram", "kg": "kilogram", "ml": "milliliter", "mL": "milliliter"},
    "fr": {"mg": "milligramme", "g": "gramme", "kg": "kilogramme", "ml": "millilitre", "mL": "millilitre"},
}


def spoken_text(text, language):
    """Expand unambiguous ISO dates, clock notation, common units and currency.

    Ambiguous slash dates, decimal punctuation and abbreviations remain Piper's
    responsibility. Original and spoken text are both retained in metadata.
    """
    def iso(match):
        try:
            value = date(*map(int, match.groups()))
        except ValueError:
            return match[0]
        month = _MONTHS[language][value.month - 1]
        return f"{value.day} {month} {value.year}" if language == "fr" else f"{month} {value.day}, {value.year}"
    text = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", iso, text)
    if language == "fr":
        def clock(match):
            hour, minute = map(int, match.groups())
            return f"{hour} {'heure' if hour == 1 else 'heures'}" + (f" {minute}" if minute else "")
        text = re.sub(r"(?<![\d:])([01]?\d|2[0-3])(?:\s*h\s*|:)([0-5]\d)\b", clock, text)
    else:
        text = re.sub(r"\b(0?[1-9]|1[0-2]):00\s*(AM|PM)\b", lambda m: f"{int(m[1])} {m[2]}", text, flags=re.I)
    def unit(match):
        number, code = match.groups()
        singular = number in {"1", "1.0", "1,0", "1.00", "1,00"}
        return number + " " + _UNITS[language][code] + ("" if singular else "s")
    text = re.sub(r"(?<!\w)([+\-]?\d+(?:[.,]\d+)?)\s*(mg|kg|mL|ml|g)\b", unit, text)
    # '$' is announced as dollars, never guessed as Canadian or US dollars.
    for symbol, word in (("$", "dollars"), ("€", "euros"), ("£", "livres" if language == "fr" else "pounds")):
        text = re.sub(re.escape(symbol) + r"\s*(\d+(?:[.,]\d+)?)", lambda m: m[1] + " " + word, text)
        text = re.sub(r"(\d+(?:[.,]\d+)?)\s*" + re.escape(symbol), lambda m: m[1] + " " + word, text)
    text = re.sub(r"(?<=\d)\s*%", " pour cent" if language == "fr" else " percent", text)
    return text
