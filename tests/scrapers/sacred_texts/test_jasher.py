"""Unit tests for ``open_canon_site.scrapers.sacred_texts.jasher`` (offline, inline HTML)."""

from __future__ import annotations

import argparse
import string
from pathlib import Path

import pyosis
import pytest
from hypothesis import given
from hypothesis import strategies as st
from open_canon_site.scrapers.sacred_texts import jasher
from open_canon_site.scrapers.sacred_texts.jasher import (
    Chapter,
    FrontMatterSection,
    JasherParser,
    Verse,
)

CHAPTER_LINKS = "".join(f'<A HREF="{n}.htm">Chapter {n}</A>\n' for n in range(1, 92))

INDEX_HTML = (
    "<HTML><BODY><H1>The Book of Jasher</H1>\n"
    "<CENTER><H6>Referred to in Joshua</H6><H5>Translated</H5>"
    "<FONT>Faithfully Translated<BR>From the Hebrew</FONT></CENTER>\n"
    "<P>A short introduction.\n<P>Second intro paragraph.\n"
    f"{CHAPTER_LINKS}"
    "<HR>Sacred Texts footer</BODY></HTML>"
)
"""A minimal index page that satisfies ``is_valid_index`` (links to chapters 1 to 91)."""


def chapter_html(number: int, body: str = "<P>1 First verse<P>2 Second verse") -> str:
    """Build a minimal chapter page with a heading, bare ``<P>`` verses and a footer ``<HR>``."""
    return (
        f"<HTML><BODY><H1>Book of Jasher, Chapter {number}</H1>\n{body}\n"
        "<P>THE END<HR>Next: Chapter 2 | Sacred Texts | Christianity</BODY></HTML>"
    )


@pytest.fixture
def parser(tmp_path):
    """Return a parser with a tmp cache directory, closed after the test."""
    instance = JasherParser(cache_dir=str(tmp_path / "cache"), delay=0)
    yield instance
    instance.close()


def cache_file(parser: JasherParser, url: str):
    """Return the cache path for ``url`` on this parser's fetcher."""
    path = parser.http.cache_path_for(url)
    assert path is not None
    return path


def stub_fetch(parser: JasherParser, monkeypatch, pages: dict[str, str]):
    """Replace the fetcher's network call with a lookup in ``pages``; return the URL call log."""
    calls: list[str] = []

    def fake_fetch_text(*, url: str, retry_count: int = 3) -> str:
        """Record the URL and return its canned page."""
        calls.append(url)
        return pages[url]

    monkeypatch.setattr(parser.http, "fetch_text", fake_fetch_text)
    return calls


# --- __init__ / close -----------------------------------------------------------------


def test_init_builds_fetcher_with_cache_and_delay(tmp_path):
    """The parser's fetcher uses the given cache directory and delay."""
    instance = JasherParser(cache_dir=str(tmp_path / "c"), delay=2.5)
    assert instance.http.cache_dir == tmp_path / "c"
    assert instance.http.delay == 2.5
    instance.close()


def test_init_without_cache_dir_disables_caching():
    """No cache directory means no cache path for any URL."""
    instance = JasherParser(delay=0)
    assert instance.http.cache_path_for(jasher.INDEX_URL) is None
    instance.close()


def test_close_closes_http_client(parser):
    """``close`` closes the underlying httpx client."""
    parser.close()
    assert parser.http._client.is_closed


# --- validators -----------------------------------------------------------------------


def test_is_valid_index_accepts_genuine_page():
    """The sample index page is accepted."""
    assert JasherParser.is_valid_index(INDEX_HTML)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda t: t.replace("The Book of Jasher", "Other"),
        lambda t: t.replace("Faithfully Translated", "Unfaithfully"),
        lambda t: t.replace('<A HREF="91.htm">Chapter 91</A>', ""),
        lambda t: t + "Just a moment...",
    ],
    ids=["title", "subtitle", "last-link", "cloudflare"],
)
def test_is_valid_index_rejects_incomplete_or_interstitial(mutate):
    """Missing title, subtitle or chapter-91 link, or a Cloudflare notice, invalidates the index."""
    assert not JasherParser.is_valid_index(mutate(INDEX_HTML))


def test_is_valid_chapter_page_accepts_bare_p_verse_one():
    """A chapter page with its heading and an unclosed ``<P>1 ...`` is valid."""
    assert JasherParser.is_valid_chapter_page(chapter_html(7), 7)


def test_is_valid_chapter_page_accepts_uppercase_p_with_attributes():
    """The verse-1 check is case-insensitive and tolerates tag attributes."""
    text = '<h1>Book of Jasher, Chapter 3</h1><P ALIGN="left"> 1 In the beginning'
    assert JasherParser.is_valid_chapter_page(text, 3)


def test_is_valid_chapter_page_rejects_wrong_chapter():
    """A page for another chapter number is invalid."""
    assert not JasherParser.is_valid_chapter_page(chapter_html(7), 8)


def test_is_valid_chapter_page_rejects_interstitial():
    """Cloudflare's "Just a moment" page is invalid even if it mentions the heading."""
    assert not JasherParser.is_valid_chapter_page(chapter_html(7) + "Just a moment", 7)


def test_is_valid_chapter_page_requires_verse_one_paragraph():
    """A page without a ``<P>1 `` paragraph is invalid."""
    assert not JasherParser.is_valid_chapter_page(chapter_html(7, "<P>2 Only second"), 7)


# --- _fetch_validated_page / fetch_index_text / fetch_chapter_text ---------------------


def test_fetch_validated_page_returns_valid_cache_without_network(parser, monkeypatch):
    """A valid cached page is returned and the network is never used."""
    path = cache_file(parser, "https://x.test/p.htm")
    path.parent.mkdir(parents=True)
    path.write_text("good", encoding="utf-8")
    calls = stub_fetch(parser, monkeypatch, {})
    result = parser._fetch_validated_page(
        url="https://x.test/p.htm", validator=lambda t: t == "good", invalid_error="bad"
    )
    assert result == "good" and calls == []


def test_fetch_validated_page_discards_invalid_cache_and_refetches(parser, monkeypatch, caplog):
    """An invalid cached file is logged, deleted and replaced by a fresh fetch."""
    url = "https://x.test/p.htm"
    path = cache_file(parser, url)
    path.parent.mkdir(parents=True)
    path.write_text("Just a moment", encoding="utf-8")
    calls = stub_fetch(parser, monkeypatch, {url: "good"})
    with caplog.at_level("WARNING"):
        result = parser._fetch_validated_page(
            url=url, validator=lambda t: t == "good", invalid_error="bad"
        )
    assert result == "good" and calls == [url]
    assert not path.exists()
    assert "Discarding invalid cached Jasher source" in caplog.text


def test_fetch_validated_page_raises_and_removes_cache_for_invalid_fetch(parser, monkeypatch):
    """An invalid fetched page raises the supplied error and leaves no cache entry."""
    url = "https://x.test/p.htm"
    path = cache_file(parser, url)

    def fake_fetch_text(*, url: str, retry_count: int = 3) -> str:
        """Write the bad page to the cache like the real fetcher, then return it."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Just a moment", encoding="utf-8")
        return "Just a moment"

    monkeypatch.setattr(parser.http, "fetch_text", fake_fetch_text)
    with pytest.raises(RuntimeError, match="blocked here"):
        parser._fetch_validated_page(
            url=url, validator=lambda t: t == "good", invalid_error="blocked here"
        )
    assert not path.exists()


def test_fetch_validated_page_works_without_cache(monkeypatch):
    """With caching disabled the page is fetched and validated directly."""
    instance = JasherParser(delay=0)
    stub_fetch(instance, monkeypatch, {"u": "good"})
    assert (
        instance._fetch_validated_page(url="u", validator=lambda t: t == "good", invalid_error="x")
        == "good"
    )
    instance.close()


def test_fetch_index_text_uses_index_url(parser, monkeypatch):
    """The index is fetched from ``INDEX_URL`` and returned when valid."""
    calls = stub_fetch(parser, monkeypatch, {jasher.INDEX_URL: INDEX_HTML})
    assert parser.fetch_index_text() == INDEX_HTML
    assert calls == [jasher.INDEX_URL]


def test_fetch_index_text_rejects_interstitial(parser, monkeypatch):
    """A Cloudflare page in place of the index raises a descriptive error."""
    stub_fetch(parser, monkeypatch, {jasher.INDEX_URL: "<html>Just a moment</html>"})
    with pytest.raises(RuntimeError, match="did not contain the Book of Jasher index"):
        parser.fetch_index_text()


def test_fetch_chapter_text_formats_url_and_validates_chapter(parser, monkeypatch):
    """The chapter URL contains the number and the page must name that chapter."""
    url = "https://sacred-texts.com/chr/apo/jasher/12.htm"
    calls = stub_fetch(parser, monkeypatch, {url: chapter_html(12)})
    assert parser.fetch_chapter_text(12) == chapter_html(12)
    assert calls == [url]


def test_fetch_chapter_text_raises_for_mismatched_page(parser, monkeypatch):
    """A page for the wrong chapter is rejected with the chapter number in the message."""
    url = "https://sacred-texts.com/chr/apo/jasher/12.htm"
    stub_fetch(parser, monkeypatch, {url: chapter_html(13)})
    with pytest.raises(RuntimeError, match="chapter 12"):
        parser.fetch_chapter_text(12)


# --- text helpers ----------------------------------------------------------------------


def test_strip_tags_converts_breaks_and_closing_paragraphs_to_newlines():
    """``<br>``, ``<BR/>`` and ``</p>`` become newlines; other tags vanish; entities unescape."""
    assert JasherParser._strip_tags("a<br>b<BR/>c</p>d <i>e</i> &amp; f") == "a\nb\nc\nd e & f"


@given(st.text(alphabet=string.ascii_letters + string.digits + " \n.,;:'-"))
def test_strip_tags_leaves_plain_text_unchanged(text):
    """Text without markup or entities passes through verbatim."""
    assert JasherParser._strip_tags(text) == text


def test_extract_content_after_heading_returns_heading_and_content_before_hr():
    """The heading text and the body up to (not including) the footer ``<HR>`` are returned."""
    heading, content = JasherParser._extract_content_after_heading(chapter_html(5))
    assert heading == "Book of Jasher, Chapter 5"
    assert "<P>1 First verse" in content
    assert "Next: Chapter" not in content and "<HR" not in content.upper()


def test_extract_content_after_heading_normalizes_heading_markup():
    """Tags and runs of whitespace inside the heading are removed or collapsed."""
    heading, _ = JasherParser._extract_content_after_heading(
        "<H1 ALIGN=center>The <i>Book</i>\n  of  Jasher</H1>x<hr>"
    )
    assert heading == "The Book of Jasher"


def test_extract_content_after_heading_requires_h1():
    """A page without an ``<h1>`` raises."""
    with pytest.raises(RuntimeError, match="locate Jasher heading"):
        JasherParser._extract_content_after_heading("<p>no heading</p><hr>")


def test_extract_content_after_heading_requires_footer_hr():
    """A page whose content is never closed by an ``<HR>`` raises."""
    with pytest.raises(RuntimeError, match="end of Jasher content block"):
        JasherParser._extract_content_after_heading("<h1>T</h1><p>1 text")


def test_extract_lines_drops_blank_lines_and_normalizes_whitespace():
    """Each non-blank line is whitespace-normalised; blank ones are dropped."""
    assert JasherParser._extract_lines("  a   b <BR>\n\n<br> c<p>") == ["a b", "c"]


# --- parse_front_matter -----------------------------------------------------------------


def test_parse_front_matter_builds_title_page_and_introduction():
    """Heading tags and the ``<font>`` block form the title page; text after ``</CENTER>`` is the intro."""
    title_page, intro = JasherParser.parse_front_matter(INDEX_HTML)
    assert title_page.title == "The Book of Jasher"
    assert title_page.div_type == pyosis.OsisDivs.TITLE_PAGE
    assert title_page.paragraphs == [
        "Referred to in Joshua",
        "Translated",
        "Faithfully Translated",
        "From the Hebrew",
    ]
    assert intro.title == "Introduction"
    assert intro.div_type == pyosis.OsisDivs.FRONT
    assert intro.paragraphs[:2] == ["A short introduction.", "Second intro paragraph."]


def test_parse_front_matter_excludes_title_lines_from_introduction():
    """A title-page line repeated after ``</CENTER>`` is not duplicated into the intro."""
    html = INDEX_HTML.replace("<P>A short", "Faithfully Translated<P>A short")
    _, intro = JasherParser.parse_front_matter(html)
    assert "Faithfully Translated" not in intro.paragraphs


def test_parse_front_matter_without_center_or_font_uses_whole_content():
    """Without ``</CENTER>`` or ``<font>`` the whole content block is the introduction."""
    html = "<h1>The Book of Jasher</h1><p>Only intro<hr>"
    title_page, intro = JasherParser.parse_front_matter(html)
    assert title_page.paragraphs == []
    assert intro.paragraphs == ["Only intro"]


def test_parse_front_matter_rejects_unexpected_heading():
    """An index whose ``<h1>`` is not the book title raises."""
    with pytest.raises(RuntimeError, match="Unexpected Jasher index heading"):
        JasherParser.parse_front_matter("<h1>Something Else</h1>x<hr>")


# --- extract_chapter_numbers ------------------------------------------------------------


def test_extract_chapter_numbers_lists_numeric_htm_links_in_order():
    """Numeric ``N.htm`` anchors are returned in order, deduplicated."""
    html = (
        '<a href="2.htm">2</a><a href=" 1.htm ">1</a><a href="2.htm">again</a>'
        '<a href="index.htm">i</a><a href="x.html">x</a><a href="3.htm#top">no</a><a>none</a>'
        '<a href="10.htm">10</a>'
    )
    assert JasherParser.extract_chapter_numbers(html) == [2, 1, 10]


def test_extract_chapter_numbers_on_sample_index_is_complete():
    """The sample index yields chapters 1 through 91."""
    assert JasherParser.extract_chapter_numbers(INDEX_HTML) == jasher.EXPECTED_CHAPTERS


# --- parse_chapter ----------------------------------------------------------------------


def test_parse_chapter_splits_verses_on_bare_p_tags():
    """Unclosed ``<P>`` tags separate verses; the footer, ``THE END`` and markup are excluded."""
    html = chapter_html(4, "<P>1 In the <i>beginning</i> &amp; so\non<P>2 Then\n  came  rest")
    chapter = JasherParser.parse_chapter(4, html)
    assert chapter == Chapter(
        number=4,
        verses=[Verse(1, "In the beginning & so on"), Verse(2, "Then came rest")],
    )


def test_parse_chapter_skips_bare_number_fragments():
    """A fragment that is only digits (such as a stray page number) is ignored."""
    chapter = JasherParser.parse_chapter(1, chapter_html(1, "<P>1 One<P>42<P>2 Two"))
    assert [v.number for v in chapter.verses] == [1, 2]


def test_parse_chapter_accepts_p_tags_with_attributes():
    """``<P ALIGN=...>`` and lower-case tags split verses too."""
    chapter = JasherParser.parse_chapter(1, chapter_html(1, '<p align="x">1 One<P CLASS=a>2 Two'))
    assert [v.text for v in chapter.verses] == ["One", "Two"]


def test_parse_chapter_rejects_unparseable_heading():
    """A heading that does not read ``Book of Jasher, Chapter N`` raises."""
    with pytest.raises(RuntimeError, match="Could not determine Jasher chapter"):
        JasherParser.parse_chapter(1, "<h1>Introduction</h1><p>1 x<hr>")


def test_parse_chapter_rejects_heading_for_other_chapter():
    """The heading's chapter must equal the expected one."""
    with pytest.raises(RuntimeError, match="expected 2, got 3"):
        JasherParser.parse_chapter(2, chapter_html(3))


def test_parse_chapter_rejects_paragraph_without_verse_number():
    """A non-numbered paragraph raises with the offending text."""
    with pytest.raises(RuntimeError, match="Could not parse Jasher chapter 1 paragraph: stray"):
        JasherParser.parse_chapter(1, chapter_html(1, "<P>1 One<P>stray text"))


def test_parse_chapter_rejects_chapter_without_verses():
    """A chapter with only ``THE END`` and numbers has no verses and raises."""
    with pytest.raises(RuntimeError, match="No verses parsed for Jasher chapter 1"):
        JasherParser.parse_chapter(1, chapter_html(1, "<P>7"))


def test_parse_chapter_rejects_non_sequential_verses():
    """Verse numbers must run 1..N without gaps."""
    with pytest.raises(RuntimeError, match="Unexpected Jasher verse sequence"):
        JasherParser.parse_chapter(1, chapter_html(1, "<P>1 One<P>3 Three"))


_VERSE_TEXT = st.text(alphabet=string.ascii_letters + " ,.;'", min_size=1).filter(
    lambda s: s.strip() and s.strip() != "THE END"
)


@given(st.lists(_VERSE_TEXT, min_size=1, max_size=12))
def test_parse_chapter_numbers_verses_consecutively_and_keeps_text(texts):
    """For any verse texts, numbering is 1..N and text equals the whitespace-normalised input."""
    body = "".join(f"<P>{i} {text}" for i, text in enumerate(texts, start=1))
    chapter = JasherParser.parse_chapter(9, chapter_html(9, body))
    assert [v.number for v in chapter.verses] == list(range(1, len(texts) + 1))
    assert [v.text for v in chapter.verses] == [" ".join(t.split()) for t in texts]


# --- generate_osis ----------------------------------------------------------------------


def _generate():
    """Generate OSIS XML for a tiny book with one front-matter section and one chapter."""
    front = [FrontMatterSection("Introduction", pyosis.OsisDivs.FRONT, ["Intro one", "Intro two"])]
    chapters = [Chapter(1, [Verse(1, "First"), Verse(2, "Second")])]
    return JasherParser.generate_osis(front, chapters)


def test_generate_osis_emits_book_chapter_and_verse_ids():
    """The XML contains the book div, chapter div and verse osisIDs with their text."""
    xml = _generate().to_xml()
    assert 'osisID="Jasher"' in xml
    assert 'osisID="Jasher.1"' in xml
    assert 'osisID="Jasher.1.1"' in xml and "First" in xml
    assert 'osisID="Jasher.1.2"' in xml and "Second" in xml


def test_generate_osis_includes_front_matter_paragraphs_as_non_canonical():
    """Front matter becomes a non-canonical div with a title and one paragraph per line."""
    doc = _generate()
    book = doc.osis.osis_text.div[0]
    front = next(
        d
        for d in book.content
        if isinstance(d, pyosis.DivCt) and d.type_value == pyosis.OsisDivs.FRONT
    )
    assert front.canonical is False
    assert [p.content for p in front.content if isinstance(p, pyosis.PCt)] == [
        ["Intro one"],
        ["Intro two"],
    ]


def test_generate_osis_header_describes_work():
    """The header names the work, language, 1887 edition and publisher."""
    xml = _generate().to_xml()
    assert "J.H. Parry &amp; Company" in xml
    assert "1887" in xml
    assert 'osisIDWork="Jasher"' in xml


# --- process / run / SPEC ---------------------------------------------------------------


def _full_site() -> dict[str, str]:
    """Map every Jasher URL to a minimal valid page."""
    pages = {jasher.INDEX_URL: INDEX_HTML}
    for n in jasher.EXPECTED_CHAPTERS:
        pages[jasher.CHAPTER_URL_TEMPLATE.format(page=n)] = chapter_html(n)
    return pages


def test_process_builds_document_from_fake_site(parser, monkeypatch):
    """``process`` fetches the index and all 91 chapters and returns an OSIS document."""
    calls = stub_fetch(parser, monkeypatch, _full_site())
    xml = parser.process().to_xml()
    assert len(calls) == 92
    assert 'osisID="Jasher.91.2"' in xml and 'osisID="Jasher.1.1"' in xml
    assert "THE END" not in xml


def test_process_rejects_incomplete_chapter_list(parser, monkeypatch):
    """An index linking fewer than 91 chapters raises before any chapter is fetched."""
    short = INDEX_HTML.replace('<A HREF="5.htm">Chapter 5</A>', "")
    stub_fetch(parser, monkeypatch, {jasher.INDEX_URL: short})
    with pytest.raises(RuntimeError, match="Unexpected Jasher chapter sequence"):
        parser.process()


def test_add_arguments_registers_nothing():
    """Jasher has no own options, so the parser gains no arguments."""
    arg_parser = argparse.ArgumentParser()
    before = list(arg_parser._actions)
    jasher.add_arguments(arg_parser)
    assert arg_parser._actions == before


def test_run_writes_output_file_using_prepopulated_cache(tmp_path):
    """``run`` reads pages from a pre-populated cache and writes ``jasher.xml``."""
    cache = tmp_path / "cache"
    base = cache / "sacred-texts.com" / "chr" / "apo" / "jasher"
    base.mkdir(parents=True)
    (base / "index.htm").write_text(INDEX_HTML, encoding="utf-8")
    for n in jasher.EXPECTED_CHAPTERS:
        (base / f"{n}.htm").write_text(chapter_html(n), encoding="utf-8")
    out = tmp_path / "out" / "nested"
    paths = jasher.run(argparse.Namespace(output_dir=out, cache_dir=cache, delay=0))
    assert paths == [out / "jasher.xml"]
    assert 'osisID="Jasher.50.1"' in paths[0].read_text(encoding="utf-8")


def test_run_closes_parser_and_propagates_errors(tmp_path, monkeypatch):
    """A failure inside ``process`` propagates and the parser is still closed."""
    closed: list[bool] = []
    monkeypatch.setattr(
        JasherParser, "process", lambda self: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    monkeypatch.setattr(JasherParser, "close", lambda self: closed.append(True))
    with pytest.raises(RuntimeError, match="boom"):
        jasher.run(argparse.Namespace(output_dir=tmp_path, cache_dir=None, delay=0))
    assert closed == [True]


def test_spec_describes_scraper():
    """``SPEC`` registers the scraper's name, output file and entry points."""
    assert jasher.SPEC.name == "jasher"
    assert jasher.SPEC.outputs == (jasher.OUTPUT_FILENAME,)
    assert jasher.SPEC.run is jasher.run and jasher.SPEC.add_arguments is jasher.add_arguments


# --- redesigned reader layout ---------------------------------------------------------

READER_FIXTURES = Path(__file__).parent / "fixtures" / "reader_layout"
"""Trimmed copies of real redesigned sacred-texts.com pages."""


def reader_fixture(name: str) -> str:
    """Return the text of a reader-layout fixture page."""
    return (READER_FIXTURES / name).read_text(encoding="utf-8")


def test_is_valid_index_accepts_reader_layout_book_overview():
    """The redesigned book overview page is a valid index (title and 91-chapter count)."""
    assert JasherParser.is_valid_index(reader_fixture("jasher-index.htm"))


def test_is_valid_index_rejects_book_overview_with_wrong_title_or_count():
    """An overview page for another book, or with another chapter count, is rejected."""
    page = reader_fixture("jasher-index.htm")
    assert not JasherParser.is_valid_index(page.replace(">The Book of Jasher<", ">Other<"))
    assert not JasherParser.is_valid_index(page.replace("91 chapters", "90 chapters"))


def test_extract_chapter_numbers_uses_book_overview_chapter_count():
    """The paginated overview table of contents yields chapters 1 through its count."""
    assert JasherParser.extract_chapter_numbers(reader_fixture("jasher-index.htm")) == list(
        range(1, 92)
    )


def test_extract_chapter_numbers_on_book_overview_without_count_is_empty():
    """An overview page with no chapter count yields no chapters."""
    page = '<article data-module-id="book-overview-about"><p>About</p></article>'
    assert JasherParser.extract_chapter_numbers(page) == []


def test_parse_front_matter_from_book_overview_uses_about_text():
    """The overview has no title page block; its "About this book" text is the introduction."""
    title_page, intro = JasherParser.parse_front_matter(reader_fixture("jasher-index.htm"))
    assert title_page == FrontMatterSection(
        title="The Book of Jasher", div_type=pyosis.OsisDivs.TITLE_PAGE, paragraphs=[]
    )
    assert intro.title == "Introduction"
    assert len(intro.paragraphs) == 2
    assert intro.paragraphs[0].startswith("This is one of the apochrypal Books of Jasher.")
    assert intro.paragraphs[1].endswith("albeit with several minor variations.")


def test_parse_front_matter_from_book_overview_rejects_other_book():
    """An overview page for another book raises."""
    page = reader_fixture("jasher-index.htm").replace(">The Book of Jasher<", ">Other<")
    with pytest.raises(RuntimeError, match="Unexpected Jasher index heading"):
        JasherParser.parse_front_matter(page)


def test_is_valid_chapter_page_accepts_reader_layout_page():
    """A reader-layout chapter page validates against its own chapter only."""
    page = reader_fixture("jasher-1.htm")
    assert JasherParser.is_valid_chapter_page(page, 1)
    assert not JasherParser.is_valid_chapter_page(page, 2)


def test_parse_chapter_reads_reader_layout_page():
    """Verses are read from the reader content, ignoring the chapter sidebar."""
    chapter = JasherParser.parse_chapter(1, reader_fixture("jasher-1.htm"))
    assert chapter.number == 1
    assert [verse.number for verse in chapter.verses] == [1, 2, 3]
    assert chapter.verses[0].text.startswith("And God said, Let us make man in our image")
