"""Tests for ``open_canon_site.scrapers._osis`` (OSIS inline helpers and Roman numerals)."""

from __future__ import annotations

import pyosis
import pytest
from hypothesis import given
from hypothesis import strategies as st
from open_canon_site.scrapers import _osis

valid_numbers = st.integers(min_value=1, max_value=3999)
"""Every integer standard Roman notation can represent."""


def _milestone(n):
    """Build a page ``MilestoneCt`` numbered ``n``."""
    return pyosis.MilestoneCt(type_value="page", n=n)


# --- consolidate_inline_strings --------------------------------------------------------


def test_consolidate_inline_strings_merges_adjacent_strings():
    """Runs of strings merge and non-string parts stay in place and split runs."""
    ms = _milestone("1")
    assert _osis.consolidate_inline_strings(["a", "b", ms, "c", "d"]) == ["ab", ms, "cd"]


def test_consolidate_inline_strings_empty_input_returns_empty_list():
    """An empty list yields a new empty list."""
    assert _osis.consolidate_inline_strings([]) == []


def test_consolidate_inline_strings_without_strings_is_unchanged():
    """Only non-string parts: order is preserved and nothing is merged."""
    a, b = _milestone("1"), _milestone("2")
    assert _osis.consolidate_inline_strings([a, b]) == [a, b]


def test_consolidate_inline_strings_does_not_mutate_input():
    """The input list is left as it was."""
    content = ["a", "b"]
    _osis.consolidate_inline_strings(content)
    assert content == ["a", "b"]


def test_consolidate_inline_strings_keeps_empty_strings_merged():
    """Empty strings merge harmlessly into neighbouring text."""
    assert _osis.consolidate_inline_strings(["", "a", ""]) == ["a"]


# --- extract_plain_text ----------------------------------------------------------------


def test_extract_plain_text_concatenates_strings():
    """Plain strings are joined without separators."""
    assert _osis.extract_plain_text(["a", "b"]) == "ab"


def test_extract_plain_text_recurses_into_nested_content():
    """Highlight and note contents are flattened; milestones add nothing."""
    inner = pyosis.HiCt(content=["b"])
    outer = pyosis.HiCt(content=["a", inner], type_value="italic")
    note = pyosis.NoteCt(content=["n"])
    assert _osis.extract_plain_text(["x", outer, note, _milestone("1")]) == "xabn"


def test_extract_plain_text_empty_returns_empty_string():
    """No parts means no text."""
    assert _osis.extract_plain_text([]) == ""


# --- is_navigation_text ----------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Next: Chapter 2",
        "Previous: Index",
        "Sacred Texts",
        "Buy this Book",
        "«",
        "»",
        "x sacred-texts.com",
    ],
)
def test_is_navigation_text_detects_each_marker(text):
    """Texts containing a navigation phrase are flagged."""
    assert _osis.is_navigation_text(text)


def test_is_navigation_text_ignores_scripture():
    """Ordinary verse text is not navigation."""
    assert not _osis.is_navigation_text("In the beginning")


def test_is_navigation_text_is_case_sensitive_substring_match():
    """Matching is by case-sensitive substring, so ``index`` passes but ``Indexed`` is flagged."""
    assert not _osis.is_navigation_text("index")
    assert _osis.is_navigation_text("Indexed")


# --- normalize_whitespace --------------------------------------------------------------


def test_normalize_whitespace_collapses_and_trims():
    """Mixed whitespace runs become single spaces and the ends are trimmed."""
    assert _osis.normalize_whitespace("  a \n\t b  ") == "a b"


def test_normalize_whitespace_blank_input_returns_empty():
    """Whitespace-only text becomes the empty string."""
    assert _osis.normalize_whitespace(" \n\t ") == ""


def test_normalize_whitespace_collapses_non_breaking_space():
    """Unicode whitespace such as NBSP is treated like a normal space."""
    assert _osis.normalize_whitespace("a  b") == "a b"


@given(st.text())
def test_normalize_whitespace_is_idempotent(text):
    """Normalising twice gives the same result as normalising once."""
    once = _osis.normalize_whitespace(text)
    assert _osis.normalize_whitespace(once) == once


# --- parse_page_marker_text ------------------------------------------------------------


def test_parse_page_marker_text_splits_text_and_arabic_marker():
    """A marker in the middle yields text, a page milestone and text."""
    parts = _osis.parse_page_marker_text("before p. 12 after")
    assert parts[0] == "before"
    assert isinstance(parts[1], pyosis.MilestoneCt) and parts[1].n == "12"
    assert parts[1].type_value == "page"
    assert parts[2] == "after"


def test_parse_page_marker_text_accepts_roman_and_case_insensitive_marker():
    """Roman numerals and an upper-case ``P.`` are recognised and kept as written."""
    parts = _osis.parse_page_marker_text("a P. xiv b")
    assert [getattr(p, "n", p) for p in parts] == ["a", "xiv", "b"]


def test_parse_page_marker_text_multiple_markers():
    """Several markers produce one milestone each in order."""
    parts = _osis.parse_page_marker_text("a p. 1 b p. 2 c")
    assert [getattr(p, "n", p) for p in parts] == ["a", "1", "b", "2", "c"]


def test_parse_page_marker_text_marker_only():
    """Text that is just a marker yields only a milestone."""
    parts = _osis.parse_page_marker_text("p. iv")
    assert len(parts) == 1 and parts[0].n == "iv"


def test_parse_page_marker_text_without_marker_returns_text():
    """Text with no marker is returned as a single string."""
    assert _osis.parse_page_marker_text("no marker here") == ["no marker here"]


def test_parse_page_marker_text_empty_and_blank_return_empty():
    """Empty or whitespace-only text yields no parts."""
    assert _osis.parse_page_marker_text("") == []
    assert _osis.parse_page_marker_text("   ") == []


@pytest.mark.xfail(
    strict=True,
    reason="Bug: the marker regex has no word boundary, so 'p. 5' inside 'Gossip. 5' is split "
    "off as a page milestone and the text loses its final 'p'.",
)
def test_parse_page_marker_text_ignores_p_dot_inside_words():
    """A ``p.`` ending an ordinary word is not a page marker."""
    assert _osis.parse_page_marker_text("Gossip. 5 times") == ["Gossip. 5 times"]


# --- roman_to_int ----------------------------------------------------------------------


def test_roman_to_int_converts_simple_and_subtractive_numerals():
    """Lower-case, subtractive and long numerals convert correctly."""
    assert _osis.roman_to_int("xiv") == 14
    assert _osis.roman_to_int("MCMXC") == 1990
    assert _osis.roman_to_int("IV") == 4 and _osis.roman_to_int("MMMCMXCIX") == 3999


def test_roman_to_int_empty_is_zero():
    """The empty string converts to 0."""
    assert _osis.roman_to_int("") == 0


def test_roman_to_int_is_case_insensitive():
    """Upper, lower and mixed case give the same value."""
    assert _osis.roman_to_int("XiV") == _osis.roman_to_int("xiv") == _osis.roman_to_int("XIV")


def test_roman_to_int_ignores_outer_whitespace_and_non_roman_characters():
    """Characters that are not Roman digits count as zero rather than raising an error."""
    assert _osis.roman_to_int(" XIV\n") == 14
    assert _osis.roman_to_int("XzIV") == 14


def test_roman_to_int_inner_non_roman_characters_reset_subtractive_context():
    """Documented current behaviour on malformed input: a stray character between digits.

    A non-Roman character resets the "previous value" used for subtractive notation, so
    ``"X I V"`` is summed as 10 + 1 + 5 = 16 instead of 14. Input is expected to be a
    clean numeral, so this is recorded rather than treated as a bug.
    """
    assert _osis.roman_to_int("X I V") == 16


def test_roman_to_int_is_lenient_about_non_canonical_numerals():
    """Non-canonical forms are summed with the subtractive rule instead of rejected.

    Documented current behaviour: ``IIII`` is 4, ``IC`` is 99 and ``MMMM`` is 4000.
    """
    assert (_osis.roman_to_int("IIII"), _osis.roman_to_int("IC")) == (4, 99)
    assert _osis.roman_to_int("MMMM") == 4000


@given(valid_numbers)
def test_roman_to_int_round_trips(number):
    """``roman_to_int(int_to_roman(n)) == n`` for every n in 1..3999."""
    assert _osis.roman_to_int(_osis.int_to_roman(number)) == number


@given(valid_numbers)
def test_roman_to_int_is_case_insensitive_property(number):
    """Lower-case and swapped-case forms of a canonical numeral decode identically."""
    numeral = _osis.int_to_roman(number)
    assert _osis.roman_to_int(numeral.lower()) == number
    assert _osis.roman_to_int(numeral.swapcase()) == number


@given(valid_numbers, st.text(alphabet=" \t\n", max_size=3))
def test_roman_to_int_ignores_interleaved_whitespace_property(number, padding):
    """Whitespace padded around a canonical numeral never changes its value."""
    assert _osis.roman_to_int(padding + _osis.int_to_roman(number) + padding) == number


# --- int_to_roman ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "number, numeral",
    [(1, "I"), (4, "IV"), (9, "IX"), (14, "XIV"), (40, "XL"), (90, "XC"), (400, "CD"),
     (1990, "MCMXC"), (2024, "MMXXIV"), (3999, "MMMCMXCIX")],
)  # fmt: skip
def test_int_to_roman_examples(number, numeral):
    """Known values use canonical upper-case subtractive notation."""
    assert _osis.int_to_roman(number) == numeral


@pytest.mark.parametrize("number", [0, -1, 4000, 10**6])
def test_int_to_roman_rejects_out_of_range(number):
    """Values outside 1..3999 raise ``ValueError`` naming the offending value."""
    with pytest.raises(ValueError, match=str(number)):
        _osis.int_to_roman(number)


@given(valid_numbers)
def test_int_to_roman_round_trips_from_numeral(number):
    """``int_to_roman(roman_to_int(s)) == s`` for canonical numerals ``s``."""
    numeral = _osis.int_to_roman(number)
    assert _osis.int_to_roman(_osis.roman_to_int(numeral)) == numeral


@given(st.one_of(st.integers(max_value=0), st.integers(min_value=4000)))
def test_int_to_roman_raises_value_error_outside_range(number):
    """Any integer below 1 or above 3999 raises ``ValueError``."""
    with pytest.raises(ValueError):
        _osis.int_to_roman(number)


@given(valid_numbers)
def test_int_to_roman_output_is_uppercase_roman_digits_only(number):
    """Output is non-empty and uses only ``IVXLCDM``."""
    numeral = _osis.int_to_roman(number)
    assert numeral and set(numeral) <= set("IVXLCDM")
