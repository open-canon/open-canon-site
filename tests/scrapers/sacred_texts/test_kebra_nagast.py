"""Unit tests for ``open_canon_site.scrapers.sacred_texts.kebra_nagast`` (offline, HTML fixtures)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from open_canon_site.scrapers.sacred_texts import kebra_nagast
from open_canon_site.scrapers.sacred_texts.kebra_nagast import KebraNagastParser

FIXTURES = Path(__file__).parent / "fixtures" / "kebra_nagast"


def fixture(name: str) -> str:
    """Return the text of a fixture page."""
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def parser(tmp_path):
    """Return a parser with a tmp cache directory, closed after the test."""
    instance = KebraNagastParser(cache_dir=str(tmp_path / "cache"), delay=0)
    yield instance
    instance.close()


def stub_fetch(parser: KebraNagastParser, monkeypatch, pages: dict[str, str]) -> list[str]:
    """Replace the fetcher's network call with a lookup in ``pages``; return the URL log."""
    calls: list[str] = []

    def fake_fetch_text(*, url: str, retry_count: int = 3) -> str:
        calls.append(url)
        return pages[url]

    monkeypatch.setattr(parser.http, "fetch_text", fake_fetch_text)
    return calls


def test_extract_pages_lists_text_pages_only():
    """Front matter (``kn000-N``) and the ``II.`` pagination links are not text pages."""
    pages = KebraNagastParser.extract_pages(fixture("index.htm"))
    assert pages == kebra_nagast.EXPECTED_PAGES
    assert pages[0] == 1
    assert pages[-1] == 118


def test_is_valid_index():
    """The index is accepted, and rejected when truncated or a Cloudflare page."""
    assert KebraNagastParser.is_valid_index(fixture("index.htm"))
    assert not KebraNagastParser.is_valid_index(fixture("index.htm").replace("kn117.htm", "x"))
    assert not KebraNagastParser.is_valid_index(fixture("index.htm") + "Just a moment")


def test_parse_chapter_one_paragraph_per_verse_without_marks():
    """Paragraphs become verses; page markers and footnote marks vanish from the text."""
    chapter = KebraNagastParser.parse_chapter(1, fixture("kn001.htm"))
    assert chapter.title == "Concerning the Glory of Kings"
    assert len(chapter.verses) == 2
    first = chapter.verses[0]
    assert first.startswith("The interpretation and explanation")
    assert "p. 2" not in first
    assert 'likeness," and with ready agreement' in first
    assert "agreement They were all of this opinion. And DAVID said" in first
    assert chapter.verses[1] == ("And He made ADAM in His own image—His own plant—for His praises.")
    assert not any("Genesis" in verse for verse in chapter.verses)


def test_parse_chapter_without_footnotes_stops_at_nav():
    """A footnote-less page ends at the navigation block and decodes entities."""
    chapter = KebraNagastParser.parse_chapter(3, fixture("kn003.htm"))
    assert chapter.title == "Concerning the Kingdom of ADAM"
    assert chapter.verses == [
        "And I go up from ADAM and I say, God is King in truth.",
        "Then CAIN was born, and LÂLÎBALÂ ’ABAL‛EZḲAL.",
    ]


def test_parse_chapter_rejects_wrong_number():
    """A page whose heading names another chapter is an error."""
    with pytest.raises(RuntimeError, match="expected 2, got 3"):
        KebraNagastParser.parse_chapter(2, fixture("kn003.htm"))


def test_parse_chapter_rejects_page_without_paragraphs():
    """A heading with no paragraphs is an error."""
    html = "<H3>4. <I>Concerning Envy</I></H3><HR>"
    with pytest.raises(RuntimeError, match="No paragraphs"):
        KebraNagastParser.parse_chapter(4, html)


def test_parse_chapter_without_heading_fails():
    """A page with no ``<h3>`` cannot be parsed."""
    with pytest.raises(RuntimeError, match="heading"):
        KebraNagastParser.parse_chapter(1, "<P>text</P>")


def test_parse_chapter_with_unnumbered_heading_fails():
    """A heading without a chapter number is not a chapter."""
    with pytest.raises(RuntimeError, match="Could not determine"):
        KebraNagastParser.parse_chapter(1, fixture("kn118.htm"))


def test_parse_invocation_only_on_first_page():
    """The invocation is read from page 1 and absent elsewhere."""
    invocation = KebraNagastParser.parse_invocation(fixture("kn001.htm"))
    assert len(invocation) == 1
    assert invocation[0].startswith("IN PRAISING GOD THE FATHER")
    assert KebraNagastParser.parse_invocation(fixture("kn003.htm")) == []


def test_parse_colophon():
    """The colophon page yields its heading and paragraphs."""
    colophon = KebraNagastParser.parse_colophon(fixture("kn118.htm"))
    assert colophon.title == "Colophon"
    assert len(colophon.paragraphs) == 2
    assert colophon.paragraphs[1] == '"And pray ye for me, your servant ISAAC the humble."'


def test_parse_colophon_rejects_chapter_page():
    """A chapter page is not the colophon."""
    with pytest.raises(RuntimeError, match="colophon heading"):
        KebraNagastParser.parse_colophon(fixture("kn003.htm"))


def test_is_valid_page():
    """Pages validate against their own number and not Cloudflare interstitials."""
    assert KebraNagastParser.is_valid_page(fixture("kn003.htm"), 3)
    assert not KebraNagastParser.is_valid_page(fixture("kn003.htm"), 4)
    assert KebraNagastParser.is_valid_page(fixture("kn118.htm"), 118)
    assert not KebraNagastParser.is_valid_page(fixture("kn003.htm"), 118)
    assert not KebraNagastParser.is_valid_page("<html>Just a moment</html>", 3)
    assert not KebraNagastParser.is_valid_page(fixture("kn003.htm") + "Just a moment", 3)


def make_book() -> kebra_nagast.Book:
    """Build a small book from the fixtures (chapters 1 and 3 stand in for the full set)."""
    return kebra_nagast.Book(
        invocation=KebraNagastParser.parse_invocation(fixture("kn001.htm")),
        chapters=[
            KebraNagastParser.parse_chapter(1, fixture("kn001.htm")),
            KebraNagastParser.parse_chapter(3, fixture("kn003.htm")),
        ],
        colophon=KebraNagastParser.parse_colophon(fixture("kn118.htm")),
    )


def test_generate_osis_ids_and_structure():
    """Verses are ``Kebra-Nagast.<chapter>.<n>`` and only chapters are canonical text."""
    xml = KebraNagastParser.generate_osis(make_book()).to_xml()
    assert 'osisID="Kebra-Nagast.1.1"' in xml
    assert 'osisID="Kebra-Nagast.1.2"' in xml
    assert 'osisID="Kebra-Nagast.3.2"' in xml
    assert 'osisID="Kebra-Nagast.3.3"' not in xml
    assert "Invocation" in xml
    assert 'type="colophon"' in xml
    assert "Concerning the Glory of Kings" in xml
    assert "Genesis i. 26" not in xml


def test_generate_osis_without_invocation_omits_div():
    """No invocation means no introduction div."""
    book = make_book()
    book.invocation = []
    assert "Invocation" not in KebraNagastParser.generate_osis(book).to_xml()


def test_process_end_to_end(parser, monkeypatch):
    """The full pipeline fetches the index, 117 chapters and the colophon."""
    chapter = fixture("kn003.htm")
    pages = {kebra_nagast.INDEX_URL: fixture("index.htm")}
    for number in range(1, kebra_nagast.CHAPTER_COUNT + 1):
        page = (
            fixture("kn001.htm")
            if number == 1
            else chapter.replace('ALIGN="CENTER">3.', f'ALIGN="CENTER">{number}.')
        )
        pages[kebra_nagast.PAGE_URL_TEMPLATE.format(page=number)] = page
    pages[kebra_nagast.PAGE_URL_TEMPLATE.format(page=118)] = fixture("kn118.htm")
    calls = stub_fetch(parser, monkeypatch, pages)

    xml = parser.process().to_xml()

    assert len(calls) == 1 + 118
    assert calls[1].endswith("/kn001.htm")
    assert calls[-1].endswith("/kn118.htm")
    assert 'osisID="Kebra-Nagast.117.1"' in xml


def test_process_rejects_unexpected_page_sequence(parser, monkeypatch):
    """An index missing the colophon link fails before any page is fetched."""
    index = fixture("index.htm").replace('<A HREF="kn118.htm">Colophon</A>', "")
    calls = stub_fetch(parser, monkeypatch, {kebra_nagast.INDEX_URL: index})
    with pytest.raises(RuntimeError, match="Unexpected Kebra Nagast page sequence"):
        parser.process()
    assert calls == [kebra_nagast.INDEX_URL]


def test_fetch_discards_invalid_cache_and_refetches(parser, monkeypatch):
    """An invalid cached page is deleted and replaced by a fresh valid fetch."""
    url = kebra_nagast.PAGE_URL_TEMPLATE.format(page=3)
    cache = parser.http.cache_path_for(url)
    assert cache is not None
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("<html>Just a moment</html>", encoding="utf-8")
    stub_fetch(parser, monkeypatch, {url: fixture("kn003.htm")})
    assert parser.fetch_page_text(3) == fixture("kn003.htm")


def test_fetch_invalid_page_raises_and_clears_cache(parser, monkeypatch):
    """A fetched interstitial raises and leaves no cache entry."""
    url = kebra_nagast.PAGE_URL_TEMPLATE.format(page=3)
    stub_fetch(parser, monkeypatch, {url: "<html>Just a moment</html>"})
    with pytest.raises(RuntimeError, match="page 3"):
        parser.fetch_page_text(3)


def test_fetch_index_uses_valid_cache(parser, monkeypatch):
    """A valid cached index is returned without a network call."""
    cache = parser.http.cache_path_for(kebra_nagast.INDEX_URL)
    assert cache is not None
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(fixture("index.htm"), encoding="utf-8")
    calls = stub_fetch(parser, monkeypatch, {})
    assert parser.fetch_index_text() == fixture("index.htm")
    assert calls == []


def test_run_writes_output(tmp_path, monkeypatch):
    """``run`` writes ``kebra-nagast.xml`` into the output directory and closes the parser."""
    book_xml = KebraNagastParser.generate_osis(make_book())
    monkeypatch.setattr(KebraNagastParser, "process", lambda self: book_xml)
    args = argparse.Namespace(cache_dir=None, delay=0, output_dir=str(tmp_path / "out"))
    paths = kebra_nagast.run(args)
    assert paths == [tmp_path / "out" / "kebra-nagast.xml"]
    assert 'osisID="Kebra-Nagast.1.1"' in paths[0].read_text(encoding="utf-8")


def test_spec():
    """The spec exposes the CLI name and single output file."""
    assert kebra_nagast.SPEC.name == "kebra-nagast"
    assert kebra_nagast.SPEC.outputs == ("kebra-nagast.xml",)
    kebra_nagast.add_arguments(argparse.ArgumentParser())
