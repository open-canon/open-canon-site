"""Unit tests for ``open_canon_site.scrapers.sacred_texts.book_of_the_bee`` (offline fixtures)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pyosis
import pytest
from bs4 import BeautifulSoup
from open_canon_site.scrapers import registry
from open_canon_site.scrapers.sacred_texts import book_of_the_bee as bee
from open_canon_site.scrapers.sacred_texts import cave_of_treasures as cot
from open_canon_site.scrapers.sacred_texts.book_of_the_bee import BookOfTheBeeParser

FIXTURES = Path(__file__).parent / "fixtures" / "book_of_the_bee"


@pytest.fixture
def parser(tmp_path):
    """Return a parser with a tmp cache directory, closed after the test."""
    instance = BookOfTheBeeParser(cache_dir=str(tmp_path / "cache"), delay=0)
    yield instance
    instance.close()


def section(parser, page: str, number: int):
    """Parse one fixture page as the matching source."""
    source = next(s for s in bee.SECTIONS if s.page == page)
    return parser.parse_section(
        (FIXTURES / f"{page}.htm").read_text(encoding="utf-8"), source, number
    )


def test_sections_are_front_matter_then_sixty_numbered_chapters():
    """Three unnumbered pages come first, then bb01 to bb60 in order."""
    assert [s.page for s in bee.FRONT_MATTER] == ["bbtp", "bbpref", "bb00"]
    assert [s.page for s in bee.CHAPTERS] == [f"bb{n:02d}" for n in range(1, 61)]
    assert len(bee.CHAPTER_TITLES) == 60
    assert [s.page for s in bee.SECTIONS] == [
        *(s.page for s in bee.FRONT_MATTER),
        *(s.page for s in bee.CHAPTERS),
    ]


def test_roman_numerals():
    """The chapter markers use correct Roman numerals."""
    assert [bee._roman(n) for n in (1, 4, 9, 14, 39, 40, 49, 60)] == [
        "I", "IV", "IX", "XIV", "XXXIX", "XL", "XLIX", "LX",
    ]  # fmt: skip


def test_chapter_headings_verses_and_navigation(parser):
    """The chapter heading and title are sub-titles; navigation and footnotes are dropped."""
    chapter = section(parser, "bb01", 1)
    kinds = [b.kind for b in chapter.blocks]
    assert kinds[:2] == ["heading", "heading"]
    assert set(kinds[2:]) == {"verse"}
    texts = [cot._plain(b.parts) for b in chapter.blocks]
    assert not any(t.startswith(("Sacred-Texts", "Next", "Footnotes")) for t in texts)
    assert texts[1] == "OF GOD'S ETERNAL INTENTION IN RESPECT OF THE CREATION OF THE UNIVERSE."


def test_small_caps_initials_are_joined_and_footnotes_become_notes(parser):
    """``I<small>T</small>`` reads ``IT``; footnote references become inline notes."""
    chapter = section(parser, "bb01", 1)
    first = next(b for b in chapter.blocks if b.kind == "verse")
    assert cot._plain(first.parts).startswith("IT is well for us to take the materials")
    notes = [p for p in first.parts if isinstance(p, pyosis.NoteCt)]
    assert [n.n for n in notes][:2] == ["2", "3"]
    assert "".join(notes[0].content) == "Ps. xc. 1, 2."


def test_heading_footnote_is_kept_as_note(parser):
    """The footnote on ``CHAPTER I`` stays in the heading."""
    chapter = section(parser, "bb01", 1)
    heading = chapter.blocks[0].parts
    assert any(isinstance(p, pyosis.NoteCt) and p.n == "1" for p in heading)


def test_page_markers_become_milestones(parser):
    """The printed page numbers ``p. 6`` and ``p. 7`` are milestones."""
    chapter = section(parser, "bb01", 1)
    pages = [p.n for b in chapter.blocks for p in b.parts if isinstance(p, pyosis.MilestoneCt)]
    assert "6" in pages or "7" in pages


def test_numbered_list_lines_keep_printed_numbers(parser):
    """Chapter 51's list of catholici keeps its ``1.`` ``2.`` numbers inside each verse."""
    chapter = section(parser, "bb51", 51)
    verses = [cot._plain(b.parts) for b in chapter.blocks if b.kind == "verse"]
    assert verses[0].startswith("1. Addai was buried in Edessa")
    assert verses[1].startswith("2. Mârî (was buried) in the convent of Kônî")


def test_front_matter_is_not_numbered(parser):
    """The preface is a non-canonical div of paragraphs."""
    preface = section(parser, "bbpref", 0)
    doc = parser.generate_osis([preface])
    xml = doc.to_xml()
    assert 'type="preface"' in xml
    assert "Bee.0" not in xml
    assert "<verse" not in xml


def test_generate_osis_ids(parser):
    """Chapters are ``Bee.<n>`` and verses ``Bee.<n>.<m>`` numbered from 1."""
    doc = parser.generate_osis([section(parser, "bb01", 1), section(parser, "bb51", 51)])
    xml = doc.to_xml()
    assert 'osisID="Bee.1"' in xml
    assert 'osisID="Bee.1.1"' in xml
    assert 'osisID="Bee.51"' in xml
    assert 'osisID="Bee.51.2"' in xml
    assert 'osisID="Bee.51.1"' in xml


def test_is_valid_page_rejects_interstitial_and_wrong_page(parser):
    """A Cloudflare interstitial or another chapter's page is not valid."""
    page = (FIXTURES / "bb01.htm").read_text(encoding="utf-8")
    assert parser.is_valid_page(page, bee.CHAPTERS[0])
    assert not parser.is_valid_page(page, bee.CHAPTERS[1])
    assert not parser.is_valid_page("<html>Just a moment...</html>", bee.CHAPTERS[0])


def test_fetch_page_text_uses_archive_url_and_rejects_invalid(parser, monkeypatch):
    """The page URL is on the archive host; an invalid page raises."""
    urls: list[str] = []

    def fake_fetch(url: str) -> str:
        urls.append(url)
        return "<html>Just a moment...</html>"

    monkeypatch.setattr(parser.http, "fetch_text", fake_fetch)
    with pytest.raises(RuntimeError):
        parser.fetch_page_text(bee.CHAPTERS[0])
    assert urls == ["https://archive.sacred-texts.com/chr/bb/bb01.htm"]


def test_spec_registered():
    """The scraper is registered and writes one file."""
    spec = registry.get_scraper("book-of-the-bee")
    assert spec.outputs == ("book-of-the-bee.xml",)
    spec.add_arguments(argparse.ArgumentParser())


@pytest.mark.network
def test_live_chapter_one(parser):
    """Chapter I fetched from the live site parses to the same shape as the fixture."""
    chapter = section_live(parser)
    assert chapter.blocks[0].kind == "heading"
    assert any(b.kind == "verse" for b in chapter.blocks)


def section_live(parser):
    """Fetch and parse chapter 1 over the network."""
    source = bee.CHAPTERS[0]
    return parser.parse_section(parser.fetch_page_text(source), source, 1)


def test_footnote_page_labels_are_not_note_text(parser):
    """A footnote that runs across a page break does not contain the ``p. v`` label."""
    preface = section(parser, "bbpref", 0)
    doc = parser.generate_osis([preface])
    xml = doc.to_xml()
    assert "See Rosen and Forshall's" in " ".join(xml.split())
    assert "Rosen p. v" not in " ".join(xml.split())


def test_page_cross_references_in_footnotes_are_kept(parser):
    """A genuine ``p.`` reference in a footnote's wording stays."""
    footnotes = parser.parse_footnotes(
        BeautifulSoup(
            '<h3>Footnotes</h3><p><a name="page_1_note_1"></a><a href="#page_1_fr_1">1</a> '
            'Compare p. 12 and <a name="footnotes_page_2"></a><font color="GREEN">p. 2</font>'
            " more.</p>",
            "html.parser",
        )
    )
    assert "".join(footnotes["page_1_note_1"].parts) == "Compare p. 12 and more."


def test_inline_figure_is_kept_with_bee_url(parser):
    """The watermark ``v.jpg`` in the preface is a figure resolved against ``/chr/bb/``."""
    preface = section(parser, "bbpref", 0)
    xml = parser.generate_osis([preface]).to_xml()
    assert 'src="https://archive.sacred-texts.com/chr/bb/v.jpg"' in xml
    assert "/chr/bct/" not in xml


def test_heading_note_is_visible_on_the_site(parser, tmp_path):
    """The footnote on ``CHAPTER I`` appears as a marker in the heading and in the notes tray."""
    from open_canon_site.generator import generate_site

    xml_path = tmp_path / "bee.xml"
    xml_path.write_text(
        parser.generate_osis([section(parser, "bb01", 1)]).to_xml(), encoding="utf-8"
    )
    out = tmp_path / "site"
    generate_site([xml_path], out)
    page = next(out.rglob("*.html"))
    pages = [p.read_text(encoding="utf-8") for p in out.rglob("*.html")]
    html = next(p for p in pages if "Chap. ii in the Oxford MS." in p)
    heading = html[html.index("verse-heading") :]
    assert 'class="note-marker"' in heading[: heading.index("</div>")]
    notes_tray = html[html.index('id="notes-tray-inner"') : html.index("</aside>")]
    assert "Chap. ii in the Oxford MS." in notes_tray
    assert page.exists()
