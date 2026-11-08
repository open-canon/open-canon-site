"""Download and parse the Book of Enoch from sacred-texts.com into OSIS XML.

The source is R. H. Charles's 1917 translation, published at
``https://sacred-texts.com/bib/boe/`` as one static HTML page per file
(``boe000.htm`` to ``boe112.htm``). Pages 0-3 are front matter (title page,
preface, introduction, abbreviations); the rest hold chapters. The page shapes
handled are:

* Chapter headings are ``<h3>CHAPTER IV.</h3>`` with a Roman numeral.
* Verses are ``<p>`` elements that start with an Arabic ``N. `` marker. Several
  verses may share one ``<p>`` (later markers inline, e.g. ``"... 2. And he..."``).
* An unnumbered ``<p>`` continues the verse before it: prose running on past a page
  marker (sometimes flagged ``[paragraph continues]``) or a further stanza of the same
  verse. At the start of a chapter it is verse 1 (chapter III has no number at all).
* Poetry lines inside a verse are separated by ``<br>``; a verse marker may also sit
  inside a line. A handful of numbers lose their period (``2 And``, ``2 .For``); those
  count only at the start of a paragraph or line and when they are the next verse.
* ``boe081`` is headed ``CHAPTER LXXVII.`` but holds chapter LXXVIII.
* Inline formatting uses ``<i>``/``<b>``/``<sup>``/``<sub>``; page numbers appear as
  ``<font color="green">p. 12</font>``; Charles's brackets (``⌈ ⌉``) are literal text.
* Footnotes sit under an ``<h3>Footnotes</h3>`` heading as
  ``<p><a name="fn_0"></a><a href="...#fr_0">label</a> text</p>`` and are referenced
  in the text by ``<a name="fr_0"></a><a href="#fn_0">1</a>``.
* Site chrome (``Next:``, ``Previous:``, ``Sacred Texts``, ``Index``, ``«``/``»``) is
  skipped.

:func:`run` is the entry point registered through :data:`SPEC`.
"""

from __future__ import annotations

import argparse
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pyosis
from bs4 import BeautifulSoup, NavigableString, Tag
from tqdm import tqdm

from open_canon_site.scrapers import _osis
from open_canon_site.scrapers._http import CachedHttpFetcher
from open_canon_site.scrapers._osis import (
    InlinePart,
    consolidate_inline_strings,
    extract_plain_text,
    is_navigation_text,
    normalize_whitespace,
    parse_page_marker_text,
)
from open_canon_site.scrapers.base import ScraperSpec
from open_canon_site.scrapers.sacred_texts._layout import legacy_html

LOGGER = logging.getLogger(__name__)
"""Module logger."""

OUTPUT_FILENAME: Final[str] = "1-enoch.xml"
"""Name of the OSIS file written by :func:`run`."""
DEFAULT_START_PAGE: Final[int] = 0  # 0 includes the title page and front matter
"""Default first page to process; 0 includes the title page and front matter."""
DEFAULT_END_PAGE: Final[int] = 112
"""Default last page to process (the appendix)."""

BASE_URL: Final[str] = "https://archive.sacred-texts.com/bib/boe/"
"""Directory URL of the Charles translation; page files are appended to it."""
FILE_RANGE: Final[tuple[int, int]] = (0, 112)
"""Inclusive range of page numbers, ``boe000.htm`` (title page) to ``boe112.htm`` (appendix)."""
OSIS_BOOK_ID: Final[str] = "1En"
"""OSIS book abbreviation used in every osisID."""
BOOK_TITLE: Final[str] = "The Book of Enoch"
"""Full title of the book."""
BOOK_SHORT_TITLE: Final[str] = "1 Enoch"
"""Short title of the book."""
FRONT_MATTER_TITLES: Final[dict[int, str]] = {
    0: "Title Page",
    1: "Editors' Preface",
    2: "Introduction",
    3: "Abbreviations, Brackets and Symbols",
}
"""Section titles for the front-matter pages, keyed by page number."""
FRONT_MATTER_BOILERPLATE: Final[set[str]] = {
    "The Book of Enoch, by R.H. Charles, [1917], at sacred-texts.com",
    "Scanned at sacred-texts.com, June 2004. Proofed and formatted by John Bruno Hare. This text is in the public domain in the United States because it was published prior to 1923.",
}
"""Exact header and credit lines sacred-texts adds to front-matter pages; never emitted."""
MISLABELLED_CHAPTER_PAGES: Final[dict[int, int]] = {81: 78}
"""Chapter number for pages whose heading is wrong: ``boe081`` repeats ``CHAPTER LXXVII.``."""
PARAGRAPH_CONTINUES: Final[str] = "[paragraph continues]"
"""Marker the site puts at the start of a paragraph that runs on after a page break."""


@dataclass
class VerseContent:
    """Parsed verse content with annotations and formatting preserved."""

    text: str
    """Plain-text rendering of the verse (formatting flattened), for reference."""
    content_parts: list[str | pyosis.HiCt | pyosis.MilestoneCt]
    """Inline parts (strings, ``hi`` formatting, page milestones, notes) in document order."""
    has_poetry: bool = False
    """True when the source ``<p>`` contained ``<br>`` line breaks."""
    poetry_lines: list[list[str | pyosis.HiCt | pyosis.MilestoneCt]] | None = None
    """Inline parts per non-empty poetry line, or ``None`` when there is no poetry."""


@dataclass
class FootnoteInfo:
    """A footnote scraped from a page's ``Footnotes`` section."""

    ref_id: str
    """Anchor id of the footnote body, e.g. ``"fn_0"``."""
    label: str
    """Verse reference printed on the footnote link, e.g. ``"viii:1"``."""
    content: str
    """Footnote text with the anchors removed."""


@dataclass
class ChapterInfo:
    """A chapter heading and, optionally, its verses (not used by the parser itself)."""

    number: int
    """1-based chapter number."""
    title: str
    """Chapter heading text, e.g. ``"CHAPTER I."``."""
    section_title: str | None = None
    """Title of the section containing the chapter, if any."""
    verses: dict[int, VerseContent] | None = None
    """Verses keyed by verse number, if collected."""


class SacredTextsParser:
    """Parse the sacred-texts.com Book of Enoch pages into a single OSIS book division.

    Feed pages through :meth:`parse_page` in order (or use :meth:`process_all_pages`),
    then call :meth:`generate_osis`.
    """

    def __init__(
        self,
        cache_dir: str | None = None,
        delay: float = 1.0,
    ) -> None:
        """Create a parser with its own cached HTTP fetcher.

        Args:
            cache_dir: Directory for the on-disk HTML cache (created if missing), or
                ``None`` to disable caching.
            delay: Seconds the fetcher sleeps around live requests.
        """
        self.current_chapter: int | None = None
        """Number of the chapter being filled, or ``None`` before the first heading."""
        self.current_verse: int | None = None
        """Number of the most recently added verse, or ``None`` before any verse."""
        self.current_div: pyosis.DivCt | None = None
        """OSIS chapter division currently receiving verses."""
        self.root_div: pyosis.DivCt | None = None
        """OSIS book division holding front matter and chapters (set by :meth:`start_book`)."""
        self.chapters: list[pyosis.DivCt] = []
        """Reserved list of chapter divisions; not populated by the parser."""
        self.footnotes: dict[str, FootnoteInfo] = {}
        """Footnotes seen so far, keyed by anchor id (``"fn_0"``), across all pages."""
        self.http = CachedHttpFetcher(cache_dir=cache_dir, delay=delay, logger=LOGGER)
        """HTTP client that fetches and caches the page HTML."""

        self.cache_dir = Path(cache_dir) if cache_dir else None
        """Resolved cache directory, or ``None`` when caching is disabled."""
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            LOGGER.info(f"Using cache directory: {self.cache_dir}")

    def fetch_page(self, page_num: int, retry_count: int = 3, delay: float = 1.0) -> str:
        """Fetch one ``boeNNN.htm`` page, using the cache when possible.

        Args:
            page_num: Page number; zero-padded to three digits in the URL.
            retry_count: Maximum number of live attempts passed to the fetcher.
            delay: Delay between requests in seconds; applied to the fetcher if it
                differs from the current value.

        Returns:
            The page HTML.
        """
        if delay != self.http.delay:
            self.http.delay = delay

        url = f"{BASE_URL}boe{page_num:03d}.htm"
        return self.http.fetch_text(url=url, retry_count=retry_count)

    def close(self) -> None:
        """Close the HTTP client."""
        self.http.close()

    def consolidate_strings(self, content: list[InlinePart]) -> list[InlinePart]:
        """Consolidate consecutive strings in a content list.

        pyosis has a bug where PCt/LCt/VerseCt don't handle multiple consecutive
        strings correctly - they only keep the first and last, dropping middle ones.
        This function merges consecutive strings to avoid that bug.

        Args:
            content: Inline parts, possibly with adjacent strings.

        Returns:
            Parts with adjacent strings merged.
        """
        return consolidate_inline_strings(content)

    def parse_inline_annotations(
        self, element: Tag | NavigableString, is_green_font: bool = False
    ) -> list[InlinePart]:
        """Parse text, preserving inline formatting, brackets, and page markers.

        Converts HTML formatting tags to OSIS equivalents:
        - <i>, <em> → <hi type="italic">
        - <b>, <strong> → <hi type="bold">
        - <sup> → <hi type="super">
        - <sub> → <hi type="sub">

        Page markers like "p. xvii" in green font tags are converted to milestone elements.
        Inline page references (e.g., "pp. 35, 36") are preserved as text.
        Brackets (⌈⌉) are preserved as literal characters.

        Footnote references (``<a name="fr_N">`` followed by ``<a href="#fn_N">``) become
        ``<note>`` elements when the footnote was already extracted; navigation-classed
        elements and ``<br>`` are dropped.

        Args:
            element: The HTML element or text node to parse.
            is_green_font: True if inside a ``<font color="green">`` tag, where text is
                scanned for page markers.

        Returns:
            Inline parts in document order. A bare whitespace-only text node yields
            ``[]`` outside green font.
        """
        if isinstance(element, NavigableString):
            text = str(element)
            # Only convert page markers if inside a green font tag
            if is_green_font:
                return parse_page_marker_text(text)
            else:
                # Not in green font - preserve text as-is
                return [text] if text.strip() else []

        result: list[InlinePart] = []

        # Track elements to skip (footnote number links)
        skip_elements = set()

        # Process all children of the element
        for child in element.children:
            if isinstance(child, NavigableString):
                # Recursively call to handle page marker conversion
                child_result = self.parse_inline_annotations(child, is_green_font=is_green_font)
                result.extend(child_result)
            elif isinstance(child, Tag):
                # Skip if this element was marked for skipping
                if child in skip_elements:
                    continue

                # Skip navigation elements
                if child.get("class") and any(
                    cls in str(child.get("class")) for cls in ["navigation", "next", "prev"]
                ):
                    continue

                # Check if this is a green font tag (for page markers)
                is_child_green_font = (
                    child.name == "font" and child.get("color", "").lower() == "green"
                )

                # Handle footnote references specially before recursing
                if child.name == "a" and child.get("name", "").startswith("fr_"):
                    # This is a footnote anchor - look for the corresponding link
                    ref_id = child.get("name").replace("fr_", "fn_")
                    # Look ahead to next sibling for the actual link
                    next_sib = child.find_next_sibling("a")
                    if next_sib and next_sib.get("href", "") == f"#{ref_id}":
                        # Found a footnote reference
                        if ref_id in self.footnotes:
                            footnote = self.footnotes[ref_id]
                            # Create note element
                            note = pyosis.NoteCt(
                                type_value="explanation",
                                n=footnote.label,
                                content=[footnote.content],
                            )
                            result.append(note)
                        # Mark the footnote number link to skip
                        skip_elements.add(next_sib)
                        continue

                # Recursively parse the child's content
                child_content = self.parse_inline_annotations(
                    child, is_green_font=is_child_green_font
                )

                # Map HTML tags to OSIS formatting
                if child.name in ["i", "em"]:
                    if child_content:
                        result.append(
                            pyosis.HiCt(type_value=pyosis.OsisHi.ITALIC, content=child_content)
                        )
                elif child.name in ["b", "strong"]:
                    if child_content:
                        result.append(
                            pyosis.HiCt(type_value=pyosis.OsisHi.BOLD, content=child_content)
                        )
                elif child.name == "sup":
                    if child_content:
                        result.append(
                            pyosis.HiCt(type_value=pyosis.OsisHi.SUPER, content=child_content)
                        )
                elif child.name == "sub":
                    if child_content:
                        result.append(
                            pyosis.HiCt(type_value=pyosis.OsisHi.SUB, content=child_content)
                        )
                elif child.name == "br":
                    # Skip br tags - handled at poetry level
                    continue
                elif child.name == "a":
                    # Regular link - passthrough
                    result.extend(child_content)
                elif child.name in ["font", "span", "div"]:
                    # For styling/formatting tags without semantic meaning, just include their content
                    # Note: Green font tags are handled specially above for page markers
                    result.extend(child_content)
                else:
                    # For other tags, just include their content
                    result.extend(child_content)

        return self.consolidate_strings(result)

    def parse_verse_text(self, verse_element: Tag) -> VerseContent:
        """Parse a verse ``<p>`` into inline parts and, if it has ``<br>``, poetry lines.

        The paragraph is split on ``<br>`` and each piece is parsed separately so
        formatting stays inside its line. Empty lines and lines containing navigation
        words (``Next:``, ``Previous:``, ``Sacred Texts``, ``Index``) are dropped.

        Args:
            verse_element: The ``<p>`` (or other) tag holding the verse.

        Returns:
            The verse text, inline parts and poetry information. The leading verse
            number is *not* stripped here.
        """
        text_parts = self.parse_inline_annotations(verse_element)

        # Extract plain text for comparison (flatten HiCt content)
        full_text = extract_plain_text(text_parts)

        # Check if verse contains poetry (multiple line breaks)
        has_poetry = bool(verse_element.find_all(["br"]))

        poetry_lines = None
        if has_poetry:
            # Get the HTML content and split by <br> tags
            # This preserves inline formatting within each line
            verse_html = str(verse_element)
            # Split by various forms of br tags
            line_htmls = re.split(r"<br\s*/?>", verse_html, flags=re.IGNORECASE)

            lines = []
            for line_html in line_htmls:
                # Parse each line as HTML, preserving formatting
                line_soup = BeautifulSoup(line_html, "html.parser")

                # Parse the line to extract formatted content
                line_parts = self.parse_inline_annotations(line_soup)

                # Check if line is not empty
                line_text = ""
                for part in line_parts:
                    if isinstance(part, str):
                        line_text += part
                    elif hasattr(part, "content"):
                        for item in part.content:
                            if isinstance(item, str):
                                line_text += item

                line_text = line_text.strip()

                # Skip empty lines and navigation elements
                if line_text and not any(
                    nav in line_text for nav in ["Next:", "Previous:", "Sacred Texts", "Index"]
                ):
                    lines.append(line_parts)

            poetry_lines = lines if lines else None

        return VerseContent(
            text=full_text.strip(),
            content_parts=text_parts,
            has_poetry=has_poetry,
            poetry_lines=poetry_lines if poetry_lines else None,
        )

    def extract_chapter_number(self, text: str) -> int | None:
        """Extract the chapter number from a ``CHAPTER IV.`` style heading.

        Args:
            text: Heading text; matching is case-insensitive and only ``IVXLC`` numerals
                are recognised.

        Returns:
            The chapter number, or ``None`` if the text has no such heading.
        """
        match = re.search(r"CHAPTER\s+([IVXLC]+)", text, re.IGNORECASE)
        if match:
            roman = match.group(1)
            return _osis.roman_to_int(roman)
        return None

    def start_book(self) -> None:
        """Create the root ``1En`` book division with its main title, replacing any existing one."""
        self.root_div = pyosis.DivCt(
            type_value=pyosis.OsisDivs.BOOK,
            osis_id=[OSIS_BOOK_ID],
            canonical=True,
            content=[
                pyosis.TitleCt(
                    type_value=pyosis.OsisTitles.MAIN,
                    short=BOOK_SHORT_TITLE,
                    content=[BOOK_TITLE],
                )
            ],
        )

    def should_skip_front_matter_paragraph(self, p_tag: Tag) -> bool:
        """Return True if a front-matter paragraph is site chrome or metadata.

        Skips paragraphs inside ``nav``/``header``/``footer``, footnote bodies (those
        with an ``<a name="fn_...">``), empty paragraphs, the known sacred-texts
        boilerplate lines and navigation text.

        Args:
            p_tag: The paragraph to classify.

        Returns:
            True if the paragraph should not be emitted.
        """
        if p_tag.find_parent(["nav", "header", "footer"]):
            return True

        if p_tag.find("a", attrs={"name": lambda x: x and x.startswith("fn_")}):
            return True

        text = normalize_whitespace(p_tag.get_text(" ", strip=True))
        if not text:
            return True

        if text in FRONT_MATTER_BOILERPLATE:
            return True

        return is_navigation_text(text)

    def extract_front_matter_lead_lines(self, soup: BeautifulSoup, title: str) -> list[str]:
        """Extract heading lines that belong to the front-matter page itself.

        This preserves the title-page block on boe000 and leading subheadings like
        the introduction's opening section, while avoiding duplicated section titles.

        Walks headings and paragraphs in order, collecting heading text until the first
        real content paragraph; skipped (chrome) paragraphs do not stop the scan.

        Args:
            soup: The parsed front-matter page.
            title: The section title already used for the division; headings equal to it
                (case-insensitively) are not repeated.

        Returns:
            Distinct heading lines, whitespace-normalised, in page order.
        """
        root = soup.body if soup.body else soup
        lead_lines = []
        seen = {title.casefold()}

        for element in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p"]):
            if element.name == "p":
                if self.should_skip_front_matter_paragraph(element):
                    continue
                break

            line = normalize_whitespace(element.get_text(" ", strip=True))
            if not line or line in FRONT_MATTER_BOILERPLATE:
                continue
            if is_navigation_text(line):
                continue
            if line.casefold() in seen:
                continue

            seen.add(line.casefold())
            lead_lines.append(line)

        return lead_lines

    def add_front_matter(
        self,
        title: str,
        content_paragraphs: list[Tag],
        lead_lines: list[str] | None = None,
    ) -> None:
        """Append a ``front`` division (preface, introduction...) to the book.

        A paragraph whose only content is a page milestone is added bare; others are
        wrapped in ``<p>``. Starts the book first if needed.

        Args:
            title: Section title for the division's main title.
            content_paragraphs: Paragraph tags with the section body.
            lead_lines: Extra heading lines emitted as paragraphs before the body.
        """
        if not self.root_div:
            self.start_book()

        front_content: list[pyosis.TitleCt | pyosis.PCt | pyosis.MilestoneCt] = [
            pyosis.TitleCt(
                type_value=pyosis.OsisTitles.MAIN,
                canonical=False,
                content=[title],
            )
        ]

        for line in lead_lines or []:
            front_content.append(pyosis.PCt(content=[line]))

        for p_tag in content_paragraphs:
            parsed_content = self.parse_inline_annotations(p_tag)
            if parsed_content:
                # If paragraph contains only a milestone, add it directly (not wrapped in PCt)
                if len(parsed_content) == 1 and isinstance(parsed_content[0], pyosis.MilestoneCt):
                    front_content.append(parsed_content[0])
                else:
                    # Regular paragraph with text/formatting
                    front_content.append(pyosis.PCt(content=parsed_content))

        front_matter_div = pyosis.DivCt(
            type_value=pyosis.OsisDivs.FRONT,
            canonical=False,
            content=front_content,
        )
        self.root_div.content.append(front_matter_div)

    def start_chapter(self, chapter_num: int, title: str = "") -> None:
        """Close the previous chapter (logging verse gaps) and open ``1En.<chapter_num>``.

        Args:
            chapter_num: Chapter number, used in the OSIS id.
            title: Heading text for the chapter title element; omitted when empty.
        """
        if self.current_div and self.current_chapter:
            # Check for verse gaps before closing the previous chapter
            self._check_verse_gaps()

        self.current_chapter = chapter_num
        self.current_verse = None
        chapter_osis_id = f"{OSIS_BOOK_ID}.{chapter_num}"

        chapter_content = []
        if title:
            chapter_content.append(
                pyosis.TitleCt(type_value=pyosis.OsisTitles.MAIN, content=[title])
            )

        self.current_div = pyosis.DivCt(
            type_value=pyosis.OsisDivs.CHAPTER,
            osis_id=[chapter_osis_id],
            canonical=True,
            content=chapter_content,
        )

        if self.root_div:
            self.root_div.content.append(self.current_div)

    def add_verse(self, verse_num: int, content: VerseContent) -> None:
        """Append a verse to the current chapter, as a line group when it has poetry.

        Logs a warning and does nothing if no chapter is open.

        Args:
            verse_num: Verse number within the current chapter.
            content: Parsed verse content; poetry lines win over ``content_parts``.
        """
        if not self.current_chapter or not self.current_div:
            LOGGER.warning(f"No chapter started for verse {verse_num}")
            return

        verse_osis_id = f"{OSIS_BOOK_ID}.{self.current_chapter}.{verse_num}"

        if content.has_poetry and content.poetry_lines:
            # Create line group for poetry
            lines = []
            for line_parts in content.poetry_lines:
                # Poetry lines contain parsed content with formatting
                lines.append(pyosis.LCt(content=line_parts))

            lg = pyosis.LgCt(l=lines)

            verse = pyosis.VerseCt(osis_id=[verse_osis_id], canonical=True, content=[lg])
        else:
            # Regular verse - use parsed content with formatting
            verse = pyosis.VerseCt(
                osis_id=[verse_osis_id],
                canonical=True,
                content=content.content_parts if content.content_parts else [content.text],
            )

        self.current_div.content.append(verse)
        self.current_verse = verse_num

    def _extend_verse_with_poetry(
        self, verse_num: int, extra_lines: list[list[InlinePart]]
    ) -> None:
        """Append additional poetry lines to the most recently added verse.

        When sacred-texts.com places the tail of a verse in a separate unnumbered
        ``<p>`` that also contains the opening of the *next* verse (separated by an
        inline ``N.`` marker), the tail lines belong to the already-emitted verse
        rather than starting a new verse element.  This helper appends those tail
        lines to the existing verse in-place, converting a plain-text verse to
        poetry if necessary.

        Args:
            verse_num: The verse number whose content should be extended.
            extra_lines: Parsed poetry lines to append.
        """
        if not self.current_div or not self.current_chapter:
            return

        verse_osis_id = f"{OSIS_BOOK_ID}.{self.current_chapter}.{verse_num}"
        new_l_elements = [pyosis.LCt(content=lp) for lp in extra_lines]

        for item in reversed(self.current_div.content):
            if hasattr(item, "osis_id") and item.osis_id and item.osis_id[0] == verse_osis_id:
                # Extend an existing LgCt if present
                for c in item.content:
                    if isinstance(c, pyosis.LgCt):
                        c.l.extend(new_l_elements)
                        return
                # No LgCt yet (verse was plain text) — append a new linegroup
                lg = pyosis.LgCt(l=new_l_elements)
                item.content.append(lg)
                return

        # Verse not found — add as a new verse (fallback)
        seg_content = VerseContent(
            text="",
            content_parts=[],
            has_poetry=True,
            poetry_lines=extra_lines,
        )
        self.add_verse(verse_num, seg_content)

    def _extend_verse_with_parts(self, verse_num: int, extra_parts: list[InlinePart]) -> None:
        """Append prose parts to the most recently added verse.

        Prose that continues a verse after a page break sits in its own unnumbered
        ``<p>``. The parts are joined to the verse with a space; a verse already holding
        poetry gets them as one more line instead.

        Args:
            verse_num: The verse number whose content should be extended.
            extra_parts: Parsed inline parts to append.
        """
        if not extra_parts or not self.current_div or not self.current_chapter:
            return

        verse_osis_id = f"{OSIS_BOOK_ID}.{self.current_chapter}.{verse_num}"
        for item in reversed(self.current_div.content):
            if isinstance(item, pyosis.VerseCt) and item.osis_id == [verse_osis_id]:
                for c in item.content:
                    if isinstance(c, pyosis.LgCt):
                        c.l.append(pyosis.LCt(content=list(extra_parts)))
                        return
                item.content = self.consolidate_strings([
                    *item.content,
                    " ",
                    *self._lstrip_parts(extra_parts),
                ])
                return

        self.add_verse(
            verse_num,
            VerseContent(text=extract_plain_text(extra_parts), content_parts=list(extra_parts)),
        )

    @staticmethod
    def _lstrip_parts(parts: list[InlinePart]) -> list[InlinePart]:
        """Return a copy of ``parts`` with leading whitespace removed from a first string.

        Args:
            parts: Inline parts; not modified.

        Returns:
            The parts, the first one left-stripped when it is a string.
        """
        result = list(parts)
        if result and isinstance(result[0], str):
            result[0] = result[0].lstrip()
        return result

    def _add_unnumbered_paragraph(self, p: Tag) -> None:
        """Place a paragraph that does not start with a verse number.

        At the start of a chapter it is verse 1 (some chapters are a single unnumbered
        verse). After a verse, prose continues that verse, as when a page break splits
        it, and inline ``N.`` markers in it start the following verses; an unnumbered
        stanza likewise continues the verse before it.

        Args:
            p: The paragraph.
        """
        verse_content = self.parse_verse_text(p)

        if self.current_verse is None:
            if verse_content.has_poetry and verse_content.poetry_lines:
                for num, lines in self.split_multi_verse_poetry_lines(
                    verse_content.poetry_lines, 1
                ):
                    self.add_verse(
                        num,
                        VerseContent(
                            text="", content_parts=[], has_poetry=True, poetry_lines=lines
                        ),
                    )
            else:
                for num, parts in self.split_multi_verse_content(
                    self._lstrip_parts(verse_content.content_parts), 1
                ):
                    self.add_verse(
                        num, VerseContent(text=extract_plain_text(parts), content_parts=parts)
                    )
            return

        if not (verse_content.has_poetry and verse_content.poetry_lines):
            segments = self.split_multi_verse_content(
                verse_content.content_parts, self.current_verse
            )
            for i, (num, parts) in enumerate(segments):
                if i == 0:
                    self._extend_verse_with_parts(num, parts)
                else:
                    self.add_verse(
                        num, VerseContent(text=extract_plain_text(parts), content_parts=parts)
                    )
            return

        # Poetry: an unnumbered stanza continues the current verse (Charles breaks a
        # verse into several stanzas, each its own <p>). An inline "N+1." line inside it
        # starts the next verse, so the lines before it stay with the current verse.
        segments = self.split_multi_verse_poetry_lines(
            verse_content.poetry_lines, self.current_verse
        )
        for i, (seg_verse_num, seg_lines) in enumerate(segments):
            if i == 0:
                if seg_lines:
                    self._extend_verse_with_poetry(seg_verse_num, seg_lines)
            else:
                self.add_verse(
                    seg_verse_num,
                    VerseContent(
                        text="", content_parts=[], has_poetry=True, poetry_lines=seg_lines
                    ),
                )

    def _check_verse_gaps(self) -> None:
        """Log a warning for any gaps in verse numbering within the current chapter.

        Called just before closing a chapter (i.e. when a new chapter starts) so
        that missing verses are surfaced to the user early. Does nothing without an
        open chapter.
        """
        if not self.current_div or not self.current_chapter:
            return

        verse_osis_prefix = f"{OSIS_BOOK_ID}.{self.current_chapter}."
        verse_nums = sorted(
            int(item.osis_id[0][len(verse_osis_prefix) :])
            for item in self.current_div.content
            if (
                hasattr(item, "osis_id")
                and item.osis_id
                and item.osis_id[0].startswith(verse_osis_prefix)
            )
        )

        for i in range(len(verse_nums) - 1):
            if verse_nums[i + 1] - verse_nums[i] > 1:
                for missing in range(verse_nums[i] + 1, verse_nums[i + 1]):
                    LOGGER.warning(
                        f"Verse {verse_osis_prefix}{missing} appears to be missing "
                        f"(gap between {verse_nums[i]} and {verse_nums[i + 1]})"
                    )

    def split_multi_verse_content(
        self,
        content_parts: list[InlinePart],
        starting_verse_num: int,
    ) -> list[tuple[int, list[InlinePart]]]:
        """Split content_parts that inline multiple verse numbers into per-verse segments.

        Sacred-texts.com often places multiple verses in a single <p> tag, with verse
        numbers like " 2. " inline in the text.  This method splits them into separate
        lists, one per verse.

        A split happens only at the *next expected* number (current verse + 1)
        surrounded by whitespace and not preceded by a digit, so page references such
        as ``"p. 32. "`` do not split. Non-string parts stay with the verse in progress.

        Args:
            content_parts: Inline parts of one paragraph.
            starting_verse_num: Number of the first verse in the paragraph (its marker
                already removed).

        Returns:
            ``(verse_num, parts)`` tuples in order; a single tuple holding the original
            parts if no marker was found.
        """
        result: list[tuple[int, list[InlinePart]]] = []
        current_verse = starting_verse_num
        current_parts: list[InlinePart] = []

        for part in content_parts:
            if not isinstance(part, str):
                current_parts.append(part)
                continue

            remaining = part

            while remaining:
                next_verse = current_verse + 1
                # Match the next expected verse number preceded by whitespace and
                # not preceded by another digit (avoids false matches such as
                # "p. 32. " or "fig. 2.").
                m = re.search(rf"(?<!\d)\s+{re.escape(str(next_verse))}\.\s+", remaining)
                if not m:
                    break

                before = remaining[: m.start()].rstrip()
                if before:
                    current_parts.append(before)

                result.append((current_verse, current_parts))
                current_parts = []
                current_verse = next_verse
                remaining = remaining[m.end() :]

            if remaining:
                current_parts.append(remaining)

        if current_parts:
            result.append((current_verse, current_parts))

        # If no split was found, return the original content as a single verse
        return result if result else [(starting_verse_num, list(content_parts))]

    def split_multi_verse_poetry_lines(
        self,
        poetry_lines: list[list[InlinePart]],
        starting_verse_num: int,
    ) -> list[tuple[int, list[list[InlinePart]]]]:
        """Split poetry lines that span multiple verses into per-verse groups.

        A line that begins with the next expected verse number starts a new verse; the
        number may lack its period there (``"4 And ..."``) as long as a capitalised word
        follows. A ``" N. "`` marker inside a line (prose verses sharing a line with
        poetry) splits that line, with the same rules as
        :meth:`split_multi_verse_content`.

        Args:
            poetry_lines: Inline parts per line.
            starting_verse_num: Number of the first verse; for each line the next
                expected number is current + 1, which is stripped from the line start.

        Returns:
            ``(verse_num, lines)`` tuples in order; a single tuple with the original
            lines if no marker was found.
        """
        result: list[tuple[int, list[list[InlinePart]]]] = []
        current_verse = starting_verse_num
        current_lines: list[list[InlinePart]] = []

        def start_verse(number: int) -> None:
            """Close the verse in progress and start ``number``."""
            nonlocal current_verse, current_lines
            result.append((current_verse, current_lines))
            current_lines = []
            current_verse = number

        for line_parts in poetry_lines:
            line = list(line_parts)
            if line and isinstance(line[0], str):
                next_verse = current_verse + 1
                m = re.match(rf"^\s*{re.escape(str(next_verse))}(?:\.\s+|\s+(?=[A-Z]))", line[0])
                if m:
                    start_verse(next_verse)
                    stripped = line[0][m.end() :]
                    line = [stripped, *line[1:]] if stripped.strip() else line[1:]

            for i, (seg_verse, seg_parts) in enumerate(
                self.split_multi_verse_content(line, current_verse)
            ):
                if i > 0:
                    start_verse(seg_verse)
                if extract_plain_text(seg_parts).strip() or any(
                    not isinstance(part, str) for part in seg_parts
                ):
                    current_lines.append(seg_parts)

        if current_lines:
            result.append((current_verse, current_lines))

        return result if result else [(starting_verse_num, list(poetry_lines))]

    def extract_footnotes(self, soup: BeautifulSoup) -> None:
        """Extract footnotes from the page and store them for inline insertion.

        Footnotes are typically in a section with <H3>Footnotes</H3> heading.
        Each footnote has the format:
        <A NAME="fn_X"></A><A HREF="...#fr_X">label</A> content

        Paragraphs are read until the next ``h1``-``h4`` heading. Footnotes with empty
        content are ignored; results are stored in :attr:`footnotes`.

        Args:
            soup: The parsed page.
        """
        # Look for "Footnotes" heading
        for h3 in soup.find_all("h3"):
            if "Footnotes" in h3.get_text():
                # Found footnotes section - extract all paragraphs after it
                current = h3.find_next_sibling()
                while current:
                    if current.name == "p":
                        # Parse footnote: <A NAME="fn_X"></A><A HREF="...">label</A> text
                        anchor = current.find(
                            "a", attrs={"name": lambda x: x and x.startswith("fn_")}
                        )
                        if anchor:
                            ref_id = anchor.get("name")  # e.g., "fn_0"

                            # Find the label link
                            label_link = anchor.find_next_sibling("a")
                            label = label_link.get_text().strip() if label_link else ""

                            # Get the footnote content (everything after the label link)
                            # Remove the anchors and get text
                            content_parts = []
                            for elem in current.children:
                                if isinstance(elem, NavigableString):
                                    text = str(elem).strip()
                                    if text:
                                        content_parts.append(text)
                                elif elem.name not in ["a"]:  # Skip anchor tags
                                    text = elem.get_text().strip()
                                    if text:
                                        content_parts.append(text)

                            # Join and clean up the content
                            content = " ".join(content_parts).strip()

                            # Store the footnote
                            if content:
                                self.footnotes[ref_id] = FootnoteInfo(
                                    ref_id=ref_id, label=label, content=content
                                )
                                LOGGER.debug(
                                    f"Extracted footnote {ref_id}: {label} = {content[:50]}..."
                                )

                    current = current.find_next_sibling()
                    # Stop if we hit another heading
                    if current and current.name in ["h1", "h2", "h3", "h4"]:
                        break

    def parse_page(self, html: str, page_num: int = -1) -> None:
        """Parse a single page and extract chapter/verse content or front matter.

        Footnotes are extracted first. Pages 0-3 become front-matter divisions. Other
        pages start chapters from ``CHAPTER`` ``<h3>`` headings and turn numbered ``<p>``
        elements into verses, splitting inline multi-verse paragraphs. Unnumbered
        poetry paragraphs after a verse continue it or become the next verse.

        Args:
            html: HTML content to parse.
            page_num: Page number (used to identify front matter pages 0-3); the
                default ``-1`` means a body page.
        """
        soup = BeautifulSoup(legacy_html(html), "html.parser")

        # Extract footnotes first (they'll be inserted inline)
        self.extract_footnotes(soup)

        # Handle front matter pages (0-3)
        if page_num in [0, 1, 2, 3]:
            title = FRONT_MATTER_TITLES[page_num]
            lead_lines = self.extract_front_matter_lead_lines(soup, title)

            # Extract all paragraphs that are actual content
            content_paragraphs = []
            for p in soup.find_all("p"):
                if self.should_skip_front_matter_paragraph(p):
                    continue
                content_paragraphs.append(p)  # Pass the Tag object, not plain text

            if lead_lines or content_paragraphs:
                self.add_front_matter(title, content_paragraphs, lead_lines)
                LOGGER.debug(f"Added front matter: {title}")
            return

        # Walk headings and paragraphs in document order so each paragraph lands in
        # the chapter whose heading precedes it.
        for element in soup.find_all(["h3", "p"]):
            if element.name == "h3":
                text = element.get_text().strip()
                if "Footnotes" in text:
                    break  # footnote bodies were already read by extract_footnotes
                if "CHAPTER" in text.upper():
                    chapter_num = self.extract_chapter_number(text)
                    if page_num in MISLABELLED_CHAPTER_PAGES:
                        chapter_num = MISLABELLED_CHAPTER_PAGES[page_num]
                        text = f"CHAPTER {_osis.int_to_roman(chapter_num)}."
                    if chapter_num:
                        clean_title = re.sub(r"\s+", " ", text).strip()
                        self.start_chapter(chapter_num, clean_title)
                        LOGGER.debug(f"Started chapter {chapter_num}: {clean_title}")
                continue

            p = element
            # Skip if paragraph is within navigation/header elements
            if p.find_parent(["nav", "header", "footer"]):
                continue
            if p.find("a", attrs={"name": lambda x: x and x.startswith("fn_")}):
                continue  # a footnote body

            text = p.get_text().strip()
            if text.startswith(PARAGRAPH_CONTINUES):
                # The site's note that a paragraph runs on past a page break.
                for node in p.find_all(string=lambda s: PARAGRAPH_CONTINUES in s):
                    node.replace_with(str(node).replace(PARAGRAPH_CONTINUES, ""))
                text = p.get_text().strip()

            # Skip empty paragraphs, navigation links, and page numbers
            if not text:
                continue
            if text.startswith("p.") and len(text) < 10:
                continue
            if text.startswith("[") or "Next:" in text or "Previous:" in text:
                continue
            if "Sacred Texts" in text or "Index" in text or "«" in text or "»" in text:
                continue
            if text in FRONT_MATTER_BOILERPLATE:
                continue  # the title banner the archive pages carry above every chapter
            if text.startswith("⌈") and text.endswith("⌉") and len(text) < 20:
                continue  # Skip standalone bracketed notes
            if not self.current_chapter:
                continue

            # Check if text starts with a verse number
            verse_match = re.match(r"^(\d+)\.\s+", text)
            if not verse_match and self.current_verse is not None:
                # A few verse numbers lose their period ("2 And I") or misplace it ("2 .For").
                bare = re.match(r"^(\d+)\s+\.?\s*(?=[A-Z])", text)
                if bare and int(bare.group(1)) == self.current_verse + 1:
                    verse_match = bare
            if not verse_match:
                self._add_unnumbered_paragraph(p)
                continue

            verse_num = int(verse_match.group(1))

            # Parse the verse content preserving inline annotations
            verse_content = self.parse_verse_text(p)

            # Remove verse number from the beginning of all content
            verse_content.text = re.sub(r"^\d+\s*\.?\s*", "", verse_content.text)

            # Remove verse number from content_parts
            if verse_content.content_parts and isinstance(verse_content.content_parts[0], str):
                verse_content.content_parts[0] = re.sub(
                    r"^\s*\d+\s*\.?\s*", "", verse_content.content_parts[0]
                )

            if verse_content.has_poetry and verse_content.poetry_lines:
                # Remove verse number from the first poetry line
                first_line = verse_content.poetry_lines[0]
                if first_line and isinstance(first_line[0], str):
                    first_line[0] = re.sub(r"^\s*\d+\s*\.?\s*", "", first_line[0])

                # Split poetry lines into individual per-verse segments
                for seg_verse_num, seg_lines in self.split_multi_verse_poetry_lines(
                    verse_content.poetry_lines, verse_num
                ):
                    seg_content = VerseContent(
                        text="",
                        content_parts=[],
                        has_poetry=True,
                        poetry_lines=seg_lines,
                    )
                    self.add_verse(seg_verse_num, seg_content)
                    LOGGER.debug(f"Added verse {self.current_chapter}.{seg_verse_num}")
            else:
                # Split non-poetry content into individual per-verse segments
                for seg_verse_num, seg_parts in self.split_multi_verse_content(
                    verse_content.content_parts, verse_num
                ):
                    seg_content = VerseContent(
                        text=extract_plain_text(seg_parts),
                        content_parts=seg_parts,
                    )
                    self.add_verse(seg_verse_num, seg_content)
                    LOGGER.debug(f"Added verse {self.current_chapter}.{seg_verse_num}")

    def generate_osis(self) -> pyosis.OsisXML:
        """Build the complete OSIS document from everything parsed so far.

        Checks the final chapter for verse gaps, then wraps the book division in an
        OSIS text with a header (scrape timestamp, 1913 edition, work metadata).

        Returns:
            The OSIS XML document.
        """
        # Check for verse gaps in the final chapter before generating output
        self._check_verse_gaps()

        # Get current date in ISO format
        from datetime import datetime

        current_date = datetime.now().strftime("%Y.%m.%dT%H:%M:%S")

        # Create header with multiple revision descriptions
        header = pyosis.HeaderCt(
            canonical=False,
            revision_desc=[
                # Latest revision - scraping from sacred-texts.com
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
                                "Scraped from https://sacred-texts.com/bib/boe/, and converted to OSIS by Andrew P. Sansom."
                            ]
                        )
                    ],
                ),
                # Original 1913 edition
                pyosis.RevisionDescCt(
                    date=pyosis.DateCt(
                        event=pyosis.OsisEvents.EDITION,
                        type_value="ISO",
                        lang="en",
                        content=["1913"],
                    ),
                    p=[
                        pyosis.PCt(
                            content=[
                                "The Apocrypha and Pseudepigrapha of the Old Testament in English : with introductions and critical and explanatory notes to the several books, Robert Henry Charles."
                            ]
                        )
                    ],
                ),
            ],
            work=[
                pyosis.WorkCt(
                    osis_work=OSIS_BOOK_ID,
                    lang="en",
                    title=[
                        pyosis.TitleCt(canonical=True, content=[BOOK_TITLE]),
                    ],
                    description=[
                        pyosis.DescriptionCt(
                            value='Excerpt from "The Apocrypha and Pseudepigrapha of the Old Testament in English : with introductions and critical and explanatory notes to the several books" by Robert Henry Charles, 1913. Transcribed by Joshua Williams, Northwest Nazarene College, 1995. Converted to OSIS by Andrew P. Sansom, 2026.'
                        )
                    ],
                    type_value=[pyosis.TypeCt(type_value="OSIS", content=["Bible"])],
                    creator=[
                        pyosis.CreatorCt(
                            role=pyosis.OsisRoles.TRL,
                            value="Robert Henry (R.H.) Charles",
                        )
                    ],
                    publisher=[pyosis.PublisherCt(value="The Clarendon Press")],
                ),
            ],
        )

        # Create the OSIS text with all divisions
        divs = []
        if self.root_div:
            divs.append(self.root_div)

        osis_text = pyosis.OsisTextCt(
            lang="en",
            osis_idwork=OSIS_BOOK_ID,
            osis_ref_work=BOOK_SHORT_TITLE,
            canonical=True,
            header=header,
            div=divs,
        )

        # Create the final OSIS XML
        osis_xml = pyosis.OsisXML(pyosis.Osis(osis_text=osis_text))

        return osis_xml

    def process_all_pages(self, start: int = 0, end: int = 112, delay: float = 1.0) -> None:
        """Start the book, then download and parse every page in the range.

        A page that fails to download or parse is logged and skipped.

        Args:
            start: First page number to process
            end: Last page number to process
            delay: Delay between requests in seconds
        """
        self.start_book()

        for page_num in tqdm(range(start, end + 1), desc="Processing pages"):
            try:
                html = self.fetch_page(page_num, delay=delay)
                self.parse_page(html, page_num=page_num)
            except Exception as e:
                LOGGER.error(f"Error processing page {page_num}: {e}")
                continue


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the ``--start-page`` and ``--end-page`` options.

    Args:
        parser: The sub-command parser to add options to.
    """
    parser.add_argument(
        "--start-page",
        type=int,
        default=DEFAULT_START_PAGE,
        help="first page to process (0 is the title page, 4 is Chapter I; default: %(default)s)",
    )
    parser.add_argument(
        "--end-page",
        type=int,
        default=DEFAULT_END_PAGE,
        help="last page to process (default: %(default)s)",
    )


def run(args: argparse.Namespace) -> list[Path]:
    """Scrape the requested pages and write ``1-enoch.xml``.

    Args:
        args: Parsed options with ``cache_dir``, ``delay``, ``start_page``,
            ``end_page`` and ``output_dir``.

    Returns:
        A one-element list with the path of the written OSIS file.
    """
    parser = SacredTextsParser(cache_dir=args.cache_dir, delay=args.delay)

    try:
        LOGGER.info(
            f"Processing pages {args.start_page} to {args.end_page} with {args.delay}s delay"
        )
        parser.process_all_pages(args.start_page, args.end_page, delay=args.delay)

        LOGGER.info("Generating OSIS XML")
        osis_doc = parser.generate_osis()

        output_path = Path(args.output_dir) / OUTPUT_FILENAME
        output_path.parent.mkdir(parents=True, exist_ok=True)

        LOGGER.info(f"Writing to {output_path}")
        output_path.write_text(osis_doc.to_xml(), encoding="utf-8")

        LOGGER.info("Done!")
    finally:
        parser.close()
    return [output_path]


SPEC = ScraperSpec(
    name="1-enoch",
    help="Book of Enoch (R. H. Charles, 1917) to OSIS",
    source="https://archive.sacred-texts.com/bib/boe/",
    outputs=(OUTPUT_FILENAME,),
    run=run,
    add_arguments=add_arguments,
)
