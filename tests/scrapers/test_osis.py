from __future__ import annotations

import pyosis

from open_canon_site.scrapers import _osis


def test_consolidate_inline_strings():
    ms = pyosis.MilestoneCt(type_value="page", n="1")
    assert _osis.consolidate_inline_strings(["a", "b", ms, "c", "d"]) == ["ab", ms, "cd"]
    assert _osis.consolidate_inline_strings([]) == []


def test_normalize_whitespace():
    assert _osis.normalize_whitespace("  a \n\t b  ") == "a b"


def test_is_navigation_text():
    assert _osis.is_navigation_text("Next: Chapter 2")
    assert not _osis.is_navigation_text("In the beginning")


def test_roman_to_int():
    assert _osis.roman_to_int("xiv") == 14
    assert _osis.roman_to_int("MCMXC") == 1990


def test_parse_page_marker_text():
    parts = _osis.parse_page_marker_text("before p. 12 after")
    assert parts[0] == "before"
    assert isinstance(parts[1], pyosis.MilestoneCt) and parts[1].n == "12"
    assert parts[2] == "after"


def test_extract_plain_text():
    assert _osis.extract_plain_text(["a", "b"]) == "ab"
