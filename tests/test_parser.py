"""Tests for the OSIS document parser."""

from __future__ import annotations

import textwrap

import pyosis

from open_canon_site.parser import (
    NoteData,
    _slugify,
    _text_of,
    parse_osis_text,
)

# ---------------------------------------------------------------------------
# Minimal sample XML helpers
# ---------------------------------------------------------------------------

_NS = 'xmlns="http://www.bibletechnologies.net/2003/OSIS/namespace"'


def _make_osis_xml(body: str, work_id: str = "TEST") -> str:
    return textwrap.dedent(
        f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <osis {_NS}>
          <osisText osisIDWork="{work_id}" xml:lang="en">
            <header>
              <work osisWork="{work_id}">
                <title>Test Document</title>
              </work>
            </header>
            {body}
          </osisText>
        </osis>
        """
    )


def _parse(body: str, work_id: str = "TEST"):
    xml = _make_osis_xml(body, work_id)
    osis_xml = pyosis.OsisXML.from_xml(xml)
    return parse_osis_text(osis_xml.osis.osis_text)


# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------


def test_slugify_simple():
    assert _slugify("Gen") == "gen"


def test_slugify_dotted():
    assert _slugify("Gen.1") == "gen-1"


def test_slugify_spaces():
    assert _slugify("Old Testament") == "old-testament"


def test_slugify_trims_dashes():
    assert _slugify("--test--") == "test"


# ---------------------------------------------------------------------------
# Document parsing – title and work_id
# ---------------------------------------------------------------------------


def test_parse_work_id():
    doc = _parse(
        "<div type='book' osisID='B'><div type='chapter' osisID='B.1'></div></div>", work_id="KJV"
    )
    assert doc.work_id == "KJV"


def test_parse_title_from_header():
    doc = _parse("<div type='book' osisID='B'><div type='chapter' osisID='B.1'></div></div>")
    assert doc.title == "Test Document"


def test_parse_slug_from_work_id():
    doc = _parse(
        "<div type='book' osisID='B'><div type='chapter' osisID='B.1'></div></div>", work_id="KJV"
    )
    assert doc.slug == "kjv"


# ---------------------------------------------------------------------------
# Division extraction
# ---------------------------------------------------------------------------


def test_parse_single_book():
    doc = _parse("""
        <div type="book" osisID="Gen">
          <title>Genesis</title>
          <div type="chapter" osisID="Gen.1">
            <verse osisID="Gen.1.1">In the beginning.</verse>
          </div>
        </div>
    """)
    assert len(doc.divisions) == 1
    assert doc.divisions[0].div_id == "Gen"
    assert doc.divisions[0].title == "Genesis"


def test_parse_book_short_title():
    """The ``short`` attribute on a book title is exposed as ``short_title``."""
    doc = _parse("""
        <div type="book" osisID="1Ne">
          <title short="1 Nephi">The First Book of Nephi</title>
          <div type="chapter" osisID="1Ne.1">
            <verse osisID="1Ne.1.1">Text.</verse>
          </div>
        </div>
    """)
    assert doc.divisions[0].title == "The First Book of Nephi"
    assert doc.divisions[0].short_title == "1 Nephi"


def test_parse_book_no_short_title():
    """A book without a ``short`` attribute has an empty ``short_title``."""
    doc = _parse("""
        <div type="book" osisID="Gen">
          <title>Genesis</title>
          <div type="chapter" osisID="Gen.1">
            <verse osisID="Gen.1.1">In the beginning.</verse>
          </div>
        </div>
    """)
    assert doc.divisions[0].short_title == ""


def test_parse_bookgroup_flattens_into_divisions():
    """bookGroup should be unwrapped; its child books become divisions."""
    doc = _parse("""
        <div type="bookGroup">
          <title>Old Testament</title>
          <div type="book" osisID="Gen">
            <title>Genesis</title>
            <div type="chapter" osisID="Gen.1">
              <verse osisID="Gen.1.1">Text.</verse>
            </div>
          </div>
          <div type="book" osisID="Exod">
            <title>Exodus</title>
            <div type="chapter" osisID="Exod.1">
              <verse osisID="Exod.1.1">Text.</verse>
            </div>
          </div>
        </div>
    """)
    assert len(doc.divisions) == 2
    assert doc.divisions[0].div_id == "Gen"
    assert doc.divisions[1].div_id == "Exod"


# ---------------------------------------------------------------------------
# Chapter extraction
# ---------------------------------------------------------------------------


def test_parse_chapter_contained():
    doc = _parse("""
        <div type="book" osisID="Gen">
          <div type="chapter" osisID="Gen.1">
            <title type="chapter">Chapter 1</title>
            <verse osisID="Gen.1.1">Verse one.</verse>
          </div>
          <div type="chapter" osisID="Gen.2">
            <verse osisID="Gen.2.1">Chapter two verse one.</verse>
          </div>
        </div>
    """)
    assert len(doc.divisions[0].chapters) == 2
    assert doc.divisions[0].chapters[0].chapter_id == "Gen.1"
    assert doc.divisions[0].chapters[0].title == "Chapter 1"
    assert doc.divisions[0].chapters[1].chapter_id == "Gen.2"


def test_parse_chapter_multiword_book_id():
    """Books whose OSIS ID contains a space (e.g. '1 Nephi') should produce correct chapter IDs and numbers."""
    doc = _parse("""
        <div type="book" osisID="1 Nephi">
          <title>The First Book of Nephi</title>
          <div type="chapter" osisID="1 Nephi.1">
            <verse osisID="1 Nephi.1.1">Verse one.</verse>
          </div>
          <div type="chapter" osisID="1 Nephi.2">
            <verse osisID="1 Nephi.2.1">Chapter two verse one.</verse>
          </div>
          <div type="chapter" osisID="1 Nephi.3">
            <verse osisID="1 Nephi.3.1">Chapter three verse one.</verse>
          </div>
        </div>
    """)
    div = doc.divisions[0]
    assert div.div_id == "1 Nephi"
    assert len(div.chapters) == 3
    assert div.chapters[0].chapter_id == "1 Nephi.1"
    assert div.chapters[0].number == "1"
    assert div.chapters[0].title == "Chapter 1"
    assert div.chapters[1].chapter_id == "1 Nephi.2"
    assert div.chapters[1].number == "2"
    assert div.chapters[1].title == "Chapter 2"
    assert div.chapters[2].chapter_id == "1 Nephi.3"
    assert div.chapters[2].number == "3"
    assert div.chapters[2].title == "Chapter 3"


def test_parse_chapter_number_extracted():
    doc = _parse("""
        <div type="book" osisID="Gen">
          <div type="chapter" osisID="Gen.3">
            <verse osisID="Gen.3.1">Text.</verse>
          </div>
        </div>
    """)
    assert doc.divisions[0].chapters[0].number == "3"


def test_parse_chapter_title_uses_arabic_numerals_for_roman_heading():
    doc = _parse("""
        <div type="book" osisID="Gen">
          <div type="chapter" osisID="Gen.18">
            <title type="chapter">CHAPTER XVIII.</title>
            <verse osisID="Gen.18.1">Text.</verse>
          </div>
        </div>
    """)
    assert doc.divisions[0].chapters[0].title == "Chapter 18"


def test_parse_milestone_chapter_title_uses_arabic_numerals_for_roman_heading():
    doc = _parse("""
        <div type="book" osisID="Gen">
          <chapter sID="Gen.9"/>
          <title type="chapter">CHAPTER IX.</title>
          <verse osisID="Gen.9.1">Text.</verse>
          <chapter eID="Gen.9"/>
        </div>
    """)
    assert doc.divisions[0].chapters[0].title == "Chapter 9"


def test_parse_chapter_element_contained():
    """<chapter osisID=...> elements (not <div type=chapter>) should be parsed as chapters."""
    doc = _parse("""
        <div type="book" osisID="1Esd">
          <chapter osisID="1Esd.1">
            <verse osisID="1Esd.1.1">Verse one.</verse>
            <verse osisID="1Esd.1.2">Verse two.</verse>
          </chapter>
          <chapter osisID="1Esd.2">
            <verse osisID="1Esd.2.1">Chapter two verse one.</verse>
          </chapter>
        </div>
    """)
    div = doc.divisions[0]
    assert len(div.chapters) == 2
    assert div.chapters[0].chapter_id == "1Esd.1"
    assert div.chapters[0].number == "1"
    assert div.chapters[1].chapter_id == "1Esd.2"


def test_parse_chapter_element_verses_extracted():
    """Verses inside contained <chapter> elements should be extracted."""
    doc = _parse("""
        <div type="book" osisID="1Esd">
          <chapter osisID="1Esd.1">
            <verse osisID="1Esd.1.1">Hello world.</verse>
            <verse osisID="1Esd.1.2">Second verse.</verse>
          </chapter>
        </div>
    """)
    verses = doc.divisions[0].chapters[0].verses
    assert len(verses) == 2
    assert verses[0].verse_id == "1Esd.1.1"
    assert verses[1].verse_id == "1Esd.1.2"


def test_parse_chapter_element_title_arabic_numerals():
    """<chapter osisID> roman-numeral chapter titles should be normalised to Arabic numerals."""
    doc = _parse("""
        <div type="book" osisID="1Esd">
          <chapter osisID="1Esd.18">
            <title type="chapter">CHAPTER XVIII.</title>
            <verse osisID="1Esd.18.1">Text.</verse>
          </chapter>
        </div>
    """)
    assert doc.divisions[0].chapters[0].title == "Chapter 18"


def test_parse_front_material_as_renderable_page():
    doc = _parse("""
        <div type="book" osisID="Gen">
          <div type="front">
            <head>Preface</head>
            <p>Introductory material.</p>
          </div>
          <div type="chapter" osisID="Gen.1">
            <verse osisID="Gen.1.1">Verse one.</verse>
          </div>
        </div>
    """)
    page = doc.divisions[0].chapters[0]
    assert page.title == "Preface"
    assert page.verses == []
    assert any("Introductory material" in _text_of([item]) for item in page.body)


def test_parse_chapter_body_without_verses_is_preserved():
    doc = _parse("""
        <div type="book" osisID="Gen">
          <div type="chapter" osisID="Gen.1">
            <title type="chapter">Chapter 1</title>
            <p>Chapter preface paragraph.</p>
          </div>
        </div>
    """)
    chapter = doc.divisions[0].chapters[0]
    assert chapter.verses == []
    assert any("Chapter preface paragraph" in _text_of([item]) for item in chapter.body)


def test_parse_front_material_extracts_nested_notes():
    doc = _parse("""
        <div type="book" osisID="Gen">
          <div type="front">
            <head>Preface</head>
            <p>Text<note type="study">Front note.</note> More text.</p>
          </div>
        </div>
    """)
    page = doc.divisions[0].chapters[0]
    assert len(page.notes) == 1
    assert any(
        isinstance(item, tuple) and item[0] == "note_marker" for item in page.body[0].content
    )


def test_parse_body_sections_for_sidebar_links():
    doc = _parse("""
        <div type="book" osisID="Gen">
          <div type="front">
            <head>Introduction</head>
            <div type="section">
              <head>Overview</head>
              <p>Overview text.</p>
            </div>
            <div type="section">
              <head>Authorship</head>
              <p>Authorship text.</p>
            </div>
          </div>
        </div>
    """)
    page = doc.divisions[0].chapters[0]
    assert [section.title for section in page.sections] == ["Overview", "Authorship"]
    assert [section.anchor for section in page.sections] == ["overview", "authorship"]


def test_parse_body_sections_deduplicate_anchor_slugs():
    doc = _parse("""
        <div type="book" osisID="Gen">
          <div type="front">
            <head>Introduction</head>
            <div type="section">
              <head>Overview</head>
              <p>First.</p>
            </div>
            <div type="section">
              <head>Overview</head>
              <p>Second.</p>
            </div>
          </div>
        </div>
    """)
    page = doc.divisions[0].chapters[0]
    assert [section.anchor for section in page.sections] == ["overview", "overview-2"]


# ---------------------------------------------------------------------------
# Verse extraction
# ---------------------------------------------------------------------------


def test_parse_verse_contained():
    doc = _parse("""
        <div type="book" osisID="Gen">
          <div type="chapter" osisID="Gen.1">
            <verse osisID="Gen.1.1">In the beginning.</verse>
            <verse osisID="Gen.1.2">And the earth.</verse>
          </div>
        </div>
    """)
    verses = doc.divisions[0].chapters[0].verses
    assert len(verses) == 2
    assert verses[0].verse_id == "Gen.1.1"
    assert verses[0].number == "1"
    assert verses[1].verse_id == "Gen.1.2"


def test_parse_verse_multiword_book_id():
    """Verses in books with spaces in their OSIS ID should have correct verse numbers."""
    doc = _parse("""
        <div type="book" osisID="Words of Mormon">
          <chapter osisID="Words of Mormon.1">
            <verse osisID="Words of Mormon.1.1">Verse one.</verse>
            <verse osisID="Words of Mormon.1.2">Verse two.</verse>
          </chapter>
        </div>
    """)
    verses = doc.divisions[0].chapters[0].verses
    assert len(verses) == 2
    assert verses[0].verse_id == "Words of Mormon.1.1"
    assert verses[0].number == "1"
    assert verses[1].verse_id == "Words of Mormon.1.2"
    assert verses[1].number == "2"


def test_parse_verse_text_content():
    doc = _parse("""
        <div type="book" osisID="Gen">
          <div type="chapter" osisID="Gen.1">
            <verse osisID="Gen.1.1">Hello world.</verse>
          </div>
        </div>
    """)
    verse = doc.divisions[0].chapters[0].verses[0]
    text_items = [item for item in verse.content if isinstance(item, str)]
    assert any("Hello world" in t for t in text_items)


# ---------------------------------------------------------------------------
# Note extraction
# ---------------------------------------------------------------------------


def test_parse_note_extracted_from_verse():
    doc = _parse("""
        <div type="book" osisID="Gen">
          <div type="chapter" osisID="Gen.1">
            <verse osisID="Gen.1.1">Text.<note type="study">Commentary.</note></verse>
          </div>
        </div>
    """)
    verse = doc.divisions[0].chapters[0].verses[0]
    assert len(verse.notes) == 1
    assert isinstance(verse.notes[0], NoteData)
    assert verse.notes[0].verse_id == "Gen.1.1"


def test_parse_note_replaced_with_marker_in_content():
    """NoteCt should be removed from verse.content and replaced with a tuple marker."""
    doc = _parse("""
        <div type="book" osisID="Gen">
          <div type="chapter" osisID="Gen.1">
            <verse osisID="Gen.1.1">Text.<note type="study">Note text.</note> More text.</verse>
          </div>
        </div>
    """)
    verse = doc.divisions[0].chapters[0].verses[0]
    # Note should not appear in content as NoteCt
    from pyosis.generated.osis_core_2_1_1 import NoteCt

    assert not any(isinstance(item, NoteCt) for item in verse.content)
    # But a marker tuple should be present
    markers = [
        item for item in verse.content if isinstance(item, tuple) and item[0] == "note_marker"
    ]
    assert len(markers) == 1


def test_parse_multiple_notes_in_verse():
    doc = _parse("""
        <div type="book" osisID="Gen">
          <div type="chapter" osisID="Gen.1">
            <verse osisID="Gen.1.1">A<note type="study">Note 1.</note>B<note type="crossReference">Note 2.</note>C</verse>
          </div>
        </div>
    """)
    verse = doc.divisions[0].chapters[0].verses[0]
    assert len(verse.notes) == 2


def test_parse_note_ids_are_unique():
    doc = _parse("""
        <div type="book" osisID="Gen">
          <div type="chapter" osisID="Gen.1">
            <verse osisID="Gen.1.1">A<note type="study">N1.</note></verse>
            <verse osisID="Gen.1.2">B<note type="study">N2.</note></verse>
          </div>
        </div>
    """)
    chap = doc.divisions[0].chapters[0]
    n1 = chap.verses[0].notes[0].note_id
    n2 = chap.verses[1].notes[0].note_id
    assert n1 != n2


# ---------------------------------------------------------------------------
# Chapter summary extraction
# ---------------------------------------------------------------------------


def test_parse_chapter_summary_div_style():
    """<div type="summary"> inside a <div type="chapter"> is extracted into ChapterData.summary."""
    doc = _parse("""
        <div type="book" osisID="Gen">
          <div type="chapter" osisID="Gen.1">
            <div type="summary">
              <p>The creation of the world.</p>
            </div>
            <verse osisID="Gen.1.1">In the beginning.</verse>
          </div>
        </div>
    """)
    chapter = doc.divisions[0].chapters[0]
    assert chapter.summary
    assert any("The creation of the world" in _text_of([item]) for item in chapter.summary)


def test_parse_chapter_summary_not_in_body():
    """Summary divs should not appear in chapter.body."""
    doc = _parse("""
        <div type="book" osisID="Gen">
          <div type="chapter" osisID="Gen.1">
            <div type="summary">
              <p>Summary text.</p>
            </div>
            <verse osisID="Gen.1.1">Verse one.</verse>
          </div>
        </div>
    """)
    chapter = doc.divisions[0].chapters[0]
    body_text = " ".join(_text_of([item]) for item in chapter.body)
    assert "Summary text" not in body_text


def test_parse_chapter_summary_chapter_element_style():
    """<div type="summary"> inside a <chapter osisID=...> element is extracted into summary."""
    doc = _parse("""
        <div type="book" osisID="1Ne">
          <chapter osisID="1Ne.1">
            <div type="summary">
              <p>Nephi begins the record.</p>
            </div>
            <verse osisID="1Ne.1.1">I, Nephi.</verse>
          </chapter>
        </div>
    """)
    chapter = doc.divisions[0].chapters[0]
    assert chapter.summary
    assert any("Nephi begins the record" in _text_of([item]) for item in chapter.summary)


def test_parse_chapter_summary_milestone_style():
    """<div type="summary"> in milestone chapters is extracted into ChapterData.summary."""
    doc = _parse("""
        <div type="book" osisID="Gen">
          <chapter sID="Gen.1"/>
          <div type="summary">
            <p>The first chapter summary.</p>
          </div>
          <verse sID="Gen.1.1" osisID="Gen.1.1"/>In the beginning.<verse eID="Gen.1.1"/>
          <chapter eID="Gen.1"/>
        </div>
    """)
    chapter = doc.divisions[0].chapters[0]
    assert chapter.summary
    assert any("The first chapter summary" in _text_of([item]) for item in chapter.summary)


def test_parse_chapter_without_summary_has_empty_summary():
    """Chapters without a summary div have an empty summary list."""
    doc = _parse("""
        <div type="book" osisID="Gen">
          <div type="chapter" osisID="Gen.1">
            <verse osisID="Gen.1.1">In the beginning.</verse>
          </div>
        </div>
    """)
    chapter = doc.divisions[0].chapters[0]
    assert chapter.summary == []


def test_parse_chapter_title_excludes_embedded_note():
    """A <note> inside a chapter title element must not appear in the chapter title string."""
    doc = _parse("""
        <div type="book" osisID="Song">
          <div type="chapter" osisID="Song.1">
            <title type="chapter"><note canonical="false">Note: not inspired.</note>Song of Solomon</title>
            <verse osisID="Song.1.1">Text.</verse>
          </div>
        </div>
    """)
    assert doc.divisions[0].chapters[0].title == "Song of Solomon"
