"""Download and parse Jubilees to OSIS XML."""

from __future__ import annotations

import argparse
import copy
import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

import pyosis
from bs4 import BeautifulSoup, NavigableString, Tag
from tqdm import tqdm

from open_canon_site.scrapers._http import CachedHttpFetcher
from open_canon_site.scrapers._osis import (
    InlinePart,
    consolidate_inline_strings,
    normalize_whitespace,
    roman_to_int,
)
from open_canon_site.scrapers.base import ScraperSpec

LOGGER = logging.getLogger(__name__)
"""Module logger; warns when an invalid cached page is discarded."""

OUTPUT_FILENAME: Final[str] = "jubilees.xml"
"""Name of the OSIS file written into the output directory."""

BASE_URL: Final[str] = "https://sacred-texts.com/bib/jub/"
"""Directory URL of the book on sacred-texts.com; pages are ``jub<NN>.htm`` beneath it."""
PAGE_RANGE: Final[tuple[int, int]] = (0, 87)
"""Inclusive ``(first, last)`` page numbers of the book (``jub00`` .. ``jub87``)."""
FRONT_MATTER_END_PAGE: Final[int] = 11
"""Last page number that is front matter (title page through prologue)."""
CONTENT_START_PAGE: Final[int] = 12
"""First page number holding chapter text; each later page is one section."""
OSIS_WORK_ID: Final[str] = "Jub"
"""OSIS work identifier, also the book id prefix (``Jub.<chapter>.<verse>``)."""
BOOK_TITLE: Final[str] = "The Book of Jubilees"
"""Full title of the book."""
BOOK_SHORT_TITLE: Final[str] = "Jubilees"
"""Short title used for the OSIS main title and ``osisRefWork``."""
FRONT_MATTER_TITLES: Final[dict[int, str]] = {
    0: "Title Page",
    1: "Editors' Preface",
    2: "Introduction: Short Account of the Book",
    3: "Introduction: Titles",
    4: "Introduction: Versions and Original Language",
    5: "Introduction: Affinities with Other Literature",
    6: "Introduction: The Special Aims and General Character of the Book",
    7: "Introduction: Authorship and Date",
    8: "Introduction: Bibliography",
    9: "Short Titles, Abbreviations and Brackets Used in this Edition",
    10: "Erratum",
    11: "Prologue",
}
"""Section title for each front-matter page number (0 through 11)."""

MARKDOWN_LINK_RE: Final[re.Pattern[str]] = re.compile(r"\[([^\]]*)\]\([^)]*\)")
"""Matches a Markdown link ``[text](url)``; the text is captured in group 1 (mirror-derived text)."""
MARKDOWN_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^#+\s+")
"""Matches leading Markdown heading markers (``#`` characters and following space)."""
HEADING_CHAPTER_RE: Final[re.Pattern[str]] = re.compile(
    r"\((?P<chapter>[ivxlcdm]+)\.", re.IGNORECASE
)
"""Matches the opening of a section heading's chapter reference, e.g. ``(xii.`` in
``Jubilees 12:1-15 (xii. 1-15)``, capturing the lower-case Roman numeral as ``chapter``.
"""
RANGE_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\((?P<chapter>[ivxlcdm]+)\..*\)\.?$", re.IGNORECASE
)
"""Matches a whole paragraph that is only a chapter/verse range such as ``(i. 1-4).``,
capturing the Roman numeral as ``chapter``. The page's first line may be one of these.
"""
CHAPTER_LINE_RE: Final[re.Pattern[str]] = re.compile(r"^(?P<chapter>[IVXLCDM]+)\.\s+(?P<text>.+)$")
"""Matches a paragraph starting with an upper-case Roman chapter numeral and a period,
e.g. ``II. And the angel ...`` (``chapter`` and ``text`` groups).

The numeral stands in for verse 1's own number.
"""
VERSE_LINE_RE: Final[re.Pattern[str]] = re.compile(r"^(?P<verse>\d+)\.\s+(?P<text>.+)$")
"""Matches a paragraph starting with ``<digits>. `` (``verse`` and ``text`` groups)."""
INLINE_VERSE_RE: Final[re.Pattern[str]] = re.compile(r"(?:(?<=^)|(?<=\s))(?P<verse>\d+)\.\s+")
"""Matches an inline verse marker ``<digits>. `` that sits at the start of a string or after
whitespace, capturing the number as ``verse``; verses run on within one paragraph.
"""
JOIN_WITH_PREVIOUS_PREFIXES: Final[tuple[str, ...]] = (
    "and ",
    "or ",
    "but ",
    "for ",
    "that ",
    "which ",
    "who ",
    "whom ",
    "whose ",
    "when ",
    "where ",
    "while ",
    "to ",
    "of ",
    "in ",
    "on ",
    "at ",
)
"""Lower-case word prefixes (with trailing space) that show a paragraph continues the previous one."""


@dataclass
class VerseBlock:
    """One verse (or verse group) with inline markup preserved."""

    verse_numbers: list[int]
    """Verse numbers covered by this block (a single number in current output)."""
    content_parts: list[InlinePart]
    """Inline OSIS parts: strings, highlights and footnote notes."""


@dataclass
class FootnoteInfo:
    """A footnote collected from the page's ``Footnotes`` section."""

    ref_id: str
    """Anchor name of the footnote target (``fn_<n>``)."""
    label: str
    """Footnote label shown to readers, taken from the sibling anchor text."""
    content_parts: list[InlinePart]
    """Inline OSIS parts of the footnote body."""


@dataclass
class PageParagraph:
    """One paragraph of a page, as plain text plus inline markup."""

    text: str
    """Plain text with footnotes dropped and whitespace normalised."""
    content_parts: list[InlinePart]
    """Inline OSIS parts for the same paragraph (including notes)."""


@dataclass
class FrontMatterSection:
    """A front-matter page of the book."""

    page_number: int
    """Source page number (0 through 11)."""
    title: str
    """Section title from ``FRONT_MATTER_TITLES``."""
    paragraphs: list[PageParagraph]
    """Paragraphs after merging fragments and removing duplicated title lines."""


@dataclass
class Section:
    """One content page: a titled run of verses within a chapter."""

    page_number: int
    """Source page number (12 through 87)."""
    title: str
    """Section heading, such as ``Jubilees 1:1-4 (i. 1-4)``."""
    chapter_number: int
    """Chapter this section belongs to."""
    verses: list[VerseBlock]
    """Verses of the section in order."""


@dataclass
class Chapter:
    """A chapter assembled from one or more sections."""

    number: int
    """Chapter number (1 through 50)."""
    sections: list[Section]
    """Sections (source pages) of the chapter in page order."""


class JubileesParser:
    """Fetch and parse R. H. Charles's Jubilees from sacred-texts.com into OSIS.

    The book is a series of pages ``jub00``..``jub87``. Pages 0-11 are front matter; each
    later page is a section with a heading (any ``<h1>``..``<h6>``) such as
    ``Jubilees 12:1-15 (xii. 1-15)``, then paragraphs where verses run on inline as
    ``1. text 2. text``. A chapter may span several pages and a page's first paragraph may
    be a ``(i. 1-4).`` range line or a ``II.`` chapter marker. Footnote references are
    paired anchors ``<a name="fr_N">`` / ``<a href="#fn_N">`` and the notes themselves
    follow a ``Footnotes`` heading.
    """

    def __init__(self, cache_dir: str | None = None, delay: float = 3.0) -> None:
        """Create a parser with a caching HTTP fetcher.

        Args:
            cache_dir: Directory for cached pages, or ``None`` to disable caching.
            delay: Seconds to wait around each live request.
        """
        self.delay = delay
        """Current request delay in seconds (kept in sync with the fetcher by ``fetch_page``)."""
        self.http = CachedHttpFetcher(cache_dir=cache_dir, delay=delay, logger=LOGGER)
        """Fetcher used for every page."""

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self.http.close()

    def fetch_page(
        self,
        page_number: int,
        retry_count: int = 3,
        delay: float | None = None,
    ) -> str:
        """Return the validated HTML of a page, from cache or the network.

        An invalid cached copy is logged and deleted, and an invalid fetched page also
        removes its cache entry (for example a Cloudflare interstitial).

        Args:
            page_number: Page number (0 through 87).
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

            LOGGER.warning("Discarding invalid cached Jubilees source at %s", cache_path)
            cache_path.unlink()

        fetched = self.http.fetch_text(url=url, retry_count=retry_count)
        if self.is_valid_page(fetched):
            return fetched

        if cache_path and cache_path.exists():
            cache_path.unlink()

        raise RuntimeError(
            "Source page did not contain a usable Jubilees witness; direct access to sacred-texts.com may be blocked in this environment"
        )

    @staticmethod
    def page_url(page_number: int) -> str:
        """Build the URL of a page.

        Args:
            page_number: Page number; zero-padded to two digits.

        Returns:
            ``BASE_URL`` plus ``jub<NN>.htm``.
        """
        return f"{BASE_URL}jub{page_number:02d}.htm"

    @staticmethod
    def is_valid_page(text: str) -> bool:
        """Report whether text is a genuine original-site Jubilees page.

        Args:
            text: Raw page text.

        Returns:
            True if it mentions the book, contains an ``<html`` tag, and is neither a
            Cloudflare interstitial ("Just a moment") nor mirror-derived Markdown.
        """
        return (
            "Book of Jubilees" in text
            and "Just a moment" not in text
            and "Markdown Content:" not in text
            and "<html" in text.lower()
        )

    @staticmethod
    def clean_line(line: str) -> str:
        """Strip Markdown remnants and entities from a line of text.

        Removes heading markers, link syntax (keeping link text), ``[paragraph continues]``,
        bold/underscore markers, unescapes HTML entities and normalises whitespace.

        Args:
            line: Raw line.

        Returns:
            The cleaned line.
        """
        cleaned = line.strip()
        cleaned = MARKDOWN_HEADING_RE.sub("", cleaned)
        cleaned = MARKDOWN_LINK_RE.sub(r"\1", cleaned)
        cleaned = cleaned.replace("[paragraph continues]", "")
        cleaned = cleaned.replace("**", "")
        cleaned = cleaned.replace("__", "")
        cleaned = cleaned.replace("\\_", "_")
        cleaned = cleaned.replace("_", "")
        cleaned = html.unescape(cleaned)
        return normalize_whitespace(cleaned)

    def consolidate_parts(self, content: list[InlinePart]) -> list[InlinePart]:
        """Merge adjacent strings in inline content.

        Args:
            content: Inline parts.

        Returns:
            Parts with consecutive strings concatenated.
        """
        return consolidate_inline_strings(content)

    def trim_parts(self, content: list[InlinePart]) -> list[InlinePart]:
        """Trim leading and trailing whitespace from inline content.

        Whitespace-only strings at either end are dropped, the outer strings are
        stripped and empty strings removed.

        Args:
            content: Inline parts.

        Returns:
            A new, trimmed list of parts.
        """
        parts = self.consolidate_parts(content)

        while parts and isinstance(parts[0], str) and not parts[0].strip():
            parts.pop(0)
        while parts and isinstance(parts[-1], str) and not parts[-1].strip():
            parts.pop()

        if parts and isinstance(parts[0], str):
            parts[0] = parts[0].lstrip()
        if parts and isinstance(parts[-1], str):
            parts[-1] = parts[-1].rstrip()

        return [
            part
            for part in self.consolidate_parts(parts)
            if not (isinstance(part, str) and part == "")
        ]

    def extract_text_without_notes(self, parts: list[InlinePart]) -> str:
        """Flatten inline parts to text, skipping footnote notes.

        Args:
            parts: Inline parts (strings, highlights, notes).

        Returns:
            Concatenated text of strings and nested highlight content.
        """
        text = ""
        for part in parts:
            if isinstance(part, str):
                text += part
                continue

            if isinstance(part, pyosis.NoteCt):
                continue

            if hasattr(part, "content"):
                text += self.extract_text_without_notes(part.content)

        return text

    def parse_inline_content(
        self,
        element: Tag | NavigableString,
        footnotes: dict[str, FootnoteInfo],
    ) -> list[InlinePart]:
        """Convert an HTML node into inline OSIS parts.

        ``i``/``em``, ``b``/``strong``, ``sup`` and ``sub`` become highlights; ``br`` becomes a
        space; table elements are dropped; other tags are transparent. A ``fr_N`` anchor
        followed by a sibling anchor linking to ``#fn_N`` becomes a footnote note (when the
        footnote is known) and consumes that sibling.

        Args:
            element: A tag or text node.
            footnotes: Footnotes keyed by anchor name (``fn_N``).

        Returns:
            Consolidated inline parts.
        """
        if isinstance(element, NavigableString):
            text = html.unescape(str(element))
            return [text] if text else []

        result: list[InlinePart] = []
        skip_elements: set[Tag] = set()

        for child in element.children:
            if isinstance(child, NavigableString):
                result.extend(self.parse_inline_content(child, footnotes))
                continue

            if child in skip_elements:
                continue

            if child.name in {"table", "tbody", "tr", "td"}:
                continue

            if child.name == "a" and child.get("name", "").startswith("fr_"):
                ref_id = child.get("name", "").replace("fr_", "fn_")
                next_sibling = child.find_next_sibling("a")
                if next_sibling and next_sibling.get("href", "").endswith(f"#{ref_id}"):
                    footnote = footnotes.get(ref_id)
                    if footnote:
                        result.append(
                            pyosis.NoteCt(
                                type_value="explanation",
                                n=footnote.label,
                                content=footnote.content_parts,
                            )
                        )
                    skip_elements.add(next_sibling)
                    continue

            child_content = self.parse_inline_content(child, footnotes)
            if child.name in ["i", "em"]:
                if child_content:
                    result.append(
                        pyosis.HiCt(
                            type_value=pyosis.OsisHi.ITALIC,
                            content=child_content,
                        )
                    )
            elif child.name in ["b", "strong"]:
                if child_content:
                    result.append(
                        pyosis.HiCt(
                            type_value=pyosis.OsisHi.BOLD,
                            content=child_content,
                        )
                    )
            elif child.name == "sup":
                if child_content:
                    result.append(
                        pyosis.HiCt(
                            type_value=pyosis.OsisHi.SUPER,
                            content=child_content,
                        )
                    )
            elif child.name == "sub":
                if child_content:
                    result.append(
                        pyosis.HiCt(
                            type_value=pyosis.OsisHi.SUB,
                            content=child_content,
                        )
                    )
            elif child.name == "br":
                result.append(" ")
            else:
                result.extend(child_content)

        return self.consolidate_parts(result)

    def make_paragraph(self, content_parts: list[InlinePart]) -> PageParagraph | None:
        """Build a paragraph from inline parts.

        Args:
            content_parts: Inline parts of the paragraph.

        Returns:
            The paragraph, or ``None`` if it has no text outside footnotes.
        """
        trimmed_parts = self.trim_parts(content_parts)
        text = normalize_whitespace(self.extract_text_without_notes(trimmed_parts))
        if not text:
            return None

        return PageParagraph(text=text, content_parts=trimmed_parts)

    def extract_footnotes(self, body: Tag) -> dict[str, FootnoteInfo]:
        """Collect footnotes from the section after the ``Footnotes`` heading.

        Each footnote paragraph holds an anchor ``<a name="fn_N">``, then an anchor whose text
        is the label, then the note body. The body is parsed as one container with the two
        anchors removed, so direct ``<i>``/``<b>`` children keep their highlights exactly as
        nested ones do.

        Args:
            body: The page body.

        Returns:
            Footnotes keyed by anchor name; empty if the page has none.
        """
        footnotes: dict[str, FootnoteInfo] = {}
        in_footnotes = False

        for element in body.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p"]):
            cleaned = self.clean_line(element.get_text(" ", strip=True))
            if not cleaned:
                continue

            if cleaned == "Footnotes":
                in_footnotes = True
                continue

            if not in_footnotes or element.name != "p":
                continue

            footnote_anchor = element.find("a", attrs={"name": re.compile(r"^fn_")})
            if footnote_anchor is None:
                continue

            label_anchor = footnote_anchor.find_next_sibling("a")
            label = ""
            if label_anchor is not None:
                label = normalize_whitespace(label_anchor.get_text(" ", strip=True))

            body_copy = copy.copy(element)
            copy_anchor = body_copy.find("a", attrs={"name": re.compile(r"^fn_")})
            copy_label = copy_anchor.find_next_sibling("a") if copy_anchor is not None else None
            for anchor in (copy_anchor, copy_label):
                if anchor is not None:
                    anchor.decompose()
            content_parts = self.parse_inline_content(body_copy, {})

            footnotes[footnote_anchor["name"]] = FootnoteInfo(
                ref_id=footnote_anchor["name"],
                label=label,
                content_parts=self.trim_parts(content_parts),
            )

        return footnotes

    def extract_page_components(self, raw_text: str) -> tuple[list[str], list[PageParagraph]]:
        """Split a page into headings and content paragraphs.

        Site chrome (archive banner, navigation words, bracketed lines, ``Sacred Texts``
        paragraphs, ``p. N`` page markers) is dropped and extraction stops at the
        ``Footnotes`` heading.

        Args:
            raw_text: Raw page HTML.

        Returns:
            ``(headings, paragraphs)`` in document order.

        Raises:
            RuntimeError: If the text is not a valid original-site page.
        """
        if not self.is_valid_page(raw_text):
            raise RuntimeError(
                "Jubilees scraper expects original sacred-texts HTML, not mirror-derived markdown or interstitial pages"
            )

        soup = BeautifulSoup(raw_text, "html.parser")
        body = soup.body if soup.body else soup
        footnotes = self.extract_footnotes(body)

        headings: list[str] = []
        paragraphs: list[PageParagraph] = []

        for element in body.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p"]):
            stripped = element.get_text(" ", strip=True)
            if not stripped:
                continue

            cleaned = self.clean_line(stripped)
            if not cleaned:
                continue

            if cleaned.endswith("Internet Sacred Text Archive"):
                continue

            if cleaned in {"Contents", "Start Reading", "Index", "Previous", "Next"}:
                continue

            if cleaned.startswith("["):
                continue

            if "Sacred Texts" in cleaned and element.name == "p":
                continue

            if cleaned == "Footnotes":
                break

            if element.name.startswith("h"):
                headings.append(cleaned)
                continue

            paragraph = self.make_paragraph(self.parse_inline_content(element, footnotes))
            if paragraph is None:
                continue

            if paragraph.text.startswith("p. "):
                continue

            paragraphs.append(paragraph)

        return headings, paragraphs

    @staticmethod
    def should_join_with_previous(paragraph: str, previous: str) -> bool:
        """Decide whether a paragraph continues the previous one.

        Args:
            paragraph: Text of the candidate paragraph.
            previous: Text of the preceding paragraph.

        Returns:
            True if it starts with a connective in ``JOIN_WITH_PREVIOUS_PREFIXES`` or a
            lower-case letter, or the previous text ends with a dangling and/or/of/the/a.
        """
        lower = paragraph.lower()
        return (
            lower.startswith(JOIN_WITH_PREVIOUS_PREFIXES)
            or paragraph[:1].islower()
            or previous.endswith(("and", "or", "of", "the", "a"))
        )

    def build_paragraphs(self, lines: list[PageParagraph]) -> list[PageParagraph]:
        """Merge fragmentary lines into paragraphs.

        Args:
            lines: Paragraphs as extracted from the page.

        Returns:
            Paragraphs where continuation lines are folded into their predecessor.
        """
        paragraphs: list[PageParagraph] = []
        for line in lines:
            if not paragraphs:
                paragraphs.append(line)
                continue

            if self.should_join_with_previous(line.text, paragraphs[-1].text):
                paragraphs[-1].text = normalize_whitespace(f"{paragraphs[-1].text} {line.text}")
                paragraphs[-1].content_parts = self.consolidate_parts(
                    paragraphs[-1].content_parts + [" "] + line.content_parts
                )
                continue

            paragraphs.append(line)

        return paragraphs

    def parse_front_matter_page(self, page_number: int, raw_text: str) -> FrontMatterSection:
        """Parse a front-matter page.

        The title page (page 0) keeps its headings as paragraphs; elsewhere headings are
        dropped. Lines that merely repeat the section title (or its colon-separated parts, in
        either case) are removed.

        Args:
            page_number: Page number (0 through 11).
            raw_text: Raw page HTML.

        Returns:
            The section.
        """
        headings, content_lines = self.extract_page_components(raw_text)
        title = FRONT_MATTER_TITLES[page_number]

        if page_number == 0:
            body_lines = [
                PageParagraph(text=heading, content_parts=[heading])
                for heading in headings
                if heading
            ] + content_lines
        else:
            body_lines = content_lines

        duplicate_lines = {title, title.upper()}
        if page_number != 0 and ":" in title:
            for part in title.split(":"):
                normalized_part = part.strip()
                duplicate_lines.add(normalized_part)
                duplicate_lines.add(normalized_part.upper())

        paragraphs = [
            line for line in self.build_paragraphs(body_lines) if line.text not in duplicate_lines
        ]
        return FrontMatterSection(page_number=page_number, title=title, paragraphs=paragraphs)

    def extract_chapter_number(self, title: str, content_lines: list[PageParagraph]) -> int:
        """Determine a section's chapter number.

        Tries the Roman numeral in the heading, then a ``(i. 1-4).`` range line, then a
        ``II.`` chapter marker at the start of the first paragraph.

        Args:
            title: The section heading.
            content_lines: The section's paragraphs.

        Returns:
            The chapter number.

        Raises:
            RuntimeError: If none of the sources gives a chapter.
        """
        title_match = HEADING_CHAPTER_RE.search(title)
        if title_match:
            return roman_to_int(title_match.group("chapter"))

        if content_lines:
            range_match = RANGE_LINE_RE.match(content_lines[0].text)
            if range_match:
                return roman_to_int(range_match.group("chapter"))

            chapter_match = CHAPTER_LINE_RE.match(content_lines[0].text)
            if chapter_match:
                return roman_to_int(chapter_match.group("chapter"))

        raise RuntimeError(f"Could not determine Jubilees chapter from section title: {title}")

    def parse_verses(
        self,
        page_number: int,
        chapter_number: int,
        content_lines: list[PageParagraph],
    ) -> list[VerseBlock]:
        """Split a section's paragraphs into verses at inline ``N. `` markers.

        A leading range line and the page's closing ``Herewith is completed ...`` line are
        dropped. A leading ``II. `` chapter marker is rewritten to verse ``1. `` (and must match
        ``chapter_number``). Paragraphs are joined with spaces and cut at each marker; markup
        (notes, highlights) stays attached to its verse.

        Args:
            page_number: Page being parsed, for error messages.
            chapter_number: Expected chapter.
            content_lines: The section's paragraphs.

        Returns:
            Verse blocks in order.

        Raises:
            RuntimeError: If no content remains, the chapter marker disagrees or cannot be
                rewritten, or no verses are found.
        """
        lines = content_lines[:]
        if lines and RANGE_LINE_RE.match(lines[0].text):
            lines = lines[1:]

        lines = [
            line
            for line in lines
            if line.text != "Herewith is completed the account of the division of the days."
        ]

        if not lines:
            raise RuntimeError(f"No Jubilees content paragraphs remained on page {page_number}")

        chapter_match = CHAPTER_LINE_RE.match(lines[0].text)
        if chapter_match:
            line_chapter_number = roman_to_int(chapter_match.group("chapter"))
            if line_chapter_number != chapter_number:
                raise RuntimeError(
                    f"Unexpected Jubilees chapter marker on page {page_number}: expected {chapter_number}, got {line_chapter_number}"
                )

            rewritten_parts: list[InlinePart] = []
            replaced = False
            for part in lines[0].content_parts:
                if not replaced and isinstance(part, str):
                    new_part, count = re.subn(r"^\s*[IVXLCDM]+\.\s+", "1. ", part, count=1)
                    if count:
                        rewritten_parts.append(new_part)
                        replaced = True
                        continue

                rewritten_parts.append(part)

            if not replaced:
                raise RuntimeError(
                    f"Could not rewrite initial Jubilees chapter marker on page {page_number}"
                )

            lines[0] = PageParagraph(
                text=f"1. {chapter_match.group('text')}",
                content_parts=self.consolidate_parts(rewritten_parts),
            )

        all_parts: list[InlinePart] = []
        for index, line in enumerate(lines):
            if index > 0:
                all_parts.append(" ")
            all_parts.extend(line.content_parts)

        verses: list[VerseBlock] = []
        current_verse_number: int | None = None
        current_parts: list[InlinePart] = []
        pending_parts: list[InlinePart] = []

        def flush_current() -> None:
            """Append the verse being collected, if any, and reset the accumulator."""
            nonlocal current_verse_number, current_parts
            if current_verse_number is None:
                return

            verses.append(
                VerseBlock(
                    verse_numbers=[current_verse_number],
                    content_parts=self.trim_parts(current_parts),
                )
            )
            current_verse_number = None
            current_parts = []

        for part in self.consolidate_parts(all_parts):
            if isinstance(part, str):
                last_end = 0
                for match in INLINE_VERSE_RE.finditer(part):
                    prefix = part[last_end : match.start()]
                    if current_verse_number is None:
                        if prefix:
                            pending_parts.append(prefix)
                    elif prefix:
                        current_parts.append(prefix)

                    flush_current()
                    current_verse_number = int(match.group("verse"))
                    current_parts = pending_parts
                    pending_parts = []
                    last_end = match.end()

                suffix = part[last_end:]
                if current_verse_number is None:
                    if suffix:
                        pending_parts.append(suffix)
                    continue

                if suffix:
                    current_parts.append(suffix)
                continue

            if current_verse_number is None:
                pending_parts.append(part)
                continue

            current_parts.append(part)

        flush_current()

        if not verses:
            raise RuntimeError(f"No verses parsed for Jubilees page {page_number}")

        return verses

    def parse_section_page(self, page_number: int, raw_text: str) -> Section:
        """Parse a content page into a section.

        Args:
            page_number: Page number (12 through 87).
            raw_text: Raw page HTML.

        Returns:
            The section, titled by the first heading.

        Raises:
            RuntimeError: If the page has no heading.
        """
        headings, content_lines = self.extract_page_components(raw_text)
        if not headings:
            raise RuntimeError(f"Missing section heading for Jubilees page {page_number}")

        title = headings[0]
        chapter_number = self.extract_chapter_number(title, content_lines)
        verses = self.parse_verses(page_number, chapter_number, content_lines)
        return Section(
            page_number=page_number,
            title=title,
            chapter_number=chapter_number,
            verses=verses,
        )

    @staticmethod
    def generate_osis(
        front_matter: list[FrontMatterSection],
        chapters: list[Chapter],
    ) -> pyosis.OsisXML:
        """Build the OSIS document for the book.

        Args:
            front_matter: Front-matter sections (page 0 becomes the title page).
            chapters: Chapters in order.

        Returns:
            An OSIS document with front matter divs and, per chapter, a canonical chapter div
            containing one section div (``Jub.<c>.s<n>``) per source page, each with verse ids
            ``Jub.<chapter>.<verse>``.
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
            div_type = (
                pyosis.OsisDivs.TITLE_PAGE if section.page_number == 0 else pyosis.OsisDivs.FRONT
            )
            book_div.content.append(
                pyosis.DivCt(
                    type_value=div_type,
                    canonical=False,
                    content=[
                        pyosis.TitleCt(
                            type_value=pyosis.OsisTitles.MAIN,
                            canonical=False,
                            content=[section.title],
                        ),
                        *[
                            pyosis.PCt(content=paragraph.content_parts)
                            for paragraph in section.paragraphs
                        ],
                    ],
                )
            )

        for chapter in chapters:
            chapter_div = pyosis.DivCt(
                type_value=pyosis.OsisDivs.CHAPTER,
                osis_id=[f"{OSIS_WORK_ID}.{chapter.number}"],
                canonical=True,
                content=[],
            )

            for section_index, section in enumerate(chapter.sections, start=1):
                section_div = pyosis.DivCt(
                    type_value=pyosis.OsisDivs.SECTION,
                    osis_id=[f"{OSIS_WORK_ID}.{chapter.number}.s{section_index}"],
                    canonical=False,
                    content=[
                        pyosis.TitleCt(
                            type_value=pyosis.OsisTitles.SUB,
                            canonical=False,
                            content=[section.title],
                        )
                    ],
                )

                for verse in section.verses:
                    verse_ids = [
                        f"{OSIS_WORK_ID}.{chapter.number}.{verse_number}"
                        for verse_number in verse.verse_numbers
                    ]
                    section_div.content.append(
                        pyosis.VerseCt(
                            osis_id=verse_ids,
                            canonical=True,
                            content=verse.content_parts,
                        )
                    )

                chapter_div.content.append(section_div)

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
                                "Scraped from https://www.sacred-texts.com/bib/jub/ and converted to OSIS by Andrew P. Sansom."
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
                                "The Book of Jubilees, translated by Robert Henry Charles with an introduction by G. H. Box, Society for Promoting Christian Knowledge, 1917."
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
                            value='The Book of Jubilees from "Translations of Early Documents: Palestinian Jewish Texts" by Robert Henry Charles, 1917. Transcribed at sacred-texts.com and converted to OSIS by the open-canon-site scrapers.'
                        )
                    ],
                    type_value=[pyosis.TypeCt(type_value="OSIS", content=["Bible"])],
                    creator=[
                        pyosis.CreatorCt(
                            role=pyosis.OsisRoles.TRL,
                            value="Robert Henry (R.H.) Charles",
                        )
                    ],
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
        """Run the full pipeline: fetch, parse and convert every page.

        Returns:
            The OSIS document.

        Raises:
            RuntimeError: If the chapters found are not exactly 1 through 50.
        """
        front_matter = [
            self.parse_front_matter_page(page_number, self.fetch_page(page_number))
            for page_number in tqdm(
                range(PAGE_RANGE[0], FRONT_MATTER_END_PAGE + 1),
                desc="Front matter",
                unit="page",
            )
        ]

        chapters_by_number: dict[int, Chapter] = {}
        for page_number in tqdm(
            range(CONTENT_START_PAGE, PAGE_RANGE[1] + 1),
            desc="Chapters",
            unit="page",
        ):
            section = self.parse_section_page(page_number, self.fetch_page(page_number))
            chapter = chapters_by_number.setdefault(
                section.chapter_number,
                Chapter(number=section.chapter_number, sections=[]),
            )
            chapter.sections.append(section)

        expected_chapters = list(range(1, 51))
        actual_chapters = sorted(chapters_by_number)
        if actual_chapters != expected_chapters:
            raise RuntimeError(
                f"Unexpected Jubilees chapter sequence: expected {expected_chapters}, got {actual_chapters}"
            )

        chapters = [chapters_by_number[number] for number in expected_chapters]
        return self.generate_osis(front_matter, chapters)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register scraper-specific options; Jubilees has none.

    Args:
        parser: Sub-parser to extend (left unchanged).
    """


def run(args: argparse.Namespace) -> list[Path]:
    """Scrape Jubilees and write ``jubilees.xml``.

    Args:
        args: Parsed CLI arguments providing ``cache_dir``, ``delay`` and ``output_dir``.

    Returns:
        A one-element list with the written file's path.
    """
    parser = JubileesParser(cache_dir=args.cache_dir, delay=args.delay)
    try:
        osis_doc = parser.process()
        output_path = Path(args.output_dir) / OUTPUT_FILENAME
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(osis_doc.to_xml(), encoding="utf-8")
    finally:
        parser.close()
    return [output_path]


SPEC = ScraperSpec(
    name="jubilees",
    help="Book of Jubilees (R. H. Charles, 1917) to OSIS",
    source="https://sacred-texts.com/bib/jub/",
    outputs=(OUTPUT_FILENAME,),
    run=run,
    add_arguments=add_arguments,
)
"""Registry entry that exposes this scraper to the CLI."""
