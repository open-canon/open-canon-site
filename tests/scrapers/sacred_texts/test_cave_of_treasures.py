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


def find(chapter, text: str):
    """Return the first block whose plain text starts with ``text``."""
    return next(b for b in chapter.blocks if cot._plain(b.parts).startswith(text))


def test_headings_verses_and_notes_are_classified(chapter1):
    """Titles, running heads, headings, paragraphs and NOTES are told apart."""
    assert kinds(chapter1) == [
        "heading",  # <h1> THE CAVE OF TREASURES
        "heading",  # TRANSLATION
        "heading",  # (Brit. Mus. MS. Add. 25875.)
        "heading",  # the scribe's prayer title
        "verse",  # the prayer
        "heading",  # THE FIRST THOUSAND YEARS: ...
        "heading",  # Creation. First Day
        "verse",
        "notes",
        "heading",
        "verse",
    ]


def test_running_heads_and_chapter_heading_are_kept_but_navigation_is_dropped(chapter1):
    """Only the site's navigation is dropped; the book's own headings stay."""
    texts = [cot._plain(b.parts) for b in chapter1.blocks]
    assert "THE CAVE OF TREASURES" in texts
    assert "TRANSLATION" in texts
    assert "(Brit. Mus. MS. Add. 25875.)" in texts
    assert "THE FIRST THOUSAND YEARS: ADAM TO YARÊD (Jared)." in texts
    assert not any(t in {"Next", "Previous"} or t.startswith("Sacred-Texts") for t in texts)


def test_heading_brackets_are_stripped(chapter1):
    """Heading text loses its enclosing square brackets."""
    assert find(chapter1, "The Creation. First").kind == "heading"
    assert cot._plain(find(chapter1, "The Creation. First").parts) == "The Creation. First Day."


def test_page_marker_becomes_milestone_inside_the_verse(chapter1):
    """A mid-paragraph ``p. 44`` anchor is a page milestone inside that verse."""
    verse = find(chapter1, "In the beginning")
    milestones = [p for p in verse.parts if isinstance(p, pyosis.MilestoneCt)]
    assert [m.n for m in milestones] == ["44"]
    assert cot._plain(verse.parts) == (
        "In the beginning, on the First Day, God created the heavens, and the earth, and the waters."
    )


def test_leading_page_marker_is_carried_past_headings_to_next_verse(chapter1):
    """A page marker before the headings is not lost: it lands on the next verse."""
    assert not any(isinstance(p, pyosis.MilestoneCt) for b in chapter1.blocks[:4] for p in b.parts)
    first_verse = next(b for b in chapter1.blocks if b.kind == "verse")
    assert isinstance(first_verse.parts[0], pyosis.MilestoneCt)
    assert first_verse.parts[0].n == "43"


def test_folio_reference_stays_in_text(chapter1):
    """Budge's folio reference is kept as printed, not turned into markup."""
    assert cot._plain(find(chapter1, "[Fol. 3b").parts).startswith(
        "[Fol. 3b, col. 1.] By the might"
    )


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
    plate = (FIXTURES / "bct_pl15.htm").read_text(encoding="utf-8")
    seen_plates: list[str] = []
    monkeypatch.setattr(parser, "fetch_page_text", lambda source: seen.append(source.page) or page)
    monkeypatch.setattr(parser, "fetch_plate_text", lambda stem: seen_plates.append(stem) or plate)
    xml = parser.process().to_xml()
    assert seen == [f"bct0{n}" for n in range(4, 10)]
    assert seen_plates == [f"bct_pl{n:02d}" for n in range(16)]
    assert xml.count('type="x-plate"') == 16
    assert all(f'osisID="CaveOfTreasures.{n}"' in xml for n in range(1, 7))


def test_run_writes_output_file(tmp_path, monkeypatch):
    """``run`` writes ``cave-of-treasures.xml`` into the output directory."""
    page = (FIXTURES / "bct04.htm").read_text(encoding="utf-8")
    plate = (FIXTURES / "bct_pl15.htm").read_text(encoding="utf-8")
    monkeypatch.setattr(CaveOfTreasuresParser, "fetch_page_text", lambda self, source: page)
    monkeypatch.setattr(CaveOfTreasuresParser, "fetch_plate_text", lambda self, stem: plate)
    args = argparse.Namespace(cache_dir=None, delay=0, output_dir=str(tmp_path / "out"))
    (path,) = cot.run(args)
    assert path == tmp_path / "out" / "cave-of-treasures.xml"
    assert "CaveOfTreasures.1.1" in path.read_text(encoding="utf-8")


def test_spec_is_registered():
    """The scraper is registered under its CLI name with one output."""
    spec = registry.get_scraper("cave-of-treasures")
    assert spec.outputs == ("cave-of-treasures.xml",)
    assert spec is cot.SPEC


def test_table_row_with_text_and_image_is_a_verse_then_a_figures_block(chapter6):
    """Nothing in a table is dropped: its text is a verse and its image a figure with absolute URL."""
    verse = next(b for b in chapter6.blocks if cot._plain(b.parts) == "1")
    assert verse.kind == "verse"
    figures = chapter6.blocks[chapter6.blocks.index(verse) + 1]
    assert figures.kind == "figures"
    assert figures.images == [
        cot.Image(src="https://archive.sacred-texts.com/chr/bct/cnf-star.jpg", alt="cuneiform")
    ]


def test_multi_cell_rows_join_cells_with_a_bar(parser):
    """A non-list row keeps every cell, joined with `` | ``."""
    html = (
        "<html><body><table><tr><td>1</td><td>The Labourer</td><td>Goat</td><td>Nisannu</td></tr>"
        "</table></body></html>"
    )
    (block,) = parser.parse_chapter(html, 1).blocks
    assert cot._plain(block.parts) == "1 | The Labourer | Goat | Nisannu"


def test_parse_plate_reads_label_facing_images_and_caption(parser):
    """A plate page yields its label, facing page, images in order and caption text."""
    plate = parser.parse_plate((FIXTURES / "bct_pl15.htm").read_text(encoding="utf-8"), "bct_pl15")
    assert plate.label == "PLATE XV"
    assert plate.facing == "272"
    assert [i.src.rsplit("/", 1)[1] for i in plate.images] == [
        "pl15-1.jpg",
        "pl15-2.jpg",
        "pl15-3.jpg",
    ]
    assert plate.images[0].src.startswith("https://archive.sacred-texts.com/chr/bct/")
    assert 'Incised shell plaques from "Ur of the Chaldees."' in plate.caption
    assert {"1", "2", "3"} <= set(plate.caption)
    assert any("Shell plaque of the Ist dynasty" in c for c in plate.caption)
    assert not any("List of Plates" in c for c in plate.caption)


def test_generate_osis_emits_figures_and_plates(parser, chapter6):
    """Inline figures and the plates div appear in the output with their URLs."""
    plate = parser.parse_plate((FIXTURES / "bct_pl15.htm").read_text(encoding="utf-8"), "bct_pl15")
    xml = parser.generate_osis([chapter6], [plate]).to_xml()
    assert 'type="x-figures"' in xml
    assert 'src="https://archive.sacred-texts.com/chr/bct/cnf-star.jpg"' in xml
    assert 'alt="cuneiform"' in xml
    assert 'type="x-plates"' in xml
    assert "PLATE XV (facing page 272)" in xml
    assert xml.count("<figure") == 4


def test_is_valid_plate_page():
    """A plate page needs an image and must not be an interstitial."""
    good = (FIXTURES / "bct_pl15.htm").read_text(encoding="utf-8")
    assert CaveOfTreasuresParser.is_valid_plate_page(good)
    assert not CaveOfTreasuresParser.is_valid_plate_page("<html><p>no images</p></html>")
    assert not CaveOfTreasuresParser.is_valid_plate_page("Just a moment <img src='a'>")


def test_list_row_number_and_text_are_one_string_in_the_verse(chapter6):
    """The ``1.`` marker and the row text form a single string, so the verse serialises whole."""
    first = [b for b in chapter6.blocks if b.kind == "verse"][0]
    assert first.parts == ["1. Adam begot Seth."]


def test_plate_footer_navigation_is_not_caption(parser):
    """The page footer's site links do not leak into a plate caption."""
    html = (
        (FIXTURES / "bct_pl15.htm")
        .read_text(encoding="utf-8")
        .replace(
            "</body>",
            "<p>Sacred Texts | Christianity</p><p>« Previous: The Book - Plate XIV</p>"
            "<p>Next: The Book - Index »</p></body>",
        )
    )
    plate = parser.parse_plate(html, "bct_pl15")
    assert not any("Previous:" in c or "Next:" in c or "Christianity" in c for c in plate.caption)


def test_folio_prefixed_heading_keeps_folio_on_next_verse(parser):
    """``[Fol. 13b, col. 2] [Title].`` becomes the title, with the folio moved to the verse."""
    html = (
        "<html><body><p align='center'>[THE SECOND THOUSAND YEARS: X.]</p>"
        "<p align='center'>[<font><a name='f'></a>Fol. 13<i>b</i>, col. 2] [The Rule of Enoch].</p>"
        "<p>   And Enoch ruled.</p></body></html>"
    )
    chapter = parser.parse_chapter(html, 2)
    assert [b.kind for b in chapter.blocks] == ["heading", "heading", "verse"]
    assert cot._plain(chapter.blocks[1].parts) == "The Rule of Enoch"
    assert cot._plain(chapter.blocks[2].parts) == "[Fol. 13b, col. 2] And Enoch ruled."


def test_internal_link_text_in_footnote_is_kept(parser):
    """A footnote's ``#page_N`` cross-reference keeps its visible text."""
    html = (
        "<html><body><p>Text.<a name='page_9_fr_1'></a><a href='#page_9_note_1'>1</a></p>"
        "<hr/><h3>Footnotes</h3>"
        "<p><a name='page_9_note_1'></a><a href='#page_9_fr_1'>1</a> See below, "
        "(<a href='#page_233'>page 233</a>) for more.</p></body></html>"
    )
    chapter = parser.parse_chapter(html, 1)
    note = next(p for p in chapter.blocks[0].parts if isinstance(p, pyosis.NoteCt))
    assert (
        "".join(c for c in note.content if isinstance(c, str)) == "See below, (page 233) for more."
    )
