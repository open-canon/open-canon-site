"""Unit tests for ``open_canon_site.scrapers.sacred_texts._layout`` (offline)."""

from __future__ import annotations

import string
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from hypothesis import given
from hypothesis import strategies as st
from open_canon_site.scrapers.sacred_texts import _layout
from open_canon_site.scrapers.sacred_texts._layout import (
    book_overview_parts,
    is_book_overview_layout,
    is_reader_layout,
    legacy_html,
    page_title,
    reader_page_to_legacy,
)

FIXTURES = Path(__file__).parent / "fixtures" / "reader_layout"
"""Trimmed copies of real redesigned sacred-texts.com pages."""


def fixture(name: str) -> str:
    """Return the text of a reader-layout fixture page."""
    return (FIXTURES / name).read_text(encoding="utf-8")


def reader_page(prose: str, footnotes: str = "", title: str = "A Page") -> str:
    """Build a minimal reader-layout page around ``prose`` with typical chrome."""
    footnote_section = ""
    if footnotes:
        footnote_section = (
            '<section data-slot="reader-footnotes"><details open><summary>'
            "<h2>Footnotes</h2></summary><ol>"
            f"{footnotes}</ol></details></section>"
        )
    return (
        f"<!doctype html><html><head><title>{title}</title></head><body>"
        "<div>View the original site, visit archive.sacred-texts.com</div>"
        '<main><div data-slot="reader-page">'
        '<aside aria-label="Chapters" data-slot="reader-chapter-sidebar">'
        "<h2>Chapters</h2><ol><li><a href='/book/x/start-reading'>Start Reading</a></li></ol>"
        "</aside>"
        '<article data-slot="reader-content"><!--[0--><h1 class="sr-only">Title copy</h1><!--]-->'
        '<div data-slot="reader-prose"><!-- --><div data-slot="ad-content">'
        f"{prose}</div></div>{footnote_section}</article>"
        '<section data-slot="reader-community-coming-soon">'
        "<h2>Comments and social are coming soon</h2></section>"
        '<aside data-slot="reader-saved-sidebar"><header><h2>Saved</h2></header></aside>'
        "</div></main><footer>Internet Sacred Text Archive</footer></body></html>"
    )


def footnote_item(item_id: str, label: str, body: str) -> str:
    """Build one reader-layout footnote list item."""
    return (
        f'<li data-slot="reader-footnote" id="{item_id}">'
        f'<a data-slot="reader-footnote-label" href="#ref-{item_id}">{label}</a>'
        f'<div><div data-slot="reader-footnote-body"><a></a> {body} <p></p></div></div></li>'
    )


def body_of(document: str) -> BeautifulSoup:
    """Rebuild ``document`` with ``legacy_html`` (a no-op if already rebuilt); return its body."""
    soup = BeautifulSoup(legacy_html(document), "html.parser")
    assert soup.body is not None
    return soup.body


# --- layout detection -----------------------------------------------------------------


def test_is_reader_layout_detects_reader_content_slot():
    """A page with ``data-slot="reader-content"`` is a reader-layout page."""
    assert is_reader_layout(reader_page("<p>x</p>"))
    assert is_reader_layout("<article data-slot='reader-content'></article>")


def test_is_reader_layout_rejects_old_layout_pages():
    """An old sacred-texts page, or a different slot name, is not a reader page."""
    assert not is_reader_layout("<HTML><BODY><H3>CHAPTER I.</H3><P>1. Text</P></BODY></HTML>")
    assert not is_reader_layout('<div data-slot="reader-contents-list"></div>')


def test_is_book_overview_layout_detects_about_module():
    """The ``book-overview-about`` module marks a redesigned book overview page."""
    assert is_book_overview_layout(fixture("jasher-index.htm"))
    assert not is_book_overview_layout(fixture("jasher-1.htm"))
    assert not is_book_overview_layout("<HTML><BODY>index</BODY></HTML>")


def test_page_title_normalizes_whitespace_and_handles_missing_title():
    """The ``<title>`` text is whitespace-normalised; no title gives ``""``."""
    assert page_title(BeautifulSoup("<title>  A \n title </title>", "html.parser")) == "A title"
    assert page_title(BeautifulSoup("<p>none</p>", "html.parser")) == ""


# --- legacy_html ------------------------------------------------------------------------


@given(st.text(alphabet=string.printable))
def test_legacy_html_returns_non_reader_text_unchanged(text):
    """Anything that is not a reader-layout page is returned as is."""
    if is_reader_layout(text):
        return
    assert legacy_html(text) is text


def test_legacy_html_is_idempotent_on_reader_pages():
    """Rebuilding an already rebuilt page changes nothing."""
    once = legacy_html(fixture("jub13.htm"))
    assert legacy_html(once) == once
    assert not is_reader_layout(once)


def test_reader_page_to_legacy_requires_reader_content():
    """A page without the reader-content element cannot be rebuilt."""
    with pytest.raises(ValueError, match="reader-content"):
        reader_page_to_legacy("<html><body><p>old</p></body></html>")


def test_reader_page_to_legacy_drops_chrome_and_title_copy():
    """Sidebar, comments, saved panel, footer and the screen-reader ``<h1>`` are removed."""
    document = legacy_html(reader_page("<h3>CHAPTER I.</h3> <p>1. Text.</p>", title="Chapter I"))
    body = body_of(document)
    text = body.get_text(" ", strip=True)
    for chrome in ("Chapters", "Comments and social", "Saved", "Title copy", "archive."):
        assert chrome not in text
    assert [h.get_text() for h in body.find_all(["h1", "h3"])] == ["CHAPTER I."]
    assert BeautifulSoup(document, "html.parser").title.get_text() == "Chapter I"
    assert "<!--" not in document


def test_reader_page_to_legacy_falls_back_to_article_without_prose_slot():
    """Without ``reader-prose`` the whole article is the content (title copy included)."""
    page = (
        '<html><body><article data-slot="reader-content"><h3>Heading</h3><p>Text</p>'
        "</article></body></html>"
    )
    body = body_of(reader_page_to_legacy(page))
    assert body.find("h3").get_text() == "Heading"
    assert body.find("p").get_text() == "Text"


def test_reader_page_to_legacy_closes_content_with_hr_and_strips_attributes():
    """The content ends with ``<hr/>`` and reader classes and data attributes are gone."""
    document = legacy_html(reader_page('<p class="prose" data-x="1" align="center">Text</p>'))
    assert "<p>Text</p>\n<hr/>" in document
    assert "class=" not in document.split("<body>", 1)[1]


def test_restore_legacy_headings_renames_demoted_h1():
    """``<div data-legacy-h1 role="heading">`` becomes an ``<h1>`` again."""
    document = reader_page(
        '<h1>THE</h1> <div aria-level="1" data-legacy-h1="" role="heading">BOOK OF ENOCH</div>'
    )
    assert [h.get_text() for h in body_of(document).find_all("h1")] == ["THE", "BOOK OF ENOCH"]


@given(
    st.one_of(
        st.integers(min_value=1, max_value=999).map(str),
        st.sampled_from(["i", "iv", "xvii", "xlix", "cxx", "XL"]),
    )
)
def test_restore_page_markers_rebuilds_named_green_anchor(page):
    """A bare ``<a>p. N</a>`` regains its ``page_N`` name and green font."""
    body = body_of(reader_page(f"<p><a>p. {page}</a></p>"))
    anchor = body.find("a")
    assert anchor["name"] == f"page_{page}"
    font = anchor.find("font")
    assert font["color"] == "green"
    assert font.get_text() == f"p. {page}"


def test_restore_page_markers_leaves_other_links_alone():
    """Links with attributes, or whose text is not a page marker, are not touched."""
    body = body_of(reader_page('<p><a>see p. 4 below</a> <a href="#x">p. 5</a></p>'))
    anchors = body.find_all("a")
    assert "name" not in anchors[0].attrs
    assert anchors[1].attrs == {"href": "#x"}


def test_wrap_loose_text_puts_flattened_paragraph_back_in_p():
    """Bare text left between paragraphs (a broken old ``<p>``) is wrapped in ``<p>``."""
    body = body_of(
        reader_page("<p>first</p> <p><a>p. 63</a></p> of weeks <i>now</i> and more <p>last</p>")
    )
    texts = [p.get_text(" ", strip=True) for p in body.find_all("p")]
    assert texts == ["first", "p. 63", "of weeks now and more", "last"]


def test_wrap_loose_text_leaves_punctuation_and_block_inline_elements_loose():
    """Stray punctuation and an inline element wrapping a block stay outside ``<p>``."""
    body = body_of(reader_page("<h3>CHAP. V.</h3> <i> <p>Summary</p></i>. <p>1 Text</p>"))
    container = body
    assert [p.get_text(strip=True) for p in container.find_all("p")] == ["Summary", "1 Text"]
    assert container.find("i").parent is container


def test_rebuild_footnotes_converts_references_and_notes_to_fr_fn_anchors():
    """References become ``fr_N``/``#fn_N`` pairs and notes ``fn_N``/``#fr_N`` paragraphs."""
    prose = (
        '<p>Text <a></a><a data-footnote-ref="39:6" href="#fn-a" id="ref-fn-a">6</a> more'
        ' <a data-footnote-ref="39:7" href="#fn-b" id="ref-fn-b">7</a></p>'
    )
    notes = footnote_item("fn-a", "39:6", "Cf. <i>Isa.</i>") + footnote_item(
        "fn-b", "39:7", "<p>Read this.</p>"
    )
    body = body_of(reader_page(prose, notes))

    paragraph = body.find("p")
    anchors = paragraph.find_all("a")
    assert [a.attrs for a in anchors] == [
        {"name": "fr_1"},
        {"href": "#fn_1"},
        {"name": "fr_2"},
        {"href": "#fn_2"},
    ]
    assert [a.get_text() for a in anchors] == ["", "6", "", "7"]

    heading = body.find("h3")
    assert heading.get_text() == "Footnotes"
    footnotes = heading.find_next_siblings("p")
    assert [p.find("a")["name"] for p in footnotes] == ["fn_1", "fn_2"]
    assert [p.find_all("a")[1]["href"] for p in footnotes] == ["#fr_1", "#fr_2"]
    assert [p.find_all("a")[1].get_text() for p in footnotes] == ["39:6", "39:7"]
    assert footnotes[0].find("i").get_text() == "Isa."
    assert footnotes[1].get_text(" ", strip=True) == "39:7 Read this."
    assert footnotes[1].find("p") is None
    assert body.find_all("hr")[-1].find_previous_sibling("p") is footnotes[-1]


def test_rebuild_footnotes_numbers_unlisted_references_after_listed_notes():
    """A reference without a listed note gets the next free number."""
    prose = '<p><a></a><a data-footnote-ref="1" href="#missing">1</a></p>'
    body = body_of(reader_page(prose, footnote_item("fn-a", "1:1", "Note.")))
    assert body.find("p").find_all("a")[1]["href"] == "#fn_2"


def test_rebuild_footnotes_skips_items_without_id():
    """A footnote list item without an ``id`` cannot be linked and is dropped."""
    notes = '<li data-slot="reader-footnote"><div data-slot="reader-footnote-body">x</div></li>'
    document = legacy_html(reader_page("<p>Text</p>", notes))
    assert "Footnotes" not in document
    assert "fn_" not in document


def test_rebuild_footnotes_handles_missing_label_and_body():
    """A footnote without label or body still yields an anchored paragraph."""
    document = reader_page("<p>Text</p>", '<li data-slot="reader-footnote" id="fn-z"></li>')
    paragraph = body_of(document).find("h3").find_next_sibling("p")
    assert paragraph.find("a")["name"] == "fn_1"
    assert paragraph.get_text(strip=True) == ""


def test_page_without_footnotes_has_no_footnotes_heading():
    """Without footnotes no ``Footnotes`` heading is emitted."""
    assert "Footnotes" not in reader_page_to_legacy(reader_page("<p>Text</p>"))


def test_is_empty_anchor():
    """Only an attribute-less ``<a>`` without text counts as an empty anchor."""
    soup = BeautifulSoup('<a></a><a name="x"></a><a>t</a><b></b>', "html.parser")
    tags = soup.find_all(True)
    assert [_layout._is_empty_anchor(tag) for tag in tags] == [True, False, False, False]
    assert not _layout._is_empty_anchor("text")


def test_legacy_document_escapes_title():
    """The title is HTML-escaped inside ``<title>``."""
    document = _layout._legacy_document("A & <B>", ["<p>x</p>"])
    assert "<title>A &amp; &lt;B&gt;</title>" in document
    assert "<body>\n<p>x</p>\n</body>" in document


# --- fixtures -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["jub13.htm", "boe000.htm", "boe010.htm", "fbe010.htm", "jasher-1.htm", "adamnev.htm"],
)
def test_fixture_pages_rebuild_without_chrome(name):
    """Every reader-layout fixture rebuilds without sidebar or panel text."""
    raw = fixture(name)
    assert is_reader_layout(raw)
    text = body_of(legacy_html(raw)).get_text(" ", strip=True)
    assert "Comments and social" not in text
    assert "Start Reading" not in text
    assert "Saved" not in text
    assert "archive.sacred-texts.com" not in text


def test_jubilees_fixture_keeps_page_marker_and_footnotes():
    """The Jubilees fixture regains its ``p. 40`` marker and all eleven footnotes."""
    body = body_of(legacy_html(fixture("jub13.htm")))
    assert body.find("a", attrs={"name": "page_40"}) is not None
    notes = body.find_all("a", attrs={"name": lambda name: name and name.startswith("fn_")})
    assert len(notes) == 11
    assert notes[0].find_next_sibling("a").get_text() == "39:6"


# --- book overview pages ----------------------------------------------------------------


def test_book_overview_parts_reads_title_about_and_chapter_count():
    """Title, "About this book" paragraphs and chapter count come from the first modules."""
    title, about, count = book_overview_parts(fixture("jasher-index.htm"))
    assert title == "The Book of Jasher"
    assert len(about) == 2
    assert about[0].startswith("<p>")
    assert "<cite>Books of Jasher</cite>" in about[0]
    assert count == 91


def test_book_overview_parts_falls_back_to_page_title_and_handles_missing_modules():
    """Without title, about or table-of-contents modules the parts are empty or ``None``."""
    page = "<html><head><title>Some Book</title></head><body><p>x</p></body></html>"
    assert book_overview_parts(page) == ("Some Book", [], None)


def test_book_overview_parts_skips_empty_paragraphs_and_non_count_lines():
    """Blank blurb paragraphs and table-of-contents text that is not a count are ignored."""
    page = (
        '<article data-module-id="book-overview-title"><h1>Book</h1></article>'
        '<article data-module-id="book-overview-about"><p> </p><p class="x">Blurb</p></article>'
        '<article data-module-id="book-overview-table-of-contents">'
        "<div><h2>Table of contents</h2><p>Chapters</p><span>3 chapters</span></div></article>"
    )
    assert book_overview_parts(page) == ("Book", ["<p>Blurb</p>"], 3)


@pytest.mark.parametrize(
    ("prose", "expected"),
    [
        ('<p>Text <a></a><a data-footnote-ref="1" href="#fn-a">1</a></p>', "Text\xa0"),
        ('<p>Text<a data-footnote-ref="1" href="#fn-a">1</a></p>', "Text\xa0"),
        ('<p>Text\xa0<a></a><a data-footnote-ref="1" href="#fn-a">1</a></p>', "Text\xa0"),
        ('<p><a data-footnote-ref="1" href="#fn-a">1</a></p>', "\xa0"),
        ('<p><i>Text</i><a></a><a data-footnote-ref="1" href="#fn-a">1</a></p>', "\xa0"),
    ],
)
def test_rebuild_footnotes_restores_no_break_space_before_reference(prose, expected):
    """Old pages always had ``&nbsp;`` before ``fr_N``; it is put back exactly once."""
    body = body_of(reader_page(prose, footnote_item("fn-a", "1:1", "Note.")))
    anchor = body.find("a", attrs={"name": "fr_1"})
    assert anchor.previous_sibling == expected


@given(st.text(alphabet=string.ascii_letters + " ", min_size=1).filter(lambda t: t.strip()))
def test_restore_reference_space_ends_text_with_single_no_break_space(text):
    """Whatever the preceding text, it ends with exactly one U+00A0 and no plain space."""
    soup = BeautifulSoup(f'<p>{text}<a name="fr_1"></a></p>', "html.parser")
    anchor = soup.find("a")
    _layout._restore_reference_space(anchor)
    previous = str(anchor.previous_sibling)
    assert previous.endswith("\xa0")
    assert not previous.endswith(" \xa0") or text.endswith("  ")
    assert previous.rstrip("\xa0") == (text[:-1] if text.endswith(" ") else text)


def test_reader_page_to_legacy_restores_newline_between_adjacent_blocks():
    """``</p><p>`` gains the newline old pages had, so joined paragraphs keep a space."""
    document = legacy_html(reader_page("<h3>H</h3><p>one</p><p>two</p>"))
    assert "<h3>H</h3>\n<p>one</p>\n<p>two</p>\n<hr/>" in document


@given(st.lists(st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=6), min_size=2))
def test_block_end_re_only_adds_newlines_after_closing_blocks(words):
    """Only block end tags directly followed by a tag get a newline; text is untouched."""
    markup = "".join(f"<p>{word}</p>" for word in words)
    result = _layout.BLOCK_END_RE.sub(r"\1\n", markup)
    assert result.replace("\n", "") == markup
    assert result.count("\n") == len(words) - 1


@pytest.mark.parametrize(
    ("label", "body", "expected_label", "expected_body"),
    [
        ("1", "viii:1 <i>Jewish</i> pp. 15", "viii:1", "<i>Jewish</i> pp. 15"),
        ("2", "12:3 Plain note.", "12:3", "Plain note."),
        ("39:6", "Cf. Isa. 5:1", "39:6", "Cf. Isa. 5:1"),
        ("1", "Cf. Isa. 5:1 and more", "1", "Cf. Isa. 5:1 and more"),
        ("1", "xi:1x not a label", "1", "xi:1x not a label"),
    ],
)
def test_rebuild_footnotes_moves_page_note_label_from_body(
    label, body, expected_label, expected_body
):
    """A leading ``page:note`` token in the note text becomes the label when the label is bare."""
    notes = footnote_item("fn-a", label, body)
    prose = '<p>Text <a></a><a data-footnote-ref="1" href="#fn-a">1</a></p>'
    paragraph = body_of(reader_page(prose, notes)).find("h3").find_next_sibling("p")
    assert paragraph.find_all("a")[1].get_text() == expected_label
    remainder = "".join(str(node) for node in list(paragraph.children)[2:]).strip()
    assert remainder == expected_body


def test_label_from_body_without_text_keeps_label():
    """A note whose body has no text node leaves the label alone."""
    body = BeautifulSoup("<div><br/></div>", "html.parser").div
    link = BeautifulSoup('<a href="#fr_1">1</a>', "html.parser").a
    assert _layout._label_from_body(body, "1", link) == "1"
    assert link.get_text() == "1"


def test_wrap_loose_text_trims_leading_whitespace_of_wrapped_paragraph():
    """A wrapped run starts at its first word, so a leading verse number stays matchable."""
    body = body_of(reader_page("<p>one</p>\n   9. And he answered <b>me</b> <p>two</p>"))
    texts = [str(p) for p in body.find_all("p")]
    assert texts[1] == "<p>9. And he answered <b>me</b> </p>"


def test_clean_footnote_body_keeps_a_space_between_unwrapped_paragraphs():
    """Footnote paragraphs are merged into one with a space, not glued together."""
    notes = footnote_item("fn-a", "1:1", "First part.</p><p>Second part.")
    prose = '<p>Text <a></a><a data-footnote-ref="1" href="#fn-a">1</a></p>'
    paragraph = body_of(reader_page(prose, notes)).find("h3").find_next_sibling("p")
    assert "First part. Second part." in paragraph.get_text()


# --- close_character_references ------------------------------------------------------------


def test_close_character_references_adds_missing_semicolons():
    """``&#7730araite`` becomes ``&#7730;araite``; closed and named references are untouched."""
    from open_canon_site.scrapers.sacred_texts._layout import close_character_references

    assert close_character_references("&#7730araite &#146 x") == "&#7730;araite &#146; x"
    assert close_character_references("&#7730; &amp; &eacute;") == "&#7730; &amp; &eacute;"


def test_legacy_html_keeps_the_rest_of_a_page_after_an_unterminated_reference():
    """The malformed reference no longer swallows the markup that follows it."""
    from bs4 import BeautifulSoup

    html = "<html><body><p>and &#7730araite Jews.</p><h3>Footnotes</h3></body></html>"
    soup = BeautifulSoup(legacy_html(html), "html.parser")
    assert soup.find("h3") is not None
