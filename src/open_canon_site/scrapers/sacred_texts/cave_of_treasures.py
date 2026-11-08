"""Download and parse E. A. Wallis Budge's *The Book of the Cave of Treasures* to OSIS XML.

Source: ``https://sacred-texts.com/chr/bct/`` (now ``/book/the-book-of-the-cave-of-treasures``).
The pages are fetched from ``archive.sacred-texts.com``, which still serves the original
markup.

Reference scheme
----------------

The translation has no chapter or verse numbering of its own, so one is imposed. It is
deliberately simple and follows the divisions Budge prints:

* **Chapter** = one of the six numbered "ages" of the book, in source order: 1 The First
  Thousand Years (``bct04.htm``), 2 The Second Thousand Years, 3 The Third, 4 The Fourth,
  5 The Fifth, 6 The Five Hundred Years from the Second Year of Cyrus to the Birth of Christ
  (``bct09.htm``). Each is one source page.
* **Verse** = one paragraph of the translation, numbered consecutively from 1 within its
  chapter (``CaveOfTreasures.<chapter>.<verse>``). A row of a numbered list of names (the
  genealogies in chapter 6) is its own verse.
* **Sub-headings** (Budge's bracketed centred headings such as ``[The Creation. First Day.]``)
  are emitted as non-canonical ``<title type="sub">`` elements before the verses they
  introduce; they are not verses.
* **Page markers** (``p. 44``, the printed page of the 1927 edition) become ``<milestone
  type="page">`` elements inside the verse (or heading) in which they fall. Folio references
  to the Syriac manuscript (``[Fol. 3b, col. 1.]``) stay in the text as printed.
* **Budge's notes** (paragraphs opening ``[NOTES.``, his commentary rather than the
  translation) are emitted as non-canonical ``<div type="x-notes">`` blocks, in place and
  not numbered. His footnotes become inline ``<note>`` elements.

Left out: the title page, preface, introduction, contents and bibliography, the plates,
the "notes to the hypertext transcription", and the appendices (Testamentum Adami,
translations from the Book of the Bee, Abraham and the City of Ur), which are separate
works Budge appended. Tables that are not numbered lists (cuneiform and hieroglyph
renderings, the zodiac tables) are dropped because they are mostly images.
"""

from __future__ import annotations

import argparse
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Final

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
    """Where one chapter lives and how to recognise it."""

    page: str
    """Page stem on the archive host, e.g. ``bct04``."""
    title: str
    """Chapter title emitted as the OSIS chapter title."""
    marker: re.Pattern[str]
    """Pattern that must match the page text; guards against interstitials and wrong pages."""


CHAPTERS: Final[tuple[ChapterSource, ...]] = (
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
)
"""The six chapters in order; chapter ``n`` is ``CHAPTERS[n - 1]``."""

CHAPTER_HEADING_RE: Final[re.Pattern[str]] = re.compile(
    r"THOUSAND YEARS|FIVE HUNDRED YEARS FROM THE SECOND YEAR", re.IGNORECASE
)
"""Matches a heading that names the chapter itself, which is not repeated as a sub-heading."""
SKIPPED_HEADING_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:TRANSLATION|\(Brit\. Mus\.[^)]*\))$", re.IGNORECASE
)
"""Matches the manuscript running heads on the first page, which are dropped."""
NAVIGATION_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:(?:Sacred-Texts|Christianity|Index|Previous|Next)\s*)+$", re.IGNORECASE
)
"""Matches the site's own navigation paragraphs, which hold only nav link words."""
NOTES_RE: Final[re.Pattern[str]] = re.compile(r"^\[?\s*NOTES?\b")
"""Matches the start of one of Budge's commentary paragraphs."""
PAGE_ANCHOR_RE: Final[re.Pattern[str]] = re.compile(r"^page_(?P<page>[0-9ivxlcdm]+)$", re.I)
"""Matches the ``name`` of a printed-page anchor such as ``page_44``."""
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
class Block:
    """One block of a chapter in source order."""

    kind: str
    """``verse``, ``heading`` or ``notes``."""
    parts: list[InlinePart]
    """Inline content, including page milestones and footnote notes."""


@dataclass
class Chapter:
    """A parsed chapter page."""

    number: int
    """Chapter number (1 through 6)."""
    title: str
    """Chapter title."""
    blocks: list[Block] = field(default_factory=list)
    """Headings, verses and notes in source order."""


def _clean(parts: list[InlinePart]) -> list[InlinePart]:
    """Normalise whitespace in inline parts and trim the outer edges.

    Args:
        parts: Inline parts as built from the markup.

    Returns:
        Parts with whitespace runs collapsed, the first string left-trimmed, the last
        right-trimmed and empty strings removed.
    """
    merged = consolidate_inline_strings([
        re.sub(r"\s+", " ", p) if isinstance(p, str) else p for p in parts
    ])
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

    def fetch_page_text(self, source: ChapterSource) -> str:
        """Return the validated HTML of one chapter page, from cache or the network.

        An invalid cached copy is logged and deleted; an invalid fetched page also removes
        its cache entry.

        Args:
            source: Chapter to fetch.

        Returns:
            Raw HTML of the page.

        Raises:
            RuntimeError: If the fetched page is not the expected chapter.
        """
        url = PAGE_URL_TEMPLATE.format(page=source.page)
        cache_path = self.http.cache_path_for(url)
        if cache_path and cache_path.exists():
            cached = cache_path.read_text(encoding="utf-8")
            if self.is_valid_page(cached, source):
                return cached
            LOGGER.warning("Discarding invalid cached Cave of Treasures page at %s", cache_path)
            cache_path.unlink()

        fetched = self.http.fetch_text(url=url)
        if self.is_valid_page(fetched, source):
            return fetched
        if cache_path and cache_path.exists():
            cache_path.unlink()
        raise RuntimeError(
            f"Source page {source.page} did not contain {source.title!r}; direct access to "
            "sacred-texts.com may be blocked in this environment"
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
                elif not href.startswith("#"):
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
        for para in heading.find_next_siblings("p"):
            anchor = para.find("a", attrs={"name": re.compile(r"_note_\d+$")})
            back = para.find("a", attrs={"href": re.compile(r"^#")})
            if not anchor or not back:
                continue
            label = normalize_whitespace(back.get_text())
            key = anchor["name"]
            for tag in (anchor, back):
                tag.decompose()
            footnotes[key] = Footnote(label=label, parts=_clean(self.parse_inline(para, {})))
        return footnotes

    def _table_blocks(
        self, table: Tag, footnotes: dict[str, Footnote], pending: list[InlinePart]
    ) -> list[Block]:
        """Turn the rows of a numbered-list table into verses.

        Rows whose first cell is not a number (and tables with none) are skipped. A row that
        holds only a page marker is carried into ``pending``.

        Args:
            table: The ``<table>`` element.
            footnotes: Page footnotes.
            pending: Page milestones waiting for the next block; extended in place.

        Returns:
            One verse block per numbered row.
        """
        blocks: list[Block] = []
        for row in table.find_all("tr"):
            cells = row.find_all("td", recursive=False)
            parts = _clean(self.parse_inline(row, footnotes))
            if not _has_text(parts):
                pending.extend(p for p in parts if isinstance(p, pyosis.MilestoneCt))
                continue
            number = normalize_whitespace(cells[0].get_text()) if cells else ""
            if len(cells) >= 2 and LIST_NUMBER_RE.match(number):
                body = _clean(self.parse_inline(cells[1], footnotes))
                blocks.append(
                    Block("verse", [*pending, number + " ", *body] if body else [*pending])
                )
                pending.clear()
            else:
                LOGGER.debug("Skipping non-list table row: %s", number)
        return blocks

    def parse_chapter(self, html_text: str, number: int) -> Chapter:
        """Parse one chapter page.

        Args:
            html_text: Raw page HTML (old layout, or reader layout via ``legacy_html``).
            number: Chapter number, 1 through 6.

        Returns:
            The chapter with its headings, verses and notes in source order.
        """
        soup = BeautifulSoup(legacy_html(html_text), "html.parser")
        footnotes = self.parse_footnotes(soup)
        chapter = Chapter(number=number, title=CHAPTERS[number - 1].title)
        pending: list[InlinePart] = []
        body = soup.body or soup

        for element in body.find_all(["p", "blockquote", "table"], recursive=False):
            if element.find_parent("table") is not None:
                continue
            if element.name == "table":
                chapter.blocks.extend(self._table_blocks(element, footnotes, pending))
                continue
            footnote_start = element.find_previous_sibling("h3", string=re.compile("Footnotes"))
            if footnote_start is not None:
                break

            parts = _clean(self.parse_inline(element, footnotes))
            if not _has_text(parts):
                pending.extend(p for p in parts if isinstance(p, pyosis.MilestoneCt))
                continue
            text = _plain(parts)
            if NAVIGATION_RE.match(text) or SKIPPED_HEADING_RE.match(text):
                continue

            centred = element.get("align") == "center"
            if (centred or element.name == "blockquote") and CHAPTER_HEADING_RE.search(text):
                continue
            if element.name == "blockquote" or (centred and text.startswith("[")):
                if text.startswith("[") and isinstance(parts[0], str):
                    parts[0] = parts[0][1:].lstrip()
                if text.endswith("]") and isinstance(parts[-1], str):
                    parts[-1] = parts[-1][:-1].rstrip()
                kind = "heading"
            elif NOTES_RE.match(text):
                kind = "notes"
            else:
                kind = "verse"
            chapter.blocks.append(Block(kind, [*pending, *parts]))
            pending.clear()

        return chapter

    @staticmethod
    def _heading_content(parts: list[InlinePart]) -> list[InlinePart]:
        """Return heading parts without page milestones, which a title cannot hold.

        Args:
            parts: Inline parts of a heading.

        Returns:
            The parts minus milestones.
        """
        return [p for p in parts if not isinstance(p, pyosis.MilestoneCt)]

    def generate_osis(self, chapters: list[Chapter]) -> pyosis.OsisXML:
        """Build the OSIS document for the book.

        Args:
            chapters: Chapters in order.

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
            chapter_div = pyosis.DivCt(
                type_value=pyosis.OsisDivs.CHAPTER,
                osis_id=[f"{OSIS_WORK_ID}.{chapter.number}"],
                canonical=True,
                content=[
                    pyosis.TitleCt(
                        type_value=pyosis.OsisTitles.CHAPTER,
                        canonical=False,
                        content=[chapter.title],
                    )
                ],
            )
            verse_number = 0
            for block in chapter.blocks:
                if block.kind == "heading":
                    chapter_div.content.append(
                        pyosis.TitleCt(
                            type_value=pyosis.OsisTitles.SUB,
                            canonical=False,
                            content=self._heading_content(block.parts),
                        )
                    )
                elif block.kind == "notes":
                    chapter_div.content.append(
                        pyosis.DivCt(
                            type_value="x-notes",
                            canonical=False,
                            content=[pyosis.PCt(content=block.parts)],
                        )
                    )
                else:
                    verse_number += 1
                    chapter_div.content.append(
                        pyosis.VerseCt(
                            osis_id=[f"{OSIS_WORK_ID}.{chapter.number}.{verse_number}"],
                            canonical=True,
                            content=block.parts,
                        )
                    )
            book_div.content.append(chapter_div)

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
        """Run the full pipeline: fetch every chapter page, parse and convert.

        Returns:
            The OSIS document.
        """
        chapters = [
            self.parse_chapter(self.fetch_page_text(source), number)
            for number, source in enumerate(CHAPTERS, start=1)
        ]
        return self.generate_osis(chapters)


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
