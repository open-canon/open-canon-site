"""Unit tests for ``open_canon_site.scrapers.sacred_texts.vita_adae_et_evae`` (offline, inline HTML)."""

from __future__ import annotations

import argparse

import pyosis
import pytest
from hypothesis import given
from hypothesis import strategies as st
from open_canon_site.scrapers._osis import int_to_roman
from open_canon_site.scrapers.sacred_texts import vita_adae_et_evae as vita
from open_canon_site.scrapers.sacred_texts.vita_adae_et_evae import (
    Chapter,
    VerseBlock,
    VitaAdaeEtEvaeParser,
)

FIRST_LINE = "i 1 When they were driven out from paradise they made themselves a tent."
SOURCE = "THE LIFE OF ADAM AND EVE (From the Latin)"


def chapter_lines(count: int = 51) -> list[str]:
    """Return one ``<roman> 1 text`` opening line per chapter, chapter 1 using the real opening."""
    lines = [FIRST_LINE]
    lines += [f"{int_to_roman(n).lower()} 1 Text of chapter {n}." for n in range(2, count + 1)]
    return lines


def vita_html(lines: list[str] | None = None, source: str = SOURCE) -> str:
    """Build a minimal original-site page: ``<h1>``, bold source line, ``<br>``-separated text, footer."""
    body = "<br>\n".join(chapter_lines() if lines is None else lines)
    return (
        "<html><body><h1>VITA ADAE ET EVAE</h1>\n"
        f"<b>{source}</b>\n<p>{body}</p>\n"
        "<hr><h5>Scanned and Edited by J. B. Hare</h5></body></html>"
    )


@pytest.fixture
def parser(tmp_path):
    """Return a parser with a tmp cache directory, closed after the test."""
    instance = VitaAdaeEtEvaeParser(cache_dir=str(tmp_path / "cache"), delay=0)
    yield instance
    instance.close()


def stub_fetch(parser: VitaAdaeEtEvaeParser, monkeypatch, pages: dict[str, str]):
    """Replace the fetcher's network call with a lookup in ``pages``; return the URL call log."""
    calls: list[str] = []

    def fake_fetch_text(*, url: str, retry_count: int = 3) -> str:
        """Record the URL and return the canned page."""
        calls.append(url)
        return pages[url]

    monkeypatch.setattr(parser.http, "fetch_text", fake_fetch_text)
    return calls


# --- constructor / close ----------------------------------------------------------------


def test_init_sets_cache_dir_and_fetcher(tmp_path):
    """The parser keeps the cache directory as a ``Path`` and configures its fetcher."""
    instance = VitaAdaeEtEvaeParser(cache_dir=str(tmp_path / "c"), delay=3.0)
    assert instance.cache_dir == tmp_path / "c"
    assert instance.http.delay == 3.0 and instance.http.cache_dir == tmp_path / "c"
    instance.close()


def test_init_without_cache_dir_leaves_it_none():
    """No cache directory means ``cache_dir`` is ``None``."""
    instance = VitaAdaeEtEvaeParser(delay=0)
    assert instance.cache_dir is None
    instance.close()


def test_close_closes_http_client(parser):
    """``close`` closes the underlying httpx client."""
    parser.close()
    assert parser.http._client.is_closed


# --- validity / fetch -------------------------------------------------------------------


def test_is_valid_source_accepts_genuine_page():
    """The sample page with the title and the opening verse is valid."""
    assert VitaAdaeEtEvaeParser.is_valid_source(vita_html())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda t: t.replace("VITA ADAE ET EVAE", "OTHER"),
        lambda t: t.replace("i 1 When they were driven out from paradise", "x"),
        lambda t: t + "Just a moment...",
    ],
    ids=["title", "opening-verse", "cloudflare"],
)
def test_is_valid_source_rejects_bad_pages(mutate):
    """A missing title, missing opening verse or Cloudflare notice invalidates the page."""
    assert not VitaAdaeEtEvaeParser.is_valid_source(mutate(vita_html()))


def test_fetch_source_text_fetches_and_returns_valid_page(parser, monkeypatch):
    """A cache miss fetches ``SOURCE_URL`` and returns the page."""
    calls = stub_fetch(parser, monkeypatch, {vita.SOURCE_URL: vita_html()})
    assert parser.fetch_source_text() == vita_html()
    assert calls == [vita.SOURCE_URL]


def test_fetch_source_text_returns_valid_cache_without_network(parser, monkeypatch):
    """A valid cached page is used without touching the network."""
    path = parser.http.cache_path_for(vita.SOURCE_URL)
    path.parent.mkdir(parents=True)
    path.write_text(vita_html(), encoding="utf-8")
    calls = stub_fetch(parser, monkeypatch, {})
    assert parser.fetch_source_text() == vita_html() and calls == []


def test_fetch_source_text_discards_invalid_cache_and_refetches(parser, monkeypatch, caplog):
    """An invalid cached page is logged, deleted and refetched."""
    path = parser.http.cache_path_for(vita.SOURCE_URL)
    path.parent.mkdir(parents=True)
    path.write_text("<html>Just a moment</html>", encoding="utf-8")
    stub_fetch(parser, monkeypatch, {vita.SOURCE_URL: vita_html()})
    with caplog.at_level("WARNING"):
        assert parser.fetch_source_text() == vita_html()
    assert "Discarding invalid cached Vita source" in caplog.text
    assert not path.exists()


def test_fetch_source_text_raises_and_clears_cache_for_invalid_fetch(parser, monkeypatch):
    """A Cloudflare page fetched live raises and leaves no cache entry."""
    path = parser.http.cache_path_for(vita.SOURCE_URL)

    def fake_fetch_text(*, url: str, retry_count: int = 3) -> str:
        """Cache then return a Cloudflare page like the real fetcher would."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Just a moment", encoding="utf-8")
        return "Just a moment"

    monkeypatch.setattr(parser.http, "fetch_text", fake_fetch_text)
    with pytest.raises(RuntimeError, match="did not contain Vita Adae et Evae"):
        parser.fetch_source_text()
    assert not path.exists()


def test_fetch_source_text_works_without_cache(monkeypatch):
    """With caching disabled the page is fetched and validated directly."""
    instance = VitaAdaeEtEvaeParser(delay=0)
    stub_fetch(instance, monkeypatch, {vita.SOURCE_URL: vita_html()})
    assert instance.fetch_source_text() == vita_html()
    instance.close()


# --- _normalize_content_lines ------------------------------------------------------------


def test_normalize_content_lines_separates_source_from_numbered_content():
    """Lines before the first ``<roman> <verse> text`` line form the source; the rest are content."""
    text = f"Header line one\n\n  Header   two \n{FIRST_LINE}\n2 Second verse\n"
    source, content = VitaAdaeEtEvaeParser._normalize_content_lines(text)
    assert source == "Header line one Header two"
    assert content == [FIRST_LINE, "2 Second verse"]


def test_normalize_content_lines_inserts_missing_markers_for_chapters_32_and_37():
    """Unmarked chapter openings for chapters 32 and 37 receive explicit markers."""
    text = (
        f"{FIRST_LINE}\n"
        "  And Adam answered and said: 'Hear me, my sons. More.\n"
        "Then Seth and his mother went.\n"
    )
    _, content = VitaAdaeEtEvaeParser._normalize_content_lines(text)
    assert content[1] == "xxxii 1 And Adam answered and said: 'Hear me, my sons. More."
    assert content[2] == "xxxvii 1 Then Seth and his mother went."


def test_normalize_content_lines_with_no_chapter_start_treats_all_as_source():
    """Without any chapter-start line everything is source text and content is empty."""
    source, content = VitaAdaeEtEvaeParser._normalize_content_lines("just\nwords\n")
    assert source == "just words" and content == []


# --- _strip_html_fragment ------------------------------------------------------------------


def test_strip_html_fragment_with_line_breaks_keeps_newlines():
    """``<br>`` becomes a newline when ``line_breaks`` is true; paragraphs and ``<hr>`` too."""
    out = VitaAdaeEtEvaeParser._strip_html_fragment(
        "a<br>b<BR/>c<p class=x>d</p>e<hr/>f <i>g</i> &amp; h", line_breaks=True
    )
    assert out == "a\nb\nc\nd\ne\nf g & h"


def test_strip_html_fragment_without_line_breaks_turns_br_into_spaces():
    """With ``line_breaks`` false ``<br>`` becomes a space (used for the one-line source heading)."""
    assert VitaAdaeEtEvaeParser._strip_html_fragment("A<br>B<BR />C", line_breaks=False) == "A B C"


# --- extract_main_text ------------------------------------------------------------------------


def test_extract_main_text_from_html_returns_source_and_lines(parser):
    """HTML between the title and the ``Scanned and Edited by`` footer is split into source and lines."""
    source, lines = parser.extract_main_text(vita_html(["i 1 One", "2 Two", "more of two"]))
    assert source == SOURCE
    assert lines == ["i 1 One", "2 Two", "more of two"]


def test_extract_main_text_from_html_without_footer_uses_body_end(parser):
    """Without the footer heading the content ends at ``</body>``."""
    html = f"<html><body><h1>VITA ADAE ET EVAE</h1><b>{SOURCE}</b><br>i 1 One</body></html>"
    assert parser.extract_main_text(html) == (SOURCE, ["i 1 One"])


def test_extract_main_text_normalizes_crlf_line_endings(parser):
    """Windows line endings are normalised before parsing."""
    html = vita_html(["i 1 One", "2 Two"]).replace("\n", "\r\n")
    assert parser.extract_main_text(html)[1] == ["i 1 One", "2 Two"]


def test_extract_main_text_html_requires_title_heading(parser):
    """HTML lacking the title ``<h1>`` raises."""
    with pytest.raises(RuntimeError, match="locate Vita Adae et Evae body"):
        parser.extract_main_text("<html><body><h1>Other</h1></body></html>")


def test_extract_main_text_html_requires_bold_source_heading(parser):
    """HTML with the title but no ``<b>`` source heading raises."""
    with pytest.raises(RuntimeError, match="source heading"):
        parser.extract_main_text("<html><body><h1>VITA ADAE ET EVAE</h1>i 1 One</body></html>")


def test_extract_main_text_accepts_markdown_mirror_text(parser):
    """Mirror-derived Markdown is cut at the title heading and the first footer marker."""
    text = (
        "Title: x\nMarkdown Content:\n## VITA ADAE ET EVAE\n**SOURCE LINE**\n\n* * *\n"
        "i 1 One\n2 Two\n##### Scanned and edited\nignored\n"
    )
    source, lines = parser.extract_main_text(text)
    assert source == "SOURCE LINE" and lines == ["i 1 One", "2 Two"]


@pytest.mark.parametrize("marker", ["\nTitle: foo", "\nURL Source: bar"])
def test_extract_main_text_markdown_stops_at_earliest_footer_marker(parser, marker):
    """``Title:`` and ``URL Source:`` lines also end the Markdown body."""
    text = f"## VITA ADAE ET EVAE\ni 1 One{marker}\nleak\n"
    assert parser.extract_main_text(text) == ("", ["i 1 One"])


def test_extract_main_text_markdown_without_end_marker_reads_to_end(parser):
    """If no footer marker exists the rest of the text is used."""
    assert parser.extract_main_text("## VITA ADAE ET EVAE\ni 1 One\n2 Two\n") == (
        "",
        ["i 1 One", "2 Two"],
    )


def test_extract_main_text_markdown_requires_title(parser):
    """Markdown without the title heading raises."""
    with pytest.raises(RuntimeError, match="locate Vita Adae et Evae title"):
        parser.extract_main_text("no heading here")


# --- parse_verse_numbers ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("1", [1]),
        ("12", [12]),
        ("1,2", [1, 2]),
        ("I", [1]),
        ("i", [1]),
        ("I,3", [1, 3]),
        (" 4 , 5", [4, 5]),
    ],
)
def test_parse_verse_numbers_examples(token, expected):
    """Digits and ``I`` (an OCR'd ``1``) parse, comma-separated and tolerant of spaces."""
    assert VitaAdaeEtEvaeParser.parse_verse_numbers(token) == expected


def test_parse_verse_numbers_rejects_garbage():
    """A non-numeric, non-``I`` token raises ``ValueError``."""
    with pytest.raises(ValueError):
        VitaAdaeEtEvaeParser.parse_verse_numbers("x")


@given(st.lists(st.integers(min_value=1, max_value=999), min_size=1, max_size=8))
def test_parse_verse_numbers_round_trips_formatted_lists(numbers):
    """Joining numbers with commas and parsing returns the same list."""
    token = ",".join(map(str, numbers))
    assert VitaAdaeEtEvaeParser.parse_verse_numbers(token) == numbers


# --- parse_chapters ------------------------------------------------------------------------------


def test_parse_chapters_groups_verses_and_continuations(parser):
    """Chapter markers start chapters, verse markers start blocks and other lines continue blocks."""
    lines = chapter_lines()
    lines[0:1] = [FIRST_LINE, "continued text", "2,3 Verses two and three", "4 Four"]
    chapters = parser.parse_chapters(lines)
    assert [c.number for c in chapters] == list(range(1, 52))
    assert chapters[0].verses == [
        VerseBlock([1], FIRST_LINE.split(" ", 2)[2] + " continued text"),
        VerseBlock([2, 3], "Verses two and three"),
        VerseBlock([4], "Four"),
    ]
    assert chapters[1].verses == [VerseBlock([1], "Text of chapter 2.")]


def test_parse_chapters_accepts_ocr_i_as_verse_one(parser):
    """A chapter marker whose verse token is ``I`` yields verse 1."""
    lines = chapter_lines()
    lines[1] = "ii I Text of chapter 2."
    assert parser.parse_chapters(lines)[1].verses[0].verse_numbers == [1]


def test_parse_chapters_rejects_continuation_before_any_marker(parser):
    """Text before the first verse marker has nothing to continue and raises."""
    with pytest.raises(RuntimeError, match="Unexpected continuation without verse marker"):
        parser.parse_chapters(["stray words"] + chapter_lines())


def test_parse_chapters_rejects_verse_marker_before_any_chapter(parser):
    """A bare verse marker with no current chapter cannot be placed and raises."""
    with pytest.raises(RuntimeError, match="Could not parse Vita block"):
        parser.parse_chapters(["1 verse with no chapter"] + chapter_lines())


def test_parse_chapters_rejects_missing_chapters(parser):
    """The chapters found must be exactly 1 through 51."""
    with pytest.raises(RuntimeError, match="Unexpected Vita chapter sequence"):
        parser.parse_chapters(chapter_lines(50))


@given(st.lists(st.integers(min_value=1, max_value=6), min_size=51, max_size=51))
def test_parse_chapters_preserves_verse_counts_and_order(counts):
    """Each chapter keeps exactly the verses given, numbered in order."""
    parser = VitaAdaeEtEvaeParser.__new__(VitaAdaeEtEvaeParser)
    lines: list[str] = []
    for chapter, count in enumerate(counts, start=1):
        lines.append(f"{int_to_roman(chapter).lower()} 1 c{chapter}v1")
        lines += [f"{verse} c{chapter}v{verse}" for verse in range(2, count + 1)]
    chapters = parser.parse_chapters(lines)
    assert [len(c.verses) for c in chapters] == counts
    assert [v.verse_numbers[0] for v in chapters[0].verses] == list(range(1, counts[0] + 1))


# --- generate_osis ---------------------------------------------------------------------------------


def _chapters() -> list[Chapter]:
    """Return a tiny two-chapter book including a grouped-verse block."""
    return [
        Chapter(1, [VerseBlock([1], "One"), VerseBlock([2, 3], "Two and three")]),
        Chapter(2, [VerseBlock([1], "Other")]),
    ]


def test_generate_osis_emits_chapter_and_verse_ids():
    """Verse ids are ``vita-adae-et-evae.<chapter>.<verse>``; groups list every verse."""
    xml = VitaAdaeEtEvaeParser.generate_osis(SOURCE, _chapters()).to_xml()
    assert 'osisID="vita-adae-et-evae.1"' in xml
    assert 'osisID="vita-adae-et-evae.1.1"' in xml
    assert "vita-adae-et-evae.1.2 vita-adae-et-evae.1.3" in xml
    assert 'osisID="vita-adae-et-evae.2.1"' in xml


def test_generate_osis_includes_source_front_matter_when_present():
    """A non-empty source line becomes a non-canonical ``Source`` front div."""
    book = VitaAdaeEtEvaeParser.generate_osis(SOURCE, _chapters()).osis.osis_text.div[0]
    front = [
        d
        for d in book.content
        if isinstance(d, pyosis.DivCt) and d.type_value == pyosis.OsisDivs.FRONT
    ]
    assert len(front) == 1 and front[0].canonical is False
    assert SOURCE in VitaAdaeEtEvaeParser.generate_osis(SOURCE, _chapters()).to_xml()


def test_generate_osis_omits_source_div_when_empty():
    """An empty source string produces no front-matter div."""
    book = VitaAdaeEtEvaeParser.generate_osis("", _chapters()).osis.osis_text.div[0]
    assert not any(
        isinstance(d, pyosis.DivCt) and d.type_value == pyosis.OsisDivs.FRONT for d in book.content
    )


def test_generate_osis_header_names_work_edition_and_publisher():
    """The header names the 1913 edition, translator and publisher."""
    xml = VitaAdaeEtEvaeParser.generate_osis(SOURCE, _chapters()).to_xml()
    assert "1913" in xml and "The Clarendon Press" in xml
    assert "Robert Henry (R.H.) Charles" in xml


# --- process / run / SPEC -----------------------------------------------------------------------------


def test_process_builds_document_from_fake_page(parser, monkeypatch):
    """``process`` fetches the page, extracts, parses and returns OSIS with all 51 chapters."""
    stub_fetch(parser, monkeypatch, {vita.SOURCE_URL: vita_html()})
    xml = parser.process().to_xml()
    assert 'osisID="vita-adae-et-evae.51.1"' in xml and SOURCE in xml


def test_add_arguments_registers_nothing():
    """Vita has no own options, so the parser gains no arguments."""
    arg_parser = argparse.ArgumentParser()
    before = list(arg_parser._actions)
    vita.add_arguments(arg_parser)
    assert arg_parser._actions == before


def test_run_writes_output_file_using_prepopulated_cache(tmp_path):
    """``run`` reads the page from a pre-populated cache and writes ``vita-adae-et-evae.xml``."""
    cache = tmp_path / "cache"
    page = cache / "sacred-texts.com" / "chr" / "apo" / "adamnev.htm"
    page.parent.mkdir(parents=True)
    page.write_text(vita_html(), encoding="utf-8")
    out = tmp_path / "out" / "deep"
    paths = vita.run(argparse.Namespace(output_dir=out, cache_dir=cache, delay=0))
    assert paths == [out / "vita-adae-et-evae.xml"]
    assert "vita-adae-et-evae.2.1" in paths[0].read_text(encoding="utf-8")


def test_run_closes_parser_and_propagates_errors(tmp_path, monkeypatch):
    """A failure inside ``process`` propagates and the parser is still closed."""
    closed: list[bool] = []

    def boom(self):
        """Fail like a broken scrape."""
        raise RuntimeError("boom")

    monkeypatch.setattr(VitaAdaeEtEvaeParser, "process", boom)
    monkeypatch.setattr(VitaAdaeEtEvaeParser, "close", lambda self: closed.append(True))
    with pytest.raises(RuntimeError, match="boom"):
        vita.run(argparse.Namespace(output_dir=tmp_path, cache_dir=None, delay=0))
    assert closed == [True]


def test_spec_describes_scraper():
    """``SPEC`` registers the scraper's name, output file and entry points."""
    assert vita.SPEC.name == "vita-adae-et-evae"
    assert vita.SPEC.outputs == (vita.OUTPUT_FILENAME,)
    assert vita.SPEC.run is vita.run and vita.SPEC.add_arguments is vita.add_arguments
