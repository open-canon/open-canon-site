"""Download and parse E. A. Wallis Budge's *The Book of the Cave of Treasures* to OSIS XML.

Source: ``https://sacred-texts.com/chr/bct/`` (now ``/book/the-book-of-the-cave-of-treasures``).
The pages are fetched from ``archive.sacred-texts.com``, which still serves the original
markup.

Reference scheme
----------------

The translation has no chapter or verse numbering of its own, so one is imposed. It is
deliberately simple and follows the divisions Budge prints:

* **Chapter** = one numbered text page, in source order: 1 The First Thousand Years
  (``bct04.htm``), 2 The Second, 3 The Third, 4 The Fourth, 5 The Fifth, 6 The Five Hundred
  Years from the Second Year of Cyrus to the Birth of Christ, 7 Testamentum Adami and 8 the
  Supplementary Translations from the "Book of the Bee" (``bct11.htm``). Chapters 1 to 6 are
  the book itself; 7 and 8 are translations Budge appended and use the same scheme.
* **Verse** = one paragraph of the translation, numbered consecutively from 1 within its
  chapter (``CaveOfTreasures.<chapter>.<verse>``). A row of a numbered list of names (the
  genealogies in chapter 6) is its own verse.
* **Sub-headings** (Budge's bracketed centred headings such as ``[The Creation. First Day.]``)
  are emitted as non-canonical ``<title type="sub">`` elements before the verses they
  introduce; they are not verses. The page's own ``<h1>``, the running heads (``TRANSLATION``,
  the manuscript reference) and the chapter's own heading are kept as headings too.
* **Page markers** (``p. 44``, the printed page of the 1927 edition) become ``<milestone
  type="page">`` elements inside the verse (or heading) in which they fall. Folio references
  to the Syriac manuscript (``[Fol. 3b, col. 1.]``) stay in the text as printed.
* **Budge's notes** (paragraphs opening ``[NOTES.``, his commentary rather than the
  translation) become ``<note n="Budge">`` elements at the end of the verse they follow
  (the site shows them as note popups next to that verse); the surrounding brackets and the
  ``NOTES.--`` label are dropped as redundant. His footnotes become inline ``<note>``
  elements too.

Images
------

Images are kept as ``<figure src=...>`` elements that point at the image files on
``archive.sacred-texts.com`` (the files themselves are not downloaded):

* Every image inside a translation page (the cuneiform and hieroglyph renderings in
  chapters 5 and 6, for instance) becomes a figure at the end of the verse it follows (in
  front and back matter, in a non-canonical ``<div type="x-figures">``). The image's
  ``alt`` text is kept.
* The sixteen plate pages (the frontispiece and Plates I to XV, ``bct_pl00`` to ``bct_pl15``)
  are collected in one non-canonical ``<div type="x-plates">`` at the very end of the book. Each
  plate is a ``<div type="x-plate">`` with a sub-title (``Plate XV (facing page 272)``), one
  figure per image and Budge's caption as a paragraph.

Front and back matter are kept, not numbered: the title page, contents, preface and
introduction come first, then the chapters, then the essay "Abraham and the City of Ur"
(``appendix``) and the bibliography, then the plates. Each is a non-canonical div (with the
matching OSIS div type) holding paragraphs, with headings as section divs.

Nothing on these pages is dropped except site navigation; a table row becomes a verse
(chapters) or paragraph (other sections) with cells joined by `` | ``. Only the transcriber's
"notes to the hypertext transcription" page is not scraped.
"""

from __future__ import annotations

import argparse
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Final
from urllib.parse import urljoin

import pyosis
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from open_canon_site.scrapers._http import CachedHttpFetcher
from open_canon_site.scrapers._osis import (
    InlinePart,
    consolidate_inline_strings,
    normalize_whitespace,
)
from open_canon_site.scrapers.base import ScraperSpec
from open_canon_site.scrapers.sacred_texts._layout import legacy_html

LOGGER = logging.getLogger(__name__)
"""Module logger; warns when an invalid cached page is discarded."""

OUTPUT_FILENAME: Final[str] = "cave-of-treasures.xml"
"""Name of the OSIS file written into the output directory."""

SOURCE_URL: Final[str] = "https://sacred-texts.com/chr/bct/index.htm"
"""Human-facing URL of the book, recorded in the OSIS header and ``SPEC.source``."""
PAGE_URL_TEMPLATE: Final[str] = "https://archive.sacred-texts.com/chr/bct/{page}.htm"
"""``str.format`` template for a page URL; ``{page}`` is the page stem such as ``bct04``."""
OSIS_WORK_ID: Final[str] = "CaveOfTreasures"
"""OSIS work identifier, also the book id prefix (``CaveOfTreasures.<chapter>.<verse>``)."""
BOOK_TITLE: Final[str] = "The Book of the Cave of Treasures"
"""Full title of the book."""
BOOK_SHORT_TITLE: Final[str] = "Cave of Treasures"
"""Short title used for the OSIS main title and ``osisRefWork``."""


@dataclass(frozen=True)
class ChapterSource:
    """Where one section of the book lives and how to recognise it."""

    page: str
    """Page stem on the archive host, e.g. ``bct04``."""
    title: str
    """Section title: the OSIS chapter title, or the title of a front/back matter div."""
    marker: re.Pattern[str]
    """Pattern that must match the page text; guards against interstitials and wrong pages."""
    role: str = "chapter"
    """``chapter`` (numbered, canonical verses) or the OSIS div type of non-numbered matter:
    ``titlePage``, ``tableOfContents``, ``preface``, ``introduction``, ``appendix`` or
    ``bibliography``."""


SECTIONS: Final[tuple[ChapterSource, ...]] = (
    ChapterSource("bct00", "Title Page", re.compile(r"CAVE OF TREASURES"), "titlePage"),
    ChapterSource("bct01", "Contents", re.compile(r"LIST OF PLATES"), "tableOfContents"),
    ChapterSource("bct02", "Preface", re.compile(r"PREFACE"), "preface"),
    ChapterSource("bct03", "Introduction", re.compile(r"INTRODUCTION"), "introduction"),
    ChapterSource("bct04", "The First Thousand Years", re.compile(r"FIRST THOUSAND YEARS")),
    ChapterSource("bct05", "The Second Thousand Years", re.compile(r"SECOND THOUSAND YEARS")),
    ChapterSource("bct06", "The Third Thousand Years", re.compile(r"THIRD THOUSAND YEARS")),
    ChapterSource("bct07", "The Fourth Thousand Years", re.compile(r"FOURTH THOUSAND YEARS")),
    ChapterSource("bct08", "The Fifth Thousand Years", re.compile(r"FIFTH THOUSAND YEARS")),
    ChapterSource(
        "bct09",
        "The Five Hundred Years from the Second Year of Cyrus to the Birth of Christ",
        re.compile(r"FIVE HUNDRED YEARS FROM THE SECOND YEAR OF CYRUS"),
    ),
    ChapterSource("bct10", "Testamentum Adami", re.compile(r"TESTAMENTUM ADAMI")),
    ChapterSource(
        "bct11",
        'Supplementary Translations from the "Book of the Bee"',
        re.compile(r"BOOK OF THE BEE"),
    ),
    ChapterSource("bct12", "Abraham and the City of Ur", re.compile(r"CITY OF UR"), "appendix"),
    ChapterSource("bct13", "Bibliography", re.compile(r"BIBLIOGRAPHY"), "bibliography"),
)
"""Every text page in book order. The ``chapter`` role pages are numbered 1 to 8 in order."""
CHAPTERS: Final[tuple[ChapterSource, ...]] = tuple(
    source for source in SECTIONS if source.role == "chapter"
)
"""The eight numbered chapters; chapter ``n`` is ``CHAPTERS[n - 1]``."""
DIV_TYPES: Final[dict[str, pyosis.OsisDivs]] = {
    "titlePage": pyosis.OsisDivs.TITLE_PAGE,
    "tableOfContents": pyosis.OsisDivs.TABLEOF_CONTENTS,
    "preface": pyosis.OsisDivs.PREFACE,
    "introduction": pyosis.OsisDivs.INTRODUCTION,
    "appendix": pyosis.OsisDivs.APPENDIX,
    "bibliography": pyosis.OsisDivs.BIBLIOGRAPHY,
}
"""OSIS div type for each non-chapter role."""

CHAPTER_HEADING_RE: Final[re.Pattern[str]] = re.compile(
    r"THOUSAND YEARS|FIVE HUNDRED YEARS FROM THE SECOND YEAR", re.IGNORECASE
)
"""Matches an unbracketed centred heading that names the chapter itself."""
RUNNING_HEAD_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:TRANSLATION|\(Brit\. Mus\.[^)]*\))$", re.IGNORECASE
)
"""Matches the manuscript running heads on the first page, kept as headings."""
NAVIGATION_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:(?:Sacred-Texts|Christianity|Index|List of Plates|Title Page|Previous Plate|Next Plate"
    r"|Previous|Next)\s*)+$",
    re.IGNORECASE,
)
"""Matches the site's own navigation paragraphs, which hold only nav link words."""
TITLE_PAGE_NAVIGATION_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:(?:Sacred-Texts|Christianity|Index|Frontespiece|Next)\s*)+$", re.IGNORECASE
)
"""Matches the title page's navigation line, which links to the frontispiece plate."""
NOTES_RE: Final[re.Pattern[str]] = re.compile(r"^\[?\s*NOTES?\b")
"""Matches the start of one of Budge's commentary paragraphs."""
PAGE_ANCHOR_RE: Final[re.Pattern[str]] = re.compile(r"^page_(?P<page>[0-9ivxlcdm]+)$", re.I)
"""Matches the ``name`` of a printed-page anchor such as ``page_44``."""
PLATE_PAGES: Final[tuple[str, ...]] = tuple(f"bct_pl{n:02d}" for n in range(16))
"""Page stems of the plates: the frontispiece (``bct_pl00``) and Plates I to XV."""
FACING_RE: Final[re.Pattern[str]] = re.compile(r"facing\s+page\s+(?P<page>[0-9ivxlcdm]+)", re.I)
"""Matches the ``{facing page 272}`` line of a plate page."""
FOLIO_HEADING_RE: Final[re.Pattern[str]] = re.compile(
    r"^\[(?P<folio>Fol\.[^\]]*)\]\s*\[(?P<title>.*?)\]\.?$"
)
"""Matches a heading that starts with a folio reference: ``[Fol. 13b, col. 2] [The Rule of Enoch].``"""
NOTE_LABEL_RE: Final[re.Pattern[str]] = re.compile(r"^\[?\s*NOTES?\s*[.:]?\s*(?:--|\u2014|-)?\s*")
"""Matches the ``[NOTES.--`` opening of one of Budge's commentary paragraphs."""
FOOTNOTE_ANCHOR_RE: Final[re.Pattern[str]] = re.compile(r"(?:_note_\d+|^fn_\d+)$")
"""Matches a footnote anchor name: ``page_92_note_1`` on the archive host, ``fn_1`` after
``legacy_html`` rebuilds a reader-layout page."""
PLATE_FOOTER_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:Sacred Texts\s*\|\s*Christianity|(?:«\s*)?(?:Previous|Next):.*)$", re.IGNORECASE
)
"""Matches the footer navigation of a page: ``Sacred Texts | Christianity`` and the
``« Previous: …`` / ``Next: … »`` links."""
FOOTNOTE_PAGE_ANCHOR_RE: Final[re.Pattern[str]] = re.compile(r"^footnotes_page_")
"""Matches the anchor that opens a page's footnotes: ``footnotes_page_v``."""
FOOTNOTE_PAGE_LABEL_RE: Final[re.Pattern[str]] = re.compile(r"^p\.\s*[0-9ivxlcdm]+$", re.I)
"""Matches the printed-page label next to such an anchor: ``p. v``."""
HEADING_TAGS: Final[list[str]] = ["h1", "h2", "h3", "h4", "h5", "h6"]
"""Heading elements; each is kept as a heading (the ``Footnotes`` heading ends the content)."""
LIST_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"^\d+\.$")
"""Matches the number cell of a numbered-list table row such as ``12.``."""


@dataclass
class Footnote:
    """One footnote from the foot of a page."""

    label: str
    """Footnote label as printed, e.g. ``1``."""
    parts: list[InlinePart]
    """Footnote body as inline parts."""


@dataclass
class Image:
    """One image on a page."""

    src: str
    """Absolute URL of the image file."""
    alt: str
    """Alternative text; empty when the page gives none."""


@dataclass
class Block:
    """One block of a chapter in source order."""

    kind: str
    """``verse``, ``heading``, ``notes`` or ``figures``."""
    parts: list[InlinePart]
    """Inline content, including page milestones and footnote notes (empty for figures)."""
    images: list[Image] = field(default_factory=list)
    """Images of a ``figures`` block."""


@dataclass
class Plate:
    """One plate page: the frontispiece or a numbered plate."""

    label: str
    """Plate label as printed, e.g. ``PLATE XV`` or ``Frontespiece``."""
    facing: str
    """Printed page the plate faces, or ``""`` when none is given."""
    images: list[Image]
    """The plate's images in page order."""
    caption: list[str]
    """Caption paragraphs as plain text."""


@dataclass
class Chapter:
    """A parsed chapter page."""

    number: int
    """Chapter number (1 through 8), or 0 for front and back matter."""
    title: str
    """Section title."""
    blocks: list[Block] = field(default_factory=list)
    """Headings, verses and notes in source order."""
    role: str = "chapter"
    """The source's ``role``; anything but ``chapter`` is emitted without verse numbers."""


def _clean(parts: list[InlinePart]) -> list[InlinePart]:
    """Normalise whitespace in inline parts and trim the outer edges.

    Args:
        parts: Inline parts as built from the markup.

    Returns:
        Parts with whitespace runs collapsed, the first string left-trimmed, the last
        right-trimmed and empty strings removed.
    """
    merged = consolidate_inline_strings(list(parts))
    merged = [re.sub(r"\s+", " ", p) if isinstance(p, str) else p for p in merged]
    while merged and isinstance(merged[0], str) and not merged[0].strip():
        merged.pop(0)
    while merged and isinstance(merged[-1], str) and not merged[-1].strip():
        merged.pop()
    if merged and isinstance(merged[0], str):
        merged[0] = merged[0].lstrip()
    if merged and isinstance(merged[-1], str):
        merged[-1] = merged[-1].rstrip()
    return merged


def _has_text(parts: list[InlinePart]) -> bool:
    """Report whether any part carries visible content other than a page milestone.

    Args:
        parts: Inline parts.

    Returns:
        True if there is non-blank text, a highlight or a note.
    """
    for part in parts:
        if isinstance(part, str):
            if part.strip():
                return True
        elif not isinstance(part, pyosis.MilestoneCt):
            return True
    return False


def _plain(parts: list[InlinePart]) -> str:
    """Flatten inline parts to text, ignoring milestones and notes.

    Args:
        parts: Inline parts.

    Returns:
        The concatenated text, whitespace-normalised.
    """
    out: list[str] = []
    for part in parts:
        if isinstance(part, str):
            out.append(part)
        elif isinstance(part, pyosis.HiCt):
            out.append(_plain(list(part.content)))
    return normalize_whitespace("".join(out))


class CaveOfTreasuresParser:
    """Fetch and parse the six translated sections of the Cave of Treasures into OSIS.

    Each section is one old-layout page: loose ``<p>`` paragraphs, centred bracketed
    headings, ``[NOTES...]`` commentary paragraphs, occasional tables and an optional
    ``Footnotes`` block after the final rule.
    """

    def __init__(self, cache_dir: str | None = None, delay: float = 1.0) -> None:
        """Create a parser with a caching HTTP fetcher.

        Args:
            cache_dir: Directory for cached pages, or ``None`` to disable caching.
            delay: Seconds to wait around each live request.
        """
        self.http = CachedHttpFetcher(cache_dir=cache_dir, delay=delay, logger=LOGGER)
        """Fetcher used for the chapter pages."""

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self.http.close()

    @staticmethod
    def is_valid_page(text: str, source: ChapterSource) -> bool:
        """Report whether text is the genuine page for the given chapter.

        Args:
            text: Raw page HTML.
            source: Chapter the page should contain.

        Returns:
            True if the main content matches the chapter's heading marker and the page is
            not a Cloudflare interstitial ("Just a moment").
        """
        return "Just a moment" not in text and bool(source.marker.search(legacy_html(text)))

    def _fetch_validated(self, url: str, validator: Callable[[str], bool], what: str) -> str:
        """Fetch a page, preferring a valid cached copy and never keeping an invalid one.

        An invalid cached copy is logged and deleted; an invalid fetched page also removes
        its cache entry.

        Args:
            url: Page URL.
            validator: Returns whether page text is genuine.
            what: Description used in log and error messages.

        Returns:
            Raw HTML of the page.

        Raises:
            RuntimeError: If the fetched page fails validation.
        """
        cache_path = self.http.cache_path_for(url)
        if cache_path and cache_path.exists():
            cached = cache_path.read_text(encoding="utf-8")
            if validator(cached):
                return cached
            LOGGER.warning("Discarding invalid cached Cave of Treasures page at %s", cache_path)
            cache_path.unlink()

        fetched = self.http.fetch_text(url=url)
        if validator(fetched):
            return fetched
        if cache_path and cache_path.exists():
            cache_path.unlink()
        raise RuntimeError(
            f"Source page {url} did not contain {what}; direct access to "
            "sacred-texts.com may be blocked in this environment"
        )

    def fetch_page_text(self, source: ChapterSource) -> str:
        """Return the validated HTML of one chapter page, from cache or the network.

        Args:
            source: Chapter to fetch.

        Returns:
            Raw HTML of the page.
        """
        return self._fetch_validated(
            PAGE_URL_TEMPLATE.format(page=source.page),
            lambda text: self.is_valid_page(text, source),
            repr(source.title),
        )

    @staticmethod
    def is_valid_plate_page(text: str) -> bool:
        """Report whether text is a genuine plate page.

        Args:
            text: Raw page HTML.

        Returns:
            True if it shows at least one image and is not a Cloudflare interstitial.
        """
        return "Just a moment" not in text and "<img" in legacy_html(text).lower()

    def fetch_plate_text(self, page: str) -> str:
        """Return the validated HTML of one plate page, from cache or the network.

        Args:
            page: Plate page stem such as ``bct_pl07``.

        Returns:
            Raw HTML of the page.
        """
        return self._fetch_validated(
            PAGE_URL_TEMPLATE.format(page=page), self.is_valid_plate_page, "a plate image"
        )

    def parse_inline(self, node: Tag, footnotes: dict[str, Footnote]) -> list[InlinePart]:
        """Convert the children of an element to inline OSIS parts.

        Page anchors become page milestones, footnote references become notes, italics and
        bold become highlights, ``<br>`` becomes a space and every other tag is unwrapped.

        Args:
            node: Element whose children to convert.
            footnotes: Page footnotes keyed by the anchor name they are linked from.

        Returns:
            Inline parts, not yet whitespace-cleaned.
        """
        parts: list[InlinePart] = []
        for child in node.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                parts.append(str(child))
                continue
            if not isinstance(child, Tag):
                continue
            if child.name == "br":
                parts.append(" ")
            elif child.name == "a":
                name = child.get("name", "")
                href = child.get("href", "")
                page = PAGE_ANCHOR_RE.match(name) if name else None
                if page:
                    parts.append(pyosis.MilestoneCt(type_value="page", n=page.group("page")))
                elif href.startswith("#") and href[1:] in footnotes:
                    note = footnotes[href[1:]]
                    parts.append(
                        pyosis.NoteCt(type_value="explanation", n=note.label, content=note.parts)
                    )
                else:
                    parts.extend(self.parse_inline(child, footnotes))
            elif child.name in {"i", "em", "b", "strong"}:
                inner = _clean(self.parse_inline(child, footnotes))
                if inner:
                    kind = pyosis.OsisHi.ITALIC if child.name in {"i", "em"} else pyosis.OsisHi.BOLD
                    parts.append(pyosis.HiCt(type_value=kind, content=inner))
            elif child.name not in {"script", "img"}:
                parts.extend(self.parse_inline(child, footnotes))
        return parts

    def parse_footnotes(self, soup: BeautifulSoup) -> dict[str, Footnote]:
        """Collect the footnotes in a page's ``Footnotes`` block.

        Each footnote paragraph is ``<p><a name="page_N_note_K"></a><a href="#page_N_fr_K">K</a>
        text</p>``. The returned mapping is keyed by ``page_N_note_K``, the fragment the
        in-text reference links to.

        Args:
            soup: Parsed page.

        Returns:
            Footnotes by anchor name; empty when the page has none.
        """
        footnotes: dict[str, Footnote] = {}
        heading = soup.find("h3", string=re.compile(r"Footnotes"))
        if not heading:
            return footnotes
        self._drop_footnote_page_labels(soup)
        for para in heading.find_next_siblings("p"):
            anchor = para.find("a", attrs={"name": FOOTNOTE_ANCHOR_RE})
            back = para.find("a", attrs={"href": re.compile(r"^#")})
            if not anchor or not back:
                continue
            label = normalize_whitespace(back.get_text())
            key = anchor["name"]
            for tag in (anchor, back):
                tag.decompose()
            footnotes[key] = Footnote(label=label, parts=_clean(self.parse_inline(para, {})))
        return footnotes

    PAGE_URL_TEMPLATE: str = PAGE_URL_TEMPLATE
    """Page URL template used to resolve relative image URLs; subclasses for other books
    override it."""

    @staticmethod
    def _drop_footnote_page_labels(soup: BeautifulSoup) -> None:
        """Remove the page labels the footnote block prints between footnotes.

        Each page's footnotes are introduced by ``<a name="footnotes_page_v"></a><font
        color="GREEN">p. v</font>``. When a footnote runs on across a page break the label
        lands in the middle of its sentence; it marks the printed page, not text, so both the
        anchor and the label that directly follows it are dropped. Page cross-references that
        are part of a footnote's wording (``see p. 12``) have no such anchor and are kept.

        Args:
            soup: Parsed page; modified in place.
        """
        for anchor in soup.find_all("a", attrs={"name": FOOTNOTE_PAGE_ANCHOR_RE}):
            label = anchor.find_next_sibling()
            if (
                isinstance(label, Tag)
                and label.name == "font"
                and FOOTNOTE_PAGE_LABEL_RE.match(label.get_text(strip=True))
            ):
                label.decompose()
            anchor.decompose()

    @classmethod
    def parse_images(cls, node: Tag, page: str) -> list[Image]:
        """Collect the images inside an element.

        Args:
            node: Element to search.
            page: Stem of the page being parsed, used to resolve relative ``src`` values.

        Returns:
            The images in document order, with absolute URLs.
        """
        base = cls.PAGE_URL_TEMPLATE.format(page=page)
        return [
            Image(src=urljoin(base, img["src"]), alt=normalize_whitespace(img.get("alt", "")))
            for img in node.find_all("img")
            if img.get("src")
        ]

    def _table_blocks(
        self, table: Tag, footnotes: dict[str, Footnote], pending: list[InlinePart], page: str
    ) -> list[Block]:
        """Turn every row of a table into verses and figures, dropping nothing.

        A row whose first cell is a list number (``12.``) is one verse reading ``12. text``.
        Any other row with text is one verse whose cells are joined with `` | ``. Images in a
        row follow it as a ``figures`` block, and a row with only images yields just that.
        A row holding only a page marker carries the marker into ``pending``. Rows that
        contain a nested table are skipped, since the nested rows are visited themselves.

        Args:
            table: The ``<table>`` element.
            footnotes: Page footnotes.
            pending: Page milestones waiting for the next block; extended in place.
            page: Stem of the page being parsed.

        Returns:
            Verse and figures blocks in row order.
        """
        blocks: list[Block] = []
        for row in table.find_all("tr"):
            if row.find("table"):
                continue
            cells = row.find_all(["td", "th"], recursive=False)
            images = self.parse_images(row, page)
            cell_parts = [_clean(self.parse_inline(cell, footnotes)) for cell in cells]
            cell_parts = [cp for cp in cell_parts if _has_text(cp)]
            if not cell_parts:
                for cp in (_clean(self.parse_inline(cell, footnotes)) for cell in cells):
                    pending.extend(p for p in cp if isinstance(p, pyosis.MilestoneCt))
                if images:
                    blocks.append(Block("figures", [], images))
                continue

            number = normalize_whitespace(cells[0].get_text()) if cells else ""
            if len(cell_parts) >= 2 and LIST_NUMBER_RE.match(number):
                joined: list[InlinePart] = [number + " ", *cell_parts[1]]
                for extra in cell_parts[2:]:
                    joined.extend([" | ", *extra])
            else:
                joined = []
                for index, cp in enumerate(cell_parts):
                    joined.extend([" | ", *cp] if index else cp)
            blocks.append(Block("verse", _clean([*pending, *joined])))
            pending.clear()
            if images:
                blocks.append(Block("figures", [], images))
        return blocks

    def parse_chapter(self, html_text: str, number: int) -> Chapter:
        """Parse one numbered chapter page.

        Args:
            html_text: Raw page HTML (old layout, or reader layout via ``legacy_html``).
            number: Chapter number, 1 through 8.

        Returns:
            The chapter with its headings, verses and notes in source order.
        """
        return self.parse_section(html_text, CHAPTERS[number - 1], number)

    def parse_section(self, html_text: str, source: ChapterSource, number: int = 0) -> Chapter:
        """Parse one text page, numbered chapter or front/back matter.

        Args:
            html_text: Raw page HTML (old layout, or reader layout via ``legacy_html``).
            source: The section the page holds.
            number: Chapter number, or 0 for front and back matter.

        Returns:
            The section with its headings, paragraphs and notes in source order.
        """
        soup = BeautifulSoup(legacy_html(html_text), "html.parser")
        footnotes = self.parse_footnotes(soup)
        page = source.page
        chapter = Chapter(number=number, title=source.title, role=source.role)
        pending: list[InlinePart] = []
        body = soup.body or soup

        for element in body.find_all(HEADING_TAGS + ["p", "blockquote", "table"], recursive=False):
            if element.find_parent("table") is not None:
                continue
            if element.name == "h3" and element.get_text(strip=True) == "Footnotes":
                break
            if element.name == "table":
                chapter.blocks.extend(self._table_blocks(element, footnotes, pending, page))
                continue
            footnote_start = element.find_previous_sibling("h3", string=re.compile("Footnotes"))
            if footnote_start is not None:
                break

            parts = _clean(self.parse_inline(element, footnotes))
            images = self.parse_images(element, page)
            if not _has_text(parts):
                pending.extend(p for p in parts if isinstance(p, pyosis.MilestoneCt))
                if images:
                    chapter.blocks.append(Block("figures", [], images))
                continue
            text = _plain(parts)
            if NAVIGATION_RE.match(text) or (
                element.find("a") and TITLE_PAGE_NAVIGATION_RE.match(text)
            ):
                continue

            centred = element.get("align") == "center" or self._looks_centred(element, text)
            is_heading = (
                element.name in HEADING_TAGS
                or (element.name == "blockquote" and len(text) <= 200)
                or (
                    centred
                    and (
                        text.startswith("[")
                        or CHAPTER_HEADING_RE.search(text)
                        or RUNNING_HEAD_RE.match(text)
                        or self._is_caps_heading(text)
                    )
                )
            )
            if is_heading:
                folio = FOLIO_HEADING_RE.match(text)
                if folio:
                    parts = [folio.group("title")]
                    pending.append(f"[{folio.group('folio')}] ")
                else:
                    if text.startswith("[") and isinstance(parts[0], str):
                        parts[0] = parts[0][1:].lstrip()
                    if text.endswith("]") and isinstance(parts[-1], str):
                        parts[-1] = parts[-1][:-1].rstrip()
                pending.extend(p for p in parts if isinstance(p, pyosis.MilestoneCt))
                parts = [p for p in parts if not isinstance(p, pyosis.MilestoneCt)]
                kind = "heading"
            elif NOTES_RE.match(text):
                kind = "notes"
            else:
                kind = "verse"
            if kind == "heading":
                # A title cannot hold milestones: they wait for the next verse.
                chapter.blocks.append(Block(kind, parts))
            else:
                chapter.blocks.append(Block(kind, [*pending, *parts]))
                pending.clear()
            if images:
                chapter.blocks.append(Block("figures", [], images))

        return chapter

    def parse_plate(self, html_text: str, page: str) -> Plate:
        """Parse one plate page.

        The label is the first centred line, the facing page comes from ``{facing page N}``,
        images are every ``<img>`` and the caption is the remaining text (only navigation, the
        label and the facing line are left out).

        Args:
            html_text: Raw page HTML (old layout, or reader layout via ``legacy_html``).
            page: Page stem such as ``bct_pl07``, used to resolve image URLs.

        Returns:
            The parsed plate; its ``images`` is empty if the page has none.
        """
        soup = BeautifulSoup(legacy_html(html_text), "html.parser")
        body = soup.body or soup
        label = ""
        facing = ""
        caption: list[str] = []
        for element in body.find_all(["p", "td"]):
            if element.find(["p", "td", "table"]):
                continue
            text = _plain(_clean(self.parse_inline(element, {})))
            if not text or NAVIGATION_RE.match(text):
                continue
            if PLATE_FOOTER_RE.match(text):
                continue
            match = FACING_RE.search(text)
            if match:
                facing = match.group("page")
            elif not label:
                label = text
            elif text not in caption:
                caption.append(text)
        return Plate(
            label=label,
            facing=facing,
            images=self.parse_images(body, page),
            caption=caption,
        )

    @staticmethod
    def _looks_centred(element: Tag, text: str) -> bool:
        """Guess whether a paragraph was a centred heading when ``align`` is unavailable.

        ``legacy_html`` strips ``align`` from reader-layout pages, so a heading there is
        recognised by its shape: a short bracketed line that is not one of Budge's notes,
        a running head, or a short all-capitals line.

        Args:
            element: The paragraph element.
            text: Its plain text.

        Returns:
            True for a short bracketed line other than a ``NOTES`` paragraph, a running
            head, or a short line that is mostly capitals.
        """
        if element.name != "p" or len(text) > 200:
            return False
        if text.startswith("[") and text.endswith("]") and not NOTES_RE.match(text):
            return True
        if RUNNING_HEAD_RE.match(text):
            return True
        return CaveOfTreasuresParser._is_caps_heading(text)

    @staticmethod
    def _is_caps_heading(text: str) -> bool:
        """Report whether a short line is in capitals, as Budge's section headings are.

        Args:
            text: Plain text of a paragraph.

        Returns:
            True for a line of at most 200 characters in which over 80% of letters are capitals.
        """
        letters = [c for c in text if c.isalpha()]
        return (
            len(text) <= 200
            and bool(letters)
            and sum(c.isupper() for c in letters) / len(letters) > 0.8
        )

    @staticmethod
    def _heading_content(parts: list[InlinePart]) -> list[InlinePart]:
        """Return heading parts without page milestones, which a title cannot hold.

        Args:
            parts: Inline parts of a heading.

        Returns:
            The parts minus milestones.
        """
        return [p for p in parts if not isinstance(p, pyosis.MilestoneCt)]

    @staticmethod
    def _commentary_note(parts: list[InlinePart]) -> pyosis.NoteCt:
        """Build the inline note for one of Budge's ``[NOTES.--...]`` paragraphs.

        The enclosing square brackets and the ``NOTES.--`` label are Budge's way of marking
        commentary; a ``<note>`` already says so, so both are removed. A footnote nested in
        the paragraph cannot be a note inside a note and is kept as bracketed text.

        Args:
            parts: Inline parts of the whole paragraph.

        Returns:
            A note attached to the verse that precedes the paragraph.
        """
        flat: list[InlinePart] = []
        for part in parts:
            if isinstance(part, pyosis.NoteCt):
                flat.append(" [" + "".join(c for c in part.content if isinstance(c, str)) + "]")
            else:
                flat.append(part)
        flat = _clean(flat)
        # The brackets are often bold highlights of their own: drop those elements.
        if flat and isinstance(flat[0], pyosis.HiCt) and _plain([flat[0]]) == "[":
            flat.pop(0)
        if flat and isinstance(flat[-1], pyosis.HiCt) and _plain([flat[-1]]) == "]":
            flat.pop()
        if flat and isinstance(flat[0], str):
            flat[0] = NOTE_LABEL_RE.sub("", flat[0], count=1)
        if flat and isinstance(flat[-1], str):
            flat[-1] = re.sub(r"\s*\]$", "", flat[-1])
        return pyosis.NoteCt(type_value="explanation", n="Budge", content=_clean(flat))

    @staticmethod
    def _figure(image: Image) -> pyosis.FigureCt:
        """Build a ``<figure>`` for an image.

        Args:
            image: The image.

        Returns:
            A figure whose ``src`` is the image URL and whose ``alt`` is the alternative text
            (omitted when empty).
        """
        return pyosis.FigureCt(src=image.src, alt=image.alt or None)

    def _plates_div(self, plates: list[Plate]) -> pyosis.DivCt:
        """Build the non-canonical div that gathers the plates.

        Args:
            plates: Plates in page order.

        Returns:
            A ``x-plates`` div holding one ``x-plate`` div per plate.
        """
        div = pyosis.DivCt(
            type_value="x-plates",
            canonical=False,
            content=[
                pyosis.TitleCt(
                    type_value=pyosis.OsisTitles.MAIN, canonical=False, content=["Plates"]
                )
            ],
        )
        for plate in plates:
            title = plate.label + (f" (facing page {plate.facing})" if plate.facing else "")
            div.content.append(
                pyosis.DivCt(
                    type_value="x-plate",
                    canonical=False,
                    content=[
                        pyosis.TitleCt(
                            type_value=pyosis.OsisTitles.SUB, canonical=False, content=[title]
                        ),
                        *[self._figure(image) for image in plate.images],
                        *[pyosis.PCt(content=[line]) for line in plate.caption],
                    ],
                )
            )
        return div

    def generate_osis(
        self, chapters: list[Chapter], plates: list[Plate] | None = None
    ) -> pyosis.OsisXML:
        """Build the OSIS document for the book.

        Args:
            chapters: Chapters in order.
            plates: Plates to append after the chapters, if any.

        Returns:
            An OSIS document with one canonical chapter div per chapter and verse ids
            ``CaveOfTreasures.<chapter>.<verse>``; headings and notes are non-canonical.
        """
        current_date = datetime.now().strftime("%Y.%m.%dT%H:%M:%S")
        book_div = pyosis.DivCt(
            type_value=pyosis.OsisDivs.BOOK,
            osis_id=[OSIS_WORK_ID],
            canonical=True,
            content=[
                pyosis.TitleCt(
                    type_value=pyosis.OsisTitles.MAIN,
                    short=BOOK_SHORT_TITLE,
                    content=[BOOK_TITLE],
                )
            ],
        )

        for chapter in chapters:
            numbered = chapter.role == "chapter"
            chapter_div = pyosis.DivCt(
                type_value=pyosis.OsisDivs.CHAPTER if numbered else DIV_TYPES[chapter.role],
                osis_id=[f"{OSIS_WORK_ID}.{chapter.number}"] if numbered else [],
                canonical=numbered,
                content=[
                    pyosis.TitleCt(
                        type_value=pyosis.OsisTitles.CHAPTER
                        if numbered
                        else pyosis.OsisTitles.MAIN,
                        canonical=False,
                        content=[chapter.title],
                    )
                ],
            )
            verse_number = 0
            last_verse: pyosis.VerseCt | None = None
            waiting: list[object] = []  # notes and figures that precede the first verse
            for block in chapter.blocks:
                if block.kind == "heading":
                    title = pyosis.TitleCt(
                        type_value=pyosis.OsisTitles.SUB,
                        canonical=False,
                        content=self._heading_content(block.parts),
                    )
                    if numbered:
                        chapter_div.content.append(title)
                    else:
                        # The site only lists and renders a heading that sits in a section div.
                        chapter_div.content.append(
                            pyosis.DivCt(
                                type_value=pyosis.OsisDivs.SECTION,
                                canonical=False,
                                content=[title],
                            )
                        )
                elif not numbered:
                    if block.kind == "figures":
                        chapter_div.content.append(
                            pyosis.DivCt(
                                type_value="x-figures",
                                canonical=False,
                                content=[self._figure(image) for image in block.images],
                            )
                        )
                    else:
                        chapter_div.content.append(pyosis.PCt(content=block.parts))
                elif block.kind in {"figures", "notes"}:
                    extras = (
                        [self._figure(image) for image in block.images]
                        if block.kind == "figures"
                        else [self._commentary_note(block.parts)]
                    )
                    if last_verse is None:
                        waiting.extend(extras)
                    else:
                        last_verse.content = [*last_verse.content, *extras]
                else:
                    verse_number += 1
                    last_verse = pyosis.VerseCt(
                        osis_id=[f"{OSIS_WORK_ID}.{chapter.number}.{verse_number}"],
                        canonical=True,
                        content=[*block.parts, *waiting],
                    )
                    waiting = []
                    chapter_div.content.append(last_verse)
            book_div.content.append(chapter_div)

        if plates:
            book_div.content.append(self._plates_div(plates))

        header = pyosis.HeaderCt(
            canonical=False,
            revision_desc=[
                pyosis.RevisionDescCt(
                    date=pyosis.DateCt(
                        event=pyosis.OsisEvents.EVERSION,
                        type_value="ISO",
                        lang="en",
                        content=[current_date],
                    ),
                    p=[
                        pyosis.PCt(
                            content=[
                                f"Scraped from {SOURCE_URL} and converted to OSIS by Andrew P. Sansom."
                            ]
                        )
                    ],
                ),
                pyosis.RevisionDescCt(
                    date=pyosis.DateCt(
                        event=pyosis.OsisEvents.EDITION,
                        type_value="ISO",
                        lang="en",
                        content=["1927"],
                    ),
                    p=[
                        pyosis.PCt(
                            content=[
                                "The Book of the Cave of Treasures, translated from the Syriac "
                                "by E. A. Wallis Budge, London: The Religious Tract Society, 1927."
                            ]
                        )
                    ],
                ),
            ],
            work=[
                pyosis.WorkCt(
                    osis_work=OSIS_WORK_ID,
                    lang="en",
                    title=[pyosis.TitleCt(canonical=True, content=[BOOK_TITLE])],
                    description=[
                        pyosis.DescriptionCt(
                            value="The Book of the Cave of Treasures, translated from the Syriac by E. A. Wallis Budge, 1927 (the six translated sections: The First Thousand Years to The Five Hundred Years from the Second Year of Cyrus to the Birth of Christ). Transcribed at sacred-texts.com and converted to OSIS by the open-canon-site scrapers."
                        )
                    ],
                    type_value=[pyosis.TypeCt(type_value="OSIS", content=["Bible"])],
                    creator=[
                        pyosis.CreatorCt(
                            role=pyosis.OsisRoles.TRL,
                            value="E. A. Wallis Budge",
                        )
                    ],
                    publisher=[pyosis.PublisherCt(value="The Religious Tract Society")],
                )
            ],
        )

        osis_text = pyosis.OsisTextCt(
            lang="en",
            osis_idwork=OSIS_WORK_ID,
            osis_ref_work=BOOK_SHORT_TITLE,
            canonical=True,
            header=header,
            div=[book_div],
        )
        return pyosis.OsisXML(pyosis.Osis(osis_text=osis_text))

    def process(self) -> pyosis.OsisXML:
        """Run the full pipeline: fetch every text and plate page, parse and convert.

        Returns:
            The OSIS document.
        """
        numbers = {source.page: n for n, source in enumerate(CHAPTERS, start=1)}
        chapters = [
            self.parse_section(self.fetch_page_text(source), source, numbers.get(source.page, 0))
            for source in SECTIONS
        ]
        plates = [self.parse_plate(self.fetch_plate_text(page), page) for page in PLATE_PAGES]
        return self.generate_osis(chapters, plates)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register scraper-specific options; the Cave of Treasures has none.

    Args:
        parser: Sub-parser to extend (left unchanged).
    """


def run(args: argparse.Namespace) -> list[Path]:
    """Scrape the Cave of Treasures and write ``cave-of-treasures.xml``.

    Args:
        args: Parsed CLI arguments providing ``cache_dir``, ``delay`` and ``output_dir``.

    Returns:
        A one-element list with the written file's path.
    """
    parser = CaveOfTreasuresParser(cache_dir=args.cache_dir, delay=args.delay)
    try:
        osis_doc = parser.process()
        output_path = Path(args.output_dir) / OUTPUT_FILENAME
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(osis_doc.to_xml(), encoding="utf-8")
    finally:
        parser.close()
    return [output_path]


SPEC = ScraperSpec(
    name="cave-of-treasures",
    help="The Book of the Cave of Treasures (E. A. Wallis Budge, 1927) to OSIS",
    source=SOURCE_URL,
    outputs=(OUTPUT_FILENAME,),
    run=run,
    add_arguments=add_arguments,
)
"""Registry entry that exposes this scraper to the CLI."""
