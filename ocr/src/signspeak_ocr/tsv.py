"""Robust Tesseract TSV parsing into a block > paragraph > line > word hierarchy.

Rules:

* Fields are split on tabs only. Text is literal: quotes are never treated as
  CSV quoting, so a word such as ``"Exit`` cannot swallow later rows.
* A word row whose empty text lost its trailing tab is padded.
* Extra tabs inside the final ``text`` column are re-joined.
* Malformed rows are counted and skipped, never fatal, unless the header is
  missing or no row is usable.
* Coordinates are kept in the OCR input (working) space as [x0, y0, x1, y1].
"""

from __future__ import annotations

import statistics
import unicodedata
from dataclasses import dataclass, field
from typing import Iterator

from .errors import TsvParseError
from .geometry import BBox, union_box

REQUIRED_COLUMNS = (
    "level", "page_num", "block_num", "par_num", "line_num", "word_num",
    "left", "top", "width", "height", "conf", "text",
)
_INT_COLUMNS = REQUIRED_COLUMNS[:10]


@dataclass
class Word:
    text: str
    bbox: BBox
    confidence: float | None
    word_num: int
    flags: list[str] = field(default_factory=list)


@dataclass
class Line:
    key: tuple[int, int, int, int]
    bbox: BBox | None
    words: list[Word] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words)

    @property
    def word_bbox(self) -> BBox | None:
        return union_box(word.bbox for word in self.words)


@dataclass
class Paragraph:
    key: tuple[int, int, int]
    bbox: BBox | None
    lines: list[Line] = field(default_factory=list)


@dataclass
class Block:
    key: tuple[int, int]
    bbox: BBox | None
    paragraphs: list[Paragraph] = field(default_factory=list)

    def iter_lines(self) -> Iterator[Line]:
        for paragraph in self.paragraphs:
            yield from paragraph.lines

    def iter_words(self) -> Iterator[Word]:
        for line in self.iter_lines():
            yield from line.words


@dataclass
class TsvDocument:
    page_size: tuple[int, int] | None
    blocks: list[Block]
    row_count: int
    word_row_count: int
    empty_word_rows: int
    malformed_rows: int
    warnings: list[str] = field(default_factory=list)

    def iter_words(self) -> Iterator[Word]:
        for block in self.blocks:
            yield from block.iter_words()

    def iter_lines(self) -> Iterator[Line]:
        for block in self.blocks:
            yield from block.iter_lines()


def _box(left: int, top: int, width: int, height: int) -> BBox:
    return (float(left), float(top), float(left + max(width, 0)), float(top + max(height, 0)))


def parse_tsv(tsv_text: str) -> TsvDocument:
    text = tsv_text.lstrip("\ufeff")
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        raise TsvParseError("Tesseract produced no TSV output")
    header = lines[0].rstrip("\r").split("\t")
    missing = [name for name in REQUIRED_COLUMNS if name not in header]
    if missing:
        raise TsvParseError(f"Tesseract TSV header is missing columns: {missing}", details={"header": header})
    index = {name: header.index(name) for name in REQUIRED_COLUMNS}
    text_last = index["text"] == len(header) - 1

    page_size: tuple[int, int] | None = None
    blocks: dict[tuple[int, int], Block] = {}
    paragraphs: dict[tuple[int, int, int], Paragraph] = {}
    line_map: dict[tuple[int, int, int, int], Line] = {}
    row_count = word_rows = empty_words = malformed = 0
    warnings: list[str] = []

    def block_for(key: tuple[int, int]) -> Block:
        if key not in blocks:
            blocks[key] = Block(key, None)
        return blocks[key]

    def paragraph_for(key: tuple[int, int, int]) -> Paragraph:
        if key not in paragraphs:
            paragraphs[key] = Paragraph(key, None)
            block_for(key[:2]).paragraphs.append(paragraphs[key])
        return paragraphs[key]

    def line_for(key: tuple[int, int, int, int]) -> Line:
        if key not in line_map:
            line_map[key] = Line(key, None)
            paragraph_for(key[:3]).lines.append(line_map[key])
        return line_map[key]

    for raw in lines[1:]:
        raw = raw.rstrip("\r")
        if not raw.strip():
            continue
        row_count += 1
        fields = raw.split("\t")
        if len(fields) == len(header) - 1 and text_last:
            fields.append("")
        elif len(fields) > len(header) and text_last:
            fields = fields[: len(header) - 1] + ["\t".join(fields[len(header) - 1:])]
        if len(fields) != len(header):
            malformed += 1
            continue
        try:
            values = {name: int(fields[index[name]]) for name in _INT_COLUMNS}
        except ValueError:
            malformed += 1
            continue
        try:
            conf_value: float | None = float(fields[index["conf"]])
        except ValueError:
            conf_value = None
        level = values["level"]
        box = _box(values["left"], values["top"], values["width"], values["height"])
        page, block_num, par_num, line_num = (
            values["page_num"], values["block_num"], values["par_num"], values["line_num"],
        )
        if level == 1:
            page_size = (values["width"], values["height"])
        elif level == 2:
            block_for((page, block_num)).bbox = box
        elif level == 3:
            paragraph_for((page, block_num, par_num)).bbox = box
        elif level == 4:
            line_for((page, block_num, par_num, line_num)).bbox = box
        elif level == 5:
            word_rows += 1
            word_text = unicodedata.normalize("NFC", fields[index["text"]]).strip()
            if not word_text:
                empty_words += 1
                continue
            flags: list[str] = []
            if conf_value is None or conf_value < 0:
                flags.append("confidence_unavailable")
                conf_value = None
            if values["width"] <= 0 or values["height"] <= 0:
                flags.append("degenerate_box")
            if "\ufffd" in word_text:
                flags.append("replacement_character")
            line_for((page, block_num, par_num, line_num)).words.append(
                Word(word_text, box, conf_value, values["word_num"], flags)
            )
        else:
            malformed += 1

    if malformed:
        warnings.append(f"tsv_malformed_rows_skipped:{malformed}")
    if row_count == 0:
        warnings.append("tsv_has_no_rows")

    ordered_blocks: list[Block] = []
    for block in blocks.values():
        block.paragraphs = [
            paragraph for paragraph in block.paragraphs
            if any(line.words for line in paragraph.lines)
        ]
        for paragraph in block.paragraphs:
            paragraph.lines = [line for line in paragraph.lines if line.words]
        if block.paragraphs:
            ordered_blocks.append(block)
    return TsvDocument(page_size, ordered_blocks, row_count, word_rows, empty_words, malformed, warnings)


def confidence_summary(words: list[Word], low_threshold: float) -> dict[str, float | int | None]:
    values = [word.confidence for word in words if word.confidence is not None]
    if not values:
        return {"word_count": len(words), "mean": None, "median": None, "min_word": None,
                "low_conf_fraction": None}
    return {
        "word_count": len(words),
        "mean": round(statistics.fmean(values), 2),
        "median": round(statistics.median(values), 2),
        "min_word": round(min(values), 2),
        "low_conf_fraction": round(sum(v < low_threshold for v in values) / len(values), 4),
    }
