"""Download and parse The Lost Books of the Bible from sacred-texts.com to OSIS XML.

Scrapes https://archive.sacred-texts.com/bib/lbob/ (pages ``lbob05.htm`` to ``lbob30.htm``;
the volume is also read at https://sacred-texts.com/book/the-lost-books-of-the-bible) and
produces one OSIS XML file per work, grouped as the volume groups them:

- The Gospel of the Birth of Mary, the Protevangelion, the First and Thomas's Gospels of the
  Infancy, the Epistles of Jesus Christ and Abgarus, the Gospel of Nicodemus (Acts of
  Pontius Pilate), the Apostles' Creed, the Epistle to the Laodiceans, the Epistles of Paul
  and Seneca and the Acts of Paul and Thecla
- 1 Clement, 2 Clement and the Epistle of Barnabas
- The seven Epistles of Ignatius (one book with seven sub-books) and the Epistle of Polycarp
- The Shepherd of Hermas (one book with three sub-books: Visions, Commands, Similitudes)
- The Letters of Herod and Pilate and the Lost Gospel According to Peter

The front matter (title page, introduction, order of the books, preface) and the two
comparison tables at the end of the volume are not converted.

It is the companion volume to *The Forgotten Books of Eden*, so the verse and inline
handling is inherited from :class:`FBEParser`. The layout differs in two ways: every work
is a single page with its chapters marked by ``<h4>`` headings, and the footnotes sit in one
``Footnotes`` section at the foot of the page.

HTML shapes handled (the page title is the first heading on the page):

- A chapter heading is ``CHAP. IV.``, ``VISION I.``, ``COMMAND II.``, ``SIMILITUDE III.`` or
  ``A Fragment.``. Chapters are numbered by position, not by their numeral, because the
  source repeats one (``COMMAND IV.`` appears twice in the Commands of Hermas). Text before
  the first chapter heading is an introduction, as is the ``Introduction.`` of the Commands.
- A work with no chapter headings (the Creed, Laodiceans, the Gospel of Peter) is a single
  chapter after its bracketed introductory note.
- A chapter summary is a ``<p>`` holding only ``<small>`` text right after the heading.
- A verse is a ``<p>`` starting with its number (``"2 text"``, ``"2. text"`` or
  ``"2 ¶ text"``); the first un-numbered paragraph is verse 1 and later un-numbered
  paragraphs continue the current verse. A number is only accepted when it follows on from
  the last one (a stray ``161`` at the start of a paragraph is text). A work with no verse
  numbers makes each paragraph a verse.
- A footnote reference is ``<a name="fr_N"></a><a href="#fn_N">`` and becomes an OSIS note
  labelled with the printed footnote number; ``[paragraph continues]`` markers are dropped.
"""

from __future__ import annotations

import argparse
import copy
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Final

import pyosis
from bs4 import BeautifulSoup, NavigableString, Tag
from tqdm import tqdm

from open_canon_site.scrapers._osis import InlinePart, normalize_whitespace
from open_canon_site.scrapers.base import ScraperSpec
from open_canon_site.scrapers.sacred_texts._layout import legacy_html
from open_canon_site.scrapers.sacred_texts.forgotten_books_of_eden import FBEParser, VerseContent

LOGGER = logging.getLogger(__name__)
"""Module logger; progress, warnings for missing pages and per-work errors go here."""

BASE_URL: Final[str] = "https://archive.sacred-texts.com/bib/lbob/"
"""Base URL of the volume on the archive host, which serves the original page layout."""
FILE_PREFIX: Final[str] = "lbob"
"""Filename prefix of every page; page ``n`` is ``lbob{n:02d}.htm``."""
FILE_RANGE: Final[tuple[int, int]] = (5, 30)
"""Inclusive range of page numbers that hold converted works (default for ``--start/--end-page``)."""

CHAPTER_HEADING_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:CHAP\b|VISION\b|COMMAND\b|SIMILITUDE\b|A\s+FRAGMENT\b)", re.IGNORECASE
)
"""Matches the heading that opens a chapter in most works."""
INTRODUCTION_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^\s*INTRODUCTION\.?\s*$", re.I)
"""Matches an ``Introduction.`` heading, whose text stays part of the introduction."""
HERODIAN_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^\s*(?:LETTER|THE)\b", re.IGNORECASE)
"""Chapter heading of the Letters of Herod and Pilate, whose sections are titled by document."""
VERSE_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"^(\d+)\.?(?:\s|$)")
"""Matches the verse number at the start of a paragraph (``1 text``, ``1. text``)."""
VERSE_PREFIX_RE: Final[re.Pattern[str]] = re.compile(r"^\d+\.?\s*")
"""Matches the verse number stripped from the front of a verse that was numbered."""
PILCROW_RE: Final[re.Pattern[str]] = re.compile(r"^¶\s*")
"""Matches the pilcrow (paragraph sign) stripped from the front of a verse."""
MAX_VERSE_JUMP: Final[int] = 5
"""Largest forward gap between verse numbers still read as a verse number."""
FOOTNOTE_REF_RE: Final[re.Pattern[str]] = re.compile(r"^fr_")
"""Matches the ``name`` of the anchor marking a footnote reference in the text."""
FOOTNOTE_TARGET_RE: Final[re.Pattern[str]] = re.compile(r"^fn_")
"""Matches the ``name`` of the anchor that starts a footnote and the ``#fn_`` link target."""
FOOTNOTE_LINK_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:lbob(?P<page>\d+)\.htm)?#(?P<name>fn_\d+)$"
)
"""Matches a footnote reference link; ``page`` is set when the note is on another page."""
CONTINUATION_RE: Final[re.Pattern[str]] = re.compile(r"^\[paragraph continues\]$", re.IGNORECASE)
"""Matches the text of the ``[paragraph continues]`` marker the site puts after a page break."""
CREDIT_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^The Lost Books of the Bible,?\s*\[1926\],?\s*at sacred-texts\.com$", re.IGNORECASE
)
"""Matches the credit line the site prints as a paragraph, which is not part of any work."""
FOOTNOTE_MARKER: Final[str] = "data-fn"
"""Attribute of the placeholder ``<span>`` that stands in for a footnote reference."""
HEADING_TAGS: Final[tuple[str, ...]] = ("h1", "h2", "h3", "h4", "h5", "h6")
"""Tag names read as headings."""

EDITION_YEAR: Final[str] = "1926"
"""Year of the print edition the site transcribes."""
EDITION_NOTE: Final[str] = "The Lost Books of the Bible, Alpha House, Inc., 1926."
"""Provenance note for the print edition."""


# ---------------------------------------------------------------------------
# Work definitions
# ---------------------------------------------------------------------------


@dataclass
class WorkDef:
    """Definition of one work: a single page of the volume."""

    page: int
    """Page number; the URL is ``BASE_URL + "lbob{page:02d}.htm"``."""
    osis_id: str
    """OSIS book id (a dotted sub-book id such as ``"Ign.Eph"`` inside a grouped document)."""
    title: str
    """Full title of the work."""
    short: str
    """Short title for the ``short`` attribute."""
    chapter_re: re.Pattern[str] = CHAPTER_HEADING_RE
    """Pattern a heading must match to open a chapter."""
    verse_per_paragraph: bool = False
    """Whether the work has no verse numbers, so every paragraph is a verse."""
    intro_paragraphs: int | None = None
    """Leading paragraphs of a work without chapter headings that form its introduction;
    ``None`` reads a leading ``[bracketed note]``."""


@dataclass
class BookDef:
    """Definition of one output document: a work, or several works as sub-books."""

    osis_id: str
    """OSIS work id of the document, and the book id when it holds a single work."""
    title: str
    """Title of the document."""
    short: str
    """Short title, also the ``osisRefWork``."""
    output_stem: str
    """Output filename stem, without ``.xml``."""
    works: list[WorkDef] = field(default_factory=list)
    """The works in the document; more than one makes them sub-books of a parent book."""

    @property
    def pages(self) -> list[int]:
        """Page numbers the document needs, in order."""
        return [work.page for work in self.works]


def _single(
    page: int, osis_id: str, title: str, short: str, stem: str, **options: object
) -> BookDef:
    """Build a document holding one work.

    Args:
        page: Page number of the work.
        osis_id: OSIS id of both document and book.
        title: Full title.
        short: Short title.
        stem: Output filename stem.
        **options: Extra :class:`WorkDef` fields.

    Returns:
        The document definition.
    """
    work = WorkDef(page, osis_id, title, short, **options)  # type: ignore[arg-type]
    return BookDef(osis_id, title, short, stem, [work])


BOOKS: Final[list[BookDef]] = [
    _single(
        5,
        "birth-of-mary",
        "The Gospel of the Birth of Mary",
        "Birth of Mary",
        "birth-of-mary",
    ),
    _single(6, "protevangelion", "The Protevangelion", "Protevangelion", "protevangelion"),
    _single(
        7,
        "first-infancy-gospel",
        "The First Gospel of the Infancy of Jesus Christ",
        "First Infancy Gospel",
        "first-infancy-gospel",
    ),
    _single(
        8,
        "thomas-infancy-gospel",
        "Thomas's Gospel of the Infancy of Jesus Christ",
        "Thomas's Infancy Gospel",
        "thomas-infancy-gospel",
    ),
    _single(
        9,
        "abgarus-correspondence",
        "The Epistles of Jesus Christ and Abgarus King of Edessa",
        "Abgarus Correspondence",
        "abgarus-correspondence",
    ),
    _single(
        10,
        "gospel-of-nicodemus",
        "The Gospel of Nicodemus, Formerly Called the Acts of Pontius Pilate",
        "Gospel of Nicodemus",
        "gospel-of-nicodemus",
    ),
    _single(
        11,
        "apostles-creed",
        "The Apostles' Creed",
        "Apostles' Creed",
        "apostles-creed",
        verse_per_paragraph=True,
        intro_paragraphs=1,
    ),
    _single(
        12,
        "laodiceans",
        "The Epistle of Paul the Apostle to the Laodiceans",
        "Laodiceans",
        "laodiceans",
    ),
    _single(
        13,
        "paul-and-seneca",
        "The Epistles of Paul the Apostle to Seneca, with Seneca's to Paul",
        "Paul and Seneca",
        "paul-and-seneca",
    ),
    _single(
        14,
        "paul-and-thecla",
        "The Acts of Paul and Thecla",
        "Paul and Thecla",
        "acts-of-paul-and-thecla",
    ),
    _single(
        15,
        "1Clem",
        "The First Epistle of Clement to the Corinthians",
        "1 Clement",
        "1-clement",
    ),
    _single(
        16,
        "2Clem",
        "The Second Epistle of Clement to the Corinthians",
        "2 Clement",
        "2-clement",
    ),
    _single(17, "Barn", "The General Epistle of Barnabas", "Barnabas", "barnabas"),
    BookDef(
        "Ign",
        "The Epistles of Ignatius",
        "Ignatius",
        "ignatius-epistles",
        [
            WorkDef(18, "Ign.Eph", "The Epistle of Ignatius to the Ephesians", "Ephesians"),
            WorkDef(19, "Ign.Magn", "The Epistle of Ignatius to the Magnesians", "Magnesians"),
            WorkDef(20, "Ign.Trall", "The Epistle of Ignatius to the Trallians", "Trallians"),
            WorkDef(21, "Ign.Rom", "The Epistle of Ignatius to the Romans", "Romans"),
            WorkDef(
                22, "Ign.Phld", "The Epistle of Ignatius to the Philadelphians", "Philadelphians"
            ),
            WorkDef(23, "Ign.Smyrn", "The Epistle of Ignatius to the Smyrnæans", "Smyrnæans"),
            WorkDef(24, "Ign.Pol", "The Epistle of Ignatius to Polycarp", "Polycarp"),
        ],
    ),
    _single(
        25,
        "Pol",
        "The Epistle of Polycarp to the Philippians",
        "Polycarp",
        "polycarp",
    ),
    BookDef(
        "Herm",
        "The Shepherd of Hermas",
        "Shepherd of Hermas",
        "shepherd-of-hermas",
        [
            WorkDef(26, "Herm.Vis", "The First Book of Hermas, Called His Visions", "Visions"),
            WorkDef(27, "Herm.Mand", "The Second Book of Hermas, Called His Commands", "Commands"),
            WorkDef(
                28,
                "Herm.Sim",
                "The Third Book of Hermas, Which Is Called His Similitudes",
                "Similitudes",
            ),
        ],
    ),
    _single(
        29,
        "herod-and-pilate",
        "Letters of Herod and Pilate",
        "Herod and Pilate",
        "herod-and-pilate",
        chapter_re=HERODIAN_HEADING_RE,
        verse_per_paragraph=True,
    ),
    _single(
        30,
        "gospel-of-peter",
        "The Lost Gospel According to Peter",
        "Gospel of Peter",
        "gospel-of-peter",
    ),
]
"""The documents written, one XML file each, in page order."""


# ---------------------------------------------------------------------------
# Parsed data containers
# ---------------------------------------------------------------------------


@dataclass
class Footnote:
    """A footnote read from the page's ``Footnotes`` section."""

    label: str
    """Printed footnote number (``"64:1"``)."""
    parts: list[InlinePart]
    """Inline OSIS content of the note."""


@dataclass
class Chapter:
    """A chapter's heading and the paragraphs under it, before verse splitting."""

    heading: str
    """Heading text (``"CHAP. IV."``)."""
    paragraphs: list[Tag] = field(default_factory=list)
    """The ``<p>`` elements under the heading, in order."""
    notes: list[str] = field(default_factory=list)
    """Footnote names referenced from the heading itself (kept at the start of verse 1)."""


@dataclass
class PageParts:
    """A work page split into introduction and chapters."""

    intro: list[str | Tag] = field(default_factory=list)
    """Introduction blocks in order: heading text, or a ``<p>`` element."""
    chapters: list[Chapter] = field(default_factory=list)
    """The chapters in order."""


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class LBOBParser(FBEParser):
    """Parse The Lost Books of the Bible pages into OSIS documents.

    Inherits the inline, verse and poetry handling of :class:`FBEParser` and adds the
    one-page-per-work chapter split and the footnotes.
    """

    def __init__(self, cache_dir: str | None = None, delay: float = 1.5) -> None:
        """Create a parser backed by a caching HTTP fetcher.

        Args:
            cache_dir: Directory for the on-disk HTML cache; ``None`` disables caching.
            delay: Seconds to sleep between uncached requests (politeness delay).
        """
        super().__init__(cache_dir=cache_dir, delay=delay)
        self._footnotes: dict[str, Footnote] = {}
        """Footnotes of the page being parsed, keyed by ``fn_N`` anchor name."""
        self._foreign_pages: dict[str, int] = {}
        """Page number holding each footnote that is printed on another page, by ``fn_N`` name."""
        self._page_html: dict[int, str] = {}
        """Pages already fetched (set by ``process_all``), used to resolve other pages' notes."""
        self._page_notes: dict[int, dict[str, Footnote]] = {}
        """Footnotes of other pages that were looked up, keyed by page number."""

    def fetch_page(self, page_num: int, retry_count: int = 3) -> str:
        """Fetch one page of the volume.

        Args:
            page_num: Page number; the URL is ``BASE_URL + "lbob{page_num:02d}.htm"``.
            retry_count: Maximum fetch attempts, passed to the HTTP fetcher.

        Returns:
            The page HTML as text.
        """
        url = f"{BASE_URL}{FILE_PREFIX}{page_num:02d}.htm"
        return self.http.fetch_text(url=url, retry_count=retry_count)

    # ------------------------------------------------------------------
    # Inline content
    # ------------------------------------------------------------------

    def parse_inline_annotations(
        self,
        element: Tag | NavigableString,
        is_green_font: bool = False,
    ) -> list[InlinePart]:
        """Parse inline HTML like :class:`FBEParser`, adding footnote notes.

        A footnote placeholder becomes an OSIS note and a ``[paragraph continues]`` marker
        is dropped.

        Args:
            element: A tag whose children are parsed, or a bare text node.
            is_green_font: Whether ``element`` is inside a green ``<font>``.

        Returns:
            Inline parts with adjacent strings consolidated.
        """
        if isinstance(element, Tag):
            if element.get(FOOTNOTE_MARKER):
                return [self._note(str(element[FOOTNOTE_MARKER]))]
            if "contnote" in (element.get("class") or []):
                return []
        return super().parse_inline_annotations(element, is_green_font)

    def _extract_text(self, parts: list[InlinePart]) -> str:
        """Flatten inline parts to plain text, leaving footnote notes out at any depth.

        Args:
            parts: Inline parts in document order.

        Returns:
            The concatenated text.
        """
        text = ""
        for part in parts:
            if isinstance(part, str):
                text += part
            elif isinstance(part, pyosis.NoteCt):
                continue
            elif hasattr(part, "content"):
                text += self._extract_text(list(part.content))
        return text

    def _note(self, ref_id: str) -> pyosis.NoteCt | str:
        """Build the OSIS note for a footnote reference.

        Args:
            ref_id: Footnote anchor name (``fn_36``).

        Returns:
            The note, or an empty string when the page has no such footnote.
        """
        footnote = self._footnotes.get(ref_id)
        if footnote is None and ref_id in self._foreign_pages:
            footnote = self._foreign_footnotes(self._foreign_pages[ref_id]).get(ref_id)
        if footnote is None:
            LOGGER.warning("Footnote %s has no text", ref_id)
            return ""
        return pyosis.NoteCt(type_value="explanation", n=footnote.label, content=footnote.parts)

    def _foreign_footnotes(self, page: int) -> dict[str, Footnote]:
        """Return the footnotes of another page.

        The site prints the notes for the last verses of a page at the foot of the next one
        (the tail of Ignatius to the Trallians has its notes on the Romans page), so a
        reference can point at ``lbobNN.htm#fn_N``.

        Args:
            page: Page number holding the notes.

        Returns:
            That page's footnotes keyed by anchor name; empty if it cannot be read.
        """
        if page not in self._page_notes:
            try:
                html = self._page_html.get(page) or self.fetch_page(page)
                soup = BeautifulSoup(legacy_html(html), "html.parser")
                self._page_notes[page] = self._collect_footnotes(soup)
            except Exception as exc:
                LOGGER.error("Cannot read footnotes on page %d: %s", page, exc)
                self._page_notes[page] = {}
        return self._page_notes[page]

    def _collect_footnotes(self, soup: BeautifulSoup) -> dict[str, Footnote]:
        """Read the footnotes after the ``Footnotes`` heading.

        Each footnote is a ``<p>`` with an ``<a name="fn_N">``, an anchor whose text is the
        label, then the note body.

        Args:
            soup: The parsed page.

        Returns:
            Footnotes keyed by anchor name; empty if the page has none.
        """
        footnotes: dict[str, Footnote] = {}
        in_notes = False
        for element in soup.find_all([*HEADING_TAGS, "p"]):
            if element.name in HEADING_TAGS:
                in_notes = in_notes or normalize_whitespace(element.get_text()) == "Footnotes"
                continue
            if not in_notes:
                continue
            target = element.find("a", attrs={"name": FOOTNOTE_TARGET_RE})
            if target is None:
                continue
            label_anchor = target.find_next_sibling("a")
            label = normalize_whitespace(label_anchor.get_text()) if label_anchor else ""
            body = copy.copy(element)
            for anchor in body.find_all("a", limit=2):
                anchor.decompose()
            parts = self.parse_inline_annotations(body)
            if parts and isinstance(parts[0], str):
                parts[0] = parts[0].lstrip()
            footnotes[str(target["name"])] = Footnote(label=label, parts=parts)
        return footnotes

    @staticmethod
    def _mark_continuations(soup: BeautifulSoup) -> None:
        """Give every ``[paragraph continues]`` marker the ``contnote`` class.

        The reader layout drops the class, so the marker is recognised by its text.

        Args:
            soup: The parsed page, modified in place.
        """
        for span in soup.find_all("span"):
            if CONTINUATION_RE.match(normalize_whitespace(span.get_text())):
                span["class"] = ["contnote"]

    def _mark_footnote_references(self, soup: BeautifulSoup) -> None:
        """Replace each footnote reference with a placeholder ``<span data-fn=...>``.

        A reference is an ``<a name="fr_N">`` followed by an ``<a href="#fn_N">`` carrying
        the superscript number; the placeholder lets the inline parser build a note without
        the number leaking into the text.

        A link to another page's notes is remembered in ``self._foreign_pages``.

        Args:
            soup: The parsed page, modified in place.
        """
        self._foreign_pages = {}
        for anchor in soup.find_all("a", attrs={"name": FOOTNOTE_REF_RE}):
            link = anchor.find_next_sibling("a")
            match = FOOTNOTE_LINK_RE.match(str(link.get("href", ""))) if link is not None else None
            if match is None:
                continue
            name = match.group("name")
            if match.group("page") and name not in self._footnotes:
                self._foreign_pages[name] = int(match.group("page"))
            marker = soup.new_tag("span")
            marker[FOOTNOTE_MARKER] = name
            anchor.replace_with(marker)
            link.decompose()

    # ------------------------------------------------------------------
    # Page structure
    # ------------------------------------------------------------------

    def _prepare_page(self, html: str) -> BeautifulSoup:
        """Parse a page, drop its navigation and footnote chrome and load its footnotes.

        Args:
            html: Page HTML, old layout or reader layout.

        Returns:
            The parsed page with footnote references replaced by placeholders;
            ``self._footnotes`` holds its footnotes.
        """
        soup = BeautifulSoup(legacy_html(html), "html.parser")
        for chrome in soup.find_all(["nav", "script", "style"]):
            chrome.decompose()
        for chrome in soup.find_all("div", class_="filenav"):
            chrome.decompose()
        for plate in soup.find_all("img"):
            holder = plate.find_parent("p")
            if holder is not None:
                holder.decompose()
        self._mark_continuations(soup)
        self._footnotes = self._collect_footnotes(soup)
        self._mark_footnote_references(soup)
        return soup

    @staticmethod
    def _is_blank(p_tag: Tag) -> bool:
        """Report whether a paragraph has no text or only a page-marker anchor.

        Args:
            p_tag: The paragraph.

        Returns:
            True if it should be ignored.
        """
        text = normalize_whitespace(p_tag.get_text())
        return (
            not text
            or bool(CREDIT_LINE_RE.match(text))
            or FBEParser._is_standalone_page_marker(p_tag)
        )

    def split_page(self, html: str, work: WorkDef) -> PageParts:
        """Split a work page into its introduction and chapters.

        The first heading is the page title and is dropped. Reading stops at the
        ``Footnotes`` heading.

        Args:
            html: Page HTML.
            work: The work the page holds.

        Returns:
            The introduction and chapters, with paragraphs still unparsed.
        """
        soup = self._prepare_page(html)
        parts = PageParts()
        current: Chapter | None = None
        seen_title = False

        for element in soup.find_all([*HEADING_TAGS, "p"]):
            if element.name == "p" and element.find_parent("p") is not None:
                continue
            if element.name in HEADING_TAGS:
                text = normalize_whitespace(element.get_text())
                if not text:
                    continue
                if text == "Footnotes":
                    break
                heading_notes = [
                    str(m[FOOTNOTE_MARKER]) for m in element.find_all(attrs={FOOTNOTE_MARKER: True})
                ]
                if not seen_title:
                    seen_title = True
                elif INTRODUCTION_HEADING_RE.match(text) and current is None:
                    parts.intro.append(text)
                elif work.chapter_re.match(text):
                    if current is not None and not current.paragraphs:
                        current.heading = f"{current.heading} {text}"
                        current.notes += heading_notes
                        continue
                    current = Chapter(text, notes=heading_notes)
                    parts.chapters.append(current)
                elif current is None:
                    parts.intro.append(text)
                continue
            if self._is_blank(element):
                continue
            (parts.intro if current is None else current.paragraphs).append(element)

        if not parts.chapters:
            self._split_chapterless(parts, work)
        return parts

    @staticmethod
    def _split_chapterless(parts: PageParts, work: WorkDef) -> None:
        """Make the body of a work with no chapter headings a single chapter.

        The introduction keeps its headings and its leading ``intro_paragraphs`` paragraphs
        (by default a leading ``[bracketed note]``); the rest becomes chapter 1.

        Args:
            parts: Split page, modified in place.
            work: The work the page holds.
        """
        blocks = parts.intro
        keep = work.intro_paragraphs
        if keep is None:
            keep = 0
            first = next((b for b in blocks if isinstance(b, Tag)), None)
            if first is not None and first.get_text().strip().startswith("["):
                for block in blocks:
                    if isinstance(block, Tag):
                        keep += 1
                        if block.get_text().strip().endswith("]"):
                            break
                else:
                    keep = 0

        intro: list[str | Tag] = []
        chapter = Chapter("")
        for block in blocks:
            if isinstance(block, str) or keep > 0:
                intro.append(block)
                if isinstance(block, Tag):
                    keep -= 1
            else:
                chapter.paragraphs.append(block)
        parts.intro = intro
        if chapter.paragraphs:
            parts.chapters.append(chapter)

    # ------------------------------------------------------------------
    # Verses
    # ------------------------------------------------------------------

    def _strip_prefix(self, parts: list[InlinePart], numbered: bool) -> list[InlinePart]:
        """Remove a leading verse number (when it was read as one) and pilcrow from parts.

        Args:
            parts: Inline parts; not modified.
            numbered: Whether the paragraph's leading number was accepted as the verse number.

        Returns:
            A copy whose first string has the prefix removed.
        """
        result = list(parts)
        if result and isinstance(result[0], str):
            text = result[0].lstrip()
            if numbered:
                text = VERSE_PREFIX_RE.sub("", text, count=1)
            result[0] = PILCROW_RE.sub("", text, count=1)
        return result

    def _verse_groups(self, chapter: Chapter, work: WorkDef) -> list[tuple[int, list[Tag], bool]]:
        """Group a chapter's paragraphs into verses.

        A paragraph starting with the next verse number (or a number up to
        ``MAX_VERSE_JUMP`` ahead) starts that verse; the first paragraph is verse 1 when
        un-numbered. Other paragraphs continue the current verse, or start the next one in
        a work with no verse numbers (unless they open with ``[paragraph continues]``).

        Args:
            chapter: The chapter.
            work: The work the chapter belongs to.

        Returns:
            ``(verse number, paragraphs, numbered)`` triples in order; ``numbered`` says the first
            paragraph's leading number is the verse number.
        """
        groups: list[tuple[int, list[Tag], bool]] = []
        for p_tag in chapter.paragraphs:
            number: int | None = None
            numbered = False
            match = VERSE_NUMBER_RE.match(p_tag.get_text().strip())
            last = groups[-1][0] if groups else 0
            if match and not work.verse_per_paragraph:
                value = int(match.group(1))
                if last < value <= last + MAX_VERSE_JUMP:
                    number = value
                    numbered = True
            if number is None:
                continued = bool(p_tag.find(class_="contnote"))
                if not groups or (work.verse_per_paragraph and not continued):
                    number = last + 1
                else:
                    groups[-1][1].append(p_tag)
                    continue
            groups.append((number, [p_tag], numbered))
        return groups

    def _build_chapter_verse(
        self, osis_id: str, paragraphs: list[Tag], numbered: bool
    ) -> pyosis.VerseCt:
        """Build one verse from its paragraphs.

        Args:
            osis_id: Verse reference (``"Barn.2.3"``).
            paragraphs: The ``<p>`` elements of the verse.
            numbered: Whether the first paragraph starts with the verse's number.

        Returns:
            The verse, with page markers, highlights and footnotes kept inline.
        """
        parsed = [self._parse_verse_content(p_tag) for p_tag in paragraphs]
        any_poetry = any(content.poetry_lines for content in parsed)
        parts: list[InlinePart] = []
        poetry: list[list] = []
        for index, content in enumerate(parsed):
            content_parts = list(content.content_parts)
            if index == 0:
                content_parts = self._strip_prefix(content_parts, numbered)
            else:
                if content_parts and isinstance(content_parts[0], str):
                    content_parts[0] = content_parts[0].lstrip()
                content_parts = [" ", *content_parts]
            parts.extend(content_parts)
            if content.poetry_lines:
                lines = list(content.poetry_lines)
                if index == 0:
                    lines[0] = self._strip_prefix(lines[0], numbered)
                poetry.extend(lines)
            elif any_poetry:
                poetry.append(content_parts if index == 0 else content_parts[1:])
        merged = self.consolidate_strings(parts)
        if merged and isinstance(merged[-1], str):
            merged[-1] = merged[-1].rstrip()
        verse = VerseContent(
            text=self._extract_text(merged).strip(),
            content_parts=merged,
            has_poetry=bool(poetry),
            poetry_lines=poetry or None,
        )
        return self._build_verse(osis_id, verse)

    def _summary_split(self, chapter: Chapter) -> tuple[Tag | None, Chapter]:
        """Separate a chapter's ``<small>`` summary paragraph from its verses.

        Args:
            chapter: The chapter.

        Returns:
            The summary paragraph (or ``None``) and the chapter without it.
        """
        first = chapter.paragraphs[0] if chapter.paragraphs else None
        if first is not None:
            small = first.find("small")
            if small is not None and small.get_text().strip() == first.get_text().strip():
                return first, Chapter(chapter.heading, chapter.paragraphs[1:])
        return None, chapter

    def _build_chapter(
        self, work: WorkDef, number: int, chapter: Chapter, book_id: str
    ) -> pyosis.DivCt | None:
        """Build the OSIS chapter div.

        Args:
            work: The work the chapter belongs to.
            number: Chapter number (position in the work).
            chapter: The chapter.
            book_id: OSIS id of the containing book.

        Returns:
            The ``<div type="chapter">``, or ``None`` for a chapter with no text.
        """
        summary, body = self._summary_split(chapter)
        osis_id = f"{book_id}.{number}"
        content: list = []
        if summary is not None:
            content.append(
                pyosis.DivCt(
                    type_value=pyosis.OsisDivs.SUMMARY,
                    canonical=False,
                    content=[pyosis.PCt(content=self.parse_inline_annotations(summary))],
                )
            )
        for verse_number, paragraphs, numbered in self._verse_groups(body, work):
            content.append(
                self._build_chapter_verse(f"{osis_id}.{verse_number}", paragraphs, numbered)
            )
        first_verse = next((c for c in content if isinstance(c, pyosis.VerseCt)), None)
        if first_verse is not None and chapter.notes:
            notes = [self._note(name) for name in chapter.notes]
            first_verse.content = [
                *(n for n in notes if isinstance(n, pyosis.NoteCt)),
                *first_verse.content,
            ]
        if first_verse is None:
            LOGGER.warning(
                "%s: chapter %d (%r) has no text; skipped", book_id, number, chapter.heading
            )
            return None
        return pyosis.DivCt(
            type_value=pyosis.OsisDivs.CHAPTER, osis_id=[osis_id], canonical=True, content=content
        )

    def _build_intro(self, blocks: list[str | Tag]) -> pyosis.DivCt | None:
        """Build the non-canonical introduction div.

        Args:
            blocks: Introduction headings (text) and paragraphs.

        Returns:
            The ``<div type="introduction">``, or ``None`` if there is nothing in it.
        """
        elements: list = []
        for block in blocks:
            if isinstance(block, str):
                elements.append(pyosis.HeadCt(content=[block]))
                continue
            parts = self.parse_inline_annotations(block)
            if parts:
                elements.append(pyosis.PCt(content=parts))
        if not elements:
            return None
        return pyosis.DivCt(
            type_value=pyosis.OsisDivs.INTRODUCTION, canonical=False, content=elements
        )

    def build_work_div(self, work: WorkDef, html: str) -> pyosis.DivCt:
        """Build the OSIS book div of one work.

        Args:
            work: The work.
            html: Its page HTML.

        Returns:
            The ``<div type="book">`` with title, introduction and chapters.
        """
        parts = self.split_page(html, work)
        content: list = [
            pyosis.TitleCt(
                type_value=pyosis.OsisTitles.MAIN,
                canonical=True,
                short=work.short,
                content=[work.title],
            )
        ]
        intro = self._build_intro(parts.intro)
        if intro is not None:
            content.append(intro)
        for number, chapter in enumerate(parts.chapters, start=1):
            div = self._build_chapter(work, number, chapter, work.osis_id)
            if div is not None:
                content.append(div)
        return pyosis.DivCt(
            type_value=pyosis.OsisDivs.BOOK,
            osis_id=[work.osis_id],
            canonical=True,
            content=content,
        )

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    @staticmethod
    def _build_header(book: BookDef) -> pyosis.HeaderCt:
        """Build the OSIS header with revision and work metadata.

        Args:
            book: The document being written.

        Returns:
            The header, stamped with the current local time as the eversion date.
        """
        stamp = datetime.now().strftime("%Y.%m.%dT%H:%M:%S")
        return pyosis.HeaderCt(
            canonical=False,
            revision_desc=[
                pyosis.RevisionDescCt(
                    date=pyosis.DateCt(
                        event=pyosis.OsisEvents.EVERSION,
                        type_value="ISO",
                        lang="en",
                        content=[stamp],
                    ),
                    p=[
                        pyosis.PCt(
                            content=[
                                "Scraped from https://sacred-texts.com/bib/lbob/, "
                                "and converted to OSIS by open-canon contributors."
                            ]
                        )
                    ],
                ),
                pyosis.RevisionDescCt(
                    date=pyosis.DateCt(
                        event=pyosis.OsisEvents.EDITION,
                        type_value="ISO",
                        lang="en",
                        content=[EDITION_YEAR],
                    ),
                    p=[pyosis.PCt(content=[EDITION_NOTE])],
                ),
            ],
            work=[
                pyosis.WorkCt(
                    osis_work=book.osis_id,
                    lang="en",
                    title=[pyosis.TitleCt(canonical=True, content=[book.title])],
                    description=[
                        pyosis.DescriptionCt(
                            value=(
                                f'Text from "The Lost Books of the Bible," 1926. {book.title}. '
                                "Scraped from sacred-texts.com and converted to OSIS."
                            )
                        )
                    ],
                    type_value=[pyosis.TypeCt(type_value="OSIS", content=["Bible"])],
                    publisher=[pyosis.PublisherCt(value="Alpha House, Inc.")],
                ),
            ],
        )

    def build_osis_for_book(self, book: BookDef, page_html: dict[int, str]) -> pyosis.OsisXML:
        """Generate a complete OSIS document.

        A document with several works wraps them as sub-books of one parent book.

        Args:
            book: The document definition.
            page_html: Page HTML keyed by page number; must hold every page of ``book``.

        Returns:
            The OSIS document.
        """
        divs = [self.build_work_div(work, page_html[work.page]) for work in book.works]
        if len(divs) == 1:
            book_div = divs[0]
        else:
            book_div = pyosis.DivCt(
                type_value=pyosis.OsisDivs.BOOK,
                osis_id=[book.osis_id],
                canonical=True,
                content=[
                    pyosis.TitleCt(
                        type_value=pyosis.OsisTitles.MAIN,
                        canonical=True,
                        short=book.short,
                        content=[book.title],
                    ),
                    *divs,
                ],
            )
        osis_text = pyosis.OsisTextCt(
            lang="en",
            osis_idwork=book.osis_id,
            osis_ref_work=book.short,
            canonical=True,
            header=self._build_header(book),
            div=[book_div],
        )
        return pyosis.OsisXML(pyosis.Osis(osis_text=osis_text))

    def process_all(
        self,
        output_dir: str = ".",
        start_page: int = FILE_RANGE[0],
        end_page: int = FILE_RANGE[1],
    ) -> None:
        """Fetch the pages and write one XML file per document.

        Pages outside ``[start_page, end_page]`` are not fetched; a document with a page
        that could not be fetched is skipped with a warning, and a failure building one
        document is logged without stopping the others.

        Args:
            output_dir: Directory for the XML files (created if missing).
            start_page: First page number to fetch.
            end_page: Last page number to fetch (inclusive).
        """
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        needed = sorted({p for book in BOOKS for p in book.pages if start_page <= p <= end_page})
        LOGGER.info("Fetching %d pages…", len(needed))
        page_html: dict[int, str] = {}
        for page in tqdm(needed, desc="Fetching pages"):
            try:
                page_html[page] = self.fetch_page(page)
            except Exception as exc:
                LOGGER.error("Failed to fetch page %d: %s", page, exc)

        self._page_html = page_html
        for book in tqdm(BOOKS, desc="Generating XML files"):
            missing = [p for p in book.pages if p not in page_html]
            if missing:
                LOGGER.warning("Skipping %s: missing pages %s", book.output_stem, missing)
                continue
            try:
                osis_doc = self.build_osis_for_book(book, page_html)
                xml_path = out_path / f"{book.output_stem}.xml"
                xml_path.write_text(osis_doc.to_xml(), encoding="utf-8")
                LOGGER.info("Wrote %s", xml_path)
            except Exception as exc:
                LOGGER.error("Error generating %s: %s", book.output_stem, exc, exc_info=True)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


OUTPUT_FILENAMES: Final[tuple[str, ...]] = tuple(f"{book.output_stem}.xml" for book in BOOKS)
"""Names of the XML files the scraper writes, in the order ``run`` reports them."""


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the ``--start-page`` and ``--end-page`` options.

    Args:
        parser: Subcommand parser to extend.
    """
    parser.add_argument(
        "--start-page",
        type=int,
        default=FILE_RANGE[0],
        help="first page number to fetch (default: %(default)s)",
    )
    parser.add_argument(
        "--end-page",
        type=int,
        default=FILE_RANGE[1],
        help="last page number to fetch (default: %(default)s)",
    )


def run(args: argparse.Namespace) -> list[Path]:
    """Run the Lost Books of the Bible scraper.

    Args:
        args: Parsed options: ``output_dir``, ``cache_dir``, ``delay``, ``start_page`` and
            ``end_page``.

    Returns:
        Paths of the expected output files that exist in ``output_dir`` afterwards.
    """
    output_dir = Path(args.output_dir)
    parser = LBOBParser(cache_dir=args.cache_dir, delay=args.delay)
    try:
        LOGGER.info(
            "Processing pages %d–%d with %.1fs delay", args.start_page, args.end_page, args.delay
        )
        parser.process_all(
            output_dir=str(output_dir), start_page=args.start_page, end_page=args.end_page
        )
        LOGGER.info("Done!")
    finally:
        parser.close()
    return [output_dir / name for name in OUTPUT_FILENAMES if (output_dir / name).exists()]


SPEC = ScraperSpec(
    name="lost-books-of-the-bible",
    help="The Lost Books of the Bible (eighteen documents) to OSIS",
    source="https://sacred-texts.com/book/the-lost-books-of-the-bible",
    outputs=OUTPUT_FILENAMES,
    run=run,
    add_arguments=add_arguments,
)
"""Registry entry for the ``lost-books-of-the-bible`` scraper."""
