"""Shared helpers for building OSIS content from scraped HTML text."""

from __future__ import annotations

import re
from typing import Union

import pyosis

InlinePart = Union[str, pyosis.HiCt, pyosis.MilestoneCt, pyosis.NoteCt]
"""One element of inline OSIS content: plain text or a highlight, milestone or note."""

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
"""Substrings that mark a text node as site navigation chrome rather than scripture."""


def consolidate_inline_strings(content: list[InlinePart]) -> list[InlinePart]:
    """Merge runs of adjacent strings into single strings.

    Non-string parts (``HiCt``, ``MilestoneCt``, ``NoteCt``) are kept in place and
    break a run, so ``["a", "b", milestone, "c"]`` becomes ``["ab", milestone, "c"]``.

    Args:
        content: Inline parts in document order.

    Returns:
        A new list with consecutive strings concatenated; ``[]`` for empty input.
    """
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
    """Flatten inline parts to plain text.

    Strings are kept as-is and parts with a ``content`` attribute (such as ``HiCt``
    or ``NoteCt``) are flattened recursively. Parts with no text content, such as
    milestones, contribute nothing.

    Args:
        parts: Inline parts in document order.

    Returns:
        The concatenated text with no separators added.
    """
    out = ""
    for part in parts:
        if isinstance(part, str):
            out += part
        elif hasattr(part, "content"):
            out += extract_plain_text(part.content)
    return out


def is_navigation_text(text: str) -> bool:
    """Report whether text looks like site navigation (``Next:``, ``Index``, ``«``...).

    Args:
        text: A text node from the page.

    Returns:
        True if any phrase in ``_NAV_PHRASES`` occurs in ``text`` (case-sensitive
        substring match, so words like ``Indexed`` also match).
    """
    return any(phrase in text for phrase in _NAV_PHRASES)


def normalize_whitespace(text: str) -> str:
    """Collapse every whitespace run to a single space and trim the ends.

    Args:
        text: Text possibly containing newlines, tabs or repeated spaces.

    Returns:
        The normalised text.
    """
    return re.sub(r"\s+", " ", text).strip()


def parse_page_marker_text(text: str) -> list[InlinePart]:
    """Split text on ``p. 12`` / ``p. xiv`` page markers into text and page milestones.

    Markers are matched case-insensitively with arabic or roman numerals, together
    with the whitespace around them. The ``p.`` must not be preceded by a word
    character, so the end of a word such as ``Gossip. 5`` is not a marker; a marker
    may follow the start of the string, whitespace or punctuation such as ``(``. Each becomes a ``MilestoneCt`` of type ``page``
    whose ``n`` is the numeral as written. Whitespace-only text segments are dropped.

    Args:
        text: Raw text that may contain page markers.

    Returns:
        Text strings and page milestones in original order.
    """
    parts: list[InlinePart] = []
    last_end = 0
    for match in re.finditer(r"\s*(?<!\w)p\.\s+(\d+|[ivxlcdm]+)\s*", text, re.IGNORECASE):
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
    """Convert a Roman numeral to an integer, honouring subtractive notation.

    Args:
        text: Numeral in any case (``"xiv"``, ``"MCMXC"``). Characters that are not
            Roman digits count as zero rather than raising.

    Returns:
        The integer value; ``0`` for an empty string.
    """
    roman_values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    previous = 0
    for char in reversed(text.upper()):
        value = roman_values.get(char, 0)
        total += value if value >= previous else -value
        previous = value
    return total


_ROMAN_NUMERALS = (
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
)
"""Value/symbol pairs in descending order, including subtractive forms, for ``int_to_roman``."""


def int_to_roman(number: int) -> str:
    """Convert an integer to its canonical Roman numeral (inverse of ``roman_to_int``).

    Uses standard subtractive notation (``4`` is ``IV``, ``1990`` is ``MCMXC``) in upper
    case.

    Args:
        number: Integer in the range 1 to 3999 inclusive.

    Returns:
        The upper-case Roman numeral for ``number``.

    Raises:
        ValueError: If ``number`` is below 1 or above 3999, which standard notation
            cannot represent.
    """
    if not 1 <= number <= 3999:
        raise ValueError(f"Roman numerals represent 1..3999, got {number}")
    parts = []
    for value, symbol in _ROMAN_NUMERALS:
        count, number = divmod(number, value)
        parts.append(symbol * count)
    return "".join(parts)
