"""Offline unit tests for every function and method in ``sacred_texts.enoch``.

HTML fixtures are minimal snippets that mimic the sacred-texts.com Book of Enoch pages
(``<h3>CHAPTER I.</h3>`` headings, ``<p>N. text</p>`` verses, ``<br>`` poetry lines,
green-font page markers and ``fn_``/``fr_`` footnote anchors). Nothing touches the network.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pyosis
import pytest
from bs4 import BeautifulSoup, NavigableString
from hypothesis import given
from hypothesis import strategies as st
from open_canon_site.scrapers import _osis
from open_canon_site.scrapers._http import CachedHttpFetcher
from open_canon_site.scrapers.base import ScraperSpec
from open_canon_site.scrapers.sacred_texts import enoch
from open_canon_site.scrapers.sacred_texts.enoch import (
    FootnoteInfo,
    SacredTextsParser,
    VerseContent,
)

WORD = st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=8)
"""Strategy for digit-free lowercase words."""


@pytest.fixture
def parser() -> SacredTextsParser:
    """Return an offline parser with the book division started."""
    p = SacredTextsParser(cache_dir=None, delay=0)
    p.start_book()
    return p


def _soup(html: str) -> BeautifulSoup:
    """Parse ``html`` with the same parser the scraper uses."""
    return BeautifulSoup(html, "html.parser")


def _p(html: str):
    """Return the first ``<p>`` tag in ``html``."""
    return _soup(html).find("p")


def _verses(parser: SacredTextsParser) -> dict[str, pyosis.VerseCt]:
    """Map osisID to verse element for the parser's current chapter."""
    assert parser.current_div is not None
    return {
        item.osis_id[0]: item
        for item in parser.current_div.content
        if isinstance(item, pyosis.VerseCt)
    }


def _text(parts) -> str:
    """Flatten inline parts to plain text."""
    return _osis.extract_plain_text(list(parts))


# --- module-level wiring ---------------------------------------------------------------


def test_spec_describes_enoch_scraper() -> None:
    """``SPEC`` names the scraper, its output file and wires ``run``/``add_arguments``."""
    assert isinstance(enoch.SPEC, ScraperSpec)
    assert enoch.SPEC.name == "1-enoch"
    assert enoch.SPEC.outputs == (enoch.OUTPUT_FILENAME,)
    assert enoch.SPEC.run is enoch.run
    assert enoch.SPEC.add_arguments is enoch.add_arguments


def test_roman_to_int_wrapper_removed() -> None:
    """The duplicate ``roman_to_int`` wrapper no longer exists on the parser."""
    assert not hasattr(SacredTextsParser, "roman_to_int")


def test_add_arguments_defaults_and_overrides() -> None:
    """``add_arguments`` registers page options with the module defaults."""
    ap = argparse.ArgumentParser()
    enoch.add_arguments(ap)
    defaults = ap.parse_args([])
    assert (defaults.start_page, defaults.end_page) == (0, 112)
    custom = ap.parse_args(["--start-page", "4", "--end-page", "6"])
    assert (custom.start_page, custom.end_page) == (4, 6)


# --- __init__ / close / fetch_page -----------------------------------------------------


def test_init_without_cache_dir_has_empty_state() -> None:
    """A parser built with no cache directory starts with no chapter, verse or footnotes."""
    p = SacredTextsParser(cache_dir=None, delay=0)
    assert p.cache_dir is None
    assert p.current_chapter is None and p.current_verse is None
    assert p.current_div is None and p.root_div is None
    assert p.chapters == [] and p.footnotes == {}
    assert isinstance(p.http, CachedHttpFetcher)
    p.close()


def test_init_creates_cache_dir(tmp_path: Path) -> None:
    """A cache directory is created when it does not exist."""
    target = tmp_path / "a" / "b"
    p = SacredTextsParser(cache_dir=str(target), delay=0)
    assert p.cache_dir == target and target.is_dir()
    p.close()


def test_close_closes_http_client(monkeypatch: pytest.MonkeyPatch, parser) -> None:
    """``close`` delegates to the fetcher's ``close``."""
    calls = []
    monkeypatch.setattr(parser.http, "close", lambda: calls.append(1))
    parser.close()
    assert calls == [1]


def test_fetch_page_builds_padded_url_and_updates_delay(
    monkeypatch: pytest.MonkeyPatch, parser
) -> None:
    """``fetch_page`` requests ``boeNNN.htm``, passes retries and updates the fetcher delay."""
    seen = {}

    def fake(*, url, retry_count):
        """Record the call and return canned HTML."""
        seen.update(url=url, retry_count=retry_count)
        return "<html/>"

    monkeypatch.setattr(parser.http, "fetch_text", fake)
    assert parser.fetch_page(7, retry_count=2, delay=0.25) == "<html/>"
    assert seen == {"url": enoch.BASE_URL + "boe007.htm", "retry_count": 2}
    assert parser.http.delay == 0.25


# --- consolidate_strings / parse_inline_annotations ------------------------------------


def test_consolidate_strings_merges_adjacent_strings(parser) -> None:
    """Adjacent strings are merged while other parts keep their place."""
    hi = pyosis.HiCt(type_value=pyosis.OsisHi.BOLD, content=["x"])
    assert parser.consolidate_strings(["a", "b", hi, "c", "d"]) == ["ab", hi, "cd"]


def test_parse_inline_annotations_plain_text_node(parser) -> None:
    """A text node outside green font is kept; a whitespace-only one is dropped."""
    assert parser.parse_inline_annotations(NavigableString("hello")) == ["hello"]
    assert parser.parse_inline_annotations(NavigableString("   ")) == []


def test_parse_inline_annotations_green_text_node_page_marker(parser) -> None:
    """Inside green font a ``p. xvii`` text node becomes a page milestone."""
    parts = parser.parse_inline_annotations(NavigableString("p. xvii"), is_green_font=True)
    assert len(parts) == 1 and isinstance(parts[0], pyosis.MilestoneCt)
    assert parts[0].n == "xvii"


def test_parse_inline_annotations_green_font_tag_becomes_milestone(parser) -> None:
    """``<font color="green">p. 12</font>`` becomes a page milestone among the text."""
    p = _p('<p>Before <font color="GREEN">p. 12</font> after</p>')
    parts = parser.parse_inline_annotations(p)
    milestones = [x for x in parts if isinstance(x, pyosis.MilestoneCt)]
    assert [m.n for m in milestones] == ["12"] and milestones[0].type_value == "page"
    assert parts[0] == "Before " and parts[-1] == " after"


def test_parse_inline_annotations_non_green_font_page_text_kept(parser) -> None:
    """Page-like text outside green font is left as plain text."""
    parts = parser.parse_inline_annotations(_p("<p>see pp. 35, 36 here</p>"))
    assert parts == ["see pp. 35, 36 here"]


@pytest.mark.parametrize(
    ("tag", "hi_type"),
    [
        ("i", pyosis.OsisHi.ITALIC),
        ("em", pyosis.OsisHi.ITALIC),
        ("b", pyosis.OsisHi.BOLD),
        ("strong", pyosis.OsisHi.BOLD),
        ("sup", pyosis.OsisHi.SUPER),
        ("sub", pyosis.OsisHi.SUB),
    ],
)
def test_parse_inline_annotations_formatting_tags_map_to_hi(parser, tag, hi_type) -> None:
    """Formatting tags become ``hi`` elements of the matching type with their text inside."""
    parts = parser.parse_inline_annotations(_p(f"<p>a <{tag}>word</{tag}> b</p>"))
    assert len(parts) == 3
    hi = parts[1]
    assert isinstance(hi, pyosis.HiCt) and hi.type_value == hi_type
    assert hi.content == ["word"]


def test_parse_inline_annotations_empty_formatting_tag_dropped(parser) -> None:
    """A formatting tag with no content produces no ``hi`` element."""
    assert parser.parse_inline_annotations(_p("<p>a<i></i>b</p>")) == ["ab"]


def test_parse_inline_annotations_passthrough_tags(parser) -> None:
    """Links, spans, divs, fonts and unknown tags contribute only their content; ``br`` none."""
    html = '<p>a<a href="x">l</a><span>s</span><font color="red">f</font><u>u</u><br/>z</p>'
    assert parser.parse_inline_annotations(_p(html)) == ["alsfuz"]


def test_parse_inline_annotations_skips_navigation_classes(parser) -> None:
    """Elements whose class mentions navigation/next/prev are skipped."""
    html = '<p>keep<span class="navigation">no</span><a class="next">no</a>'
    html += '<span class="prev">no</span></p>'
    assert parser.parse_inline_annotations(_p(html)) == ["keep"]


def test_parse_inline_annotations_footnote_reference_becomes_note(parser) -> None:
    """An ``fr_`` anchor plus its ``#fn_`` link becomes a ``note`` and the number is hidden."""
    parser.footnotes["fn_0"] = FootnoteInfo("fn_0", "i:1", "The note.")
    html = '<p>Text<a name="fr_0"></a><a href="#fn_0">1</a> more</p>'
    parts = parser.parse_inline_annotations(_p(html))
    notes = [x for x in parts if isinstance(x, pyosis.NoteCt)]
    assert len(notes) == 1
    assert notes[0].n == "i:1" and notes[0].content == ["The note."]
    assert notes[0].type_value == "explanation"
    assert "1" not in "".join(x for x in parts if isinstance(x, str))


def test_parse_inline_annotations_unknown_footnote_dropped_silently(parser) -> None:
    """A footnote reference with no extracted footnote emits no note but hides the number."""
    html = '<p>Text<a name="fr_9"></a><a href="#fn_9">1</a> more</p>'
    parts = parser.parse_inline_annotations(_p(html))
    assert parts == ["Text more"]


def test_parse_inline_annotations_footnote_anchor_without_matching_link(parser) -> None:
    """An ``fr_`` anchor whose next link points elsewhere is treated as an ordinary link."""
    html = '<p>a<a name="fr_0"></a><a href="#other">b</a></p>'
    assert parser.parse_inline_annotations(_p(html)) == ["ab"]


# --- parse_verse_text ------------------------------------------------------------------


def test_parse_verse_text_prose(parser) -> None:
    """A paragraph without ``<br>`` has no poetry and keeps its text and number prefix."""
    vc = parser.parse_verse_text(_p("<p>1. In the beginning <i>was</i> it.</p>"))
    assert vc.text == "1. In the beginning was it."
    assert not vc.has_poetry and vc.poetry_lines is None
    assert any(isinstance(x, pyosis.HiCt) for x in vc.content_parts)


def test_parse_verse_text_poetry_lines_keep_formatting(parser) -> None:
    """``<br>`` splits poetry into lines, keeping inline formatting within each line."""
    vc = parser.parse_verse_text(_p("<p>1. Line one<br/>Line <i>two</i><br>Line three</p>"))
    assert vc.has_poetry and vc.poetry_lines is not None
    assert [_text(line) for line in vc.poetry_lines] == ["1. Line one", "Line two", "Line three"]
    assert any(isinstance(x, pyosis.HiCt) for x in vc.poetry_lines[1])


def test_parse_verse_text_poetry_drops_empty_and_navigation_lines(parser) -> None:
    """Blank lines and lines containing navigation words are dropped from poetry."""
    vc = parser.parse_verse_text(_p("<p>Keep<br/> <br/>Next: chapter II<br/>Back to Index</p>"))
    assert vc.has_poetry
    assert [_text(line) for line in vc.poetry_lines] == ["Keep"]


def test_parse_verse_text_only_blank_lines_gives_no_poetry_lines(parser) -> None:
    """If every line is empty the result flags poetry but has ``poetry_lines`` None."""
    vc = parser.parse_verse_text(_p("<p><br/></p>"))
    assert vc.has_poetry and vc.poetry_lines is None


# --- extract_chapter_number ------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("CHAPTER I.", 1),
        ("Chapter xiv", 14),
        ("CHAPTER   XCIX.", 99),
        ("CHAPTER CVIII", 108),
        ("Introduction", None),
        ("CHAPTER", None),
        ("CHAPTER 5", None),
    ],
)
def test_extract_chapter_number_examples(parser, text, expected) -> None:
    """Roman-numeral chapter headings are decoded; other text gives ``None``."""
    assert parser.extract_chapter_number(text) == expected


@given(st.integers(min_value=1, max_value=399), st.booleans())
def test_extract_chapter_number_roundtrips_roman(number: int, lower: bool) -> None:
    """Any numeral up to CCCXCIX in a heading decodes back to its integer."""
    numeral = _osis.int_to_roman(number)
    heading = f"Chapter {numeral.lower() if lower else numeral}."
    assert SacredTextsParser(cache_dir=None, delay=0).extract_chapter_number(heading) == number


# --- start_book ----------------------------


def test_start_book_creates_root_division() -> None:
    """``start_book`` creates a canonical ``1En`` book div with a titled main title."""
    p = SacredTextsParser(cache_dir=None, delay=0)
    p.start_book()
    assert p.root_div is not None
    assert p.root_div.type_value == pyosis.OsisDivs.BOOK
    assert p.root_div.osis_id == ["1En"]
    title = p.root_div.content[0]
    assert title.content == ["The Book of Enoch"] and title.short == "1 Enoch"


# --- front matter ----------------------------------------------------------------------


def test_should_skip_front_matter_paragraph_cases(parser) -> None:
    """Chrome, footnote bodies, empty text and boilerplate are skipped; real text is not."""
    skip = [
        "<nav><p>Real looking</p></nav>",
        "<footer><p>Real looking</p></footer>",
        '<p><a name="fn_1"></a>note</p>',
        "<p>   </p>",
        "<p>The Book of Enoch, by R.H. Charles, [1917], at sacred-texts.com</p>",
        "<p>Next: Introduction</p>",
    ]
    for html in skip:
        assert parser.should_skip_front_matter_paragraph(_soup(html).find("p")), html
    assert not parser.should_skip_front_matter_paragraph(_p("<p>The  text\nof the preface.</p>"))


def test_extract_front_matter_lead_lines_collects_headings_before_body(parser) -> None:
    """Headings before the first body paragraph become lead lines, minus duplicates and chrome."""
    soup = _soup(
        "<body><h1>Introduction</h1><h2>I.  THE   BOOK</h2><h2>i. the book</h2>"
        "<h3>Sacred Texts Index</h3><p>Next: x</p><h2>II. Second</h2>"
        "<p>Body text.</p><h2>Too late</h2></body>"
    )
    assert parser.extract_front_matter_lead_lines(soup, "Introduction") == [
        "I. THE BOOK",
        "II. Second",
    ]


def test_extract_front_matter_lead_lines_skips_boilerplate_headings(parser) -> None:
    """A heading equal to a known boilerplate line is not a lead line."""
    soup = _soup(
        "<h1>The Book of Enoch, by R.H. Charles, [1917], at sacred-texts.com</h1>"
        "<h2>By R. H. Charles</h2><h2></h2><p>Body</p>"
    )
    assert parser.extract_front_matter_lead_lines(soup, "Title Page") == ["By R. H. Charles"]


def test_extract_front_matter_lead_lines_without_body_tag(parser) -> None:
    """A fragment with no ``<body>`` is scanned from the soup root."""
    assert parser.extract_front_matter_lead_lines(_soup("<h2>Part</h2>"), "T") == ["Part"]


def test_add_front_matter_appends_front_division(parser) -> None:
    """``add_front_matter`` adds a non-canonical ``front`` div: title, lead lines, paragraphs."""
    paragraphs = [_p("<p>First <i>para</i>.</p>"), _p('<p><font color="green">p. 9</font></p>')]
    parser.add_front_matter("Editors' Preface", paragraphs, ["Lead"])
    div = parser.root_div.content[-1]
    assert div.type_value == pyosis.OsisDivs.FRONT and div.canonical is False
    title, lead, para, milestone = div.content
    assert title.content == ["Editors' Preface"] and title.canonical is False
    assert lead.content == ["Lead"]
    assert isinstance(para, pyosis.PCt) and _text(para.content) == "First para."
    assert isinstance(milestone, pyosis.MilestoneCt) and milestone.n == "9"


def test_add_front_matter_starts_book_and_skips_empty_paragraphs() -> None:
    """Without a book the method starts one; paragraphs that parse to nothing are omitted."""
    p = SacredTextsParser(cache_dir=None, delay=0)
    p.add_front_matter("Intro", [_p("<p>   </p>")])
    assert p.root_div is not None
    assert len(p.root_div.content[-1].content) == 1  # just the title


# --- chapters and verses ---------------------------------------------------------------


def test_start_chapter_opens_chapter_div_with_title(parser) -> None:
    """``start_chapter`` appends a canonical chapter div with its title to the book."""
    parser.start_chapter(3, "CHAPTER III.")
    assert parser.current_chapter == 3
    assert parser.current_div.osis_id == ["1En.3"]
    assert parser.current_div.content[0].content == ["CHAPTER III."]
    assert parser.root_div.content[-1] is parser.current_div


def test_start_chapter_without_title_or_book() -> None:
    """With no title there is no title element, and with no book nothing is appended."""
    p = SacredTextsParser(cache_dir=None, delay=0)
    p.start_chapter(1)
    assert p.current_div.content == [] and p.root_div is None


def test_start_chapter_warns_about_gaps_in_previous_chapter(
    parser, caplog: pytest.LogCaptureFixture
) -> None:
    """Starting a new chapter checks the old one for verse gaps."""
    parser.start_chapter(1)
    parser.add_verse(1, VerseContent("a", ["a"]))
    parser.add_verse(3, VerseContent("c", ["c"]))
    with caplog.at_level(logging.WARNING, logger=enoch.LOGGER.name):
        parser.start_chapter(2)
    assert "1En.1.2 appears to be missing" in caplog.text


def test_add_verse_plain_text(parser) -> None:
    """A prose verse is appended with its osisID and parts, and becomes the current verse."""
    parser.start_chapter(2)
    parser.add_verse(4, VerseContent("hello", ["hello"]))
    verse = _verses(parser)["1En.2.4"]
    assert verse.content == ["hello"] and verse.canonical is True
    assert parser.current_verse == 4


def test_add_verse_falls_back_to_text_without_parts(parser) -> None:
    """If there are no content parts the plain text is used."""
    parser.start_chapter(1)
    parser.add_verse(1, VerseContent("only text", []))
    assert _verses(parser)["1En.1.1"].content == ["only text"]


def test_add_verse_poetry_uses_line_group(parser) -> None:
    """A verse with poetry lines is emitted as an ``lg`` of ``l`` elements."""
    parser.start_chapter(1)
    parser.add_verse(1, VerseContent("", [], True, [["one"], ["two"]]))
    (lg,) = _verses(parser)["1En.1.1"].content
    assert isinstance(lg, pyosis.LgCt) and [_text(line.content) for line in lg.l] == ["one", "two"]


def test_add_verse_without_chapter_warns(parser, caplog: pytest.LogCaptureFixture) -> None:
    """Adding a verse before any chapter logs a warning and adds nothing."""
    with caplog.at_level(logging.WARNING, logger=enoch.LOGGER.name):
        parser.add_verse(1, VerseContent("x", ["x"]))
    assert "No chapter started for verse 1" in caplog.text
    assert parser.current_verse is None


def test_extend_verse_with_poetry_appends_to_existing_line_group(parser) -> None:
    """Extra lines are appended to the verse's existing line group."""
    parser.start_chapter(1)
    parser.add_verse(1, VerseContent("", [], True, [["a"]]))
    parser._extend_verse_with_poetry(1, [["b"], ["c"]])
    (lg,) = _verses(parser)["1En.1.1"].content
    assert [_text(line.content) for line in lg.l] == ["a", "b", "c"]


def test_extend_verse_with_poetry_converts_plain_verse(parser) -> None:
    """A prose verse keeps its text and gains a line group with the extra lines."""
    parser.start_chapter(1)
    parser.add_verse(1, VerseContent("prose", ["prose"]))
    parser._extend_verse_with_poetry(1, [["tail"]])
    content = _verses(parser)["1En.1.1"].content
    assert content[0] == "prose" and isinstance(content[1], pyosis.LgCt)


def test_extend_verse_with_poetry_missing_verse_added_as_new(parser) -> None:
    """If the verse was never emitted the lines become a new poetry verse."""
    parser.start_chapter(1)
    parser._extend_verse_with_poetry(5, [["x"]])
    assert "1En.1.5" in _verses(parser)


def test_extend_verse_with_poetry_without_chapter_is_noop(parser) -> None:
    """With no open chapter nothing happens."""
    parser._extend_verse_with_poetry(1, [["x"]])
    assert parser.current_div is None


def test_check_verse_gaps_warns_for_each_missing_verse(
    parser, caplog: pytest.LogCaptureFixture
) -> None:
    """Every missing number between two verses is reported."""
    parser.start_chapter(1)
    for n in (1, 4):
        parser.add_verse(n, VerseContent("x", ["x"]))
    with caplog.at_level(logging.WARNING, logger=enoch.LOGGER.name):
        parser._check_verse_gaps()
    assert "1En.1.2" in caplog.text and "1En.1.3" in caplog.text


def test_check_verse_gaps_silent_when_contiguous_or_no_chapter(
    parser, caplog: pytest.LogCaptureFixture
) -> None:
    """Contiguous verses (or no chapter at all) log nothing."""
    with caplog.at_level(logging.WARNING, logger=enoch.LOGGER.name):
        parser._check_verse_gaps()
        parser.start_chapter(1)
        for n in (1, 2, 3):
            parser.add_verse(n, VerseContent("x", ["x"]))
        parser._check_verse_gaps()
    assert caplog.text == ""


# --- verse splitting (direct, incl. properties) ----------------------------------------


@given(st.lists(WORD, min_size=1, max_size=6), st.integers(min_value=1, max_value=50))
def test_split_multi_verse_content_roundtrips_marked_verses(words, start: int) -> None:
    """Joining verse texts with ``N.`` markers and splitting recovers numbers and texts."""
    chunks = [f"{w} {w}" for w in words]
    text = chunks[0]
    for offset, chunk in enumerate(chunks[1:], start=1):
        text += f" {start + offset}. {chunk}"
    result = SacredTextsParser(cache_dir=None, delay=0).split_multi_verse_content([text], start)
    assert result == [(start + i, [c]) for i, c in enumerate(chunks)]


@given(st.text(alphabet="abc xyz.,\n", max_size=60), st.integers(min_value=1, max_value=9))
def test_split_multi_verse_content_without_digits_is_single_verse(text: str, start: int) -> None:
    """Text with no numbers is never split and is returned verbatim."""
    result = SacredTextsParser(cache_dir=None, delay=0).split_multi_verse_content([text], start)
    assert result == [(start, [text])]


@given(st.lists(WORD, min_size=1, max_size=5))
def test_split_multi_verse_content_preserves_all_words(words) -> None:
    """Splitting loses no words: the words of all segments equal the words of the input."""
    text = words[0]
    for i, w in enumerate(words[1:], start=2):
        text += f" {i}. {w}"
    result = SacredTextsParser(cache_dir=None, delay=0).split_multi_verse_content([text], 1)
    out_words = " ".join(_text(parts) for _, parts in result).split()
    assert out_words == words


def test_split_multi_verse_content_ignores_out_of_sequence_numbers(parser) -> None:
    """Only the next expected verse number splits; ``5.`` after verse 1 does not."""
    assert parser.split_multi_verse_content(["a 5. b"], 1) == [(1, ["a 5. b"])]


@given(st.lists(st.lists(WORD, min_size=1, max_size=3), min_size=1, max_size=5))
def test_split_multi_verse_poetry_lines_without_markers_is_single_verse(lines) -> None:
    """Lines with no verse-number prefix always stay in the starting verse."""
    result = SacredTextsParser(cache_dir=None, delay=0).split_multi_verse_poetry_lines(lines, 3)
    assert result == [(3, lines)]


def test_split_multi_verse_poetry_lines_prefix_only_line_is_dropped(parser) -> None:
    """A line that is only the verse marker opens the verse without adding an empty line."""
    result = parser.split_multi_verse_poetry_lines([["a"], ["2. "], ["b"]], 1)
    assert result == [(1, [["a"]]), (2, [["b"]])]


def test_split_multi_verse_poetry_lines_keeps_inline_parts_after_prefix(parser) -> None:
    """Non-string parts that follow the stripped marker are retained."""
    hi = pyosis.HiCt(type_value=pyosis.OsisHi.ITALIC, content=["x"])
    result = parser.split_multi_verse_poetry_lines([["a"], ["2. ", hi]], 1)
    assert result[1] == (2, [[hi]])


def test_split_multi_verse_poetry_lines_empty_input(parser) -> None:
    """With no lines the single starting verse is returned empty."""
    assert parser.split_multi_verse_poetry_lines([], 7) == [(7, [])]


# --- extract_footnotes -----------------------------------------------------------------


def test_extract_footnotes_reads_label_and_text(parser) -> None:
    """A footnote paragraph yields its id, label and text without the anchors."""
    soup = _soup(
        "<h3>Footnotes</h3>"
        '<p><a name="fn_0"></a><a href="x.htm#fr_0">i:1</a> A note <i>here</i>.</p>'
        "<p>no anchor</p>"
        '<p><a name="fn_1"></a>Labelless.</p>'
        '<p><a name="fn_2"></a><a href="#fr_2">i:2</a></p>'
    )
    parser.extract_footnotes(soup)
    assert parser.footnotes["fn_0"] == FootnoteInfo("fn_0", "i:1", "A note here .")
    assert parser.footnotes["fn_1"] == FootnoteInfo("fn_1", "", "Labelless.")
    assert "fn_2" not in parser.footnotes  # empty content is ignored


def test_extract_footnotes_stops_at_next_heading(parser) -> None:
    """Paragraphs after a following heading are not read as footnotes."""
    soup = _soup(
        '<h3>Footnotes</h3><p><a name="fn_0"></a><a href="#">a</a> one</p>'
        '<h3>Other</h3><p><a name="fn_1"></a><a href="#">b</a> two</p>'
    )
    parser.extract_footnotes(soup)
    assert set(parser.footnotes) == {"fn_0"}


def test_extract_footnotes_without_footnotes_heading(parser) -> None:
    """Pages with no ``Footnotes`` heading leave the footnote table untouched."""
    parser.extract_footnotes(_soup('<h3>CHAPTER I.</h3><p><a name="fn_0"></a>x</p>'))
    assert parser.footnotes == {}


# --- parse_page ------------------------------------------------------------------------


def test_parse_page_front_matter_page(parser) -> None:
    """Pages 0-3 become one front division with the configured title and the body paragraphs."""
    html = (
        "<body><h1>Introduction</h1><h2>Section A</h2><p>Next: preface</p>"
        "<p>Intro body text.</p><p>[ bracket nav ]</p></body>"
    )
    parser.parse_page(html, page_num=2)
    (front,) = [d for d in parser.root_div.content if isinstance(d, pyosis.DivCt)]
    assert front.type_value == pyosis.OsisDivs.FRONT
    texts = [_text(c.content) for c in front.content if isinstance(c, (pyosis.TitleCt, pyosis.PCt))]
    assert texts[:3] == ["Introduction", "Section A", "Intro body text."]


def test_parse_page_front_matter_with_only_chrome_adds_nothing(parser) -> None:
    """A front-matter page containing only navigation emits no division."""
    parser.parse_page("<body><p>Next: x</p><p>   </p></body>", page_num=1)
    assert len(parser.root_div.content) == 1  # just the book title


def test_parse_page_starts_chapter_and_numbers_verses(parser) -> None:
    """A ``CHAPTER`` heading opens a chapter and numbered paragraphs become verses."""
    html = (
        "<h3>CHAPTER   II.</h3><p>1. First verse.</p><p>2. Second <i>verse</i>.</p><p>3. Third.</p>"
    )
    parser.parse_page(html, page_num=5)
    assert parser.current_div.osis_id == ["1En.2"]
    assert parser.current_div.content[0].content == ["CHAPTER II."]
    verses = _verses(parser)
    assert list(verses) == ["1En.2.1", "1En.2.2", "1En.2.3"]
    assert verses["1En.2.1"].content == ["First verse."]
    assert _text(verses["1En.2.2"].content) == "Second verse."
    assert parser.current_verse == 3


def test_parse_page_heading_without_numeral_is_ignored(parser) -> None:
    """A heading containing ``CHAPTER`` but no numeral starts nothing."""
    parser.parse_page("<h3>CHAPTER</h3><p>1. Orphan.</p>", page_num=5)
    assert parser.current_chapter is None and _no_verses(parser)


def _no_verses(parser: SacredTextsParser) -> bool:
    """Return True if the parser has no open chapter division containing verses."""
    return parser.current_div is None or not _verses(parser)


def test_parse_page_skips_chrome_and_verses_before_any_chapter(parser) -> None:
    """Navigation paragraphs, page numbers and verses before a chapter are ignored."""
    html = (
        "<p>1. Before any chapter.</p><h3>CHAPTER I.</h3>"
        "<p>p. 5</p><p>[note]</p><p>Next: II</p><p>Previous: 0</p><p>Sacred Texts</p>"
        "<p>« back</p><p>⌈ref⌉</p><p>   </p><nav><p>1. In nav.</p></nav>"
        "<p>1. Real verse.</p>"
    )
    parser.parse_page(html, page_num=5)
    assert list(_verses(parser)) == ["1En.1.1"]
    assert _verses(parser)["1En.1.1"].content == ["Real verse."]


def test_parse_page_splits_inline_multi_verse_paragraph(parser) -> None:
    """Verses sharing one paragraph are split on inline numbers."""
    parser.parse_page("<h3>CHAPTER I.</h3><p>1. One text. 2. Two text. 3. Three text.</p>", 5)
    verses = _verses(parser)
    assert [_text(v.content) for v in verses.values()] == ["One text.", "Two text.", "Three text."]


def test_parse_page_numbered_poetry_splits_on_inline_markers(parser) -> None:
    """A numbered poetry paragraph splits into verses where a line begins with the next number."""
    html = "<h3>CHAPTER I.</h3><p>1. A<br/>B<br/>2. C<br/>D</p>"
    parser.parse_page(html, 5)
    verses = _verses(parser)
    lines = {k: [_text(line.content) for line in v.content[0].l] for k, v in verses.items()}
    assert lines == {"1En.1.1": ["A", "B"], "1En.1.2": ["C", "D"]}


def _lines(verse: pyosis.VerseCt) -> list[str]:
    """Return the text of each poetry line in a verse's first line group."""
    lg = next(c for c in verse.content if isinstance(c, pyosis.LgCt))
    return [_text(line.content).strip() for line in lg.l]


def test_parse_page_unnumbered_chapter_is_verse_one(parser) -> None:
    """A chapter whose only paragraph has no number (chapter III) is verse 1."""
    parser.parse_page("<h3>CHAPTER II.</h3><p>1. Two.</p>", 5)
    parser.parse_page("<h3>CHAPTER III.</h3><p>Observe and see.</p>", 6)
    assert parser.current_div.osis_id == ["1En.3"]
    assert _verses(parser)["1En.3.1"].content == ["Observe and see."]


def test_parse_page_prose_after_page_break_continues_verse(parser) -> None:
    """Prose that runs on past a page marker extends the verse and splits on its markers."""
    html = (
        "<h3>CHAPTER XIII.</h3><p>1. And Enoch said: 'Azazel,</p>"
        '<p><a name="page_40"><font color="green">p. 40</font></a></p>'
        "<p>thou shalt have no peace. 2. And thou shalt not. 3. Then I went.</p>"
    )
    parser.parse_page(html, 16)
    verses = _verses(parser)
    assert [_text(v.content) for v in verses.values()] == [
        "And Enoch said: 'Azazel, thou shalt have no peace.",
        "And thou shalt not.",
        "Then I went.",
    ]


def test_parse_page_paragraph_continues_marker_is_dropped(parser) -> None:
    """``[paragraph continues]`` paragraphs are kept, without the marker."""
    html = (
        "<h3>CHAPTER LXXXIII.</h3><p>1. I prayed to the</p>"
        '<p><span class="contnote"><font color="green">[paragraph continues]</font></span>'
        " Lord. 2. I had laid me down.</p>"
    )
    parser.parse_page(html, 86)
    verses = _verses(parser)
    assert _text(verses["1En.83.1"].content) == "I prayed to the Lord."
    assert _text(verses["1En.83.2"].content) == "I had laid me down."


def test_parse_page_unnumbered_stanza_continues_verse(parser) -> None:
    """An unnumbered stanza belongs to the verse before it, not to the next number."""
    html = (
        "<h3>CHAPTER I.</h3><p>8. But with the righteous He will make peace.</p>"
        "<p>And will protect the elect,<br/> And mercy shall be upon them.</p>"
        "<p>9. And behold!<br/> To execute judgement</p>"
    )
    parser.parse_page(html, 4)
    verses = _verses(parser)
    assert list(verses) == ["1En.1.8", "1En.1.9"]
    assert _lines(verses["1En.1.8"]) == [
        "And will protect the elect,",
        "And mercy shall be upon them.",
    ]


def test_parse_page_poetry_line_with_inline_marker_splits(parser) -> None:
    """A verse marker inside a poetry line, or a line-start number without a period, splits."""
    html = (
        "<h3>CHAPTER XCI.</h3><p>1. 'And now, my son,<br/> That shall befall you.'"
        "<br/>2 And Methuselah went. 3. And he spake:<br/>'Hear, ye sons.</p>"
    )
    parser.parse_page(html, 95)
    verses = _verses(parser)
    assert list(verses) == ["1En.91.1", "1En.91.2", "1En.91.3"]
    assert _lines(verses["1En.91.2"]) == ["And Methuselah went."]
    assert _lines(verses["1En.91.3"]) == ["And he spake:", "'Hear, ye sons."]


@pytest.mark.parametrize("marker", ["2 And", "2 .And"])
def test_parse_page_paragraph_number_without_period(parser, marker: str) -> None:
    """A paragraph opening with the next number and a stray or missing period is that verse."""
    html = f"<h3>CHAPTER C.</h3><p>1. One.</p><p>{marker} two.</p><p>5 And five.</p>"
    parser.parse_page(html, 104)
    verses = _verses(parser)
    assert list(verses) == ["1En.100.1", "1En.100.2"]
    assert _text(verses["1En.100.2"].content) == "And two. 5 And five."


def test_parse_page_lettered_verses(parser) -> None:
    """Lettered sub-verses start the next verse; others stay with the verse in progress."""
    html = (
        "<h3>CHAPTER V.</h3><p>5. Therefore shall ye execrate your days.</p>"
        "<p>6<i>a</i>. In those days,<br/> <i>b</i>. And by you,<br/> 7<i>c</i>. And for you.</p>"
        "<p>6<i>d</i>. And all the . . . shall rejoice.</p>"
        "<i>\n<p>i</i>. And for all of you sinners<br/> 7<i>a</i>. But for the elect.</p>"
        "<p>8 And then there shall be wisdom.</p>"
    )
    parser.parse_page(html, 8)
    verses = _verses(parser)
    assert list(verses) == ["1En.5.5", "1En.5.6", "1En.5.7", "1En.5.8"]
    assert _lines(verses["1En.5.6"]) == ["a. In those days,", "b. And by you,"]
    assert _lines(verses["1En.5.7"]) == [
        "c. And for you.",
        "6d. And all the . . . shall rejoice.",
        "i. And for all of you sinners",
        "7a. But for the elect.",
    ]


def test_parse_page_lettered_part_of_a_later_verse_stays(parser) -> None:
    """``5a.`` before verse 2 (chapter LI) does not open verse 5 early."""
    html = (
        "<h3>CHAPTER LI.</h3><p>1. And in those days.</p>"
        "<p>5<i>a</i>. For in those days,<br/> 2. And he shall choose.</p>"
        "<p>3. Three.</p><p>4. Four.</p><p>5<i>b</i>. And the earth shall rejoice.</p>"
    )
    parser.parse_page(html, 54)
    assert list(_verses(parser)) == [f"1En.51.{n}" for n in range(1, 6)]


def test_parse_page_section_heading_becomes_chapter_subtitle(parser) -> None:
    """An editorial heading above the chapter heading is a sub-title, not verse text."""
    parser.parse_page("<h3>CHAPTER V.</h3><p>1. Five.</p>", 8)
    parser.parse_page(
        "<p>VI-XI. <i>The Fall of the Angels</i>.</p><h3>CHAPTER VI.</h3><p>1. Six.</p>", 9
    )
    assert _text(parser.root_div.content[-2].content[-1].content) == "Five."
    title = parser.current_div.content[1]
    assert isinstance(title, pyosis.TitleCt) and title.canonical is False
    assert title.type_value == pyosis.OsisTitles.SUB
    assert _text(title.content) == "VI-XI. The Fall of the Angels."


def test_parse_page_bracketed_passage_keeps_bracket(parser) -> None:
    """A bracketed passage (chapter LIX) is verse text, not an editorial note."""
    html = "<h3>CHAPTER LIX.</h3><p>[1. In those days. 2. And there.]</p><p>[Lost passage.]</p>"
    parser.parse_page(html, 62)
    verses = _verses(parser)
    assert [_text(v.content) for v in verses.values()] == ["[In those days.", "And there.]"]


@pytest.mark.parametrize("marker", ["1 And", "1 .And"])
def test_parse_page_first_verse_number_without_period(parser, marker: str) -> None:
    """Verse 1 printed without (or with a stray) period loses its number too."""
    parser.parse_page(f"<h3>CHAPTER XXX.</h3><p>{marker} beyond these.</p>", 33)
    assert _verses(parser)["1En.30.1"].content == ["And beyond these."]


def test_parse_page_mislabelled_chapter_page(parser) -> None:
    """boe081 prints ``CHAPTER LXXVII.`` for chapter LXXVIII."""
    parser.parse_page("<h3>CHAPTER LXXVII.</h3><p>1. The sun.</p>", 81)
    assert parser.current_div.osis_id == ["1En.78"]
    assert parser.current_div.content[0].content == ["CHAPTER LXXVIII."]


def test_parse_page_stops_at_footnotes(parser) -> None:
    """Paragraphs after the Footnotes heading are not verse text."""
    html = (
        "<h3>CHAPTER I.</h3><p>1. Text.</p><h3>Footnotes</h3>"
        '<p><a name="fn_0"></a><a href="#fr_0">1:1</a> A note.</p><p>Stray.</p>'
    )
    parser.parse_page(html, 4)
    assert [_text(v.content) for v in _verses(parser).values()] == ["Text."]


def test_parse_page_footnote_is_inlined_as_note(parser) -> None:
    """A footnote on the page is attached to the verse that references it."""
    html = (
        '<h3>CHAPTER I.</h3><p>1. Text<a name="fr_0"></a><a href="#fn_0">1</a> more.</p>'
        '<h3>Footnotes</h3><p><a name="fn_0"></a><a href="#fr_0">i:1</a> The note.</p>'
    )
    parser.parse_page(html, 5)
    notes = [x for x in _verses(parser)["1En.1.1"].content if isinstance(x, pyosis.NoteCt)]
    assert len(notes) == 1 and notes[0].n == "i:1" and notes[0].content == ["The note."]


def test_parse_page_default_page_num_is_body_page(parser) -> None:
    """Omitting ``page_num`` treats the page as a chapter page."""
    parser.parse_page("<h3>CHAPTER I.</h3><p>1. Verse.</p>")
    assert "1En.1.1" in _verses(parser)


# --- generate_osis ---------------------------------------------------------------------


def test_generate_osis_contains_book_header_and_verses(parser) -> None:
    """The generated XML includes the work metadata, the scrape revision note and the verses."""
    parser.parse_page("<h3>CHAPTER I.</h3><p>1. Verse one.</p>", 5)
    xml = parser.generate_osis().to_xml()
    assert 'osisIDWork="1En"' in xml and "1En.1.1" in xml and "Verse one." in xml
    assert "Scraped from https://sacred-texts.com/bib/boe/" in xml
    assert 'event="eversion"' in xml and "Robert Henry (R.H.) Charles" in xml


def test_generate_osis_without_book_has_no_divisions() -> None:
    """With nothing parsed the document is still valid but has no book division."""
    xml = SacredTextsParser(cache_dir=None, delay=0).generate_osis().to_xml()
    assert 'type="book"' not in xml


def test_generate_osis_warns_about_gap_in_final_chapter(
    parser, caplog: pytest.LogCaptureFixture
) -> None:
    """The final chapter is gap-checked before output is generated."""
    parser.start_chapter(1)
    parser.add_verse(1, VerseContent("a", ["a"]))
    parser.add_verse(3, VerseContent("c", ["c"]))
    with caplog.at_level(logging.WARNING, logger=enoch.LOGGER.name):
        parser.generate_osis()
    assert "1En.1.2 appears to be missing" in caplog.text


# --- process_all_pages / run -----------------------------------------------------------


def test_process_all_pages_fetches_range_and_survives_errors(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Every page in the range is fetched; a failing page is logged and skipped."""
    p = SacredTextsParser(cache_dir=None, delay=0)
    fetched = []

    def fake_fetch(page_num, retry_count=3, delay=1.0):
        """Return a chapter page, failing for page 5."""
        fetched.append((page_num, delay))
        if page_num == 5:
            raise RuntimeError("boom")
        return f"<h3>CHAPTER I.</h3><p>1. Page {page_num}.</p>"

    monkeypatch.setattr(p, "fetch_page", fake_fetch)
    with caplog.at_level(logging.ERROR, logger=enoch.LOGGER.name):
        p.process_all_pages(4, 6, delay=0.5)
    assert fetched == [(4, 0.5), (5, 0.5), (6, 0.5)]
    assert "Error processing page 5: boom" in caplog.text
    assert p.root_div is not None and p.current_chapter == 1


def test_run_writes_osis_from_prepopulated_cache(tmp_path: Path) -> None:
    """``run`` parses cached pages and writes ``1-enoch.xml`` under the output directory."""
    cache = tmp_path / "cache"
    fetcher = CachedHttpFetcher(cache_dir=cache, delay=0)
    page = fetcher.cache_path_for(enoch.BASE_URL + "boe004.htm")
    fetcher.close()
    page.parent.mkdir(parents=True)
    page.write_text(
        "<h3>CHAPTER I.</h3><p>1. The words of the blessing.</p><p>2. And he said.</p>",
        encoding="utf-8",
    )
    out = tmp_path / "out" / "nested"
    args = argparse.Namespace(
        output_dir=out, cache_dir=str(cache), delay=0, start_page=4, end_page=4
    )
    written = enoch.run(args)
    assert written == [out / "1-enoch.xml"]
    xml = written[0].read_text(encoding="utf-8")
    assert "1En.1.1" in xml and "The words of the blessing." in xml and "1En.1.2" in xml


# --- redesigned reader layout ---------------------------------------------------------

READER_FIXTURES = Path(__file__).parent / "fixtures" / "reader_layout"
"""Trimmed copies of real redesigned sacred-texts.com pages."""


def reader_fixture(name: str) -> str:
    """Return the text of a reader-layout fixture page."""
    return (READER_FIXTURES / name).read_text(encoding="utf-8")


def test_parse_page_reader_layout_front_matter_restores_demoted_heading(parser) -> None:
    """The title page's demoted second ``<h1>`` is kept, and sidebar text is not."""
    parser.parse_page(reader_fixture("boe000.htm"), page_num=0)
    front = parser.root_div.content[-1]
    lines = [_text(item.content) for item in front.content]
    assert lines[:4] == ["Title Page", "THE", "BOOK OF ENOCH", "TRANSLATED BY"]
    assert lines[-1] == "[1917]"
    assert not any("Chapters" in line for line in lines)


def test_parse_page_reader_layout_chapter(parser) -> None:
    """A reader-layout chapter page starts its chapter and splits its inline verses."""
    parser.parse_page(reader_fixture("boe010.htm"), page_num=10)
    assert parser.current_chapter == 7
    verses = _verses(parser)
    assert list(verses) == [f"1En.7.{n}" for n in range(1, 7)]
    assert (
        _text(verses["1En.7.6"].content)
        == "Then the earth laid accusation against the lawless ones."
    )


def test_parse_page_skips_archive_title_banner_between_verses(parser) -> None:
    """The archive's "The Book of Enoch, by ..." banner is not taken as the next verse."""
    banner = "<i>The Book of Enoch</i>, by R.H. Charles, [1917], at sacred-texts.com"
    html = f"<h3>CHAPTER I.</h3><p>1. First verse.</p><p>{banner}</p><p>2. Second verse.</p>"
    parser.parse_page(html, page_num=5)
    assert list(_verses(parser)) == ["1En.1.1", "1En.1.2"]
    assert _verses(parser)["1En.1.1"].content == ["First verse."]
