"""Download and parse M. R. James's *The Biblical Antiquities of Philo* to OSIS XML."""

from __future__ import annotations

import argparse
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Final

import pyosis
from bs4 import BeautifulSoup, NavigableString, Tag
from tqdm import tqdm

from open_canon_site.scrapers._osis import (
    InlinePart,
    normalize_whitespace,
    roman_to_int,
)
from open_canon_site.scrapers.base import ScraperSpec
from open_canon_site.scrapers.sacred_texts._layout import legacy_html
from open_canon_site.scrapers.sacred_texts.jubilees import JubileesParser

LOGGER = logging.getLogger(__name__)
"""Module logger; warns when an invalid cached page is discarded."""

OUTPUT_FILENAME: Final[str] = "pseudo-philo.xml"
"""Name of the OSIS file written into the output directory."""

BASE_URL: Final[str] = "https://archive.sacred-texts.com/bib/bap/"
"""Directory URL of the book on the sacred-texts.com archive host; pages are ``bap<NN>.htm``.

The archive host still serves the original page layout, whose footnotes are complete.
"""
TITLE_PAGE: Final[int] = 0
"""Page number of the title page (``bap00``)."""
INTRODUCTION_PAGES: Final[range] = range(2, 17)
"""Page numbers of James's introduction and notes (``bap02`` .. ``bap16``).

``bap01`` is only the printed table of contents, so it is not scraped.
"""
FRONT_MATTER_TITLES: Final[dict[int, str]] = {
    2: "Introduction: 1. General",
    3: "Introduction: 2. History of the Book",
    4: "Introduction: 3. Authorities for the Text",
    5: "Introduction: 4. Title, and Attribution to Philo",
    6: "Introduction: 5. Original Language",
    7: "Introduction: 6. Date",
    8: "Introduction: 7. Form",
    9: "Introduction: 8. Purpose",
    10: "Introduction: 9. Unity. Contents",
    11: "Introduction: 10. Relation to Other Literature",
    12: "Introduction: 11. Extent of the Complete Book: The Lost Conclusion Discussed",
    13: "Introduction: 12. Conclusion. Character of the Present Edition",
    14: "Introduction: 13. Synopsis of the Contents",
    15: "Additional Note",
    16: "Note",
}
"""Section title for each introduction page, as named on the site's index page."""
CHAPTER_PAGES: Final[range] = range(17, 80)
"""Page numbers holding the translation (``bap17`` .. ``bap79``); one page per chapter, except
that a few pages also carry the following chapter (see :data:`EXPECTED_CHAPTERS`).
"""
EXPECTED_CHAPTERS: Final[list[int]] = list(range(1, 66))
"""The chapters the pages must yield, in order (1 through 65).

James's text has 65 chapters, but the site has no page for chapters 43 and 47: each is
printed on the page of the chapter before it (``bap58`` and ``bap61``).
"""
OSIS_WORK_ID: Final[str] = "PsPhilo"
"""OSIS work identifier, also the book id prefix (``PsPhilo.<chapter>.<verse>``).

OSIS has no registered abbreviation for Pseudo-Philo, so this is a custom id.
"""
BOOK_TITLE: Final[str] = "The Biblical Antiquities of Philo"
"""Full title of the book."""
BOOK_SHORT_TITLE: Final[str] = "Pseudo-Philo"
"""Short title used for the OSIS main title and ``osisRefWork``."""

CHAPTER_HEADING_RE: Final[re.Pattern[str]] = re.compile(
    r"^CHAPTER\s+(?P<chapter>[IVXLC]+)\.?$", re.IGNORECASE
)
"""Matches a page's chapter heading (``CHAPTER XLII.``), capturing the Roman numeral."""
CHAPTER_MARKER_RE: Final[re.Pattern[str]] = re.compile(r"^(?P<roman>[IVXLC]+)\.?\s+")
"""Matches the Roman numeral that opens a chapter's first verse (``XLIII. And it ...``).

The period is sometimes missing (``XXIX And``).
"""
INLINE_BEFORE_PARAGRAPH_RE: Final[re.Pattern[str]] = re.compile(r"(?i)(<[ib]>)\s*<p>")
"""Matches an emphasis tag opened just before a ``<P>`` (``<I><P>and Sella``).

A page break splits an italic passage this way. The parser would close the paragraph at the
``</I>`` and lose the text after it, so the tags are swapped to ``<P><I>`` first.
"""
REFERENCE_START: Final[str] = "\ue000"
"""Private-use character that opens a margin reference left in the text by ``_body``."""
REFERENCE_END: Final[str] = "\ue001"
"""Private-use character that closes a margin reference left in the text by ``_body``."""
REFERENCE_RE: Final[re.Pattern[str]] = re.compile(f"{REFERENCE_START}(.*?){REFERENCE_END}")
"""Matches a margin reference placeholder, capturing the reference text (``Gen. 5:4``)."""
HEADING_TAGS: Final[tuple[str, ...]] = ("h1", "h2", "h3", "h4", "h5", "h6")
"""Heading tag names."""


def verse_marker_re(verse: int) -> re.Pattern[str]:
    """Build the pattern for the marker that opens ``verse`` inside a text string.

    The marker must start the string or follow whitespace. The usual form is ``7. `` but the
    source also prints ``3, `` and, before a capital letter, ``4 `` with no punctuation. A
    marker may end a string when a footnote reference follows it.

    Args:
        verse: Verse number being looked for.

    Returns:
        A compiled pattern matching the marker and the whitespace after it.
    """
    return re.compile(rf"(?<![^\s]){verse}(?:[.,]\s*|\s+(?=[A-Z(\[<“\"']))")


Atom = tuple["str | pyosis.NoteCt | pyosis.HiCt | pyosis.MilestoneCt", "pyosis.OsisHi | None"]
"""A string or note with the highlight type it sits in (``None`` outside any highlight)."""


@dataclass
class Verse:
    """A single verse of a chapter."""

    number: int
    """1-based verse number within its chapter."""
    parts: list[InlinePart]
    """Inline OSIS parts: strings, italic highlights and footnote notes."""


@dataclass
class Chapter:
    """A parsed chapter."""

    number: int
    """Chapter number (1 through 65)."""
    page_number: int
    """Source page the chapter starts on."""
    verses: list[Verse] = field(default_factory=list)
    """Verses in source order; numbered consecutively from 1."""


@dataclass
class FrontMatterSection:
    """A front-matter page: the title page or a section of James's introduction."""

    page_number: int
    """Source page number."""
    title: str
    """Section title, rendered as the OSIS main title."""
    div_type: pyosis.OsisDivs
    """``titlePage`` for the title page, ``front`` otherwise."""
    paragraphs: list[list[InlinePart]]
    """Paragraphs as inline OSIS parts, in document order."""


class PseudoPhiloParser(JubileesParser):
    """Fetch and parse sacred-texts.com's Biblical Antiquities of Philo into OSIS.

    It reuses the inline markup and footnote handling of ``JubileesParser``, as both books are
    typeset the same way on the archive host: a ``fr_N`` anchor followed by a ``#fn_N`` link in
    the text and the notes after a ``Footnotes`` heading.

    The translation is one chapter per page (``bap17``..``bap79``) headed ``CHAPTER XII.``.
    Verse numbers run on inside the text (``... 2. And Adam ...``), and paragraphs break at
    printed page boundaries, so the verses are found by scanning for the next expected number
    rather than by paragraph. A chapter's first verse carries the chapter's Roman numeral
    instead of ``1.``, which is also how the two chapters sharing a page with another are told
    apart. Biblical cross-references printed in the margin (right-aligned tables) become
    ``crossReference`` notes at the point where they are printed.
    """

    def __init__(self, cache_dir: str | None = None, delay: float = 1.0) -> None:
        """Create a parser with a caching HTTP fetcher.

        Args:
            cache_dir: Directory for cached pages, or ``None`` to disable caching.
            delay: Seconds to wait around each live request.
        """
        super().__init__(cache_dir=cache_dir, delay=delay)

    @staticmethod
    def page_url(page_number: int | str) -> str:
        """Build the URL of a page.

        Args:
            page_number: Page number (zero-padded to two digits) or ``"index"``.

        Returns:
            ``BASE_URL`` plus ``bap<NN>.htm`` (or ``index.htm``).
        """
        if page_number == "index":
            return f"{BASE_URL}index.htm"
        return f"{BASE_URL}bap{int(page_number):02d}.htm"

    @staticmethod
    def is_valid_page(text: str) -> bool:
        """Report whether text is a genuine original-site page of this book.

        Args:
            text: Raw page text.

        Returns:
            True if it mentions the book, contains an ``<html`` tag and is neither a
            Cloudflare interstitial nor mirror-derived Markdown.
        """
        return (
            "Philo" in text
            and "Just a moment" not in text
            and "Markdown Content:" not in text
            and "<html" in text.lower()
        )

    def fetch_page(
        self,
        page_number: int | str,
        retry_count: int = 3,
        delay: float | None = None,
    ) -> str:
        """Return the validated HTML of a page, from cache or the network.

        An invalid cached copy is logged and deleted, and an invalid fetched page also
        removes its cache entry.

        Args:
            page_number: Page number, or ``"index"`` for the book's index page.
            retry_count: Attempts the fetcher makes on transient errors.
            delay: If given and different from the fetcher's, replaces the request delay.

        Returns:
            Raw page HTML.

        Raises:
            RuntimeError: If the fetched page fails validation.
        """
        url = self.page_url(page_number)
        cache_path = self.http.cache_path_for(url)

        if delay is not None and delay != self.http.delay:
            self.delay = delay
            self.http.delay = delay

        if cache_path and cache_path.exists():
            cached = cache_path.read_text(encoding="utf-8")
            if self.is_valid_page(cached):
                return cached

            LOGGER.warning("Discarding invalid cached Pseudo-Philo source at %s", cache_path)
            cache_path.unlink()

        fetched = self.http.fetch_text(url=url, retry_count=retry_count)
        if self.is_valid_page(fetched):
            return fetched

        if cache_path and cache_path.exists():
            cache_path.unlink()

        raise RuntimeError(
            f"Source page {url} did not contain the Biblical Antiquities of Philo; "
            "direct access to sacred-texts.com may be blocked in this environment"
        )

    @staticmethod
    def extract_chapter_pages(raw_index_html: str) -> list[int]:
        """List the ``bap<NN>.htm`` pages linked from the index page.

        Args:
            raw_index_html: Raw index page HTML.

        Returns:
            Page numbers in order of first appearance.
        """
        pages: list[int] = []
        for match in re.finditer(r'href="bap(\d+)\.htm"', raw_index_html, re.IGNORECASE):
            number = int(match.group(1))
            if number not in pages:
                pages.append(number)
        return pages

    def _content_elements(self, body: Tag, *, stop_at: str | None) -> list[Tag]:
        """Return the content paragraphs and headings of a page, in order.

        The page navigation before the first ``<hr>`` is skipped. Collection ends at the next
        ``<hr>`` (the footer) or at a heading whose text is ``stop_at``. Paragraphs inside
        tables (margin references) and the empty ``<p>`` that wraps an ``<hr>`` are skipped.

        Args:
            body: The page body.
            stop_at: Heading text that ends the content early, or ``None``.

        Returns:
            Heading and paragraph tags.
        """
        elements: list[Tag] = []
        started = False
        for element in body.find_all([*HEADING_TAGS, "p", "hr"]):
            if element.name == "hr":
                if started:
                    break
                started = True
                continue
            if not started:
                continue
            if element.name in HEADING_TAGS and stop_at is not None:
                if normalize_whitespace(element.get_text(" ", strip=True)) == stop_at:
                    break
            if element.find_parent("table") is not None or element.find("hr") is not None:
                continue
            elements.append(element)
        return elements

    def parse_front_matter_page(  # type: ignore[override]
        self, page_number: int, raw_text: str
    ) -> FrontMatterSection:
        """Parse the title page or one introduction page.

        Page-number markers are dropped, and the headings of an introduction page are replaced by the title from ``FRONT_MATTER_TITLES``. A paragraph that begins where the page break cut the
        previous one (the previous paragraph does not end in sentence punctuation) is merged
        into it. The title page keeps its headings as paragraphs.

        Args:
            page_number: Page number (``0`` or ``2`` through ``16``).
            raw_text: Raw page HTML.

        Returns:
            The section.

        Raises:
            RuntimeError: If the page is not a valid page of the book.
        """
        if not self.is_valid_page(raw_text):
            raise RuntimeError(f"bap{page_number:02d} is not a page of the book")

        body = self._body(raw_text)
        footnotes = self.extract_footnotes(body)
        headings: list[str] = []
        paragraphs: list[list[InlinePart]] = []
        previous_text = ""
        after_marker = False

        for element in self._content_elements(body, stop_at="Footnotes"):
            if element.name in HEADING_TAGS:
                heading = normalize_whitespace(element.get_text(" ", strip=True))
                if heading:
                    headings.append(heading)
                continue

            if element.find("a", attrs={"name": re.compile(r"^page_")}):
                after_marker = True
                continue

            parts = self.trim_parts(
                self._expand_references(self.parse_inline_content(element, footnotes))
            )
            text = normalize_whitespace(self.extract_text_without_notes(parts))
            if not text:
                continue

            if (
                after_marker
                and paragraphs
                and previous_text
                and not previous_text.endswith((".", "!", "?", ":", ";", '"', ")", "”"))
            ):
                paragraphs[-1] = self.consolidate_parts([*paragraphs[-1], " ", *parts])
                previous_text = normalize_whitespace(f"{previous_text} {text}")
            else:
                paragraphs.append(parts)
                previous_text = text
            after_marker = False

        if page_number == TITLE_PAGE:
            title = BOOK_TITLE
            paragraphs = [[heading] for heading in headings] + paragraphs
            div_type = pyosis.OsisDivs.TITLE_PAGE
        else:
            title = FRONT_MATTER_TITLES[page_number]
            div_type = pyosis.OsisDivs.FRONT

        return FrontMatterSection(
            page_number=page_number, title=title, div_type=div_type, paragraphs=paragraphs
        )

    @staticmethod
    def _body(raw_text: str) -> Tag:
        """Parse a page (in either site layout) and return its body.

        An emphasis tag opened just before a ``<P>`` is moved inside it first (see
        ``INLINE_BEFORE_PARAGRAPH_RE``). Each right-aligned margin table (a Bible
        cross-reference) is replaced by its text between ``REFERENCE_START`` and
        ``REFERENCE_END``, which ``_split_references`` later turns into a note.

        Args:
            raw_text: Raw page HTML.

        Returns:
            The ``<body>`` tag (or the soup when there is none).
        """
        html = INLINE_BEFORE_PARAGRAPH_RE.sub(r"<P>\g<1>", legacy_html(raw_text))
        soup = BeautifulSoup(html, "html.parser")
        for table in soup.find_all("table", attrs={"align": re.compile("^right$", re.I)}):
            reference = normalize_whitespace(table.get_text(" ", strip=True))
            table.replace_with(
                NavigableString(f"{REFERENCE_START}{reference}{REFERENCE_END}" if reference else "")
            )
        return soup.body if soup.body else soup

    @staticmethod
    def _split_references(text: str) -> list[InlinePart]:
        """Split a string at margin reference placeholders, turning each into a note.

        Args:
            text: A string that may contain ``REFERENCE_START`` .. ``REFERENCE_END`` runs.

        Returns:
            Strings and ``crossReference`` notes in order; empty strings are dropped.
        """
        result: list[InlinePart] = []
        position = 0
        for match in REFERENCE_RE.finditer(text):
            if match.start() > position:
                result.append(text[position : match.start()])
            result.append(pyosis.NoteCt(type_value="crossReference", content=[match.group(1)]))
            position = match.end()
        if position < len(text):
            result.append(text[position:])
        return result

    def _expand_references(self, parts: list[InlinePart]) -> list[InlinePart]:
        """Turn margin reference placeholders in strings (and highlights) into notes.

        Args:
            parts: Inline parts.

        Returns:
            Parts with every placeholder replaced by a ``crossReference`` note.
        """
        result: list[InlinePart] = []
        for part in parts:
            if isinstance(part, str):
                result.extend(self._split_references(part))
            elif isinstance(part, pyosis.HiCt):
                part.content = self._expand_references(part.content)
                result.append(part)
            else:
                result.append(part)
        return self.consolidate_parts(result)

    @staticmethod
    def _clean_string(text: str) -> str:
        """Collapse every whitespace run (including non-breaking spaces) to one space.

        Args:
            text: A text string.

        Returns:
            The text with each whitespace run replaced by a single plain space.
        """
        return re.sub(r"\s+", " ", text)

    def _atoms(self, parts: list[InlinePart]) -> list[Atom]:
        """Flatten inline parts so verse markers inside highlights can be found.

        Highlights are replaced by their strings, each tagged with the highlight's type (the
        innermost one for nested highlights); notes are kept whole.

        Args:
            parts: Inline parts of a paragraph.

        Returns:
            ``(string or note, highlight type or None)`` pairs in order.
        """
        atoms: list[Atom] = []
        for part in parts:
            if isinstance(part, str):
                atoms.append((part, None))
            elif isinstance(part, pyosis.HiCt):
                style = part.type_value
                for inner, inner_style in self._atoms(part.content):
                    atoms.append((inner, inner_style or style))
            else:
                atoms.append((part, None))
        return atoms

    def _regroup(self, atoms: list[Atom]) -> list[InlinePart]:
        """Rebuild inline parts from atoms, wrapping runs of one style in a highlight.

        Args:
            atoms: ``(string or note, highlight type or None)`` pairs.

        Returns:
            Consolidated inline parts.
        """
        result: list[InlinePart] = []
        run: list[InlinePart] = []
        run_style = None

        def close_run() -> None:
            """Move the pending run into ``result``, wrapped when it has a style."""
            if not run:
                return
            if run_style is None:
                result.extend(run)
            else:
                result.append(
                    pyosis.HiCt(type_value=run_style, content=self.consolidate_parts(run))
                )

        previous_space = True
        for item, style in atoms:
            if isinstance(item, str):
                if previous_space:
                    item = item.lstrip()
                if not item:
                    continue
                previous_space = item[-1].isspace()
            if style != run_style:
                close_run()
                run = []
                run_style = style
            run.append(item)
        close_run()
        if result and isinstance(result[-1], pyosis.HiCt):
            result[-1].content = self.trim_parts(result[-1].content)
        return self.consolidate_parts(result)

    def parse_chapter_page(self, page_number: int, raw_text: str) -> list[Chapter]:
        """Parse a chapter page into one or more chapters.

        The heading names the page's first chapter. Paragraphs are scanned in order; a
        paragraph that opens with the Roman numeral of the next chapter starts that chapter
        (this is how ``bap58`` and ``bap61`` carry chapters 43 and 47), and the next
        expected verse number starts each new verse wherever it appears in a paragraph.
        Text before the next marker, including a paragraph cut by a page break, belongs to the
        current verse.

        Args:
            page_number: Page number (``17`` through ``79``).
            raw_text: Raw page HTML.

        Returns:
            The chapters on the page, each with consecutively numbered verses.

        Raises:
            RuntimeError: If the page is invalid, has no chapter heading, a chapter has no
                verses, or text appears before the chapter's opening marker.
        """
        if not self.is_valid_page(raw_text):
            raise RuntimeError(f"bap{page_number:02d} is not a page of the book")

        body = self._body(raw_text)
        footnotes = self.extract_footnotes(body)
        elements = self._content_elements(body, stop_at="Footnotes")

        first_chapter: int | None = None
        chapters: list[Chapter] = []
        current: Chapter | None = None
        verse_parts: list[Atom] = []
        verse_number = 0

        def flush_verse() -> None:
            """Close the verse being collected and add it to the current chapter.

            Raises:
                RuntimeError: If the verse has no text.
            """
            nonlocal verse_parts
            if current is None or verse_number == 0:
                return
            parts = self.trim_parts(self._regroup(verse_parts))
            if not normalize_whitespace(self.extract_text_without_notes(parts)):
                raise RuntimeError(
                    f"Empty verse {current.number}:{verse_number} on bap{page_number:02d}"
                )
            current.verses.append(Verse(number=verse_number, parts=parts))
            verse_parts = []

        for element in elements:
            if element.name in HEADING_TAGS:
                heading = normalize_whitespace(element.get_text(" ", strip=True))
                match = CHAPTER_HEADING_RE.match(heading)
                if match and first_chapter is None:
                    first_chapter = roman_to_int(match.group("chapter").upper())
                continue

            if first_chapter is None:
                continue

            parts = self.consolidate_parts([
                self._clean_string(part) if isinstance(part, str) else part
                for part in self.parse_inline_content(element, footnotes)
            ])
            if not normalize_whitespace(self.extract_text_without_notes(parts)):
                continue

            scanned: list[Atom] = []
            leading: list[Atom] = []
            at_paragraph_start = True
            for part, style in self._atoms(self._expand_references(parts)):
                if at_paragraph_start and (
                    isinstance(part, pyosis.NoteCt) or (isinstance(part, str) and not part.strip())
                ):
                    # A margin reference printed before the paragraph's first word: it
                    # belongs with that word, which may open a new chapter.
                    leading.append((part, style))
                    continue
                if not isinstance(part, str):
                    scanned.extend(leading)
                    leading = []
                    scanned.append((part, style))
                    at_paragraph_start = False
                    continue

                text = part
                while text:
                    chapter_start = None
                    if at_paragraph_start:
                        stripped = text.lstrip()
                        marker = CHAPTER_MARKER_RE.match(stripped)
                        wanted = first_chapter if current is None else current.number + 1
                        if marker and roman_to_int(marker.group("roman")) == wanted:
                            chapter_start = (wanted, len(text) - len(stripped) + marker.end())
                    if chapter_start is not None:
                        flush_verse()
                        number, end = chapter_start
                        current = Chapter(number=number, page_number=page_number)
                        chapters.append(current)
                        verse_number = 1
                        verse_parts.extend(leading)
                        leading = []
                        text = text[end:]
                        at_paragraph_start = False
                        continue

                    at_paragraph_start = False
                    scanned.extend(leading)
                    leading = []
                    if current is None:
                        raise RuntimeError(
                            f"Text before the opening chapter marker on bap{page_number:02d}: "
                            f"{text[:60]!r}"
                        )

                    search = verse_marker_re(verse_number + 1)
                    match_ = search.search(text)
                    if match_ is None:
                        scanned.append((text, style))
                        text = ""
                        continue

                    scanned.append((text[: match_.start()], style))
                    verse_parts.extend(scanned)
                    scanned = []
                    flush_verse()
                    verse_number += 1
                    text = text[match_.end() :]

            verse_parts.extend(scanned)
            verse_parts.extend(leading)
            verse_parts.append((" ", None))

        flush_verse()

        if first_chapter is None:
            raise RuntimeError(f"No chapter heading found on bap{page_number:02d}")
        for chapter in chapters:
            if not chapter.verses:
                raise RuntimeError(f"No verses parsed for chapter {chapter.number}")
        if not chapters:
            raise RuntimeError(f"No chapter text found on bap{page_number:02d}")
        return chapters

    @staticmethod
    def generate_osis(
        front_matter: list[FrontMatterSection], chapters: list[Chapter]
    ) -> pyosis.OsisXML:
        """Build the OSIS document for the book.

        Args:
            front_matter: Title page and introduction sections.
            chapters: Parsed chapters in order.

        Returns:
            An OSIS document with front matter divs, one canonical chapter div per chapter
            and verse ids ``PsPhilo.<chapter>.<verse>``.
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

        for section in front_matter:
            book_div.content.append(
                pyosis.DivCt(
                    type_value=section.div_type,
                    canonical=False,
                    content=[
                        pyosis.TitleCt(
                            type_value=pyosis.OsisTitles.MAIN,
                            canonical=False,
                            content=[section.title],
                        ),
                        *[pyosis.PCt(content=paragraph) for paragraph in section.paragraphs],
                    ],
                )
            )

        for chapter in chapters:
            book_div.content.append(
                pyosis.DivCt(
                    type_value=pyosis.OsisDivs.CHAPTER,
                    osis_id=[f"{OSIS_WORK_ID}.{chapter.number}"],
                    canonical=True,
                    content=[
                        pyosis.VerseCt(
                            osis_id=[f"{OSIS_WORK_ID}.{chapter.number}.{verse.number}"],
                            canonical=True,
                            content=verse.parts,
                        )
                        for verse in chapter.verses
                    ],
                )
            )

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
                                "Scraped from https://sacred-texts.com/bib/bap/ and converted to OSIS by Andrew P. Sansom."
                            ]
                        )
                    ],
                ),
                pyosis.RevisionDescCt(
                    date=pyosis.DateCt(
                        event=pyosis.OsisEvents.EDITION,
                        type_value="ISO",
                        lang="en",
                        content=["1917"],
                    ),
                    p=[
                        pyosis.PCt(
                            content=[
                                "The Biblical Antiquities of Philo, now first translated from the Old Latin version by M. R. James, S.P.C.K., London, 1917."
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
                            value="The Biblical Antiquities of Philo (Pseudo-Philo, Liber Antiquitatum Biblicarum), translated from the Old Latin by M. R. James, 1917. Transcribed at sacred-texts.com and converted to OSIS by the open-canon-site scrapers."
                        )
                    ],
                    type_value=[pyosis.TypeCt(type_value="OSIS", content=["Bible"])],
                    creator=[pyosis.CreatorCt(role=pyosis.OsisRoles.TRL, value="M. R. James")],
                    publisher=[
                        pyosis.PublisherCt(value="Society for Promoting Christian Knowledge")
                    ],
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
        """Run the full pipeline: fetch, validate, parse and convert every page.

        Returns:
            The OSIS document.

        Raises:
            RuntimeError: If the index does not link the expected pages, or the chapters
                found are not exactly 1 through 65, or any page fails validation or parsing.
        """
        index_text = self.fetch_page("index")
        linked = self.extract_chapter_pages(index_text)
        expected_pages = [TITLE_PAGE, 1, *INTRODUCTION_PAGES, *CHAPTER_PAGES]
        if linked != expected_pages:
            raise RuntimeError(
                f"Unexpected Biblical Antiquities page list: expected {expected_pages}, got {linked}"
            )

        front_matter = [
            self.parse_front_matter_page(number, self.fetch_page(number))
            for number in tqdm([TITLE_PAGE, *INTRODUCTION_PAGES], desc="Front matter", unit="page")
        ]

        chapters: list[Chapter] = []
        for number in tqdm(CHAPTER_PAGES, desc="Chapters", unit="page"):
            chapters.extend(self.parse_chapter_page(number, self.fetch_page(number)))

        numbers = [chapter.number for chapter in chapters]
        if numbers != EXPECTED_CHAPTERS:
            raise RuntimeError(
                f"Unexpected Biblical Antiquities chapter sequence: expected {EXPECTED_CHAPTERS}, got {numbers}"
            )
        for chapter in chapters:
            actual = [verse.number for verse in chapter.verses]
            if actual != list(range(1, len(actual) + 1)):
                raise RuntimeError(f"Chapter {chapter.number} verse numbers are not 1..N: {actual}")

        return self.generate_osis(front_matter, chapters)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register scraper-specific options; this scraper has none.

    Args:
        parser: Sub-parser to extend (left unchanged).
    """


def run(args: argparse.Namespace) -> list[Path]:
    """Scrape the book and write ``pseudo-philo.xml``.

    Args:
        args: Parsed CLI arguments providing ``cache_dir``, ``delay`` and ``output_dir``.

    Returns:
        A one-element list with the written file's path.
    """
    parser = PseudoPhiloParser(cache_dir=args.cache_dir, delay=args.delay)
    try:
        osis_doc = parser.process()
        output_path = Path(args.output_dir) / OUTPUT_FILENAME
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(osis_doc.to_xml(), encoding="utf-8")
    finally:
        parser.close()
    return [output_path]


SPEC = ScraperSpec(
    name="pseudo-philo",
    help="Biblical Antiquities of Philo (M. R. James, 1917) to OSIS",
    source="https://archive.sacred-texts.com/bib/bap/",
    outputs=(OUTPUT_FILENAME,),
    run=run,
    add_arguments=add_arguments,
)
"""Registry entry that exposes this scraper to the CLI."""
