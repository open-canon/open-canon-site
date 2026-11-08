"""Unit tests for ``open_canon_site.scrapers.sacred_texts.pseudo_philo`` (offline, trimmed real pages)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pyosis
import pytest
from open_canon_site.scrapers.sacred_texts import pseudo_philo
from open_canon_site.scrapers.sacred_texts.pseudo_philo import (
    PseudoPhiloParser,
    verse_marker_re,
)

FIXTURES = Path(__file__).parent / "fixtures" / "pseudo_philo"


def fixture(name: str) -> str:
    """Return the text of a fixture page (trimmed copies of archive.sacred-texts.com pages)."""
    return (FIXTURES / f"{name}.htm").read_text(encoding="utf-8")


def flatten(parts: list) -> str:
    """Flatten inline parts to text, skipping notes."""
    text = ""
    for part in parts:
        if isinstance(part, str):
            text += part
        elif not isinstance(part, pyosis.NoteCt):
            text += flatten(part.content)
    return text


@pytest.fixture
def parser():
    """Return a parser without a cache, closed after the test."""
    instance = PseudoPhiloParser(cache_dir=None, delay=0)
    yield instance
    instance.close()


@pytest.mark.parametrize(
    ("verse", "text", "matches"),
    [
        (7, "and 7. And he", True),
        (3, "3, And he", True),
        (4, "4 And when", True),
        (4, "4 sons", False),
        (4, "of 14. And", False),
        (2, "2.", True),
    ],
)
def test_verse_marker_re(verse: int, text: str, matches: bool) -> None:
    """Markers match with a period, comma, or bare before a capital, and only as whole numbers."""
    assert bool(verse_marker_re(verse).search(text)) is matches


def test_first_chapter_page(parser: PseudoPhiloParser) -> None:
    """Chapter I: the Roman numeral opens verse 1, inline numbers split verses, margin refs drop."""
    (chapter,) = parser.parse_chapter_page(17, fixture("bap17"))
    assert chapter.number == 1
    assert [verse.number for verse in chapter.verses] == [1, 2, 3, 4, 5, 6]
    first = chapter.verses[0]
    assert isinstance(first.parts[0], pyosis.NoteCt)
    assert flatten(first.parts).startswith("The beginning of the world.")
    assert "Gen. 5:4" not in "".join(flatten(v.parts) for v in chapter.verses)
    assert (
        flatten(chapter.verses[1].parts)
        == "And Adam lived after he begat Seth 700 years, and begat 12 sons and 8 daughters."
    )
    assert (
        flatten(chapter.verses[5].parts)
        == "But Enoch pleased God at that time and was not found, for God translated him."
    )


def test_page_with_two_chapters(parser: PseudoPhiloParser) -> None:
    """bap58 carries chapters 42 and 43; chapter 43 starts at the paragraph opening ``XLIII.``."""
    chapters = parser.parse_chapter_page(58, fixture("bap58"))
    assert [chapter.number for chapter in chapters] == [42, 43]
    assert [v.number for v in chapters[0].verses] == [1, 2, 3]
    assert [v.number for v in chapters[1].verses] == [1, 2, 3, 4]
    assert flatten(chapters[0].verses[0].parts).startswith(
        "Now there was a man of the tribe of Dan"
    )
    assert flatten(chapters[1].verses[0].parts).startswith(
        "And it came to pass in the time of those days"
    )
    assert isinstance(chapters[0].verses[0].parts[-1], pyosis.NoteCt)


def test_verse_marker_variants_and_page_breaks(parser: PseudoPhiloParser) -> None:
    """A marker without a period (``4 And``) is accepted and a paragraph cut by a page break is rejoined."""
    (chapter,) = parser.parse_chapter_page(72, fixture("bap72"))
    assert chapter.number == 58
    assert [v.number for v in chapter.verses] == [1, 2, 3, 4]
    assert flatten(chapter.verses[3].parts).endswith(
        "Therefore he that was saved alive by thee shall die now, and 40 men returned unto his house."
    )


def test_chapter_page_errors(parser: PseudoPhiloParser) -> None:
    """Invalid pages and pages without a chapter heading raise ``RuntimeError``."""
    with pytest.raises(RuntimeError):
        parser.parse_chapter_page(17, "<html>Just a moment</html>")
    with pytest.raises(RuntimeError, match="No chapter heading"):
        parser.parse_chapter_page(17, "<html><body>Philo<hr><p>Text</p><hr></body></html>")


def test_front_matter_pages(parser: PseudoPhiloParser) -> None:
    """The title page keeps its headings; an introduction page merges paragraphs cut by a page break."""
    title = parser.parse_front_matter_page(0, fixture("bap00"))
    assert title.div_type == pyosis.OsisDivs.TITLE_PAGE
    assert [flatten(p) for p in title.paragraphs][:2] == [
        "THE BIBLICAL ANTIQUITIES OF PHILO",
        "NOW FIRST",
    ]
    intro = parser.parse_front_matter_page(2, fixture("bap02"))
    assert intro.title == "Introduction: 1. General"
    assert intro.div_type == pyosis.OsisDivs.FRONT
    assert len(intro.paragraphs) == 2
    assert "destruction of Jerusalem in A.D. 70" in flatten(intro.paragraphs[1])


def test_generate_osis(parser: PseudoPhiloParser) -> None:
    """The document has front matter, canonical chapters and ``PsPhilo.<c>.<v>`` verse ids."""
    front = [parser.parse_front_matter_page(0, fixture("bap00"))]
    chapters = parser.parse_chapter_page(58, fixture("bap58"))
    xml = parser.generate_osis(front, chapters).to_xml()
    assert 'osisID="PsPhilo.43.4"' in xml
    assert 'osisID="PsPhilo.42"' in xml
    assert "Pseudo-Philo" in xml


def test_extract_chapter_pages() -> None:
    """Page numbers are read from index links in order, without duplicates."""
    html = '<a href="bap00.htm">a</a><a HREF="bap17.htm">b</a><a href="bap17.htm">c</a><a href="x.htm">d</a>'
    assert PseudoPhiloParser.extract_chapter_pages(html) == [0, 17]


def test_page_url() -> None:
    """URLs point at the archive host with zero-padded page numbers."""
    assert PseudoPhiloParser.page_url(7) == "https://archive.sacred-texts.com/bib/bap/bap07.htm"
    assert PseudoPhiloParser.page_url("index").endswith("/bib/bap/index.htm")


def test_fetch_page_rejects_interstitial(parser: PseudoPhiloParser, monkeypatch) -> None:
    """A fetched page that is not the book raises ``RuntimeError``."""
    monkeypatch.setattr(parser.http, "fetch_text", lambda **_: "<html>Just a moment</html>")
    with pytest.raises(RuntimeError, match="did not contain"):
        parser.fetch_page(17)


def test_process_rejects_wrong_page_list(parser: PseudoPhiloParser, monkeypatch) -> None:
    """``process`` refuses an index that does not link the expected pages."""
    monkeypatch.setattr(parser, "fetch_page", lambda *_a, **_k: '<html>Philo<a href="bap00.htm">')
    with pytest.raises(RuntimeError, match="page list"):
        parser.process()


def test_spec_and_run(monkeypatch, tmp_path: Path) -> None:
    """The spec names the scraper and ``run`` writes the one output file."""
    assert pseudo_philo.SPEC.name == "pseudo-philo"
    assert pseudo_philo.SPEC.outputs == ("pseudo-philo.xml",)

    class Stub(PseudoPhiloParser):
        def process(self):
            return self.generate_osis([], self.parse_chapter_page(17, fixture("bap17")))

    monkeypatch.setattr(pseudo_philo, "PseudoPhiloParser", Stub)
    args = argparse.Namespace(cache_dir=None, delay=0, output_dir=tmp_path)
    (path,) = pseudo_philo.run(args)
    assert path == tmp_path / "pseudo-philo.xml"
    assert "PsPhilo.1.1" in path.read_text(encoding="utf-8")


def test_italic_opened_before_paragraph_and_marker_inside_italics(
    parser: PseudoPhiloParser,
) -> None:
    """``<I><P>`` (italics cut by a page break) keeps its text, and markers inside italics split verses."""
    html = (
        "<html>Philo<hr><h3>CHAPTER LXV.</h3>"
        "<P>LXV. <I>And the Philistines fought</I>&nbsp;</P>"
        '<P><A NAME="page_242"><FONT SIZE=1>p. 242</FONT></A></P>'
        "<I><P>before the Philistines</I>: and Saul fled. 2. <I>And Saul said: Slay me. 3. And he bowed</I>.</P>"
        "<hr></html>"
    )
    (chapter,) = parser.parse_chapter_page(79, html)
    assert [v.number for v in chapter.verses] == [1, 2, 3]
    assert (
        flatten(chapter.verses[0].parts)
        == "And the Philistines fought before the Philistines: and Saul fled."
    )
    assert flatten(chapter.verses[1].parts) == "And Saul said: Slay me."
    assert isinstance(chapter.verses[2].parts[0], pyosis.HiCt)
