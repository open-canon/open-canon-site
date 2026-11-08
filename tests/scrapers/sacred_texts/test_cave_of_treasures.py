"""Unit tests for ``open_canon_site.scrapers.sacred_texts.cave_of_treasures`` (offline fixtures)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pyosis
import pytest
from open_canon_site.scrapers import registry
from open_canon_site.scrapers.sacred_texts import cave_of_treasures as cot
from open_canon_site.scrapers.sacred_texts.cave_of_treasures import CaveOfTreasuresParser

FIXTURES = Path(__file__).parent / "fixtures" / "cave_of_treasures"


@pytest.fixture
def parser(tmp_path):
    """Return a parser with a tmp cache directory, closed after the test."""
    instance = CaveOfTreasuresParser(cache_dir=str(tmp_path / "cache"), delay=0)
    yield instance
    instance.close()


@pytest.fixture
def chapter1(parser):
    """Parse the first-thousand-years fixture as chapter 1."""
    return parser.parse_chapter((FIXTURES / "bct04.htm").read_text(encoding="utf-8"), 1)


@pytest.fixture
def chapter6(parser):
    """Parse the five-hundred-years fixture as chapter 6."""
    return parser.parse_chapter((FIXTURES / "bct09.htm").read_text(encoding="utf-8"), 6)


def kinds(chapter) -> list[str]:
    """Return the block kinds of a chapter in order."""
    return [block.kind for block in chapter.blocks]


def test_chapter_table_is_six_ordered_pages():
    """Six chapters, bct04 through bct09, in order."""
    assert [c.page for c in cot.CHAPTERS] == [f"bct0{n}" for n in range(4, 10)]


def test_headings_verses_and_notes_are_classified(chapter1):
    """Bracketed centred headings, paragraphs and NOTES are told apart; furniture is dropped."""
    assert kinds(chapter1) == [
        "heading",  # the scribe's prayer title
        "verse",  # the prayer
        "heading",  # Creation. First Day
        "verse",
        "notes",
        "heading",
        "verse",
    ]


def test_chapter_title_heading_navigation_and_running_heads_are_dropped(chapter1):
    """The chapter heading, nav line and manuscript running heads do not become blocks."""
    texts = [cot._plain(b.parts) for b in chapter1.blocks]
    assert not any("THOUSAND YEARS" in t or "TRANSLATION" in t or "Brit. Mus" in t for t in texts)
    assert not any(t in {"Next", "Previous"} or t.startswith("Sacred-Texts") for t in texts)


def test_heading_brackets_are_stripped(chapter1):
    """Heading text loses its enclosing square brackets."""
    assert cot._plain(chapter1.blocks[2].parts) == "The Creation. First Day."


def test_page_marker_becomes_milestone_inside_the_verse(chapter1):
    """A mid-paragraph ``p. 44`` anchor is a page milestone inside that verse."""
    verse = chapter1.blocks[3]
    milestones = [p for p in verse.parts if isinstance(p, pyosis.MilestoneCt)]
    assert [m.n for m in milestones] == ["44"]
    assert cot._plain(verse.parts) == (
        "In the beginning, on the First Day, God created the heavens, and the earth, and the waters."
    )


def test_leading_page_marker_paragraph_is_carried_to_next_block(chapter1):
    """A page-marker-only paragraph before the first text attaches to that text."""
    first = chapter1.blocks[0].parts
    assert isinstance(first[0], pyosis.MilestoneCt)
    assert first[0].n == "43"


def test_folio_reference_stays_in_text(chapter1):
    """Budge's folio reference is kept as printed, not turned into markup."""
    assert cot._plain(chapter1.blocks[1].parts).startswith("[Fol. 3b, col. 1.] By the might")


def test_numbered_list_rows_are_verses_and_image_tables_dropped(chapter6):
    """Numbered table rows become verses; the cuneiform image table is dropped."""
    verses = [cot._plain(b.parts) for b in chapter6.blocks if b.kind == "verse"]
    assert verses[:3] == [
        "1. Adam begot Seth.",
        "2. Seth took to wife Kelîmath, and begot by her Enos.",
        "3. Enos took to wife Hannâ.",
    ]
    assert not any("cuneiform" in v for v in verses)


def test_page_marker_row_inside_table_is_carried_forward(chapter6):
    """A table row holding only a page marker attaches to the next list verse."""
    third = [b for b in chapter6.blocks if b.kind == "verse"][2]
    assert isinstance(third.parts[0], pyosis.MilestoneCt)
    assert third.parts[0].n == "198"


def test_footnote_becomes_inline_note_in_heading(chapter6):
    """The footnote reference in a heading becomes a ``NoteCt`` carrying the footnote text."""
    heading = next(b for b in chapter6.blocks if "Flight" in cot._plain(b.parts))
    notes = [p for p in heading.parts if isinstance(p, pyosis.NoteCt)]
    assert len(notes) == 1
    assert notes[0].n == "1"
    assert "order in which this paragraph appears" in "".join(
        p for p in notes[0].content if isinstance(p, str)
    )


def test_footnote_paragraphs_are_not_content(chapter6):
    """The Footnotes block is not parsed as verses."""
    assert not any("order in which" in cot._plain(b.parts) for b in chapter6.blocks)


def test_unbracketed_centred_closing_line_is_a_verse(chapter6):
    """A centred line without brackets (the closing doxology) is text, not a heading."""
    assert cot._plain(chapter6.blocks[-1].parts) == "And to God be glory for ever!"
    assert chapter6.blocks[-1].kind == "verse"


def test_is_valid_page_checks_marker_and_interstitial():
    """A page must show its chapter's heading and not be a Cloudflare interstitial."""
    text = (FIXTURES / "bct04.htm").read_text(encoding="utf-8")
    assert CaveOfTreasuresParser.is_valid_page(text, cot.CHAPTERS[0])
    assert not CaveOfTreasuresParser.is_valid_page(text, cot.CHAPTERS[1])
    assert not CaveOfTreasuresParser.is_valid_page("<html>Just a moment</html>", cot.CHAPTERS[0])


def test_fetch_page_text_uses_cache_and_replaces_invalid_cache(parser, monkeypatch):
    """A valid cache is used; an invalid one is deleted and refetched; a bad fetch raises."""
    source = cot.CHAPTERS[0]
    url = cot.PAGE_URL_TEMPLATE.format(page=source.page)
    good = (FIXTURES / "bct04.htm").read_text(encoding="utf-8")
    cache_path = parser.http.cache_path_for(url)
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text("Just a moment", encoding="utf-8")
    calls: list[str] = []

    def fake_fetch_text(*, url: str, retry_count: int = 3) -> str:
        """Return the genuine page and record the call."""
        calls.append(url)
        return good

    monkeypatch.setattr(parser.http, "fetch_text", fake_fetch_text)
    assert parser.fetch_page_text(source) == good
    assert calls == [url]

    monkeypatch.setattr(parser.http, "fetch_text", lambda *, url, retry_count=3: "Just a moment")
    cache_path.unlink(missing_ok=True)
    with pytest.raises(RuntimeError, match="may be blocked"):
        parser.fetch_page_text(source)


def test_generate_osis_numbers_verses_per_chapter(parser, chapter1, chapter6):
    """Verse ids run ``CaveOfTreasures.<chapter>.<n>`` from 1 per chapter; notes are unnumbered."""
    xml = parser.generate_osis([chapter1, chapter6]).to_xml()
    assert 'osisID="CaveOfTreasures.1"' in xml
    assert 'osisID="CaveOfTreasures.1.1"' in xml
    assert 'osisID="CaveOfTreasures.1.3"' in xml
    assert 'osisID="CaveOfTreasures.1.4"' not in xml
    assert 'osisID="CaveOfTreasures.6.1"' in xml
    assert 'type="x-notes"' in xml
    assert 'type="page" n="44"' in xml or 'n="44"' in xml
    assert "The First Thousand Years" in xml


def test_process_fetches_all_six_pages(parser, monkeypatch):
    """The pipeline fetches bct04..bct09 and emits six chapters."""
    page = (FIXTURES / "bct04.htm").read_text(encoding="utf-8")
    seen: list[str] = []
    monkeypatch.setattr(parser, "fetch_page_text", lambda source: seen.append(source.page) or page)
    xml = parser.process().to_xml()
    assert seen == [f"bct0{n}" for n in range(4, 10)]
    assert all(f'osisID="CaveOfTreasures.{n}"' in xml for n in range(1, 7))


def test_run_writes_output_file(tmp_path, monkeypatch):
    """``run`` writes ``cave-of-treasures.xml`` into the output directory."""
    page = (FIXTURES / "bct04.htm").read_text(encoding="utf-8")
    monkeypatch.setattr(CaveOfTreasuresParser, "fetch_page_text", lambda self, source: page)
    args = argparse.Namespace(cache_dir=None, delay=0, output_dir=str(tmp_path / "out"))
    (path,) = cot.run(args)
    assert path == tmp_path / "out" / "cave-of-treasures.xml"
    assert "CaveOfTreasures.1.1" in path.read_text(encoding="utf-8")


def test_spec_is_registered():
    """The scraper is registered under its CLI name with one output."""
    spec = registry.get_scraper("cave-of-treasures")
    assert spec.outputs == ("cave-of-treasures.xml",)
    assert spec is cot.SPEC
