"""Unit tests for ``open_canon_site.scrapers.sacred_texts.lost_books_of_the_bible`` (offline).

Pages are minimal inline HTML mimicking the archive.sacred-texts.com ``lbob`` pages: one page
per work, ``<h4>`` chapter headings, numbered verse paragraphs, a navigation block at the
foot and a ``Footnotes`` section after the text. ``process_all`` and ``run`` are exercised
with a fake fetcher or a pre-populated cache directory.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pyosis
import pytest
from open_canon_site.scrapers.sacred_texts import lost_books_of_the_bible as lbob
from open_canon_site.scrapers.sacred_texts.lost_books_of_the_bible import (
    BookDef,
    LBOBParser,
    WorkDef,
)

NAV = (
    '<p><div class="filenav"><hr><center><a href="lbob11.htm">Next: The Creed</a></center></div>'
    '<hr><nav role="navigation"><center><p><a href="../../index.htm">Sacred Texts</a> | '
    '<a href="../index.htm">Bible</a></p><table><tr><td><a href="lbob09.htm">&laquo; Previous: '
    "X</a></td><td><a>Index</a></td><td><a>Next: Y &raquo;</a></td></tr></table></center></nav>"
)
"""Footer markup of an old-layout page: ``filenav`` block, then the page navigation."""

PAGE_MARKER = '<p><a name="page_91"><font size="1" color="green">p. 91</font></A></p>'
"""A standalone printed-page marker paragraph."""


@pytest.fixture
def parser() -> LBOBParser:
    """Return a parser with caching disabled and no politeness delay."""
    p = LBOBParser(delay=0)
    yield p
    p.close()


def _work(**options: object) -> WorkDef:
    """Build a work definition for the tests."""
    return WorkDef(10, "Test", "The Test Work", "Test", **options)  # type: ignore[arg-type]


def _page(body: str, footnotes: str = "") -> str:
    """Wrap ``body`` (and optional footnote paragraphs) in an old-layout page skeleton."""
    notes = f'<HR><H3 ALIGN="CENTER">Footnotes</H3>{footnotes}' if footnotes else ""
    return f"<HTML><HEAD><title>T</title></HEAD><BODY>{body}{notes}{NAV}</BODY></HTML>"


def _ref(n: int, shown: int = 1) -> str:
    """Build a footnote reference as the site writes it."""
    return f'&nbsp;<A NAME="fr_{n}"></A><A HREF="#fn_{n}"><FONT SIZE="1">{shown}</FONT></A>'


def _note(n: int, label: str, text: str) -> str:
    """Build a footnote paragraph as the site writes it."""
    return f'<P><A NAME="fn_{n}"></A><A HREF="x.htm#fr_{n}">{label}</A> {text}</P>'


def _chapters(div: pyosis.DivCt) -> list[pyosis.DivCt]:
    """Return the chapter divs of a book div."""
    return [
        c
        for c in div.content
        if isinstance(c, pyosis.DivCt) and c.type_value == pyosis.OsisDivs.CHAPTER
    ]


def _verses(div: pyosis.DivCt) -> list[pyosis.VerseCt]:
    """Return the verse children of a chapter div."""
    return [c for c in div.content if isinstance(c, pyosis.VerseCt)]


def _ids(div: pyosis.DivCt) -> list[str]:
    """Return the verse ids of a chapter div."""
    return [v.osis_id[0] for v in _verses(div)]


def _intro(div: pyosis.DivCt) -> pyosis.DivCt | None:
    """Return the introduction div of a book div, if any."""
    for child in div.content:
        if isinstance(child, pyosis.DivCt) and child.type_value == pyosis.OsisDivs.INTRODUCTION:
            return child
    return None


NICODEMUS = _page(
    "<h3 align=center>The GOSPEL of NICODEMUS, formerly called the Acts of Pilate.</h3>"
    "<h3 align=center>The Gospel of NICODEMUS the disciple.</h3>"
    "<p>[A note on the origin of the book.]</p>"
    "<h4 align=center>CHAP. I.</h4>"
    "<p><small>2<i> Is compassionated by Pilate's wife. </i>7<i> Charged</i>.</small></p>"
    f"<p>NOW when Pilate saw this, he was afraid.{_ref(36)}</p>"
    "<p>2 But while he thought to rise, his own wife sent to him, saying</p>"
    f"{PAGE_MARKER}"
    '<p><span class="contnote"><FONT SIZE=-2 COLOR=GREEN>[paragraph continues]</FONT></span> '
    "Have thou nothing to do with that <i>just</i> man.</p>"
    "<p>3 Then said the Jews, He is a conjuror.</p>"
    "<h4 align=center>CHAP. II.</h4>"
    "<p>1 Jesus stood before the governor.</p>"
    "<p>2 He said nothing.</p>",
    _note(36, "64:1", "Matt. xxvii. 19, and <i>John</i> xix.") + _note(37, "64:2", "Unused."),
)
"""A Gospel of Nicodemus style page: two headings, intro, summary, footnote and page break."""


# --- definitions -----------------------------------------------------------------------


def test_books_cover_every_work_page_once() -> None:
    """Each page from 5 to 30 belongs to exactly one document."""
    pages = [p for book in lbob.BOOKS for p in book.pages]
    assert sorted(pages) == list(range(lbob.FILE_RANGE[0], lbob.FILE_RANGE[1] + 1))
    assert len(lbob.OUTPUT_FILENAMES) == len(lbob.BOOKS) == len(set(lbob.OUTPUT_FILENAMES))


def test_grouped_documents() -> None:
    """Ignatius has seven sub-books, Hermas three, and the rest hold one work."""
    groups = {b.osis_id: [w.osis_id for w in b.works] for b in lbob.BOOKS if len(b.works) > 1}
    assert groups == {
        "Ign": [
            "Ign.Eph",
            "Ign.Magn",
            "Ign.Trall",
            "Ign.Rom",
            "Ign.Phld",
            "Ign.Smyrn",
            "Ign.Pol",
        ],
        "Herm": ["Herm.Vis", "Herm.Mand", "Herm.Sim"],
    }


def test_nicodemus_is_page_ten() -> None:
    """Issue #54: the Gospel of Nicodemus is ``lbob10.htm`` and is written to its own file."""
    book = next(b for b in lbob.BOOKS if b.osis_id == "gospel-of-nicodemus")
    assert book.pages == [10]
    assert "gospel-of-nicodemus.xml" in lbob.OUTPUT_FILENAMES


# --- fetching --------------------------------------------------------------------------


def test_fetch_page_builds_two_digit_url(parser, monkeypatch) -> None:
    """``fetch_page`` requests ``lbob07.htm`` on the archive host and forwards retries."""
    calls = []
    monkeypatch.setattr(parser.http, "fetch_text", lambda **kw: calls.append(kw) or "<html/>")
    assert parser.fetch_page(7, retry_count=5) == "<html/>"
    parser.fetch_page(23)
    assert calls == [
        {"url": "https://archive.sacred-texts.com/bib/lbob/lbob07.htm", "retry_count": 5},
        {"url": "https://archive.sacred-texts.com/bib/lbob/lbob23.htm", "retry_count": 3},
    ]


# --- page structure --------------------------------------------------------------------


def test_split_page_drops_title_and_navigation(parser) -> None:
    """The first heading is the title; subtitle goes to the intro; footer text is gone."""
    parts = parser.split_page(NICODEMUS, _work())
    assert parts.intro[0] == "The Gospel of NICODEMUS the disciple."
    assert [c.heading for c in parts.chapters] == ["CHAP. I.", "CHAP. II."]
    everything = [p.get_text() for c in parts.chapters for p in c.paragraphs]
    assert not any("Sacred Texts" in t or "Next:" in t or "Unused" in t for t in everything)


def test_chapters_are_numbered_by_position(parser) -> None:
    """A repeated numeral (``COMMAND IV.`` twice in Hermas) still gives distinct chapters."""
    body = "<h3>T</h3>" + "".join(
        f"<h4>COMMAND {n}.</h4><p>1 text {n}</p>" for n in ("III", "IV", "IV", "VII")
    )
    div = parser.build_work_div(_work(), _page(body))
    assert [c.osis_id[0] for c in _chapters(div)] == ["Test.1", "Test.2", "Test.3", "Test.4"]


def test_introduction_heading_stays_in_the_introduction(parser) -> None:
    """An ``Introduction.`` heading and its numbered paragraphs are not chapter 1."""
    body = "<h3>T</h3><h4>Introduction.</h4><p>1 First.</p><h4>COMMAND I.</h4><p>1 Believe.</p>"
    div = parser.build_work_div(_work(), _page(body))
    assert [c.osis_id[0] for c in _chapters(div)] == ["Test.1"]
    assert _intro(div) is not None


# --- verses ----------------------------------------------------------------------------


def test_nicodemus_chapter_one(parser) -> None:
    """Summary, unnumbered verse 1, numbered verses, page break and continuation."""
    div = parser.build_work_div(_work(), NICODEMUS)
    chapter = _chapters(div)[0]
    summary = chapter.content[0]
    assert summary.type_value == pyosis.OsisDivs.SUMMARY and summary.canonical is False
    assert _ids(chapter) == ["Test.1.1", "Test.1.2", "Test.1.3"]
    verses = {v.osis_id[0]: parser._extract_text(list(v.content)) for v in _verses(chapter)}
    assert verses["Test.1.1"] == "NOW when Pilate saw this, he was afraid. "
    assert verses["Test.1.2"] == (
        "But while he thought to rise, his own wife sent to him, saying"
        " Have thou nothing to do with that just man."
    )
    assert "[paragraph" not in verses["Test.1.2"]
    assert _ids(_chapters(div)[1]) == ["Test.2.1", "Test.2.2"]


def test_footnote_becomes_note_with_label(parser) -> None:
    """A footnote reference becomes a note labelled with its printed number."""
    chapter = _chapters(parser.build_work_div(_work(), NICODEMUS))[0]
    notes = [p for p in _verses(chapter)[0].content if isinstance(p, pyosis.NoteCt)]
    assert [n.n for n in notes] == ["64:1"]
    assert parser._extract_text(list(notes[0].content)) == "Matt. xxvii. 19, and John xix."
    assert any(isinstance(p, pyosis.HiCt) for p in notes[0].content)
    text = parser._extract_text(list(_verses(chapter)[0].content))
    assert "Matt." not in text
    xml = parser.build_osis_for_book(
        BookDef("t", "T", "T", "t", [_work()]), {10: NICODEMUS}
    ).to_xml()
    assert 'n="64:1"' in xml and "Unused" not in xml


def test_footnote_without_text_is_dropped(parser, caplog) -> None:
    """A reference whose note is missing leaves no note and a warning."""
    page = _page(f"<h3>T</h3><h4>CHAP. I.</h4><p>1 Word{_ref(5)} more.</p>")
    with caplog.at_level(logging.WARNING, logger=lbob.LOGGER.name):
        verse = _verses(_chapters(parser.build_work_div(_work(), page))[0])[0]
    assert not any(isinstance(p, pyosis.NoteCt) for p in verse.content)
    assert "fn_5" in caplog.text


def test_page_marker_inside_a_verse_becomes_a_milestone(parser) -> None:
    """A green ``p. N`` inside a verse paragraph is kept as a page milestone."""
    page = _page(
        '<h3>T</h3><h4>CHAP. I.</h4><p>1 Before <font color="green" size="1">p. 12</font> after</p>'
    )
    verse = _verses(_chapters(parser.build_work_div(_work(), page))[0])[0]
    marks = [p for p in verse.content if isinstance(p, pyosis.MilestoneCt)]
    assert [m.n for m in marks] == ["12"]


def test_stray_number_is_text_not_a_verse(parser) -> None:
    """A paragraph starting ``161`` after verse 2 continues verse 2."""
    page = _page(
        "<h3>T</h3><h4>CHAP. I.</h4><p>1 One.</p><p>2 Two.</p><p>161 martyrs were there.</p>"
        "<p>3 Three.</p>"
    )
    chapter = _chapters(parser.build_work_div(_work(), page))[0]
    assert _ids(chapter) == ["Test.1.1", "Test.1.2", "Test.1.3"]
    assert "161 martyrs" in parser._extract_text(list(_verses(chapter)[1].content))


@pytest.mark.parametrize("prefix", ["2 ", "2. ", "2 ¶ "])
def test_verse_number_and_pilcrow_are_stripped(parser, prefix: str) -> None:
    """``2 ``, ``2. `` and ``2 ¶ `` all leave just the verse text."""
    page = _page(f"<h3>T</h3><h4>CHAP. I.</h4><p>1 One.</p><p>{prefix}When the child.</p>")
    verse = _verses(_chapters(parser.build_work_div(_work(), page))[0])[1]
    assert parser._extract_text(list(verse.content)) == "When the child."


def test_paragraph_per_verse_without_numbers(parser) -> None:
    """A work with no verse numbers makes each paragraph a verse, joining continuations."""
    page = _page(
        "<h3>T</h3><h4>LETTER ONE.</h4><p>Alpha.</p><p>Beta.</p>"
        f"{PAGE_MARKER}"
        '<p><span class="contnote">[paragraph continues]</span> gamma.</p>'
    )
    work = _work(verse_per_paragraph=True, chapter_re=lbob.HERODIAN_HEADING_RE)
    chapter = _chapters(parser.build_work_div(work, page))[0]
    texts = [parser._extract_text(list(v.content)) for v in _verses(chapter)]
    assert texts == ["Alpha.", "Beta. gamma."]


def test_poetry_lines_are_kept(parser) -> None:
    """``<br>`` lines in a verse become a line group."""
    page = _page("<h3>T</h3><h4>CHAP. I.</h4><p>1 Line one<br>Line two<br>Line three</p>")
    verse = _verses(_chapters(parser.build_work_div(_work(), page))[0])[0]
    assert isinstance(verse.content[0], pyosis.LgCt)
    assert len(verse.content[0].l) == 3


def test_footnote_on_a_chapter_heading_moves_to_verse_one(parser) -> None:
    """A note referenced from a heading is kept at the start of the chapter's first verse."""
    page = _page(
        f"<h3>T</h3><h4>THE TRIAL.{_ref(9)}</h4><p>First words.</p><p>2 Second.</p>",
        _note(9, "5:1", "About the trial."),
    )
    work = _work(chapter_re=lbob.HERODIAN_HEADING_RE)
    verse = _verses(_chapters(parser.build_work_div(work, page))[0])[0]
    assert isinstance(verse.content[0], pyosis.NoteCt) and verse.content[0].n == "5:1"


def test_unaccepted_leading_number_is_kept_as_text(parser) -> None:
    """A first paragraph ``161 martyrs ...`` is verse 1 and keeps its number as text."""
    page = _page("<h3>T</h3><h4>CHAP. I.</h4><p>161 martyrs were there.</p><p>2 Two.</p>")
    chapter = _chapters(parser.build_work_div(_work(), page))[0]
    assert _ids(chapter) == ["Test.1.1", "Test.1.2"]
    assert parser._extract_text(list(_verses(chapter)[0].content)) == "161 martyrs were there."


def test_leading_numbers_are_kept_in_paragraph_per_verse_works(parser) -> None:
    """A paragraph-per-verse work never strips digits, but still drops a pilcrow."""
    page = _page("<h3>T</h3><h4>LETTER ONE.</h4><p>12 men came.</p><p>\u00b6 Then they went.</p>")
    work = _work(verse_per_paragraph=True, chapter_re=lbob.HERODIAN_HEADING_RE)
    chapter = _chapters(parser.build_work_div(work, page))[0]
    texts = [parser._extract_text(list(v.content)) for v in _verses(chapter)]
    assert texts == ["12 men came.", "Then they went."]


def test_continuation_marker_survives_the_reader_layout(parser) -> None:
    """The reader layout drops the ``contnote`` class; the marker is still recognised by text."""
    page = _page(
        "<h3>T</h3><h4>LETTER ONE.</h4><p>Alpha.</p><p><span>[paragraph continues]</span> beta.</p>"
    )
    work = _work(verse_per_paragraph=True, chapter_re=lbob.HERODIAN_HEADING_RE)
    chapter = _chapters(parser.build_work_div(work, page))[0]
    texts = [parser._extract_text(list(v.content)) for v in _verses(chapter)]
    assert texts == ["Alpha. beta."]


def test_plain_paragraph_before_poetry_is_kept(parser) -> None:
    """A verse that opens with prose and continues in ``<br>`` lines keeps the prose line."""
    page = _page(
        "<h3>T</h3><h4>CHAP. I.</h4><p>1 A prose opening.</p>"
        '<p><span class="contnote">[paragraph continues]</span> Line one<br>Line two</p>'
    )
    verse = _verses(_chapters(parser.build_work_div(_work(), page))[0])[0]
    lines = verse.content[0].l
    assert [parser._extract_text(list(line.content)).strip() for line in lines] == [
        "A prose opening.",
        "Line one",
        "Line two",
    ]


def test_illustration_paragraph_is_dropped(parser) -> None:
    """A plate (``<img>`` and caption) between a verse and its continuation is not text."""
    plate = (
        '<p align="center"><A NAME="img_1"></A><span><A HREF="i.jpg"><IMG SRC="t.jpg">'
        "<BR><FONT SIZE=-3>Click to enlarge</A><BR>A CAPTION.</FONT><BR></span></p>"
    )
    page = _page(
        "<h3>T</h3><h4>CHAP. I.</h4><p>1 Before the plate</p>"
        f'{plate}<p><span class="contnote">[paragraph continues]</span> after it.</p>'
        "<p>2 Next.</p>"
    )
    chapter = _chapters(parser.build_work_div(_work(), page))[0]
    assert _ids(chapter) == ["Test.1.1", "Test.1.2"]
    assert parser._extract_text(list(_verses(chapter)[0].content)) == "Before the plate after it."


def test_prose_continuation_after_poetry_is_kept(parser) -> None:
    """A verse mixing ``<br>`` lines and a plain continuation keeps both as lines."""
    page = _page(
        "<h3>T</h3><h4>CHAP. I.</h4><p>1 Line one<br>Line two</p>"
        '<p><span class="contnote">[paragraph continues]</span> and a prose tail.</p>'
    )
    verse = _verses(_chapters(parser.build_work_div(_work(), page))[0])[0]
    lines = verse.content[0].l
    assert len(lines) == 3
    assert "prose tail" in parser._extract_text(list(lines[2].content))


def test_empty_trailing_chapter_is_skipped_with_warning(parser, caplog) -> None:
    """A last heading with no text under it gives no chapter."""
    page = _page("<h3>T</h3><h4>CHAP. IV.</h4><p>1 Four.</p><h4>CHAP. V.</h4>")
    with caplog.at_level(logging.WARNING, logger=lbob.LOGGER.name):
        div = parser.build_work_div(_work(), page)
    assert [c.osis_id[0] for c in _chapters(div)] == ["Test.1"]
    assert "no text" in caplog.text


def test_consecutive_chapter_headings_make_one_chapter(parser) -> None:
    """2 Clement: ``CHAP. V.`` directly followed by ``A Fragment.`` is one chapter."""
    page = _page(
        "<h3>T</h3><h4>CHAP. IV.</h4><p>1 Four.</p><h4>CHAP. V.</h4>"
        "<h4>A Fragment.</h4><p>1 Rest.</p><p>2 More.</p>"
    )
    chapters = _chapters(parser.build_work_div(_work(), page))
    assert [c.osis_id[0] for c in chapters] == ["Test.1", "Test.2"]
    assert _ids(chapters[1]) == ["Test.2.1", "Test.2.2"]


def test_credit_line_paragraph_is_ignored(parser) -> None:
    """The site's ``The Lost Books of the Bible, [1926], at sacred-texts.com`` line is dropped."""
    page = _page(
        "<h3>T</h3><p><i>The Lost Books of the Bible</i>, [1926], at sacred-texts.com</p>"
        "<h4>CHAP. I.</h4><p>1 Text.</p>"
    )
    parts = parser.split_page(page, _work())
    assert parts.intro == []


def test_footnote_printed_on_the_next_page(parser, monkeypatch) -> None:
    """A reference to ``lbobNN.htm#fn_N`` takes its text from that page's footnotes."""
    ref = '<A NAME="fr_7"></A><A HREF="lbob11.htm#fn_7"><FONT SIZE="1">1</FONT></A>'
    page = _page(f"<h3>T</h3><h4>CHAP. I.</h4><p>1 Word {ref} more.</p>")
    other = _page("<h3>U</h3><p>1 x</p>", _note(7, "182:1", "Printed on the next page."))
    monkeypatch.setattr(parser, "fetch_page", lambda n, retry_count=3: other)
    verse = _verses(_chapters(parser.build_work_div(_work(), page))[0])[0]
    notes = [p for p in verse.content if isinstance(p, pyosis.NoteCt)]
    assert [n.n for n in notes] == ["182:1"]
    assert parser._extract_text(list(notes[0].content)) == "Printed on the next page."


# --- works without chapter headings ------------------------------------------------------


def test_chapterless_work_is_one_chapter_after_its_note(parser) -> None:
    """The Laodiceans: a bracketed note is the introduction and the verses are chapter 1."""
    page = _page(
        "<h3>The EPISTLE to the LAODICEANS.</h3>"
        "<p>[This Epistle has been esteemed by several learned men.]</p>"
        "<p>1 Paul, an apostle.</p><p>2 I thank Christ.</p><p>3. Wherefore.</p>"
    )
    div = parser.build_work_div(_work(), page)
    assert _intro(div) is not None
    assert [c.osis_id[0] for c in _chapters(div)] == ["Test.1"]
    assert _ids(_chapters(div)[0]) == ["Test.1.1", "Test.1.2", "Test.1.3"]


def test_chapterless_work_with_unclosed_note_uses_intro_paragraphs(parser) -> None:
    """The Creed: ``intro_paragraphs=1`` keeps one paragraph as intro, the rest are verses."""
    page = _page(
        "<h3>The APOSTLES' CREED.</h3><p>[It is affirmed that the Apostles</p>"
        "<p>Peter. 1. I believe in God;</p><p>John. 2. Maker of heaven;</p>"
    )
    div = parser.build_work_div(_work(verse_per_paragraph=True, intro_paragraphs=1), page)
    assert _ids(_chapters(div)[0]) == ["Test.1.1", "Test.1.2"]


def test_chapterless_work_without_note_has_no_intro(parser) -> None:
    """Without a bracketed note nothing is held back as introduction."""
    div = parser.build_work_div(_work(), _page("<h3>T</h3><p>1 One.</p><p>2 Two.</p>"))
    assert _intro(div) is None
    assert _ids(_chapters(div)[0]) == ["Test.1.1", "Test.1.2"]


# --- documents -------------------------------------------------------------------------


def test_single_work_document(parser) -> None:
    """A one-work document is a single book div with that work's id and title."""
    book = BookDef("Test", "The Test Work", "Test", "test", [_work()])
    osis = parser.build_osis_for_book(book, {10: NICODEMUS})
    xml = osis.to_xml()
    assert 'osisIDWork="Test"' in xml and 'osisID="Test.1.1"' in xml
    assert xml.count('type="book"') == 1
    assert "Alpha House" in xml


def test_grouped_document_nests_sub_books(parser) -> None:
    """A multi-work document wraps its works as sub-books of the parent id."""
    works = [
        WorkDef(1, "Ign.Eph", "To the Ephesians", "Ephesians"),
        WorkDef(2, "Ign.Rom", "To the Romans", "Romans"),
    ]
    book = BookDef("Ign", "The Epistles of Ignatius", "Ignatius", "ignatius", works)
    page = _page("<h3>T</h3><h4>CHAP. I.</h4><p>1 Text.</p>")
    xml = parser.build_osis_for_book(book, {1: page, 2: page}).to_xml()
    assert xml.count('type="book"') == 3
    assert 'osisID="Ign.Eph.1.1"' in xml and 'osisID="Ign.Rom.1.1"' in xml


# --- process_all / run -----------------------------------------------------------------


def _fake_pages(parser: LBOBParser, missing: tuple[int, ...] = ()) -> list[int]:
    """Make ``fetch_page`` return a tiny chapter page, failing for ``missing``; log requests."""
    requested: list[int] = []

    def fetch(page: int, retry_count: int = 3) -> str:
        requested.append(page)
        if page in missing:
            raise RuntimeError("boom")
        return _page("<h3>T</h3><h4>CHAP. I.</h4><p>1 Text.</p>")

    parser.fetch_page = fetch  # type: ignore[method-assign]
    return requested


def test_process_all_writes_every_document(parser, tmp_path: Path) -> None:
    """Every document is written to the output directory."""
    _fake_pages(parser)
    parser.process_all(output_dir=str(tmp_path))
    assert sorted(p.name for p in tmp_path.glob("*.xml")) == sorted(lbob.OUTPUT_FILENAMES)


def test_process_all_skips_documents_with_a_missing_page(parser, tmp_path: Path, caplog) -> None:
    """A failed fetch skips only the documents that need that page."""
    _fake_pages(parser, missing=(19,))
    with caplog.at_level(logging.WARNING, logger=lbob.LOGGER.name):
        parser.process_all(output_dir=str(tmp_path))
    names = {p.name for p in tmp_path.glob("*.xml")}
    assert "ignatius-epistles.xml" not in names
    assert "polycarp.xml" in names
    assert "Skipping ignatius-epistles" in caplog.text


def test_process_all_respects_page_range(parser, tmp_path: Path) -> None:
    """Only pages inside the range are fetched and only their documents written."""
    requested = _fake_pages(parser)
    parser.process_all(output_dir=str(tmp_path), start_page=10, end_page=10)
    assert requested == [10]
    assert [p.name for p in tmp_path.glob("*.xml")] == ["gospel-of-nicodemus.xml"]


def test_process_all_logs_a_build_failure(parser, tmp_path: Path, monkeypatch, caplog) -> None:
    """An exception building one document is logged and the others still get written."""
    _fake_pages(parser)
    original = parser.build_osis_for_book

    def build(book: BookDef, page_html: dict[int, str]) -> pyosis.OsisXML:
        if book.output_stem == "barnabas":
            raise ValueError("bad")
        return original(book, page_html)

    monkeypatch.setattr(parser, "build_osis_for_book", build)
    with caplog.at_level(logging.ERROR, logger=lbob.LOGGER.name):
        parser.process_all(output_dir=str(tmp_path))
    assert not (tmp_path / "barnabas.xml").exists()
    assert (tmp_path / "polycarp.xml").exists()
    assert "Error generating barnabas" in caplog.text


def test_run_reads_the_cache_and_reports_outputs(tmp_path: Path) -> None:
    """``run`` builds from cached pages and returns the files it wrote."""
    cache = tmp_path / "cache"
    page_dir = cache / "archive.sacred-texts.com" / "bib" / "lbob"
    page_dir.mkdir(parents=True)
    (page_dir / "lbob10.htm").write_text(NICODEMUS, encoding="utf-8")
    out = tmp_path / "out"
    args = argparse.Namespace(
        output_dir=out, cache_dir=str(cache), delay=0, start_page=10, end_page=10
    )
    assert lbob.run(args) == [out / "gospel-of-nicodemus.xml"]
    assert 'osisID="gospel-of-nicodemus.1.1"' in (out / "gospel-of-nicodemus.xml").read_text(
        encoding="utf-8"
    )


def test_spec_is_registered() -> None:
    """The scraper is registered under ``lost-books-of-the-bible`` with its outputs."""
    from open_canon_site.scrapers import cli, registry

    spec = registry.get_scraper("lost-books-of-the-bible")
    assert spec.outputs == lbob.OUTPUT_FILENAMES
    args = cli.build_parser().parse_args(["lost-books-of-the-bible"])
    assert (args.start_page, args.end_page) == lbob.FILE_RANGE
