"""Unit tests for ``open_canon_site.scrapers.sacred_texts.jubilees`` (offline, inline HTML)."""

from __future__ import annotations

import argparse
import string
from pathlib import Path

import pyosis
import pytest
from bs4 import BeautifulSoup, NavigableString
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from open_canon_site.scrapers._osis import extract_plain_text, int_to_roman
from open_canon_site.scrapers.sacred_texts import jubilees
from open_canon_site.scrapers.sacred_texts.jubilees import (
    Chapter,
    FootnoteInfo,
    FrontMatterSection,
    JubileesParser,
    PageParagraph,
    Section,
    VerseBlock,
)


def page(heading: str, paragraphs: list[str], footnotes: str = "", extra_head: str = "") -> str:
    """Build a minimal original-site Jubilees page: banner, heading, paragraphs, footnotes."""
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    foot = f"<h3>Footnotes</h3>{footnotes}" if footnotes else ""
    return (
        "<html><head><title>Book of Jubilees</title></head><body>"
        "<p>Sacred Texts | Apocrypha | Index</p>"
        f"{extra_head}<h3>{heading}</h3>{body}{foot}"
        "<p>Next</p></body></html>"
    )


def pp(text: str) -> PageParagraph:
    """Build a plain-text ``PageParagraph``."""
    return PageParagraph(text=text, content_parts=[text])


def soup_body(markup: str):
    """Parse ``markup`` and return the ``<body>`` tag."""
    return BeautifulSoup(f"<html><body>{markup}</body></html>", "html.parser").body


def first_child(markup: str):
    """Return the first tag inside a parsed ``<p>`` wrapper."""
    return soup_body(markup).find()


@pytest.fixture
def parser(tmp_path):
    """Return a parser with a tmp cache directory, closed after the test."""
    instance = JubileesParser(cache_dir=str(tmp_path / "cache"), delay=0)
    yield instance
    instance.close()


def stub_fetch(parser: JubileesParser, monkeypatch, pages: dict[str, str]):
    """Replace the fetcher's network call with a lookup in ``pages``; return the call log."""
    calls: list[tuple[str, int]] = []

    def fake_fetch_text(*, url: str, retry_count: int = 3) -> str:
        """Record ``(url, retry_count)`` and return the canned page."""
        calls.append((url, retry_count))
        return pages[url]

    monkeypatch.setattr(parser.http, "fetch_text", fake_fetch_text)
    return calls


# --- constructor / close / url / validity ----------------------------------------------


def test_init_stores_delay_and_builds_fetcher(tmp_path):
    """The parser records the delay and builds a fetcher with the cache directory."""
    instance = JubileesParser(cache_dir=str(tmp_path / "c"), delay=4.0)
    assert instance.delay == 4.0 and instance.http.delay == 4.0
    assert instance.http.cache_dir == tmp_path / "c"
    instance.close()


def test_close_closes_http_client(parser):
    """``close`` closes the underlying httpx client."""
    parser.close()
    assert parser.http._client.is_closed


def test_page_url_zero_pads_page_number():
    """Page numbers are zero-padded to two digits under the base URL."""
    assert JubileesParser.page_url(3) == "https://sacred-texts.com/bib/jub/jub03.htm"
    assert JubileesParser.page_url(87).endswith("jub87.htm")


def test_is_valid_page_accepts_original_html():
    """A page mentioning the book and containing ``<html`` is valid."""
    assert JubileesParser.is_valid_page(page("Jubilees 1:1 (i. 1)", ["1. x"]))


@pytest.mark.parametrize(
    "text",
    [
        "<html>Jubilees only</html>",
        "<html>Book of Jubilees Just a moment</html>",
        "Markdown Content: Book of Jubilees <html>",
        "Book of Jubilees but no markup",
    ],
    ids=["no-title", "cloudflare", "markdown", "no-html"],
)
def test_is_valid_page_rejects_bad_pages(text):
    """Missing title, a Cloudflare notice, mirror Markdown or missing ``<html`` invalidate a page."""
    assert not JubileesParser.is_valid_page(text)


# --- fetch_page ------------------------------------------------------------------------


def test_fetch_page_fetches_valid_page_with_retry_count(parser, monkeypatch):
    """A cache miss fetches from the page URL, passing the retry count through."""
    url = JubileesParser.page_url(5)
    good = page("Jubilees 1:1 (i. 1)", ["1. x"])
    calls = stub_fetch(parser, monkeypatch, {url: good})
    assert parser.fetch_page(5, retry_count=7) == good
    assert calls == [(url, 7)]


def test_fetch_page_returns_valid_cache_without_network(parser, monkeypatch):
    """A valid cached page short-circuits the network."""
    url = JubileesParser.page_url(5)
    good = page("Jubilees 1:1 (i. 1)", ["1. x"])
    path = parser.http.cache_path_for(url)
    path.parent.mkdir(parents=True)
    path.write_text(good, encoding="utf-8")
    calls = stub_fetch(parser, monkeypatch, {})
    assert parser.fetch_page(5) == good and calls == []


def test_fetch_page_discards_invalid_cache_and_refetches(parser, monkeypatch, caplog):
    """An invalid cached page is logged, deleted and refetched."""
    url = JubileesParser.page_url(5)
    good = page("Jubilees 1:1 (i. 1)", ["1. x"])
    path = parser.http.cache_path_for(url)
    path.parent.mkdir(parents=True)
    path.write_text("<html>Just a moment</html>", encoding="utf-8")
    stub_fetch(parser, monkeypatch, {url: good})
    with caplog.at_level("WARNING"):
        assert parser.fetch_page(5) == good
    assert "Discarding invalid cached Jubilees source" in caplog.text
    assert not path.exists()


def test_fetch_page_raises_and_clears_cache_for_invalid_fetch(parser, monkeypatch):
    """An interstitial fetched live raises and leaves no cache entry behind."""
    url = JubileesParser.page_url(5)
    path = parser.http.cache_path_for(url)

    def fake_fetch_text(*, url: str, retry_count: int = 3) -> str:
        """Cache then return a Cloudflare page, like the real fetcher would."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Just a moment", encoding="utf-8")
        return "Just a moment"

    monkeypatch.setattr(parser.http, "fetch_text", fake_fetch_text)
    with pytest.raises(RuntimeError, match="usable Jubilees witness"):
        parser.fetch_page(5)
    assert not path.exists()


def test_fetch_page_applies_new_delay_to_parser_and_fetcher(parser, monkeypatch):
    """Passing a different ``delay`` updates both the parser and its fetcher."""
    url = JubileesParser.page_url(5)
    stub_fetch(parser, monkeypatch, {url: page("Jubilees 1:1 (i. 1)", ["1. x"])})
    parser.fetch_page(5, delay=9.0)
    assert parser.delay == 9.0 and parser.http.delay == 9.0


def test_fetch_page_works_without_cache(monkeypatch):
    """With caching disabled the fetch and validation still work."""
    instance = JubileesParser(delay=0)
    good = page("Jubilees 1:1 (i. 1)", ["1. x"])
    stub_fetch(instance, monkeypatch, {JubileesParser.page_url(1): good})
    assert instance.fetch_page(1) == good
    instance.close()


# --- text helpers ----------------------------------------------------------------------


def test_clean_line_strips_markdown_remnants():
    """Heading markers, links, bold, underscores and ``[paragraph continues]`` are removed."""
    raw = "## **Bold** [link text](http://x) __it__ \\_a_ [paragraph continues] &amp; more"
    assert JubileesParser.clean_line(raw) == "Bold link text it a & more"


def test_clean_line_normalizes_whitespace():
    """Surrounding and repeated whitespace collapses to single spaces."""
    assert JubileesParser.clean_line("  a \t b  ") == "a b"


@given(st.text(alphabet=string.ascii_letters + " *_#[]()\n", max_size=60))
def test_clean_line_output_has_no_markdown_markers_or_edge_whitespace(text):
    """Bold/underscore markers are always removed and whitespace is trimmed and collapsed."""
    cleaned = JubileesParser.clean_line(text)
    assert "**" not in cleaned and "_" not in cleaned
    assert cleaned == " ".join(cleaned.split())


def test_consolidate_parts_merges_adjacent_strings(parser):
    """Adjacent strings merge while non-string parts stay in place."""
    hi = pyosis.HiCt(type_value=pyosis.OsisHi.ITALIC, content=["x"])
    assert parser.consolidate_parts(["a", "b", hi, "c"]) == ["ab", hi, "c"]


def test_trim_parts_strips_outer_whitespace_and_drops_blank_edges(parser):
    """Blank strings at both ends vanish and outer strings are stripped; inner space stays."""
    hi = pyosis.HiCt(type_value=pyosis.OsisHi.BOLD, content=["x"])
    assert parser.trim_parts(["  ", " a ", hi, " b ", "  "]) == ["a ", hi, " b"]


def test_trim_parts_of_only_whitespace_is_empty(parser):
    """Whitespace-only content trims to nothing."""
    assert parser.trim_parts([" ", "\n"]) == []


@given(st.lists(st.text(alphabet=string.ascii_letters + " \n", max_size=8), max_size=6))
def test_trim_parts_is_idempotent(strings):
    """Trimming twice equals trimming once."""
    p = JubileesParser.__new__(JubileesParser)
    once = p.trim_parts(list(strings))
    assert p.trim_parts(list(once)) == once


def test_extract_text_without_notes_skips_notes_and_recurses_into_highlights(parser):
    """Footnote text is excluded; highlight content is included."""
    note = pyosis.NoteCt(type_value="explanation", n="1", content=["NOTE"])
    hi = pyosis.HiCt(type_value=pyosis.OsisHi.ITALIC, content=["it", pyosis.HiCt(content=["al"])])
    assert parser.extract_text_without_notes(["a ", hi, note, " b"]) == "a ital b"


def test_extract_text_without_notes_ignores_parts_without_content(parser):
    """A milestone (no ``content``) contributes nothing."""
    mile = pyosis.MilestoneCt(type_value="page", n="5")
    assert parser.extract_text_without_notes(["a", mile, "b"]) == "ab"


# --- parse_inline_content ---------------------------------------------------------------


def test_parse_inline_content_of_text_node_unescapes_entities(parser):
    """A bare text node yields its unescaped string; an empty node yields nothing."""
    assert parser.parse_inline_content(NavigableString("a &amp; b"), {}) == ["a & b"]
    assert parser.parse_inline_content(NavigableString(""), {}) == []


@pytest.mark.parametrize(
    ("tag", "style"),
    [
        ("i", pyosis.OsisHi.ITALIC),
        ("em", pyosis.OsisHi.ITALIC),
        ("b", pyosis.OsisHi.BOLD),
        ("strong", pyosis.OsisHi.BOLD),
        ("sup", pyosis.OsisHi.SUPER),
        ("sub", pyosis.OsisHi.SUB),
    ],
)
def test_parse_inline_content_maps_styling_tags_to_highlights(parser, tag, style):
    """Italic, bold, superscript and subscript tags become matching ``HiCt`` parts."""
    el = first_child(f"<p>a <{tag}>x</{tag}> b</p>")
    parts = parser.parse_inline_content(el, {})
    assert parts[0] == "a " and parts[2] == " b"
    assert isinstance(parts[1], pyosis.HiCt)
    assert parts[1].type_value == style and parts[1].content == ["x"]


def test_parse_inline_content_drops_empty_highlights(parser):
    """An empty ``<i></i>`` produces no highlight."""
    assert parser.parse_inline_content(first_child("<p>a<i></i>b</p>"), {}) == ["ab"]


def test_parse_inline_content_turns_br_into_space_and_skips_tables(parser):
    """``<br>`` becomes a space, table elements are ignored and unknown tags are transparent."""
    el = first_child("<p>a<br/>b<table><tr><td>gone</td></tr></table><span>c</span></p>")
    assert parser.parse_inline_content(el, {}) == ["a b" + "c"]


def test_parse_inline_content_converts_footnote_reference_to_note(parser):
    """A ``fr_N`` anchor followed by an ``#fn_N`` link becomes a note and the link is not emitted."""
    foot = FootnoteInfo("fn_1", "1", ["See Gen."])
    el = first_child('<p>word<a name="fr_1"></a><a href="#fn_1"><sup>1</sup></a> more</p>')
    parts = parser.parse_inline_content(el, {"fn_1": foot})
    assert parts[0] == "word" and parts[2] == " more"
    note = parts[1]
    assert isinstance(note, pyosis.NoteCt)
    assert note.n == "1" and note.content == ["See Gen."]
    assert len(parts) == 3


def test_parse_inline_content_drops_reference_to_unknown_footnote(parser):
    """If the footnote text is unknown the reference anchors disappear without a note."""
    el = first_child('<p>word<a name="fr_9"></a><a href="#fn_9">9</a> more</p>')
    assert parser.parse_inline_content(el, {}) == ["word more"]


def test_parse_inline_content_keeps_text_of_anchor_without_matching_link(parser):
    """A ``fr_`` anchor lacking the paired ``#fn_`` link is treated as an ordinary tag."""
    el = first_child('<p>a<a name="fr_2">text</a><a href="#other">b</a></p>')
    assert parser.parse_inline_content(el, {}) == ["atextb"]


# --- make_paragraph / extract_footnotes --------------------------------------------------


def test_make_paragraph_trims_and_computes_text_without_notes(parser):
    """Text excludes notes; parts are trimmed."""
    note = pyosis.NoteCt(type_value="explanation", n="1", content=["N"])
    para = parser.make_paragraph(["  Hello  ", note, "  world "])
    assert para is not None and para.text == "Hello world"
    assert para.content_parts == ["Hello  ", note, "  world"]


def test_make_paragraph_returns_none_for_note_only_content(parser):
    """A paragraph with nothing but a footnote has no text and is dropped."""
    note = pyosis.NoteCt(type_value="explanation", n="1", content=["N"])
    assert parser.make_paragraph([" ", note]) is None


FOOTNOTES_HTML = (
    "<h3>Footnotes</h3>"
    '<p><a name="fn_1"></a><a href="#fr_1">1</a> First <i>note</i>.</p>'
    '<p><a name="fn_2"></a><a href="#fr_2"> 2 </a>Second.</p>'
    "<p>stray text without an anchor</p>"
    '<p><a name="fn_3"></a>No label</p>'
)


def test_extract_footnotes_collects_labels_and_content(parser):
    """Each ``fn_N`` paragraph yields a label (next anchor text) and the remaining content."""
    notes = parser.extract_footnotes(soup_body(FOOTNOTES_HTML))
    assert set(notes) == {"fn_1", "fn_2", "fn_3"}
    assert notes["fn_1"].label == "1" and notes["fn_1"].ref_id == "fn_1"
    assert extract_plain_text(notes["fn_1"].content_parts) == "First note."
    assert notes["fn_2"].label == "2"
    assert notes["fn_3"].label == ""


def test_extract_footnotes_preserves_top_level_italics(parser):
    """Italic text directly inside a footnote paragraph stays a ``HiCt`` highlight."""
    notes = parser.extract_footnotes(soup_body(FOOTNOTES_HTML))
    parts = notes["fn_1"].content_parts
    assert [p for p in parts if isinstance(p, pyosis.HiCt)] == [
        pyosis.HiCt(type_value=pyosis.OsisHi.ITALIC, content=["note"])
    ]
    assert extract_plain_text(parts) == "First note."


def test_extract_footnotes_preserves_top_level_bold_sup_sub(parser):
    """Direct ``<b>``, ``<sup>`` and ``<sub>`` children of a footnote keep their highlight type."""
    body = soup_body(
        "<h3>Footnotes</h3>"
        '<p><a name="fn_1"></a><a href="#fr_1">1</a> <b>B</b><sup>S</sup><sub>U</sub></p>'
    )
    parts = parser.extract_footnotes(body)["fn_1"].content_parts
    kinds = [p.type_value for p in parts if isinstance(p, pyosis.HiCt)]
    assert kinds == [pyosis.OsisHi.BOLD, pyosis.OsisHi.SUPER, pyosis.OsisHi.SUB]


def test_extract_footnotes_top_level_and_nested_italics_match(parser):
    """A direct ``<i>`` yields the same highlight as one wrapped in a transparent ``<span>``."""
    direct = soup_body(
        '<h3>Footnotes</h3><p><a name="fn_1"></a><a href="#x">1</a> a <i>b</i> c</p>'
    )
    nested = soup_body(
        '<h3>Footnotes</h3><p><a name="fn_1"></a><a href="#x">1</a><span> a <i>b</i> c</span></p>'
    )
    assert (
        parser.extract_footnotes(direct)["fn_1"].content_parts
        == parser.extract_footnotes(nested)["fn_1"].content_parts
    )


def test_extract_footnotes_does_not_mutate_source_tree(parser):
    """Extracting footnotes leaves the footnote anchors in the original soup."""
    body = soup_body(FOOTNOTES_HTML)
    parser.extract_footnotes(body)
    assert body.find("a", attrs={"name": "fn_1"}) is not None


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(text=st.from_regex(r"[A-Za-z]+( [A-Za-z]+)*", fullmatch=True))
def test_extract_footnotes_top_level_italic_text_is_preserved(parser, text):
    """Italic text in a footnote round-trips as an italic highlight whatever the text."""
    body = soup_body(f'<h3>Footnotes</h3><p><a name="fn_1"></a><a href="#x">1</a><i>{text}</i></p>')
    parts = parser.extract_footnotes(body)["fn_1"].content_parts
    assert parts == [pyosis.HiCt(type_value=pyosis.OsisHi.ITALIC, content=[text])]


def test_extract_footnotes_ignores_paragraphs_before_footnotes_heading(parser):
    """Anchors outside the ``Footnotes`` section are not collected."""
    body = soup_body('<p><a name="fn_1"></a><a href="#x">1</a> early</p>' + FOOTNOTES_HTML)
    assert "fn_1" in parser.extract_footnotes(body)
    early_only = soup_body('<p><a name="fn_1"></a><a href="#x">1</a> early</p>')
    assert parser.extract_footnotes(early_only) == {}


def test_extract_footnotes_returns_empty_without_footnotes_section(parser):
    """A page with no ``Footnotes`` heading has no footnotes."""
    assert parser.extract_footnotes(soup_body("<h3>T</h3><p>text</p>")) == {}


# --- extract_page_components --------------------------------------------------------------


def test_extract_page_components_returns_headings_and_paragraphs(parser):
    """Headings and paragraph text are separated; footnote references become notes."""
    html = page(
        "Jubilees 1:1 (i. 1)",
        ['1. Word<a name="fr_1"></a><a href="#fn_1">1</a> end'],
        footnotes='<p><a name="fn_1"></a><a href="#fr_1">1</a> Note body</p>',
    )
    headings, paragraphs = parser.extract_page_components(html)
    assert headings == ["Jubilees 1:1 (i. 1)"]
    assert len(paragraphs) == 1
    assert paragraphs[0].text == "1. Word end"
    assert any(isinstance(p, pyosis.NoteCt) for p in paragraphs[0].content_parts)


def test_extract_page_components_filters_site_chrome(parser):
    """Banner, navigation words, bracketed lines, ``Sacred Texts`` paragraphs and ``p. N`` markers are skipped."""
    html = (
        "<html><body>Book of Jubilees"
        "<h1>Jubilees at the Internet Sacred Text Archive</h1>"
        "<h2>Contents</h2><h2>Start Reading</h2><h2>Index</h2><h2>Previous</h2><h2>Next</h2>"
        "<h3>Real Heading</h3>"
        "<p>[paragraph continues]</p><p>Sacred Texts home</p><p>p. 12</p><p>   </p><p><b></b></p>"
        "<p>Kept paragraph</p>"
        "<h3>Footnotes</h3><p>ignored</p></body></html>"
    )
    headings, paragraphs = parser.extract_page_components(html)
    assert headings == ["Real Heading"]
    assert [p.text for p in paragraphs] == ["Kept paragraph"]


def test_extract_page_components_stops_at_footnotes_heading(parser):
    """Nothing after the ``Footnotes`` heading is returned as content."""
    html = page("H", ["body"], footnotes="<p>note text</p>")
    _, paragraphs = parser.extract_page_components(html)
    assert [p.text for p in paragraphs] == ["body"]


def test_extract_page_components_rejects_mirror_markdown(parser):
    """Mirror-derived Markdown or Cloudflare pages are refused."""
    with pytest.raises(RuntimeError, match="expects original sacred-texts HTML"):
        parser.extract_page_components("Markdown Content: Book of Jubilees <html")


def test_extract_page_components_handles_page_without_body_tag(parser):
    """HTML lacking ``<body>`` is still parsed from the document root."""
    html = "<html><h3>Book of Jubilees</h3><p>Text</p></html>"
    headings, paragraphs = parser.extract_page_components(html)
    assert headings == ["Book of Jubilees"] and [p.text for p in paragraphs] == ["Text"]


# --- should_join_with_previous / build_paragraphs ------------------------------------------


@pytest.mark.parametrize(
    ("paragraph", "previous", "expected"),
    [
        ("and then", "Done.", True),
        ("That is", "Done.", True),
        ("that is", "Done.", True),
        ("Which one", "Done.", True),
        ("lowercase start", "Done.", True),
        ("Capital", "He saw the", True),
        ("Capital", "Alpha and", True),
        ("Capital", "Done.", False),
        ("", "Done.", False),
    ],
)
def test_should_join_with_previous_rules(paragraph, previous, expected):
    """Connective prefixes, lowercase starts and dangling words in the previous text trigger joining."""
    assert JubileesParser.should_join_with_previous(paragraph, previous) is expected


def test_build_paragraphs_joins_continuations_and_keeps_markup(parser):
    """A continuation line merges into the previous one, normalising text and merging parts."""
    note = pyosis.NoteCt(type_value="explanation", n="1", content=["N"])
    first = PageParagraph("First line", ["First line"])
    second = PageParagraph("and more", ["and more", note])
    third = PageParagraph("New para.", ["New para."])
    result = parser.build_paragraphs([first, second, third])
    assert [p.text for p in result] == ["First line and more", "New para."]
    assert result[0].content_parts == ["First line and more", note]


def test_build_paragraphs_of_empty_list_is_empty(parser):
    """No lines gives no paragraphs."""
    assert parser.build_paragraphs([]) == []


# --- parse_front_matter_page ----------------------------------------------------------------


def test_parse_front_matter_page_zero_includes_headings_as_paragraphs(parser):
    """On the title page, headings become paragraphs ahead of the body paragraphs."""
    html = page("THE BOOK OF JUBILEES", ["Translated by Charles"], extra_head="<h4>Subtitle</h4>")
    section = parser.parse_front_matter_page(0, html)
    assert section.page_number == 0 and section.title == "Title Page"
    texts = [p.text for p in section.paragraphs]
    assert texts[:2] == ["THE BOOK OF JUBILEES", "Subtitle"] or texts[:2] == [
        "Subtitle",
        "THE BOOK OF JUBILEES",
    ]
    assert texts[-1] == "Translated by Charles"


def test_parse_front_matter_page_drops_lines_repeating_the_title(parser):
    """Paragraphs equal to the section title (any case) are removed; real text stays."""
    html = page("Prologue", ["PROLOGUE", "Prologue", "Real prologue text."])
    section = parser.parse_front_matter_page(11, html)
    assert [p.text for p in section.paragraphs] == ["Real prologue text."]


def test_parse_front_matter_page_drops_title_parts_for_colon_titles(parser):
    """For ``Introduction: X`` titles each colon-separated part counts as a duplicate."""
    html = page("Intro", ["Introduction", "Short Account of the Book", "Body text here."])
    section = parser.parse_front_matter_page(2, html)
    assert section.title == "Introduction: Short Account of the Book"
    assert [p.text for p in section.paragraphs] == ["Body text here."]


def test_parse_front_matter_page_merges_continuation_lines(parser):
    """Fragmentary lines on a front-matter page merge into paragraphs."""
    html = page("Erratum", ["Page 3 reads", "and not that.", "Another."])
    section = parser.parse_front_matter_page(10, html)
    assert [p.text for p in section.paragraphs] == ["Page 3 reads and not that.", "Another."]


# --- extract_chapter_number ------------------------------------------------------------------


def test_extract_chapter_number_prefers_heading_numeral(parser):
    """The Roman numeral in the heading's parentheses wins (case-insensitive)."""
    assert parser.extract_chapter_number("Jubilees 12:1-15 (xii. 1-15)", []) == 12
    assert parser.extract_chapter_number("Jubilees (IV. 3)", []) == 4


def test_extract_chapter_number_falls_back_to_range_line(parser):
    """Without a heading numeral the first paragraph's ``(iii. 1-4).`` range is used."""
    assert parser.extract_chapter_number("Jubilees", [pp("(iii. 1-4).")]) == 3


def test_extract_chapter_number_falls_back_to_chapter_marker(parser):
    """Otherwise an upper-case ``II. `` marker opening the first paragraph is used."""
    assert parser.extract_chapter_number("Jubilees", [pp("XIV. In the year")]) == 14


def test_extract_chapter_number_raises_when_unknown(parser):
    """No source of a chapter number raises, with and without content."""
    with pytest.raises(RuntimeError, match="Could not determine Jubilees chapter"):
        parser.extract_chapter_number("Jubilees", [pp("1. plain verse")])
    with pytest.raises(RuntimeError, match="Could not determine Jubilees chapter"):
        parser.extract_chapter_number("Jubilees", [])


# --- parse_verses ------------------------------------------------------------------------------


def numbers_and_texts(verses: list[VerseBlock], parser: JubileesParser):
    """Summarise verse blocks as ``(numbers, text)`` pairs."""
    return [(v.verse_numbers, parser.extract_text_without_notes(v.content_parts)) for v in verses]


def test_parse_verses_splits_inline_markers(parser):
    """Verses run on within a paragraph and are cut at ``N. `` markers."""
    verses = parser.parse_verses(12, 1, [pp("1. In the first 2. And God said 3. Last.")])
    assert numbers_and_texts(verses, parser) == [
        ([1], "In the first"),
        ([2], "And God said"),
        ([3], "Last."),
    ]


def test_parse_verses_spans_multiple_paragraphs(parser):
    """Paragraphs are joined by a space so a verse can continue into the next paragraph."""
    verses = parser.parse_verses(12, 1, [pp("1. Alpha"), pp("beta 2. Gamma")])
    assert numbers_and_texts(verses, parser) == [([1], "Alpha beta"), ([2], "Gamma")]


def test_parse_verses_drops_leading_range_line_and_completion_line(parser):
    """A ``(i. 1-4).`` range line and the closing ``Herewith ...`` line are removed."""
    lines = [
        pp("(i. 1-4)."),
        pp("1. Text"),
        pp("Herewith is completed the account of the division of the days."),
    ]
    assert numbers_and_texts(parser.parse_verses(12, 1, lines), parser) == [([1], "Text")]


def test_parse_verses_rewrites_leading_chapter_marker_to_verse_one(parser):
    """``II. text`` on the first line becomes verse 1 for chapter 2 (Roman marker removed)."""
    verses = parser.parse_verses(13, 2, [pp("II. And he said 2. Next")])
    assert numbers_and_texts(verses, parser) == [([1], "And he said"), ([2], "Next")]


def test_parse_verses_rejects_chapter_marker_for_other_chapter(parser):
    """The marker's chapter must equal the expected chapter."""
    with pytest.raises(RuntimeError, match="expected 3, got 2"):
        parser.parse_verses(13, 3, [pp("II. text")])


def test_parse_verses_rejects_unrewritable_chapter_marker(parser):
    """If the marker is not in a string part the rewrite fails loudly."""
    hi = pyosis.HiCt(type_value=pyosis.OsisHi.ITALIC, content=["II. x"])
    line = PageParagraph(text="II. x", content_parts=[hi])
    with pytest.raises(RuntimeError, match="Could not rewrite initial Jubilees chapter marker"):
        parser.parse_verses(13, 2, [line])


def test_parse_verses_rejects_empty_content(parser):
    """If nothing remains after dropping furniture lines, parsing raises."""
    with pytest.raises(RuntimeError, match="No Jubilees content paragraphs remained on page 14"):
        parser.parse_verses(14, 1, [pp("(i. 1-4).")])
    with pytest.raises(RuntimeError, match="No Jubilees content paragraphs"):
        parser.parse_verses(14, 1, [])


def test_parse_verses_rejects_text_without_verse_markers(parser):
    """Content with no ``N. `` marker yields no verses and raises."""
    with pytest.raises(RuntimeError, match="No verses parsed for Jubilees page 15"):
        parser.parse_verses(15, 1, [pp("just words")])


def test_parse_verses_keeps_notes_and_highlights_with_their_verse(parser):
    """Non-string parts stay attached to the verse in which they occur."""
    note = pyosis.NoteCt(type_value="explanation", n="1", content=["N"])
    hi = pyosis.HiCt(type_value=pyosis.OsisHi.ITALIC, content=["it"])
    line = PageParagraph("1. a it 2. b", ["1. a ", hi, " 2. b ", note])
    verses = parser.parse_verses(12, 1, [line])
    assert verses[0].content_parts == ["a ", hi]
    assert verses[1].content_parts == ["b ", note] or verses[1].content_parts == ["b", note]


def test_parse_verses_prepends_text_before_first_marker_to_first_verse(parser):
    """Text and parts that precede the first marker are attached to verse 1."""
    hi = pyosis.HiCt(type_value=pyosis.OsisHi.ITALIC, content=["it"])
    line = PageParagraph("lead 1. rest", ["lead ", hi, "1. rest"])
    verses = parser.parse_verses(12, 1, [line])
    assert verses[0].verse_numbers == [1]
    assert verses[0].content_parts == ["lead ", hi, "rest"]


def test_parse_verses_ignores_digits_not_followed_by_period_space(parser):
    """Numbers inside text (``3 days``, ``1.5``) are not verse markers."""
    verses = parser.parse_verses(12, 1, [pp("1. It lasted 3 days and 1.5 years")])
    assert numbers_and_texts(verses, parser) == [([1], "It lasted 3 days and 1.5 years")]


_WORDS = st.text(alphabet=string.ascii_letters + " ,;'", min_size=1).filter(lambda s: s.strip())


@given(st.lists(_WORDS, min_size=1, max_size=10))
def test_parse_verses_numbers_monotonic_and_text_preserved(texts):
    """Generated ``1. a 2. b ...`` paragraphs give verses 1..N whose text is the stripped input."""
    parser = JubileesParser.__new__(JubileesParser)
    paragraph = " ".join(f"{i}. {t}" for i, t in enumerate(texts, start=1))
    verses = parser.parse_verses(12, 1, [pp(paragraph)])
    assert [v.verse_numbers for v in verses] == [[i] for i in range(1, len(texts) + 1)]
    assert [parser.extract_text_without_notes(v.content_parts) for v in verses] == [
        t.strip() for t in texts
    ]


# --- parse_section_page -------------------------------------------------------------------------


def test_parse_section_page_builds_section_with_chapter_and_verses(parser):
    """The first heading titles the section and gives the chapter; paragraphs become verses."""
    html = page("Jubilees 2:1-3 (ii. 1-3)", ["1. One 2. Two"])
    section = parser.parse_section_page(14, html)
    assert section.page_number == 14 and section.chapter_number == 2
    assert section.title == "Jubilees 2:1-3 (ii. 1-3)"
    assert [v.verse_numbers for v in section.verses] == [[1], [2]]


def test_parse_section_page_requires_heading(parser):
    """A page with no heading raises."""
    html = "<html><body>Book of Jubilees<p>1. text</p></body></html>"
    with pytest.raises(RuntimeError, match="Missing section heading for Jubilees page 20"):
        parser.parse_section_page(20, html)


# --- generate_osis -----------------------------------------------------------------------------


def _document() -> pyosis.OsisXML:
    """Build OSIS for a title page, one front section, and chapter 1 with two sections."""
    note = pyosis.NoteCt(type_value="explanation", n="1", content=["Note text"])
    front = [
        FrontMatterSection(0, "Title Page", [pp("The Book")]),
        FrontMatterSection(1, "Editors' Preface", [pp("Preface text")]),
    ]
    sec1 = Section(12, "Jubilees 1:1 (i. 1)", 1, [VerseBlock([1], ["First ", note])])
    sec2 = Section(13, "Jubilees 1:2 (i. 2)", 1, [VerseBlock([2, 3], ["Second"])])
    return JubileesParser.generate_osis(front, [Chapter(1, [sec1, sec2])])


def test_generate_osis_emits_chapters_sections_and_verse_ids():
    """Each section becomes ``Jub.<c>.s<n>`` and verses carry ``Jub.<c>.<v>`` ids (several for groups)."""
    xml = _document().to_xml()
    for expected in (
        'osisID="Jub.1"',
        'osisID="Jub.1.s1"',
        'osisID="Jub.1.s2"',
        'osisID="Jub.1.1"',
    ):
        assert expected in xml
    assert "Jub.1.2 Jub.1.3" in xml
    assert "Note text" in xml


def test_generate_osis_marks_page_zero_as_title_page_and_rest_as_front():
    """Page 0 is a ``titlePage`` div; other front matter is ``front``; both are non-canonical."""
    book = _document().osis.osis_text.div[0]
    divs = [d for d in book.content if isinstance(d, pyosis.DivCt)]
    assert [d.type_value for d in divs[:2]] == [pyosis.OsisDivs.TITLE_PAGE, pyosis.OsisDivs.FRONT]
    assert all(d.canonical is False for d in divs[:2])


def test_generate_osis_header_names_work_and_edition():
    """The header names the work, the 1917 edition, translator and publisher."""
    xml = _document().to_xml()
    assert 'osisIDWork="Jub"' in xml and "1917" in xml
    assert "Society for Promoting Christian Knowledge" in xml
    assert "Robert Henry (R.H.) Charles" in xml


# --- process / run / SPEC ------------------------------------------------------------------------


def _front_page(number: int) -> str:
    """Build a minimal front-matter page for ``number``."""
    return page(_front_title(number), [f"Body of page {number}."])


def _front_title(number: int) -> str:
    """Return the page heading used for front-matter page ``number``."""
    return jubilees.FRONT_MATTER_TITLES[number]


def _content_page(number: int) -> str:
    """Build a section page for page ``number``, cycling pages over chapters 1 to 50."""
    chapter = (number - jubilees.CONTENT_START_PAGE) % 50 + 1
    heading = f"Jubilees {chapter}:1-2 ({int_to_roman(chapter).lower()}. 1-2)"
    return page(heading, [f"1. Verse one of page {number} 2. Verse two."])


def _site() -> dict[str, str]:
    """Map every Jubilees page URL to a minimal valid page."""
    pages = {}
    for number in range(jubilees.PAGE_RANGE[0], jubilees.PAGE_RANGE[1] + 1):
        build = _front_page if number <= jubilees.FRONT_MATTER_END_PAGE else _content_page
        pages[JubileesParser.page_url(number)] = build(number)
    return pages


def test_process_assembles_chapters_from_all_pages(parser, monkeypatch):
    """``process`` fetches pages 0..87, groups sections by chapter and emits all 50 chapters."""
    calls = stub_fetch(parser, monkeypatch, _site())
    xml = parser.process().to_xml()
    assert len(calls) == 88
    assert 'osisID="Jub.50.2"' in xml and 'osisID="Jub.1.s2"' in xml


def test_process_rejects_missing_chapters(parser, monkeypatch):
    """If a chapter never appears the chapter sequence check fails."""
    pages = _site()
    for number in range(jubilees.CONTENT_START_PAGE, jubilees.PAGE_RANGE[1] + 1):
        if (number - jubilees.CONTENT_START_PAGE) % 50 + 1 == 7:
            pages[JubileesParser.page_url(number)] = pages[JubileesParser.page_url(number - 1)]
    stub_fetch(parser, monkeypatch, pages)
    with pytest.raises(RuntimeError, match="Unexpected Jubilees chapter sequence"):
        parser.process()


def test_add_arguments_registers_nothing():
    """Jubilees has no own options, so the parser gains no arguments."""
    arg_parser = argparse.ArgumentParser()
    before = list(arg_parser._actions)
    jubilees.add_arguments(arg_parser)
    assert arg_parser._actions == before


def test_run_writes_output_file_using_prepopulated_cache(tmp_path):
    """``run`` reads pages from a pre-populated cache and writes ``jubilees.xml``."""
    cache = tmp_path / "cache"
    for url, text in _site().items():
        path = cache / url.split("://", 1)[1]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    out = tmp_path / "out" / "deep"
    paths = jubilees.run(argparse.Namespace(output_dir=out, cache_dir=cache, delay=0))
    assert paths == [out / "jubilees.xml"]
    assert 'osisID="Jub.50.1"' in paths[0].read_text(encoding="utf-8")


def test_run_closes_parser_and_propagates_errors(tmp_path, monkeypatch):
    """A failure inside ``process`` propagates and the parser is still closed."""
    closed: list[bool] = []

    def boom(self):
        """Fail like a broken scrape."""
        raise RuntimeError("boom")

    monkeypatch.setattr(JubileesParser, "process", boom)
    monkeypatch.setattr(JubileesParser, "close", lambda self: closed.append(True))
    with pytest.raises(RuntimeError, match="boom"):
        jubilees.run(argparse.Namespace(output_dir=tmp_path, cache_dir=None, delay=0))
    assert closed == [True]


def test_spec_describes_scraper():
    """``SPEC`` registers the scraper's name, output file and entry points."""
    assert jubilees.SPEC.name == "jubilees"
    assert jubilees.SPEC.outputs == (jubilees.OUTPUT_FILENAME,)
    assert jubilees.SPEC.run is jubilees.run
    assert jubilees.SPEC.add_arguments is jubilees.add_arguments


# --- redesigned reader layout ---------------------------------------------------------

READER_FIXTURES = Path(__file__).parent / "fixtures" / "reader_layout"
"""Trimmed copies of real redesigned sacred-texts.com pages."""


def reader_fixture(name: str) -> str:
    """Return the text of a reader-layout fixture page."""
    return (READER_FIXTURES / name).read_text(encoding="utf-8")


def test_is_valid_page_accepts_reader_layout_page():
    """A redesigned reader-layout page still counts as a genuine Jubilees page."""
    assert JubileesParser.is_valid_page(reader_fixture("jub13.htm"))


def test_extract_page_components_ignores_reader_layout_chrome(parser):
    """The "Chapters" sidebar heading and other panels are not taken as headings."""
    headings, paragraphs = parser.extract_page_components(reader_fixture("jub13.htm"))
    assert headings == ["God commands the Angel to write (i. 27-29)."]
    assert [p.text[:30] for p in paragraphs] == [
        "27. And He said to the angel o",
        "of all, and all will know that",
    ]


def test_parse_section_page_reads_reader_layout_verses_and_footnotes(parser):
    """Verses and their footnote notes (with page:note labels) come out of a reader page."""
    section = parser.parse_section_page(13, reader_fixture("jub13.htm"))
    assert section.title == "God commands the Angel to write (i. 27-29)."
    assert section.chapter_number == 1
    assert [verse.verse_numbers for verse in section.verses] == [[27], [28], [29]]
    labels = [
        [part.n for part in verse.content_parts if isinstance(part, pyosis.NoteCt)]
        for verse in section.verses
    ]
    assert labels == [
        ["39:6", "39:7"],
        ["39:8", "40:1", "40:2", "40:3"],
        ["40:4", "40:5", "40:6", "40:7", "40:8"],
    ]
    first_note = section.verses[0].content_parts[1]
    assert isinstance(first_note, pyosis.NoteCt)
    assert any(isinstance(part, pyosis.HiCt) for part in first_note.content)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("of the 2450 A.M. (A.M. = Anno Mundi) exodus", "of the exodus"),
        ("from the day of 1309-1659 A.M. Noah's death", "from the day of Noah's death"),
        ("fourth year (99-127) 130 A.M. of the", "fourth year of the"),
        ("of Dânêl, 587 AM. the daughter", "of Dânêl, the daughter"),
        ("fourteenth 652 A M. jubilee", "fourteenth jubilee"),
        ("1-25). 2057 (?2050) A.M. XXI. And", "1-25). XXI. And"),
        ("nation. 195 I A.M. p. 91", "nation. 195 I A.M. p. 91"),
        ("in the 2450th year", "in the 2450th year"),
    ],
)
def test_margin_date_re_removes_flattened_anno_mundi_dates(text, expected):
    """Margin dates and their variants are removed; other text is left alone."""
    assert jubilees.MARGIN_DATE_RE.sub("", text) == expected


@given(st.integers(min_value=1, max_value=2450), st.integers(min_value=0, max_value=50))
def test_margin_date_re_removes_any_year_or_range(start, length):
    """Any ``N A.M.`` or ``N-M A.M.`` date between two words is removed with its space."""
    date = f"{start} A.M." if length == 0 else f"{start}-{start + length} A.M."
    assert jubilees.MARGIN_DATE_RE.sub("", f"before {date} after") == "before after"


def test_strip_margin_dates_rewrites_text_nodes_in_place():
    """Every matching text node under the body is rewritten; markup is kept."""
    body = soup_body("<p>of the 2450 A.M. exodus <i>in 8 A.M. May</i></p>")
    JubileesParser.strip_margin_dates(body)
    assert str(body.find("p")) == "<p>of the exodus <i>in May</i></p>"


def test_extract_page_components_strips_margin_dates_only_on_reader_pages(parser):
    """Reader pages lose flattened margin dates; old pages keep any text outside tables."""
    paragraph = "<p>1. And in the first week 1-7 A.M. of the first jubilee.</p>"
    old_page = page("Jubilees 3:1-35 (iii. 1-35)", [paragraph])
    _, old_paragraphs = parser.extract_page_components(old_page)
    assert old_paragraphs[0].text == "1. And in the first week 1-7 A.M. of the first jubilee."

    reader_page = reader_fixture("jub13.htm").replace(
        "27. And He said", "27. And in the first week 1-7 A.M. He said"
    )
    _, reader_paragraphs = parser.extract_page_components(reader_page)
    assert reader_paragraphs[0].text.startswith("27. And in the first week He said")
