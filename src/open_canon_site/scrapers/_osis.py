from __future__ import annotations

import re
from typing import Union

import pyosis

InlinePart = Union[str, pyosis.HiCt, pyosis.MilestoneCt, pyosis.NoteCt]

_NAV_PHRASES = (
    "Next:",
    "Previous:",
    "Sacred Texts",
    "Buy this Book",
    "Index",
    "«",
    "»",
    "sacred-texts.com",
)


def consolidate_inline_strings(content: list[InlinePart]) -> list[InlinePart]:
    if not content:
        return []

    result: list[InlinePart] = []
    current: str | None = None
    for item in content:
        if isinstance(item, str):
            current = (current or "") + item
            continue

        if current is not None:
            result.append(current)
            current = None
        result.append(item)

    if current is not None:
        result.append(current)

    return result


def extract_plain_text(parts: list[InlinePart]) -> str:
    out = ""
    for part in parts:
        if isinstance(part, str):
            out += part
        elif hasattr(part, "content"):
            out += extract_plain_text(part.content)
    return out


def is_navigation_text(text: str) -> bool:
    return any(phrase in text for phrase in _NAV_PHRASES)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_page_marker_text(text: str) -> list[InlinePart]:
    parts: list[InlinePart] = []
    last_end = 0
    for match in re.finditer(r"\s*p\.\s+(\d+|[ivxlcdm]+)\s*", text, re.IGNORECASE):
        if match.start() > last_end:
            parts.append(text[last_end : match.start()])
        parts.append(pyosis.MilestoneCt(type_value="page", n=match.group(1)))
        last_end = match.end()

    if last_end < len(text):
        parts.append(text[last_end:])

    return [
        part
        for part in parts
        if isinstance(part, pyosis.MilestoneCt) or (isinstance(part, str) and part.strip())
    ]


def roman_to_int(text: str) -> int:
    roman_values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    previous = 0
    for char in reversed(text.upper()):
        value = roman_values.get(char, 0)
        total += value if value >= previous else -value
        previous = value
    return total
