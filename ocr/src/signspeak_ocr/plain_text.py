"""Remove generated Markdown presentation without changing OCR source text."""
import re


def plain_answer(text: str) -> str:
    text = re.sub(r"(?m)^\s*```[^\n]*\n?|```\s*$", "", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"(?m)^\s*\*\s+", "- ", text)
    text = re.sub(r"\[([^\]\n]+)\]\([^\)\n]+\)", r"\1", text)
    # The user requests no asterisks in generated answers. Source transcription
    # is never passed through this function; mathematical multiplication stays meaningful.
    text = re.sub(r"(?<=\d)\s*\*\s*(?=\d)", " × ", text)
    text = text.replace("*", "").replace("`", "")
    text = re.sub(r"(?<!\w)_{1,2}(.+?)_{1,2}(?!\w)", r"\1", text)
    return text.strip()
