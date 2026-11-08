"""Unit tests for ``open_canon_site.scrapers.sacred_texts.forgotten_books_of_eden`` (offline).

Pages are minimal inline HTML snippets mimicking the sacred-texts.com FBE shapes; ``run``
and ``process_all`` are exercised with a fake fetcher or a pre-populated cache directory.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pyosis
import pytest
from bs4 import BeautifulSoup
from hypothesis import given
from hypothesis import strategies as st
from open_canon_site.scrapers import _osis
from open_canon_site.scrapers.sacred_texts import forgotten_books_of_eden as fbe
from open_canon_site.scrapers.sacred_texts.forgotten_books_of_eden import (
    FBEParser,
    VerseContent,
    WorkDef,
)


@pytest.fixture
def parser() -> FBEParser:
    """Return a parser with caching disabled and no politeness delay."""
    p = FBEParser(delay=0)
    yield p
    p.close()


def _tag(html: str, name: str = "p"):
    """Parse ``html`` and return its first ``name`` tag."""
    return BeautifulSoup(html, "html.parser").find(name)


def _xml(osis: pyosis.OsisXML) -> str:
    """Serialise an OSIS document to XML."""
    return osis.to_xml()


def _page(body: str) -> str:
    """Wrap ``body`` in a minimal FBE page skeleton."""
    return f"<html><body>{body}</body></html>"


def _chapter(num: str, *paragraphs: str) -> str:
    """Build a chapter page with an ``<h3>`` heading and the given paragraphs."""
    return _page(f"<h3>{num}</h3>" + "".join(f"<p>{p}</p>" for p in paragraphs))


def _verses(div: pyosis.DivCt) -> list[pyosis.VerseCt]:
    """Return the verse children of a chapter div."""
    return [c for c in div.content if isinstance(c, pyosis.VerseCt)]


def _text(parts) -> str:
    """Flatten inline parts to text."""
    return _osis.extract_plain_text(list(parts))


# --- constants / data containers ------------------------------------------------------


def test_works_definitions_are_consistent():
    """Every work has non-overlapping contiguous pages inside FILE_RANGE."""
    seen: list[int] = []
    for w in fbe.WORKS:
        seen += w.intro_pages + w.chapter_pages
    seen += fbe.TESTAMENTS_INTRO_PAGES + [p for t in fbe.TESTAMENTS for p in t.chapter_pages]
    assert len(seen) == len(set(seen))
    assert min(seen) >= fbe.FILE_RANGE[0] and max(seen) == fbe.FILE_RANGE[1]
    assert len(fbe.TESTAMENTS) == 12
    assert set(fbe.ADAM_EVE_WORK_IDS) <= {w.osis_id for w in fbe.WORKS}


def test_workdef_defaults():
    """Optional WorkDef fields default to no override."""
    w = WorkDef("x", "X", "X", [], [1])
    assert (w.output_stem, w.intro_title, w.intro_subtitle) == (None, None, None)
    assert w.intro_headings_as_subtitles is False


def test_versecontent_defaults():
    """VerseContent defaults to non-poetry with no lines."""
    vc = VerseContent(text="a", content_parts=["a"])
    assert vc.has_poetry is False and vc.poetry_lines is None


# --- __init__ / fetch_page / close ----------------------------------------------------


def test_init_sets_cache_dir_and_fetcher(tmp_path, caplog):
    """A cache directory is stored as a Path and logged."""
    with caplog.at_level(logging.INFO, logger=fbe.LOGGER.name):
        p = FBEParser(cache_dir=str(tmp_path), delay=0)
    assert p.cache_dir == tmp_path
    assert p.http.cache_dir == tmp_path
    assert "Using cache directory" in caplog.text
    p.close()


def test_init_without_cache_dir(parser):
    """No cache directory leaves cache_dir as None."""
    assert parser.cache_dir is None


def test_fetch_page_builds_zero_padded_url(parser, monkeypatch):
    """fetch_page requests ``fbe007.htm`` for page 7 and forwards retry_count."""
    calls = []
    monkeypatch.setattr(parser.http, "fetch_text", lambda **kw: calls.append(kw) or "<html></html>")
    assert parser.fetch_page(7, retry_count=5) == "<html></html>"
    assert calls == [{"url": "https://sacred-texts.com/bib/fbe/fbe007.htm", "retry_count": 5}]
    parser.fetch_page(123)
    assert calls[-1] == {"url": "https://sacred-texts.com/bib/fbe/fbe123.htm", "retry_count": 3}


def test_close_closes_http_client(parser, monkeypatch):
    """Close delegates to the fetcher."""
    closed = []
    monkeypatch.setattr(parser.http, "close", lambda: closed.append(True))
    parser.close()
    assert closed == [True]


# --- text helpers ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ('<p><a name="page_12"></a></p>', True),
        ('<p>\n <a name="page_12"></a>\n</p>', True),
        ('<p><a name="other"></a></p>', False),
        ('<p><a href="x">link</a></p>', False),
        ('<p><a name="page_1"></a> text</p>', False),
        ("<p><i>x</i></p>", False),
        ("<p>plain</p>", False),
    ],
)
def test_is_standalone_page_marker(html, expected):
    """Only a paragraph whose sole child is a ``page_`` anchor qualifies."""
    assert FBEParser._is_standalone_page_marker(_tag(html)) is expected


def test_consolidate_strings_merges_adjacent(parser):
    """Adjacent strings are merged, other parts kept."""
    ms = pyosis.MilestoneCt(type_value="page", n="1")
    assert parser.consolidate_strings(["a", "b", ms, "c"]) == ["ab", ms, "c"]


def test_extract_text_flattens_parts(parser):
    """Highlights are flattened to their text."""
    hi = pyosis.HiCt(type_value=pyosis.OsisHi.ITALIC, content=["b"])
    assert parser._extract_text(["a", hi, "c"]) == "abc"


# --- parse_inline_annotations ---------------------------------------------------------


def test_parse_inline_annotations_text_node(parser):
    """A plain text node returns itself unless blank."""
    soup = BeautifulSoup("hello", "html.parser")
    assert parser.parse_inline_annotations(soup.contents[0]) == ["hello"]


def test_parse_inline_annotations_blank_text_node_is_dropped(parser):
    """A whitespace-only text node outside green font yields nothing."""
    from bs4 import NavigableString

    assert parser.parse_inline_annotations(NavigableString("  ")) == []


def test_parse_inline_annotations_green_text_node_splits_page_markers(parser):
    """A text node flagged green is scanned for ``p. N`` markers."""
    from bs4 import NavigableString

    parts = parser.parse_inline_annotations(NavigableString("p. 12"), is_green_font=True)
    assert len(parts) == 1 and isinstance(parts[0], pyosis.MilestoneCt)
    assert parts[0].n == "12"


@pytest.mark.parametrize(
    ("tag", "hi"),
    [
        ("i", pyosis.OsisHi.ITALIC),
        ("em", pyosis.OsisHi.ITALIC),
        ("b", pyosis.OsisHi.BOLD),
        ("strong", pyosis.OsisHi.BOLD),
        ("sup", pyosis.OsisHi.SUPER),
        ("sub", pyosis.OsisHi.SUB),
    ],
)
def test_parse_inline_annotations_formatting_tags(parser, tag, hi):
    """Formatting tags become the matching ``hi`` type."""
    el = _tag(f"<p>a <{tag}>x</{tag}> b</p>")
    parts = parser.parse_inline_annotations(el)
    assert parts[0] == "a "
    assert isinstance(parts[1], pyosis.HiCt)
    assert parts[1].type_value == hi and parts[1].content == ["x"]
    assert parts[2] == " b"


def test_parse_inline_annotations_empty_formatting_omitted(parser):
    """Empty formatting elements add nothing."""
    el = _tag("<p>a<i></i><b> </b><sup></sup><sub></sub>b</p>")
    assert parser.parse_inline_annotations(el) == ["ab"]


def test_parse_inline_annotations_br_dropped_and_transparent_tags(parser):
    """``br`` is dropped; ``a``/``span`` pass their content through."""
    el = _tag('<p>a<br/><a href="x">b</a><span>c</span></p>')
    assert parser.parse_inline_annotations(el) == ["abc"]


def test_parse_inline_annotations_green_font_page_marker(parser):
    """Green ``<font>`` text with ``p. 12`` becomes a page milestone."""
    el = _tag('<p>before <font color="Green">p. 12</font> after</p>')
    parts = parser.parse_inline_annotations(el)
    assert parts[0] == "before "
    assert isinstance(parts[1], pyosis.MilestoneCt) and parts[1].n == "12"
    assert parts[2] == " after"


def test_parse_inline_annotations_nested_formatting(parser):
    """Nested formatting nests ``hi`` elements."""
    el = _tag("<p><b><i>x</i></b></p>")
    (outer,) = parser.parse_inline_annotations(el)
    assert outer.type_value == pyosis.OsisHi.BOLD
    assert outer.content[0].type_value == pyosis.OsisHi.ITALIC


@given(
    st.text(
        alphabet=st.characters(blacklist_characters="<>&", blacklist_categories=["Cs", "Cc"]),
        min_size=1,
    )
)
def test_parse_inline_annotations_preserves_plain_text(text):
    """Text without markup survives, except whitespace-only input which is dropped."""
    parser = FBEParser(delay=0)
    try:
        el = BeautifulSoup(f"<p>{text}</p>", "html.parser").find("p")
        out = parser._extract_text(parser.parse_inline_annotations(el))
        assert out == (text if text.strip() else "")
    finally:
        parser.close()


# --- extract_chapter_number -----------------------------------------------------------


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("CHAP. I.", 1),
        ("CHAP. II", 2),
        ("chap. xiv.", 14),
        ("  CHAP. XLIX.  ", 49),
        ("ODE 1.", 1),
        ("ode 42", 42),
        ("XVII", 17),
        ("iv.", 4),
        ("12", 12),
        ("7.", 7),
        ("Introduction", None),
        ("", None),
        ("CHAP. 5", None),
    ],
)
def test_extract_chapter_number_formats(parser, heading, expected):
    """Every documented heading form is parsed; others return None."""
    assert parser.extract_chapter_number(heading) == expected


@given(st.integers(min_value=1, max_value=3999))
def test_extract_chapter_number_roman_roundtrip(n):
    """``CHAP. <roman>.`` headings round-trip through the shared converter."""
    parser = FBEParser(delay=0)
    try:
        assert parser.extract_chapter_number(f"CHAP. {_osis.int_to_roman(n)}.") == n
    finally:
        parser.close()


def test_extract_chapter_number_zero_roman_value_is_ignored(parser, monkeypatch):
    """A bare Roman numeral evaluating to 0 falls through to None."""
    monkeypatch.setattr(_osis, "roman_to_int", lambda s: 0)
    assert parser.extract_chapter_number("V") is None


def test_extract_chapter_number_swallows_converter_errors(parser, monkeypatch):
    """An exception from the converter on a bare numeral is swallowed."""

    def boom(_s):
        """Raise unconditionally."""
        raise ValueError

    monkeypatch.setattr(_osis, "roman_to_int", boom)
    assert parser.extract_chapter_number("V") is None


def test_roman_to_int_wrapper_removed():
    """The package has a single converter, in ``_osis``; no wrapper on the parser."""
    assert not hasattr(FBEParser, "roman_to_int")


# --- _parse_verse_content / strip helpers / _build_verse ------------------------------


def test_parse_verse_content_prose(parser):
    """A prose paragraph yields text and parts without poetry."""
    vc = parser._parse_verse_content(_tag("<p>1 In the <i>beginning</i> </p>"))
    assert vc.text == "1 In the beginning"
    assert vc.has_poetry is False and vc.poetry_lines is None
    assert isinstance(vc.content_parts[1], pyosis.HiCt)


def test_parse_verse_content_poetry_lines(parser):
    """``<br>`` splits the paragraph into stripped lines; nav and blank chunks are dropped."""
    vc = parser._parse_verse_content(
        _tag("<p>1 line one<br/>  line two<br/><br/>Next: foo<br/>line three</p>")
    )
    assert vc.has_poetry is True
    assert [_text(line) for line in vc.poetry_lines] == [
        "1 line one",
        "line two",
        "line three",
    ]


def test_parse_verse_content_br_only_has_no_poetry_lines(parser):
    """A paragraph with only ``<br>`` flags poetry but has no lines."""
    vc = parser._parse_verse_content(_tag("<p><br/></p>"))
    assert vc.has_poetry is True and vc.poetry_lines is None


def test_strip_leading_whitespace():
    """Only the first string is left-stripped; input is not mutated."""
    ms = pyosis.MilestoneCt(type_value="page", n="1")
    src = ["  a ", "  b"]
    assert FBEParser._strip_leading_whitespace(src) == ["a ", "  b"]
    assert src[0] == "  a "
    assert FBEParser._strip_leading_whitespace([ms, " x"]) == [ms, " x"]
    assert FBEParser._strip_leading_whitespace([]) == []


@given(st.text())
def test_strip_leading_whitespace_idempotent(text):
    """Stripping twice equals stripping once."""
    once = FBEParser._strip_leading_whitespace([text])
    assert FBEParser._strip_leading_whitespace(once) == once


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ("12 text", "text"),
        ("12. text", "text"),
        ("12text", "12text"),
        ("no number", "no number"),
    ],
)
def test_strip_verse_number(src, expected):
    """A leading ``N `` or ``N. `` is removed from the first string."""
    assert FBEParser._strip_verse_number([src, "tail"]) == [expected, "tail"]


def test_strip_verse_number_empty_and_non_string_first():
    """Empty input gives ``[]``; a non-string first item is untouched."""
    ms = pyosis.MilestoneCt(type_value="page", n="1")
    assert FBEParser._strip_verse_number([]) == []
    assert FBEParser._strip_verse_number([ms, "1 x"]) == [ms, "1 x"]


def test_build_verse_prose_uses_parts(parser):
    """Prose verses keep their annotated parts."""
    vc = VerseContent(text="a b", content_parts=["a ", "b"])
    v = parser._build_verse("B.1.1", vc)
    assert v.osis_id == ["B.1.1"] and v.canonical is True
    assert v.content == ["a ", "b"]


def test_build_verse_falls_back_to_text(parser):
    """Without parts the plain text is used; canonical can be overridden."""
    v = parser._build_verse("B.1.1", VerseContent(text="t", content_parts=[]), canonical=False)
    assert v.content == ["t"] and v.canonical is False


def test_build_verse_poetry_makes_linegroup(parser):
    """Poetry verses become a line group with one ``<l>`` per line."""
    vc = VerseContent(
        text="a b", content_parts=["a b"], has_poetry=True, poetry_lines=[["a"], ["b"]]
    )
    (lg,) = parser._build_verse("B.1.1", vc).content
    assert isinstance(lg, pyosis.LgCt) and len(lg.l) == 2


def test_build_verse_poetry_flag_without_lines_is_prose(parser):
    """has_poetry with no lines falls back to prose content."""
    vc = VerseContent(text="a", content_parts=["a"], has_poetry=True, poetry_lines=None)
    assert parser._build_verse("B.1.1", vc).content == ["a"]


# --- _skip_paragraph ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("<p>   </p>", True),
        ("<p>Next: chapter</p>", True),
        ('<p><a name="page_3"></a></p>', True),
        ("<p>Real text</p>", False),
        ("<p><br/>Click to enlarge<br/>THE FIRST SUNRISE<br/></p>", True),
        (
            '<p><span><a href="img/1.jpg"><img src="tn/1.jpg"/><br/><font>Click to enlarge'
            "</font></a><br/>PLATE</span></p>",
            True,
        ),
    ],
)
def test_skip_paragraph(parser, html, expected):
    """Empty, navigation and page-anchor paragraphs are skipped."""
    assert parser._skip_paragraph(_tag(html)) is expected


# --- intro helpers --------------------------------------------------------------------

INTRO = _page(
    "<h1>THE BOOK</h1><h2>ALSO CALLED</h2><h3>THE SECRETS OF ENOCH.</h3>"
    "<h3>THE BOOK</h3><h4>Next: foo</h4><h4></h4>"
    "<p>Next: skip</p><p>First para <i>it</i></p><h5>LATE</h5><p>Second</p>"
)


def test_extract_intro_headings_stops_at_first_paragraph(parser):
    """Headings before the first real paragraph are returned, deduplicated, nav removed."""
    assert parser._extract_intro_headings(INTRO) == [
        "THE BOOK",
        "ALSO CALLED",
        "THE SECRETS OF ENOCH.",
    ]


def test_extract_intro_headings_without_body_tag(parser):
    """HTML fragments without ``<body>`` are searched from the root."""
    assert parser._extract_intro_headings("<h1>A</h1><p>x</p>") == ["A"]


def test_extract_intro_subtitle_after_also_called(parser):
    """The heading after ``ALSO CALLED`` is the subtitle, minus its trailing period."""
    assert parser._extract_intro_subtitle(INTRO) == "THE SECRETS OF ENOCH"


@pytest.mark.parametrize(
    "html",
    [
        "<h1>X</h1><p>t</p>",
        "<h1>ALSO CALLED</h1><p>t</p>",
    ],
)
def test_extract_intro_subtitle_none(parser, html):
    """No ``ALSO CALLED`` heading, or none following it, gives None."""
    assert parser._extract_intro_subtitle(html) is None


def test_parse_intro_page_default_emits_heads_and_paragraphs(parser):
    """By default headings become ``<head>`` and paragraphs ``<p>``."""
    html = _page(
        "<h1>HEAD</h1><p>Text <b>b</b></p>"
        '<p><font color="green">p. 5</font></p><p><a name="page_5"></a></p><p>Next: x</p><p></p>'
    )
    els = parser._parse_intro_page(html)
    assert isinstance(els[0], pyosis.HeadCt) and els[0].content == ["HEAD"]
    assert isinstance(els[1], pyosis.PCt)
    assert isinstance(els[2], pyosis.MilestoneCt) and els[2].n == "5"
    assert len(els) == 3


def test_parse_intro_page_overrides_and_subtitles(parser):
    """Overrides come first, then heading subtitles; headings can be suppressed."""
    html = _page("<h1>A</h1><h2>B</h2><p>x</p>")
    els = parser._parse_intro_page(
        html,
        title_override="Intro",
        subtitle_override="Sub",
        headings_as_subtitles=True,
        include_headings=False,
    )
    kinds = [(e.type_value, _text(e.content)) for e in els[:4]]
    assert kinds == [
        (pyosis.OsisTitles.MAIN, "Intro"),
        (pyosis.OsisTitles.SUB, "Sub"),
        (pyosis.OsisTitles.SUB, "A"),
        (pyosis.OsisTitles.SUB, "B"),
    ]
    assert isinstance(els[4], pyosis.PCt) and len(els) == 5


def test_parse_intro_page_skips_paragraphs_without_parts(parser):
    """A paragraph with only an empty ``<i>`` yields no element."""
    assert parser._parse_intro_page("<p><i>x</i></p>") != []
    assert parser._parse_intro_page("<p><i>  </i>\u00a0</p>") == []


def test_build_intro_div_wraps_elements(parser):
    """The intro div is non-canonical and carries the parsed elements."""
    div = parser._build_intro_div(_page("<h1>H</h1><p>x</p>"), title_override="Introduction")
    assert div.type_value == pyosis.OsisDivs.INTRODUCTION and div.canonical is False
    assert isinstance(div.content[0], pyosis.TitleCt)
    assert isinstance(div.content[-1], pyosis.PCt)


# --- _parse_chapter_page --------------------------------------------------------------


def test_parse_chapter_page_numbered_verses_and_summary(parser):
    """Numbered paragraphs are verses; the italic block after ``<h3>`` is the summary."""
    html = _page(
        "<h3>CHAP. IV.</h3><i><p>Summary here.</p></i><p>1 First verse.</p><p>2. Second verse.</p>"
    )
    div = parser._parse_chapter_page(html, "Bk", 4)
    assert div.osis_id == ["Bk.4"] and div.type_value == pyosis.OsisDivs.CHAPTER
    summary = div.content[0]
    assert summary.type_value == pyosis.OsisDivs.SUMMARY and summary.canonical is False
    assert _text(summary.content[0].content) == "Summary here."
    verses = _verses(div)
    assert [v.osis_id[0] for v in verses] == ["Bk.4.1", "Bk.4.2"]
    assert verses[0].content == ["First verse."]
    assert verses[1].content == ["Second verse."]


def test_parse_chapter_page_inline_italic_summary(parser):
    """An ``<em>`` without inner ``<p>`` is also a summary."""
    html = _page("<h3>I</h3><em>Short summary</em><p>1 v</p>")
    div = parser._parse_chapter_page(html, "Bk", 1)
    assert div.content[0].type_value == pyosis.OsisDivs.SUMMARY
    assert len(_verses(div)) == 1


def test_parse_chapter_page_summary_skips_navigable_siblings(parser):
    """Text nodes between ``<h3>`` and the italic are skipped when locating it."""
    html = "<h3>I</h3>\n<i><p>S</p></i>\n<p>1 v</p>"
    div = parser._parse_chapter_page(html, "Bk", 1)
    assert div.content[0].type_value == pyosis.OsisDivs.SUMMARY


def test_parse_chapter_page_quoted_italic_paragraph_is_summary(parser):
    """``<p>"<i>summary</i>."</p>`` after the ``<h3>`` is a summary, not part of verse 1."""
    html = _page(
        '<h3>CHAP. XIII.</h3> <p>"<i>Among the children of Cain</i>."</p> '
        "<p>IN those days lived Lamech.</p> <p>2 But Lamech</p>"
    )
    div = parser._parse_chapter_page(html, "Bk", 13)
    summary = div.content[0]
    assert summary.type_value == pyosis.OsisDivs.SUMMARY
    assert summary.content[0].content == ['"Among the children of Cain."']
    v1, v2 = _verses(div)
    assert v1.content == ["IN those days lived Lamech."]
    assert v2.osis_id == ["Bk.13.2"]


@pytest.mark.parametrize(
    "first",
    [
        '"<i>Quoted</i> and more text."',
        "<i>a</i> <b>b</b>",
        "Plain opening line.",
    ],
)
def test_parse_chapter_page_paragraph_with_more_than_quoted_italic_is_verse(parser, first):
    """A first paragraph with text or tags beyond one quoted italic stays verse 1."""
    div = parser._parse_chapter_page(_chapter("I", first, "2 Two"), "Bk", 1)
    assert not any(isinstance(c, pyosis.DivCt) for c in div.content)
    assert [v.osis_id[0] for v in _verses(div)] == ["Bk.1.1", "Bk.1.2"]


def test_parse_chapter_page_image_caption_does_not_replace_verse(parser):
    """An illustration caption after a verse is dropped instead of becoming its text."""
    html = _page(
        "<h3>CHAP. XIV.</h3><p>WHEN Enos was old.</p><p>2 He then prayed over them.</p>"
        "<p> </p> <a></a> <img/><p><br/>Click to enlarge<br/>FACSIMILE.<br/> Gutenberg.<br/></p>"
        "<img/><p><br/>Click to enlarge<br/>THE FIRST SUNRISE<br/></p><p>3 Then Enos</p>"
    )
    div = parser._parse_chapter_page(html, "Bk", 14)
    v1, v2, v3 = _verses(div)
    assert v2.content == ["He then prayed over them."]
    assert v3.content == ["Then Enos"]


def test_parse_odes_chapter_page_quoted_italic_summary(parser):
    """The Odes parser recognises the quoted-italic summary and emits no duplicate verse 1."""
    html = _page('<h3>ODE 35.</h3><p>"<i>No cradled child</i>."</p><p>1 The dew<br/>2 And</p>')
    div = parser._parse_odes_chapter_page(html, "Odes", 35)
    assert div.content[0].type_value == pyosis.OsisDivs.SUMMARY
    assert [v.osis_id[0] for v in _verses(div)] == ["Odes.35.1", "Odes.35.2"]


def test_parse_chapter_page_unnumbered_first_paragraph_is_verse_one(parser):
    """An un-numbered first paragraph is verse 1; later ones continue it with a space."""
    div = parser._parse_chapter_page(_chapter("I", "Alpha", "Beta"), "Bk", 1)
    (v,) = _verses(div)
    assert v.osis_id == ["Bk.1.1"]
    assert _text(v.content) == "Alpha Beta"


def test_parse_chapter_page_continuation_after_numbered_verse(parser):
    """Un-numbered paragraphs after a numbered verse extend it."""
    div = parser._parse_chapter_page(_chapter("I", "1 One", "more", "2 Two"), "Bk", 1)
    v1, v2 = _verses(div)
    assert _text(v1.content) == "One more" and _text(v2.content) == "Two"


def test_parse_chapter_page_poetry_verses(parser):
    """``<br>`` lines in numbered, first and continuation paragraphs build line groups."""
    html = _page(
        "<h3>I</h3><p>1 a1<br/>a2</p><p>b1<br/>b2</p><p>2 c1<br/>c2</p><p><br/></p><p>3 d<br/></p>"
    )
    div = parser._parse_chapter_page(html, "Bk", 1)
    v1, v2, v3 = _verses(div)
    (lg1,) = v1.content
    assert [_text(line.content) for line in lg1.l] == ["a1", "a2", "b1", "b2"]
    assert [_text(line.content) for line in v2.content[0].l] == ["c1", "c2"]
    assert v3.osis_id == ["Bk.1.3"]


def test_parse_chapter_page_first_unnumbered_poetry(parser):
    """A poetic first paragraph without number becomes verse 1 as a line group."""
    div = parser._parse_chapter_page(_chapter("I", "x<br/>y"), "Bk", 1)
    (v,) = _verses(div)
    assert [_text(line.content) for line in v.content[0].l] == ["x", "y"]


def test_parse_chapter_page_skips_pre_h3_italic_subtitle(parser):
    """An italic paragraph before the ``<h3>`` (testament subtitle) is not a verse."""
    html = _page("<h1>TESTAMENT</h1><i><p>The First-Born Son.</p></i><h3>I</h3><p>1 v</p>")
    div = parser._parse_chapter_page(html, "Bk", 1)
    assert [v.osis_id[0] for v in _verses(div)] == ["Bk.1.1"]
    assert all(
        not (isinstance(c, pyosis.DivCt) and c.type_value == pyosis.OsisDivs.SUMMARY)
        for c in div.content
    )


def test_parse_chapter_page_without_h3_or_body(parser):
    """Fragments without ``<body>``/``<h3>`` still parse; nav and page anchors are skipped."""
    div = parser._parse_chapter_page(
        '<p>1 a</p><p><a name="page_1"></a></p><p>Next: z</p>', "Bk", 2
    )
    assert [v.osis_id[0] for v in _verses(div)] == ["Bk.2.1"]


def test_parse_chapter_page_empty_gives_empty_chapter(parser):
    """A page with no paragraphs gives a chapter with no content."""
    div = parser._parse_chapter_page("<h3>I</h3>", "Bk", 1)
    assert div.content == []


def test_parse_chapter_page_page_marker_milestone_in_verse(parser):
    """Green page markers inside a verse become milestones."""
    html = _chapter("I", '1 before <font color="green">p. 9</font> after')
    (v,) = _verses(parser._parse_chapter_page(html, "Bk", 1))
    assert any(isinstance(c, pyosis.MilestoneCt) for c in v.content)


# --- Odes -----------------------------------------------------------------------------


def test_parse_odes_chapter_page_splits_verses_on_br(parser):
    """One ``<p>`` with ``<br>``-separated numbered lines becomes several verses."""
    html = _page(
        "<h3>ODE 1.</h3><i><p>Motto</p></i>"
        "<p>1 First line<br/>continuing<br/>2 Second<br/>  <br/>3 Third</p>"
    )
    div = parser._parse_odes_chapter_page(html, "Odes", 1)
    assert div.content[0].type_value == pyosis.OsisDivs.SUMMARY
    v1, v2, v3 = _verses(div)
    assert [v.osis_id[0] for v in (v1, v2, v3)] == ["Odes.1.1", "Odes.1.2", "Odes.1.3"]
    assert [_text(line.content) for line in v1.content[0].l] == ["First line", "continuing"]
    assert v2.content == ["Second"] and v3.content == ["Third"]


def test_parse_odes_chapter_page_unnumbered_first_line_is_verse_one(parser):
    """Text before any verse number is treated as verse 1."""
    html = _page("<h3>ODE 2.</h3><em>Inline summary</em><p>Opening<br/>2 Next</p>")
    div = parser._parse_odes_chapter_page(html, "Odes", 2)
    v1, v2 = _verses(div)
    assert v1.osis_id == ["Odes.2.1"] and v1.content == ["Opening"]
    assert v2.osis_id == ["Odes.2.2"]
    assert div.content[0].type_value == pyosis.OsisDivs.SUMMARY


def test_parse_odes_chapter_page_blank_summary_not_emitted(parser):
    """A blank italic block after the heading does not create a summary."""
    html = _page("<h3>ODE 2.</h3><i><p> </p></i><p>1 v</p>")
    div = parser._parse_odes_chapter_page(html, "Odes", 2)
    assert [type(c) for c in div.content] == [pyosis.VerseCt]


def test_parse_odes_chapter_page_falls_back_when_no_verses(parser):
    """A page with no content falls back to the standard chapter parser."""
    div = parser._parse_odes_chapter_page("<h3>ODE 3.</h3>", "Odes", 3)
    assert div.osis_id == ["Odes.3"] and div.content == []


def test_parse_odes_chapter_page_without_h3(parser):
    """Pages lacking an ``<h3>`` are still split into verses."""
    div = parser._parse_odes_chapter_page("<p>1 a<br/>2 b</p><p>Next: z</p>", "Odes", 1)
    assert len(_verses(div)) == 2


# --- Psalms ---------------------------------------------------------------------------


def test_parse_psalms_chapter_page_single_linegroup(parser):
    """Poetry lines from all paragraphs make one verse containing a line group."""
    html = _page("<h3>I</h3><p>line a<br/>line b</p><p>prose para</p><p>x<br/> <br/>y</p>")
    div = parser._parse_psalms_chapter_page(html, "Ps", 1)
    (v,) = _verses(div)
    assert v.osis_id == ["Ps.1.1"]
    assert [_text(line.content) for line in v.content[0].l] == [
        "line a",
        "line b",
        "prose para",
        "x",
        "y",
    ]


def test_parse_psalms_chapter_page_italic_motto_summary(parser):
    """An italic motto after the ``<h3>`` becomes the summary, not a line."""
    html = _page("<h3>II</h3><i><p>Motto</p></i><p>a<br/>b</p>")
    div = parser._parse_psalms_chapter_page(html, "Ps", 2)
    assert div.content[0].type_value == pyosis.OsisDivs.SUMMARY
    assert len(_verses(div)[0].content[0].l) == 2


def test_parse_psalms_chapter_page_inline_italic_motto(parser):
    """An ``<i>`` without a ``<p>`` is also a motto."""
    html = _page("<h3>II</h3><i>Quoted</i><p>a<br/>b</p>")
    div = parser._parse_psalms_chapter_page(html, "Ps", 2)
    assert div.content[0].type_value == pyosis.OsisDivs.SUMMARY


def test_parse_psalms_chapter_page_blank_italic_motto_ignored(parser):
    """A blank italic block yields no summary."""
    html = _page("<h3>II</h3><i> </i><p>a<br/>b</p>")
    div = parser._parse_psalms_chapter_page(html, "Ps", 2)
    assert all(isinstance(c, pyosis.VerseCt) for c in div.content)


def test_parse_psalms_chapter_page_quoted_plain_paragraph_motto(parser):
    """A plain ``<p>`` after the ``<h3>`` that starts with a quote mark is a summary."""
    for quote in ('"', "“"):
        html = _page(f"<h3>III</h3><p>{quote}Motto text</p><p>a<br/>b</p>")
        div = parser._parse_psalms_chapter_page(html, "Ps", 3)
        assert div.content[0].type_value == pyosis.OsisDivs.SUMMARY


def test_parse_psalms_chapter_page_unquoted_following_paragraph_is_text(parser):
    """A plain unquoted ``<p>`` after the ``<h3>`` is part of the psalm."""
    html = _page("<h3>III</h3><p>Plain</p><p>a<br/>b</p>")
    div = parser._parse_psalms_chapter_page(html, "Ps", 3)
    (v,) = _verses(div)
    assert len(v.content[0].l) == 3


def test_parse_psalms_chapter_page_numbered_paragraph_falls_back(parser):
    """A numbered non-poetry paragraph triggers the standard chapter parser."""
    html = _page("<h3>IV</h3><p>1 numbered</p>")
    div = parser._parse_psalms_chapter_page(html, "Ps", 4)
    assert _verses(div)[0].content == ["numbered"]


def test_parse_psalms_chapter_page_empty(parser):
    """No lines gives a chapter div with no verse."""
    div = parser._parse_psalms_chapter_page("<h3>V</h3>", "Ps", 5)
    assert div.content == [] and div.osis_id == ["Ps.5"]


def test_parse_psalms_chapter_page_without_h3(parser):
    """Pages without ``<h3>`` still gather lines."""
    div = parser._parse_psalms_chapter_page("<p>a<br/>b</p>", "Ps", 1)
    assert len(_verses(div)) == 1


# --- _detect_chapter_number / _extract_pre_h3_italic ----------------------------------


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("<h3>CHAP. XII.</h3>", 12),
        ("<h3>ODE 7.</h3>", 7),
        ("<h3>Foreword</h3>", 99),
        ("<p>no heading</p>", 99),
    ],
)
def test_detect_chapter_number(parser, html, expected):
    """The ``<h3>`` heading wins, otherwise the fallback is used."""
    assert parser._detect_chapter_number(html, 99) == expected


def test_extract_pre_h3_italic_with_inner_paragraph(parser):
    """An italic block holding a ``<p>`` before the ``<h3>`` is returned without its period."""
    html = "<h1>T</h1><i><p>The First-Born Son of Jacob.</p></i><h3>I</h3>"
    assert parser._extract_pre_h3_italic(html) == "The First-Born Son of Jacob"


def test_extract_pre_h3_italic_plain_italic(parser):
    """A bare ``<em>`` works too."""
    assert parser._extract_pre_h3_italic("<em>Sub.</em><h3>I</h3>") == "Sub"


def test_extract_pre_h3_italic_none_cases(parser):
    """No ``<h3>``, no italic, or only blank italics give None."""
    assert parser._extract_pre_h3_italic("<i>x</i>") is None
    assert parser._extract_pre_h3_italic("<h3>I</h3><p>x</p>") is None
    assert parser._extract_pre_h3_italic("<i> </i><h3>I</h3>") is None


# --- book / testament builders --------------------------------------------------------


def _mini_work(**kw) -> WorkDef:
    """Build a one-intro, two-chapter work definition."""
    base = {
        "osis_id": "Bk",
        "title": "The Book",
        "short": "Bk",
        "intro_pages": [1],
        "chapter_pages": [2, 3],
    }
    base.update(kw)
    return WorkDef(**base)


def test_build_book_div_generic_work(parser):
    """A work yields title, subtitle, intro div and chapter divs with detected numbers."""
    pages = {
        1: _page("<h1>THE BOOK</h1><h2>ALSO CALLED</h2><h2>THE OTHER.</h2><p>Intro</p>"),
        2: _chapter("CHAP. I.", "1 a"),
        3: _chapter("nonsense", "1 b"),
    }
    div = parser._build_book_div(_mini_work(intro_title="Introduction"), pages)
    assert div.osis_id == ["Bk"] and div.type_value == pyosis.OsisDivs.BOOK
    title, sub, intro, ch1, ch2 = div.content
    assert title.short == "Bk" and title.content == ["The Book"]
    assert sub.type_value == pyosis.OsisTitles.SUB and sub.content == ["THE OTHER"]
    assert intro.type_value == pyosis.OsisDivs.INTRODUCTION
    assert ch1.osis_id == ["Bk.1"] and ch2.osis_id == ["Bk.2"]


def test_build_book_div_without_intro_pages(parser):
    """No intro pages means no subtitle or intro div."""
    pages = {2: _chapter("I", "1 a")}
    div = parser._build_book_div(_mini_work(intro_pages=[], chapter_pages=[2]), pages)
    assert len(div.content) == 2


def test_build_book_div_intro_options_forwarded(parser):
    """intro_title/subtitle/headings flags reach the intro parser."""
    pages = {1: _page("<h1>H</h1><p>x</p>"), 2: _chapter("I", "1 a")}
    work = _mini_work(
        chapter_pages=[2],
        intro_title="Intro",
        intro_subtitle="Sub",
        intro_headings_as_subtitles=True,
    )
    intro = parser._build_book_div(work, pages).content[1]
    texts = [_text(e.content) for e in intro.content if isinstance(e, pyosis.TitleCt)]
    assert texts == ["Intro", "Sub", "H"]
    assert not any(isinstance(e, pyosis.HeadCt) for e in intro.content)
    work2 = _mini_work(chapter_pages=[2])
    intro2 = parser._build_book_div(work2, pages).content[1]
    assert any(isinstance(e, pyosis.HeadCt) for e in intro2.content)


def test_build_book_div_psalms_use_psalm_parser(parser):
    """Psalms of Solomon chapters become a single linegroup verse."""
    pages = {2: _page("<h3>I</h3><p>a<br/>b</p>")}
    work = _mini_work(osis_id="psalms-of-solomon", intro_pages=[], chapter_pages=[2])
    ch = parser._build_book_div(work, pages).content[1]
    (v,) = _verses(ch)
    assert isinstance(v.content[0], pyosis.LgCt)


def test_build_book_div_odes_use_odes_parser(parser):
    """Odes of Solomon chapters are split into numbered verses on ``<br>``."""
    pages = {2: _page("<h3>ODE 5.</h3><p>1 a<br/>2 b</p>")}
    work = _mini_work(osis_id="odes-of-solomon", intro_pages=[], chapter_pages=[2])
    ch = parser._build_book_div(work, pages).content[1]
    assert ch.osis_id == ["odes-of-solomon.5"] and len(_verses(ch)) == 2


def test_build_book_div_missing_page_raises_keyerror(parser):
    """A page absent from the mapping propagates a KeyError."""
    with pytest.raises(KeyError):
        parser._build_book_div(_mini_work(), {})


def _testament_pages() -> dict[int, str]:
    """Build page HTML for every page the Testaments builder needs."""
    pages = {266: _page("<h1>INTRO</h1><p>Intro text</p>")}
    for t in fbe.TESTAMENTS:
        for n, pg in enumerate(t.chapter_pages, 1):
            sub = "<i><p>The Subtitle.</p></i>" if n == 1 and t.osis_id.endswith("TReu") else ""
            pages[pg] = _page(f"{sub}<h3>CHAP. {_osis.int_to_roman(n)}.</h3><p>1 verse</p>")
    return pages


def test_build_testaments_div_structure(parser):
    """The parent book holds an intro and twelve sub-books with subtitles and chapters."""
    div = parser._build_testaments_div(_testament_pages())
    assert div.osis_id == ["T12Patr"]
    title, intro, *subs = div.content
    assert title.short == "Testaments of the Twelve Patriarchs"
    assert intro.type_value == pyosis.OsisDivs.INTRODUCTION
    assert [s.osis_id[0] for s in subs] == [t.osis_id for t in fbe.TESTAMENTS]
    reuben = subs[0]
    assert reuben.content[1].type_value == pyosis.OsisTitles.SUB
    assert reuben.content[1].content == ["The Subtitle"]
    assert reuben.content[2].osis_id == ["T12Patr.TReu.1"]
    assert reuben.content[3].osis_id == ["T12Patr.TReu.2"]
    # Testaments without a subtitle go straight from title to chapters.
    assert subs[1].content[1].osis_id == ["T12Patr.TSim.1"]


def test_build_testaments_div_testament_without_pages(parser, monkeypatch):
    """A testament with no chapter pages produces a title-only sub-book."""
    monkeypatch.setattr(fbe, "TESTAMENTS", [fbe.TestamentDef("T12Patr.TX", "T", "T", [])])
    div = parser._build_testaments_div({266: _page("<p>x</p>")})
    assert len(div.content[2].content) == 1


# --- header / build_osis_* ------------------------------------------------------------


def test_build_header_contents():
    """The header names the work, editor, publisher and a timestamped revision."""
    h = FBEParser._build_header("wid", "Title", "Desc")
    assert h.canonical is False
    work = h.work[0]
    assert work.osis_work == "wid" and work.title[0].content == ["Title"]
    assert work.description[0].value == "Desc"
    assert work.creator[0].value == "Rutherford H. Platt, Jr."
    assert work.publisher[0].value == "Alpha House, Inc."
    stamp = h.revision_desc[0].date.content[0]
    assert len(stamp) == 19 and stamp[4] == "." and stamp[10] == "T"
    assert h.revision_desc[1].date.content == ["1926"]


def test_build_osis_for_work(parser):
    """A single-work document has one book and the work's identifiers."""
    pages = {2: _chapter("I", "1 a")}
    work = _mini_work(intro_pages=[], chapter_pages=[2], short="Short")
    xml = _xml(parser.build_osis_for_work(work, pages))
    assert 'osisIDWork="Bk"' in xml and 'osisRefWork="Short"' in xml
    assert 'osisID="Bk.1.1"' in xml and "Text from" in xml


def test_build_osis_for_adam_and_eve(parser):
    """The combined document holds both Adam and Eve books."""
    pages = {}
    for w in fbe.WORKS:
        if w.osis_id in fbe.ADAM_EVE_WORK_IDS:
            for pg in w.intro_pages:
                pages[pg] = _page("<p>intro</p>")
            for pg in w.chapter_pages:
                pages[pg] = _page("<h3>I</h3><p>1 x</p>")
    xml = _xml(parser.build_osis_for_adam_and_eve(pages))
    assert 'osisIDWork="adam-and-eve"' in xml and 'osisRefWork="Adam and Eve"' in xml
    assert 'osisID="1-adam-and-eve"' in xml and 'osisID="2-adam-and-eve"' in xml


def test_build_osis_for_testaments(parser):
    """The testaments document wraps the T12Patr book."""
    xml = _xml(parser.build_osis_for_testaments(_testament_pages()))
    assert (
        'osisIDWork="T12Patr"' in xml and 'osisRefWork="Testaments of the Twelve Patriarchs"' in xml
    )
    assert 'osisID="T12Patr.TBenj"' in xml


# --- process_all / run / add_arguments / SPEC -----------------------------------------


def _all_pages() -> dict[int, str]:
    """Build a minimal valid page for every page number the scraper needs."""
    pages: dict[int, str] = {}
    for w in fbe.WORKS:
        for pg in w.intro_pages:
            pages[pg] = _page("<h1>H</h1><p>intro</p>")
        for pg in w.chapter_pages:
            pages[pg] = _page("<h3>I</h3><p>1 verse<br/>2 more</p>")
    pages.update(_testament_pages())
    return pages


@pytest.fixture
def fake_pages(parser, monkeypatch):
    """Make ``fetch_page`` serve ``_all_pages()`` and record requested page numbers."""
    pages = _all_pages()
    requested: list[int] = []

    def fetch(n, retry_count=3):
        """Return canned page HTML or raise for pages marked missing."""
        requested.append(n)
        if n not in pages:
            raise RuntimeError(f"boom {n}")
        return pages[n]

    monkeypatch.setattr(parser, "fetch_page", fetch)
    return pages, requested


def test_process_all_writes_every_output(parser, fake_pages, tmp_path):
    """All eight documents are written when every page is available."""
    parser.process_all(output_dir=str(tmp_path / "out"))
    assert sorted(p.name for p in (tmp_path / "out").glob("*.xml")) == sorted(fbe.OUTPUT_FILENAMES)
    assert "T12Patr" in (tmp_path / "out" / "testaments-twelve-patriarchs.xml").read_text("utf-8")


def test_process_all_respects_page_range(parser, fake_pages, tmp_path, caplog):
    """Only pages in range are fetched; works with missing pages are skipped with a warning."""
    _, requested = fake_pages
    with caplog.at_level(logging.WARNING, logger=fbe.LOGGER.name):
        parser.process_all(output_dir=str(tmp_path), start_page=176, end_page=194)
    assert min(requested) == 176 and max(requested) == 194
    assert [p.name for p in tmp_path.glob("*.xml")] == ["psalms-of-solomon.xml"]
    assert "Skipping adam-and-eve" in caplog.text
    assert "Skipping testaments" in caplog.text
    assert "Skipping 2En" in caplog.text


def test_process_all_logs_fetch_failures(parser, fake_pages, tmp_path, caplog):
    """A page that fails to fetch is logged and its work skipped."""
    pages, _ = fake_pages
    del pages[250]
    with caplog.at_level(logging.ERROR, logger=fbe.LOGGER.name):
        parser.process_all(output_dir=str(tmp_path))
    assert "Failed to fetch page 250" in caplog.text
    assert not (tmp_path / "4-maccabees.xml").exists()
    assert (tmp_path / "2-enoch.xml").exists()


def test_process_all_logs_build_errors_and_continues(
    parser, fake_pages, tmp_path, caplog, monkeypatch
):
    """An exception while building one document is logged and others still get written."""

    def boom(*_a, **_k):
        """Raise unconditionally."""
        raise RuntimeError("bad build")

    monkeypatch.setattr(parser, "build_osis_for_adam_and_eve", boom)
    monkeypatch.setattr(parser, "build_osis_for_testaments", boom)
    original = parser.build_osis_for_work

    def selective(work, pages):
        """Fail for Enoch only."""
        if work.osis_id == "2En":
            raise RuntimeError("bad enoch")
        return original(work, pages)

    monkeypatch.setattr(parser, "build_osis_for_work", selective)
    with caplog.at_level(logging.ERROR, logger=fbe.LOGGER.name):
        parser.process_all(output_dir=str(tmp_path))
    assert "Error generating adam-and-eve" in caplog.text
    assert "Error generating 2-enoch" in caplog.text
    assert "Error generating testaments" in caplog.text
    assert (tmp_path / "psalms-of-solomon.xml").exists()
    assert not (tmp_path / "2-enoch.xml").exists()


def test_add_arguments_defaults_and_overrides():
    """--start-page/--end-page default to FILE_RANGE and parse as ints."""
    ap = argparse.ArgumentParser()
    fbe.add_arguments(ap)
    ns = ap.parse_args([])
    assert (ns.start_page, ns.end_page) == fbe.FILE_RANGE
    ns = ap.parse_args(["--start-page", "5", "--end-page", "9"])
    assert (ns.start_page, ns.end_page) == (5, 9)


def test_run_uses_prepopulated_cache_and_reports_outputs(tmp_path, monkeypatch):
    """Run reads pages from a cache directory and returns the files it produced."""
    cache = tmp_path / "cache"
    pages = _all_pages()
    for n, html in pages.items():
        path = cache / "sacred-texts.com" / "bib" / "fbe" / f"fbe{n:03d}.htm"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
    out = tmp_path / "out"
    result = fbe.run(
        argparse.Namespace(output_dir=out, cache_dir=cache, delay=0, start_page=0, end_page=295)
    )
    assert result == [out / name for name in fbe.OUTPUT_FILENAMES]
    assert all(p.exists() for p in result)


def test_run_closes_parser_and_returns_only_existing(tmp_path, monkeypatch):
    """Run closes the parser even on failure and lists only files that exist."""
    closed = []

    class Fake(FBEParser):
        """Parser double whose process_all writes one file or raises."""

        fail = False

        def process_all(self, output_dir, start_page, end_page):
            """Write a single output file, or raise when ``fail`` is set."""
            if Fake.fail:
                raise RuntimeError("x")
            (Path(output_dir) / "2-enoch.xml").write_text("x")

        def close(self):
            """Record that close was called."""
            closed.append(True)
            super().close()

    monkeypatch.setattr(fbe, "FBEParser", Fake)
    ns = argparse.Namespace(output_dir=tmp_path, cache_dir=None, delay=0, start_page=0, end_page=1)
    assert fbe.run(ns) == [tmp_path / "2-enoch.xml"]
    Fake.fail = True
    with pytest.raises(RuntimeError):
        fbe.run(ns)
    assert closed == [True, True]


def test_spec_is_wired_to_module():
    """SPEC names the scraper and points at run/add_arguments/OUTPUT_FILENAMES."""
    assert fbe.SPEC.name == "forgotten-books-of-eden"
    assert fbe.SPEC.run is fbe.run and fbe.SPEC.add_arguments is fbe.add_arguments
    assert fbe.SPEC.outputs == fbe.OUTPUT_FILENAMES
    assert fbe.SPEC.source == fbe.BASE_URL


# --- redesigned reader layout ---------------------------------------------------------

READER_FIXTURES = Path(__file__).parent / "fixtures" / "reader_layout"
"""Trimmed copies of real redesigned sacred-texts.com pages."""


def reader_fixture(name: str) -> str:
    """Return the text of a reader-layout fixture page."""
    return (READER_FIXTURES / name).read_text(encoding="utf-8")


def test_parse_chapter_page_reader_layout(parser):
    """A reader-layout chapter keeps its italic summary and numbered verses."""
    html = reader_fixture("fbe010.htm")
    assert parser._detect_chapter_number(html, 0) == 5
    div = parser._parse_chapter_page(html, "Bk", 5)
    summary = div.content[0]
    assert summary.type_value == pyosis.OsisDivs.SUMMARY
    assert _text(summary.content[0].content).startswith("In which Eve makes a noble")
    verses = _verses(div)
    assert [v.osis_id[0] for v in verses] == [f"Bk.5.{n}" for n in range(1, 15)]
    assert _text(verses[11].content).endswith(
        "while we dwell in it on account of our transgression."
    )


def test_parse_chapter_page_reader_layout_matches_old_layout(parser):
    """The reader-layout page and the equivalent old-layout markup parse identically."""
    old = _page(
        '<h3 align="CENTER">CHAP. V.</h3> <i>\n<p align="CENTER">In which Eve makes a noble '
        "and emotionable intercession, taking the blame on herself</i>.</p>"
        "<p>THEN Adam and Eve entered the cave, and stood praying, in their own tongue, "
        "unknown to us, but which they knew well.</p>"
    )
    new = reader_fixture("fbe010.htm")
    old_div = parser._parse_chapter_page(old, "Bk", 5)
    new_div = parser._parse_chapter_page(new, "Bk", 5)
    assert new_div.content[0] == old_div.content[0]
    assert _verses(new_div)[0] == _verses(old_div)[0]


def test_parse_chapter_page_reader_layout_italic_summary_is_a_summary(parser):
    """On a reader page a bare ``<em>`` after the heading is still the summary (no duplicate verse 1)."""
    html = (
        '<html><body><article data-slot="reader-content"><div data-slot="reader-prose">'
        '<div data-slot="ad-content"><h3>I</h3> <em>Short summary</em> <p>1 v</p></div>'
        "</div></article></body></html>"
    )
    div = parser._parse_chapter_page(html, "Bk", 1)
    assert div.content[0].type_value == pyosis.OsisDivs.SUMMARY
    assert [v.osis_id[0] for v in _verses(div)] == ["Bk.1.1"]
