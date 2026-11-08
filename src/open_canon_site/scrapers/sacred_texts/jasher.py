"""Download and parse the Book of Jasher to OSIS XML."""

from __future__ import annotations

import argparse
import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

import pyosis
from bs4 import BeautifulSoup

from open_canon_site.scrapers._http import CachedHttpFetcher
from open_canon_site.scrapers._osis import normalize_whitespace
from open_canon_site.scrapers.base import ScraperSpec
from open_canon_site.scrapers.sacred_texts._layout import (
    book_overview_parts,
    is_book_overview_layout,
    legacy_html,
)

LOGGER = logging.getLogger(__name__)
"""Module logger; warns when an invalid cached page is discarded."""

OUTPUT_FILENAME: Final[str] = "jasher.xml"
"""Name of the OSIS file written into the output directory."""

INDEX_URL: Final[str] = "https://archive.sacred-texts.com/chr/apo/jasher/index.htm"
"""URL of the book's index page (title page, introduction and chapter links)."""
CHAPTER_URL_TEMPLATE: Final[str] = "https://archive.sacred-texts.com/chr/apo/jasher/{page}.htm"
"""``str.format`` template for a chapter page URL; ``{page}`` is the chapter number (``1`` .. ``91``)."""
OSIS_WORK_ID: Final[str] = "Jasher"
"""OSIS work identifier, also the book id prefix (``Jasher.<chapter>.<verse>``)."""
BOOK_TITLE: Final[str] = "The Book of Jasher"
"""Full title; the index page's ``<h1>`` must equal this exactly."""
BOOK_SHORT_TITLE: Final[str] = "Jasher"
"""Short title used for the OSIS main title and ``osisRefWork``."""
EXPECTED_CHAPTERS: Final[list[int]] = list(range(1, 92))
"""The chapter numbers the index page must link to, in order (1 through 91)."""

CHAPTER_HEADING_RE: Final[re.Pattern[str]] = re.compile(
    r"Book of Jasher,\s*Chapter\s*(?P<chapter>\d+)",
    re.IGNORECASE,
)
"""Matches a chapter ``<h1>`` such as ``Book of Jasher, Chapter 12``, capturing the number as ``chapter``."""
VERSE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<verse>\d+)\s+(?P<text>.+)$",
    re.DOTALL,
)
"""Matches a verse paragraph: leading digits, whitespace, then the text (``verse`` and ``text`` groups).

``DOTALL`` lets the text span the line breaks left inside a paragraph.
"""
PARAGRAPH_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"(?i)<p(?:\s+[^>]*)?>")
"""Matches an opening ``<p>`` tag (any case, optional attributes).

Used to split a chapter body into verse fragments, because the pages use bare, unclosed
``<P>`` tags as separators rather than well-formed paragraphs.
"""
TAG_RE: Final[re.Pattern[str]] = re.compile(r"<[^>]+>")
"""Matches any single HTML tag; used to strip markup once line-break tags are converted."""
BODY_AFTER_H1_RE: Final[re.Pattern[str]] = re.compile(
    r"(?is)<h1[^>]*>\s*(?P<heading>.*?)\s*</h1>(?P<body>.*)"
)
"""Matches the first ``<h1>`` (``heading`` group, lazily) and everything after it (``body`` group).

The footer ``<HR>`` is located afterwards inside ``body``.
"""


@dataclass
class FrontMatterSection:
    """A front-matter section (title page or introduction) of the book."""

    title: str
    """Section title rendered as the OSIS main title."""
    div_type: pyosis.OsisDivs
    """OSIS div type: ``titlePage`` for the title page, ``front`` for the introduction."""
    paragraphs: list[str]
    """Non-empty plain-text paragraphs (one per source line) in document order."""


@dataclass
class Verse:
    """A single verse of a chapter."""

    number: int
    """1-based verse number within its chapter."""
    text: str
    """Verse text with markup removed and whitespace normalised."""


@dataclass
class Chapter:
    """A parsed chapter page."""

    number: int
    """Chapter number (1 through 91)."""
    verses: list[Verse]
    """Verses in source order; numbered consecutively from 1."""


class JasherParser:
    """Fetch and parse sacred-texts.com's Book of Jasher into OSIS.

    The site serves an index page plus one page per chapter. Chapter pages are loosely
    structured HTML: an ``<h1>`` heading, then verses separated by bare ``<P>`` tags that
    are never closed, and a footer introduced by an ``<HR>``. Everything after the heading
    and before that ``<HR>`` is the chapter content.
    """

    def __init__(self, cache_dir: str | None = None, delay: float = 1.0) -> None:
        """Create a parser with a caching HTTP fetcher.

        Args:
            cache_dir: Directory for cached pages, or ``None`` to disable caching.
            delay: Seconds to wait around each live request.
        """
        self.http = CachedHttpFetcher(cache_dir=cache_dir, delay=delay, logger=LOGGER)
        """Fetcher used for the index and chapter pages."""

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self.http.close()

    def fetch_index_text(self) -> str:
        """Return the validated index page HTML, from cache or the network.

        A fetched page that is not the real index (for example a Cloudflare interstitial)
        makes the underlying helper raise ``RuntimeError``.

        Returns:
            Raw HTML of the index page.
        """
        return self._fetch_validated_page(
            url=INDEX_URL,
            validator=self.is_valid_index,
            invalid_error=(
                "Source page did not contain the Book of Jasher index; direct access "
                "to sacred-texts.com may be blocked in this environment"
            ),
        )

    def fetch_chapter_text(self, chapter_number: int) -> str:
        """Return the validated HTML of one chapter page, from cache or the network.

        Args:
            chapter_number: Chapter to fetch (1-based).

        A fetched page that is not that chapter (for example a Cloudflare interstitial)
        makes the underlying helper raise ``RuntimeError``.

        Returns:
            Raw HTML of the chapter page.
        """
        return self._fetch_validated_page(
            url=CHAPTER_URL_TEMPLATE.format(page=chapter_number),
            validator=lambda text: self.is_valid_chapter_page(text, chapter_number),
            invalid_error=(
                f"Source page did not contain the Book of Jasher chapter {chapter_number}; "
                "direct access to sacred-texts.com may be blocked in this environment"
            ),
        )

    def _fetch_validated_page(
        self,
        *,
        url: str,
        validator: callable,
        invalid_error: str,
    ) -> str:
        """Fetch a page, preferring a valid cached copy and never keeping an invalid one.

        An invalid cached file is logged and deleted before refetching. An invalid fetched
        page also removes any cache entry so a bad response is not reused.

        Args:
            url: Page URL.
            validator: Callable taking the page text and returning whether it is genuine.
            invalid_error: Message for the ``RuntimeError`` raised when the fetched page fails
                validation.

        Returns:
            The valid page text.

        Raises:
            RuntimeError: If the freshly fetched page fails validation.
        """
        cache_path = self.http.cache_path_for(url)
        if cache_path and cache_path.exists():
            cached = cache_path.read_text(encoding="utf-8")
            if validator(cached):
                return cached

            LOGGER.warning("Discarding invalid cached Jasher source at %s", cache_path)
            cache_path.unlink()

        fetched = self.http.fetch_text(url=url)
        if validator(fetched):
            return fetched

        if cache_path and cache_path.exists():
            cache_path.unlink()

        raise RuntimeError(invalid_error)

    @staticmethod
    def is_valid_index(text: str) -> bool:
        """Report whether text is the genuine Jasher index page.

        Args:
            text: Raw page HTML.

        Returns:
            For an old-layout page, True if it has the book title, the "Faithfully
            Translated" subtitle and a link to chapter 91, and is not a Cloudflare
            interstitial ("Just a moment"). For a redesigned book overview page, True if its
            title is ``BOOK_TITLE`` and its table of contents counts 91 chapters.
        """
        if is_book_overview_layout(text):
            title, _, chapter_count = book_overview_parts(text)
            return title == BOOK_TITLE and chapter_count == len(EXPECTED_CHAPTERS)
        return (
            "The Book of Jasher" in text
            and "Faithfully Translated" in text
            and '<A HREF="91.htm">Chapter 91</A>' in text
            and "Just a moment" not in text
        )

    @staticmethod
    def is_valid_chapter_page(text: str, chapter_number: int) -> bool:
        """Report whether text is the genuine page for the given chapter.

        Args:
            text: Raw page HTML.
            chapter_number: Chapter the page should contain.

        Returns:
            True if the heading names that chapter, a verse-1 paragraph (``<P>1 ...``) is
            present in the main content (isolated with ``legacy_html``) and it is not a
            Cloudflare interstitial ("Just a moment").
        """
        content = legacy_html(text)
        return (
            f"Book of Jasher, Chapter {chapter_number}" in content
            and "Just a moment" not in text
            and bool(re.search(r"(?i)<p(?:\s+[^>]*)?>\s*1\s+", content))
        )

    @staticmethod
    def _strip_tags(fragment: str) -> str:
        """Convert an HTML fragment to text, turning ``<br>`` and ``</p>`` into newlines.

        Args:
            fragment: HTML fragment.

        Returns:
            Text with all tags removed and entities unescaped.
        """
        text = re.sub(r"(?i)<br\s*/?>", "\n", fragment)
        text = re.sub(r"(?i)</p>", "\n", text)
        text = TAG_RE.sub("", text)
        return html.unescape(text)

    @classmethod
    def _extract_content_after_heading(cls, raw_html: str) -> tuple[str, str]:
        """Split a page into its ``<h1>`` heading text and the content before the footer ``<HR>``.

        The main content is isolated with ``legacy_html`` first, so a redesigned reader-layout
        page yields the same split as the old page.

        Args:
            raw_html: Raw page HTML.

        Returns:
            ``(heading, content_html)``; the heading has tags stripped and whitespace
            normalised, the content runs from after ``</h1>`` up to the first ``<hr``.

        Raises:
            RuntimeError: If there is no ``<h1>`` or no later ``<hr>``.
        """
        match = BODY_AFTER_H1_RE.search(legacy_html(raw_html))
        if not match:
            raise RuntimeError("Could not locate Jasher heading in source HTML")

        heading = normalize_whitespace(cls._strip_tags(match.group("heading")))
        body = match.group("body")
        next_hr_index = re.search(r"(?i)<hr\b", body)
        if not next_hr_index:
            raise RuntimeError("Could not locate end of Jasher content block")

        return heading, body[: next_hr_index.start()]

    @classmethod
    def _extract_lines(cls, raw_html_fragment: str) -> list[str]:
        """Convert an HTML fragment into non-empty, whitespace-normalised text lines.

        Args:
            raw_html_fragment: HTML fragment.

        Returns:
            One string per non-blank line after tag stripping.
        """
        text = cls._strip_tags(raw_html_fragment)
        return [
            normalized
            for raw_line in text.splitlines()
            if (normalized := normalize_whitespace(raw_line))
        ]

    @classmethod
    def parse_front_matter(cls, raw_index_html: str) -> list[FrontMatterSection]:
        """Extract the title page and introduction from the index page.

        The title page lines come from the ``<h6>``/``<h5>`` headings and the ``<font>`` block;
        the introduction is the text after the closing ``</CENTER>`` minus those lines.

        A redesigned book overview page no longer carries the title page block, so its title
        page has no lines; its introduction is the "About this book" blurb.

        Args:
            raw_index_html: Raw index page HTML.

        Returns:
            Two sections: the title page and the introduction.

        Raises:
            RuntimeError: If the heading is not ``BOOK_TITLE`` or the structure is missing.
        """
        if is_book_overview_layout(raw_index_html):
            return cls._parse_book_overview_front_matter(raw_index_html)

        heading, content_html = cls._extract_content_after_heading(raw_index_html)
        if heading != BOOK_TITLE:
            raise RuntimeError(
                f"Unexpected Jasher index heading: expected {BOOK_TITLE!r}, got {heading!r}"
            )

        soup = BeautifulSoup(content_html, "html.parser")

        title_page_lines = [
            normalize_whitespace(tag.get_text(" ", strip=True))
            for tag in soup.find_all(["h6", "h5"])
        ]
        title_page_lines = [line for line in title_page_lines if line]

        font_tag = soup.find("font")
        if font_tag is not None:
            title_page_lines.extend(cls._extract_lines(font_tag.decode_contents()))

        intro_html = content_html
        if "</CENTER>" in intro_html:
            intro_html = intro_html.rsplit("</CENTER>", 1)[1]

        intro_paragraphs = cls._extract_lines(intro_html)
        intro_paragraphs = [
            paragraph
            for paragraph in intro_paragraphs
            if paragraph not in title_page_lines and paragraph != heading
        ]

        return [
            FrontMatterSection(
                title=BOOK_TITLE,
                div_type=pyosis.OsisDivs.TITLE_PAGE,
                paragraphs=title_page_lines,
            ),
            FrontMatterSection(
                title="Introduction",
                div_type=pyosis.OsisDivs.FRONT,
                paragraphs=intro_paragraphs,
            ),
        ]

    @classmethod
    def _parse_book_overview_front_matter(cls, raw_index_html: str) -> list[FrontMatterSection]:
        """Extract the front matter from a redesigned book overview (index) page.

        Args:
            raw_index_html: Raw book overview page HTML.

        Returns:
            Two sections: a title page without lines (the overview page omits the old
            title page block) and the "About this book" paragraphs as the introduction.

        Raises:
            RuntimeError: If the overview title is not ``BOOK_TITLE``.
        """
        title, about_html, _ = book_overview_parts(raw_index_html)
        if title != BOOK_TITLE:
            raise RuntimeError(
                f"Unexpected Jasher index heading: expected {BOOK_TITLE!r}, got {title!r}"
            )
        intro_paragraphs = cls._extract_lines("".join(about_html))
        return [
            FrontMatterSection(
                title=BOOK_TITLE,
                div_type=pyosis.OsisDivs.TITLE_PAGE,
                paragraphs=[],
            ),
            FrontMatterSection(
                title="Introduction",
                div_type=pyosis.OsisDivs.FRONT,
                paragraphs=intro_paragraphs,
            ),
        ]

    @staticmethod
    def extract_chapter_numbers(raw_index_html: str) -> list[int]:
        """List the chapter numbers linked from the index page.

        Only anchors whose ``href`` is ``<digits>.htm`` count; duplicates are dropped. A
        redesigned book overview page paginates its table of contents, so there the
        chapters are ``1`` through the stated chapter count (empty if it has none).

        Args:
            raw_index_html: Raw index page HTML.

        Returns:
            Chapter numbers in order of first appearance.
        """
        if is_book_overview_layout(raw_index_html):
            _, _, chapter_count = book_overview_parts(raw_index_html)
            return list(range(1, (chapter_count or 0) + 1))

        soup = BeautifulSoup(raw_index_html, "html.parser")
        chapter_numbers: list[int] = []
        seen: set[int] = set()

        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href.endswith(".htm"):
                continue

            stem = href[:-4]
            if not stem.isdigit():
                continue

            chapter_number = int(stem)
            if chapter_number in seen:
                continue

            chapter_numbers.append(chapter_number)
            seen.add(chapter_number)

        return chapter_numbers

    @classmethod
    def parse_chapter(cls, chapter_number: int, raw_html: str) -> Chapter:
        """Parse a chapter page into verses.

        The content is split on bare ``<P>`` tags. Empty fragments, bare numbers and the
        ``THE END`` marker are skipped; every other fragment must start with its verse number.

        Args:
            chapter_number: Chapter the page is expected to contain.
            raw_html: Raw chapter page HTML.

        Returns:
            The parsed chapter.

        Raises:
            RuntimeError: If the heading is missing or names another chapter, a paragraph has
                no verse number, no verses are found, or verse numbers are not 1..N.
        """
        heading, content_html = cls._extract_content_after_heading(raw_html)
        heading_match = CHAPTER_HEADING_RE.search(heading)
        if not heading_match:
            raise RuntimeError(f"Could not determine Jasher chapter from heading: {heading}")

        actual_chapter_number = int(heading_match.group("chapter"))
        if actual_chapter_number != chapter_number:
            raise RuntimeError(
                f"Unexpected Jasher chapter heading: expected {chapter_number}, got {actual_chapter_number}"
            )

        verses: list[Verse] = []
        for fragment in PARAGRAPH_SPLIT_RE.split(content_html):
            text = normalize_whitespace(cls._strip_tags(fragment))
            if not text or text == "THE END" or text.isdigit():
                continue

            verse_match = VERSE_RE.match(text)
            if not verse_match:
                raise RuntimeError(
                    f"Could not parse Jasher chapter {chapter_number} paragraph: {text}"
                )

            verses.append(
                Verse(
                    number=int(verse_match.group("verse")),
                    text=normalize_whitespace(verse_match.group("text")),
                )
            )

        if not verses:
            raise RuntimeError(f"No verses parsed for Jasher chapter {chapter_number}")

        expected_verses = list(range(1, len(verses) + 1))
        actual_verses = [verse.number for verse in verses]
        if actual_verses != expected_verses:
            raise RuntimeError(
                f"Unexpected Jasher verse sequence in chapter {chapter_number}: expected {expected_verses}, got {actual_verses}"
            )

        return Chapter(number=chapter_number, verses=verses)

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
            and verse ids ``Jasher.<chapter>.<verse>``.
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
                        *[pyosis.PCt(content=[paragraph]) for paragraph in section.paragraphs],
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

            for verse in chapter.verses:
                chapter_div.content.append(
                    pyosis.VerseCt(
                        osis_id=[f"{OSIS_WORK_ID}.{chapter.number}.{verse.number}"],
                        canonical=True,
                        content=[verse.text],
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
                                "Scraped from https://www.sacred-texts.com/chr/apo/jasher/ and converted to OSIS by Andrew P. Sansom."
                            ]
                        )
                    ],
                ),
                pyosis.RevisionDescCt(
                    date=pyosis.DateCt(
                        event=pyosis.OsisEvents.EDITION,
                        type_value="ISO",
                        lang="en",
                        content=["1887"],
                    ),
                    p=[
                        pyosis.PCt(
                            content=[
                                "The Book of Jasher, faithfully translated from the original Hebrew into English and published by J.H. Parry & Company, Salt Lake City, 1887."
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
                            value="The Book of Jasher from the 1887 English edition published by J.H. Parry & Company. Transcribed at sacred-texts.com and converted to OSIS by the open-canon-site scrapers."
                        )
                    ],
                    type_value=[pyosis.TypeCt(type_value="OSIS", content=["Bible"])],
                    publisher=[pyosis.PublisherCt(value="J.H. Parry & Company")],
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
        """Run the full pipeline: fetch, validate, parse and convert.

        Returns:
            The OSIS document.

        Raises:
            RuntimeError: If the index does not link exactly chapters 1 through 91, or any
                page fails validation or parsing.
        """
        index_text = self.fetch_index_text()
        chapter_numbers = self.extract_chapter_numbers(index_text)
        if chapter_numbers != EXPECTED_CHAPTERS:
            raise RuntimeError(
                f"Unexpected Jasher chapter sequence: expected {EXPECTED_CHAPTERS}, got {chapter_numbers}"
            )

        front_matter = self.parse_front_matter(index_text)
        chapters = [
            self.parse_chapter(chapter_number, self.fetch_chapter_text(chapter_number))
            for chapter_number in chapter_numbers
        ]
        return self.generate_osis(front_matter, chapters)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register scraper-specific options; Jasher has none.

    Args:
        parser: Sub-parser to extend (left unchanged).
    """


def run(args: argparse.Namespace) -> list[Path]:
    """Scrape the Book of Jasher and write ``jasher.xml``.

    Args:
        args: Parsed CLI arguments providing ``cache_dir``, ``delay`` and ``output_dir``.

    Returns:
        A one-element list with the written file's path.
    """
    parser = JasherParser(cache_dir=args.cache_dir, delay=args.delay)
    try:
        osis_doc = parser.process()
        output_path = Path(args.output_dir) / OUTPUT_FILENAME
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(osis_doc.to_xml(), encoding="utf-8")
    finally:
        parser.close()
    return [output_path]


SPEC = ScraperSpec(
    name="jasher",
    help="Book of Jasher (1887 Parry & Company edition) to OSIS",
    source="https://archive.sacred-texts.com/chr/apo/jasher/",
    outputs=(OUTPUT_FILENAME,),
    run=run,
    add_arguments=add_arguments,
)
"""Registry entry that exposes this scraper to the CLI."""
