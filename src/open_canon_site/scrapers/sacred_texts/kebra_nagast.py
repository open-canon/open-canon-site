"""Download and parse E. A. Wallis Budge's translation of the Kebra Nagast to OSIS XML.

Source: https://archive.sacred-texts.com/chr/kn/ (``index.htm``, then ``kn001.htm`` ..
``kn117.htm`` for the 117 numbered chapters and ``kn118.htm`` for the colophon). The
archive host still serves the original page layout.

Versification
-------------
The translation has chapters but no verse numbers: each chapter is a run of plain
paragraphs. Other unversified texts in this project either carry verse numbers in the
source (Vita Adae et Evae, Jasher) or number paragraphs the way the printed edition does
(Forgotten Books of Eden). Following the paragraph convention, **each source paragraph is
one verse**: ``Kebra-Nagast.<chapter>.<n>``, with ``n`` counting the chapter's paragraphs
from 1. Chapter numbers are Budge's own (1 to 117), so a reference such as
``Kebra-Nagast.28.3`` points at the third paragraph of Budge's chapter 28. The numbering
follows the sacred-texts transcription of the paragraph breaks and is not a traditional
Ethiopian versification; it is stable for a given source text but is a project convention.

Scope
-----
* Canonical text: the 117 chapters. The chapter heading's title becomes the OSIS chapter
  title.
* The invocation printed before chapter 1 ("In praising God the Father ...") is kept as a
  non-canonical ``introduction`` div titled "Invocation", so it does not shift chapter 1's
  verse numbers.
* The colophon (``kn118.htm``) is kept as a non-canonical ``colophon`` div.
* Budge's title page, prefaces, list of plates and long introduction (``kn000-*.htm``) are
  editorial front matter, not part of the text, and are left out. So are his footnotes and
  the printed page markers (``p. 12``) and footnote reference marks inside the paragraphs.
"""

from __future__ import annotations

import argparse
import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Final

import pyosis

from open_canon_site.scrapers._http import CachedHttpFetcher
from open_canon_site.scrapers._osis import normalize_whitespace
from open_canon_site.scrapers.base import ScraperSpec
from open_canon_site.scrapers.sacred_texts._layout import legacy_html

LOGGER = logging.getLogger(__name__)
"""Module logger; warns when an invalid cached page is discarded."""

OUTPUT_FILENAME: Final[str] = "kebra-nagast.xml"
"""Name of the OSIS file written into the output directory."""

INDEX_URL: Final[str] = "https://archive.sacred-texts.com/chr/kn/index.htm"
"""URL of the book's index page (table of contents)."""
PAGE_URL_TEMPLATE: Final[str] = "https://archive.sacred-texts.com/chr/kn/kn{page:03d}.htm"
"""``str.format`` template for a page URL; ``{page}`` is the page number (``1`` .. ``118``)."""
OSIS_WORK_ID: Final[str] = "Kebra-Nagast"
"""OSIS work identifier, also the book id prefix (``Kebra-Nagast.<chapter>.<verse>``)."""
BOOK_TITLE: Final[str] = "The Kebra Nagast"
"""Full title used for the OSIS main title."""
BOOK_SHORT_TITLE: Final[str] = "Kebra Nagast"
"""Short title used for the OSIS main title and ``osisRefWork``."""
CHAPTER_COUNT: Final[int] = 117
"""Number of numbered chapters (pages ``kn001`` .. ``kn117``)."""
COLOPHON_PAGE: Final[int] = 118
"""Page number of the colophon."""
EXPECTED_PAGES: Final[list[int]] = list(range(1, COLOPHON_PAGE + 1))
"""Page numbers the index must link to, in order: 117 chapters then the colophon."""

PAGE_LINK_RE: Final[re.Pattern[str]] = re.compile(
    r"""href\s*=\s*["']kn(?P<page>\d{3})\.htm["']""", re.I
)
"""Matches an index link to a text page (``kn001.htm``), capturing ``page`` as digits."""
HEADING_RE: Final[re.Pattern[str]] = re.compile(r"(?is)<h3[^>]*>(?P<heading>.*?)</h3>")
"""Matches a ``<h3>`` heading, capturing its inner HTML as ``heading``."""
H1_END_RE: Final[re.Pattern[str]] = re.compile(r"(?i)</h1>")
"""Matches the end of a page's ``<h1>`` (only the first page has one)."""
CHAPTER_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^(?P<number>\d+)\.\s*(?P<title>.+)$")
"""Matches chapter heading text such as ``28. How Solomon gave ...`` (``number``, ``title``)."""
CONTENT_END_RE: Final[re.Pattern[str]] = re.compile(
    r"""(?is)<h3[^>]*>\s*Footnotes|<hr\b|<div\s+class\s*=\s*["']filenav"""
)
"""Matches the first thing after the prose: the ``Footnotes`` heading, an ``<hr>`` or the nav block."""
PARAGRAPH_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"(?i)<p(?:\s+[^>]*)?>")
"""Matches an opening ``<p>`` tag; the pages use bare, unclosed ``<P>`` tags as separators."""
ANCHOR_RE: Final[re.Pattern[str]] = re.compile(r"(?is)<a\b[^>]*>.*?</a>")
"""Matches a whole ``<a>`` element; in the prose these are page markers and footnote marks."""
TAG_RE: Final[re.Pattern[str]] = re.compile(r"<[^>]+>")
"""Matches any single HTML tag."""


@dataclass
class Chapter:
    """A parsed chapter page."""

    number: int
    """Chapter number (1 through 117)."""
    title: str
    """Chapter title without its number, e.g. ``Concerning the Glory of Kings``."""
    verses: list[str]
    """Paragraph texts in source order; verse ``n`` is ``verses[n - 1]``."""


@dataclass
class Colophon:
    """The colophon page."""

    title: str
    """Heading text (``Colophon``)."""
    paragraphs: list[str]
    """Paragraph texts in source order."""


@dataclass
class Book:
    """The parsed book."""

    invocation: list[str]
    """Paragraphs printed before chapter 1's heading."""
    chapters: list[Chapter]
    """The 117 chapters in order."""
    colophon: Colophon
    """The closing colophon."""


class KebraNagastParser:
    """Fetch and parse sacred-texts.com's Kebra Nagast into OSIS.

    Every page is loosely structured HTML: navigation, an ``<h3>`` heading, bare ``<P>``
    paragraphs (with page markers and footnote marks inline), an optional ``Footnotes``
    section and a navigation footer. The paragraphs between the heading and the first
    footnote heading, ``<hr>`` or nav block are the chapter text.
    """

    def __init__(self, cache_dir: str | None = None, delay: float = 1.0) -> None:
        """Create a parser with a caching HTTP fetcher.

        Args:
            cache_dir: Directory for cached pages, or ``None`` to disable caching.
            delay: Seconds to wait around each live request.
        """
        self.http = CachedHttpFetcher(cache_dir=cache_dir, delay=delay, logger=LOGGER)
        """Fetcher used for the index and text pages."""

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self.http.close()

    def fetch_index_text(self) -> str:
        """Return the validated index page HTML, from cache or the network.

        Returns:
            Raw HTML of the index page.
        """
        return self._fetch_validated_page(
            url=INDEX_URL,
            validator=self.is_valid_index,
            invalid_error=(
                "Source page did not contain the Kebra Nagast index; direct access "
                "to sacred-texts.com may be blocked in this environment"
            ),
        )

    def fetch_page_text(self, page: int) -> str:
        """Return the validated HTML of one text page, from cache or the network.

        Args:
            page: Page number (``1`` .. ``118``).

        Returns:
            Raw HTML of the page.
        """
        return self._fetch_validated_page(
            url=PAGE_URL_TEMPLATE.format(page=page),
            validator=lambda text: self.is_valid_page(text, page),
            invalid_error=(
                f"Source page did not contain Kebra Nagast page {page}; "
                "direct access to sacred-texts.com may be blocked in this environment"
            ),
        )

    def _fetch_validated_page(
        self,
        *,
        url: str,
        validator: Callable[[str], bool],
        invalid_error: str,
    ) -> str:
        """Fetch a page, preferring a valid cached copy and never keeping an invalid one.

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

            LOGGER.warning("Discarding invalid cached Kebra Nagast source at %s", cache_path)
            cache_path.unlink()

        fetched = self.http.fetch_text(url=url)
        if validator(fetched):
            return fetched

        if cache_path and cache_path.exists():
            cache_path.unlink()

        raise RuntimeError(invalid_error)

    @classmethod
    def is_valid_index(cls, text: str) -> bool:
        """Report whether text is the genuine Kebra Nagast index page.

        Args:
            text: Raw page HTML.

        Returns:
            True if it names the book, links to exactly pages 1 through 118 (so a truncated
            index is rejected and refetched) and is not a Cloudflare interstitial
            ("Just a moment").
        """
        return (
            "Kebra Nagast" in text
            and cls.extract_pages(text) == EXPECTED_PAGES
            and "Just a moment" not in text
        )

    @classmethod
    def is_valid_page(cls, text: str, page: int) -> bool:
        """Report whether text is the genuine page with the given number.

        Args:
            text: Raw page HTML.
            page: Expected page number; ``COLOPHON_PAGE`` expects the colophon heading.

        Returns:
            True if the heading is that chapter's (or the colophon's), at least one paragraph
            follows and it is not a Cloudflare interstitial ("Just a moment").
        """
        if "Just a moment" in text:
            return False
        try:
            heading, body = cls._split_page(text)
        except RuntimeError:
            return False
        if page == COLOPHON_PAGE:
            valid_heading = heading == "Colophon"
        else:
            match = CHAPTER_HEADING_RE.match(heading)
            valid_heading = bool(match) and int(match.group("number")) == page
        return valid_heading and bool(cls._paragraphs(body))

    @staticmethod
    def extract_pages(raw_index_html: str) -> list[int]:
        """List the text page numbers linked from the index page.

        Args:
            raw_index_html: Raw index page HTML.

        Returns:
            Page numbers (``kn001.htm`` gives ``1``) in order of first appearance; the
            ``kn000-N.htm`` front matter pages do not match.
        """
        pages: list[int] = []
        for match in PAGE_LINK_RE.finditer(raw_index_html):
            page = int(match.group("page"))
            if page and page not in pages:
                pages.append(page)
        return pages

    @staticmethod
    def _plain(fragment: str) -> str:
        """Convert an HTML fragment to whitespace-normalised plain text.

        Whole ``<a>`` elements (page markers, footnote marks) are dropped, other tags are
        removed and entities are unescaped.

        Args:
            fragment: HTML fragment.

        Returns:
            The plain text.
        """
        text = ANCHOR_RE.sub("", fragment)
        text = re.sub(r"(?i)<br\s*/?>", " ", text)
        return normalize_whitespace(html.unescape(TAG_RE.sub("", text)))

    @classmethod
    def _paragraphs(cls, body_html: str) -> list[str]:
        """Split prose HTML on ``<p>`` tags into non-empty plain-text paragraphs.

        Args:
            body_html: HTML of the prose.

        Returns:
            One string per non-empty paragraph.
        """
        texts = (cls._plain(fragment) for fragment in PARAGRAPH_SPLIT_RE.split(body_html))
        return [text for text in texts if text]

    @classmethod
    def _split_page(cls, raw_html: str) -> tuple[str, str]:
        """Split a page into its heading text and the prose HTML after it.

        Args:
            raw_html: Raw page HTML.

        Returns:
            ``(heading, prose_html)``; the prose stops at the footnotes, an ``<hr>`` or the
            navigation block.

        Raises:
            RuntimeError: If the page has no ``<h3>`` heading.
        """
        content = legacy_html(raw_html)
        match = HEADING_RE.search(content)
        if not match:
            raise RuntimeError("Could not locate Kebra Nagast heading in source HTML")
        heading = cls._plain(match.group("heading"))
        rest = content[match.end() :]
        end = CONTENT_END_RE.search(rest)
        return heading, rest[: end.start()] if end else rest

    @classmethod
    def parse_invocation(cls, raw_html: str) -> list[str]:
        """Extract the paragraphs printed between a page's ``<h1>`` and its chapter heading.

        Args:
            raw_html: Raw HTML of the first page.

        Returns:
            The invocation paragraphs; empty if the page has no ``<h1>`` before its heading.
        """
        content = legacy_html(raw_html)
        heading = HEADING_RE.search(content)
        h1_end = H1_END_RE.search(content)
        if not heading or not h1_end or h1_end.end() > heading.start():
            return []
        return cls._paragraphs(content[h1_end.end() : heading.start()])

    @classmethod
    def parse_chapter(cls, number: int, raw_html: str) -> Chapter:
        """Parse a chapter page.

        Args:
            number: Chapter the page is expected to contain.
            raw_html: Raw page HTML.

        Returns:
            The chapter, one verse per paragraph.

        Raises:
            RuntimeError: If the heading is not that chapter's or there are no paragraphs.
        """
        heading, body = cls._split_page(raw_html)
        match = CHAPTER_HEADING_RE.match(heading)
        if not match:
            raise RuntimeError(f"Could not determine Kebra Nagast chapter from heading: {heading}")
        if int(match.group("number")) != number:
            raise RuntimeError(
                f"Unexpected Kebra Nagast chapter heading: expected {number}, "
                f"got {match.group('number')}"
            )
        verses = cls._paragraphs(body)
        if not verses:
            raise RuntimeError(f"No paragraphs parsed for Kebra Nagast chapter {number}")
        return Chapter(number=number, title=match.group("title").strip(), verses=verses)

    @classmethod
    def parse_colophon(cls, raw_html: str) -> Colophon:
        """Parse the colophon page.

        Args:
            raw_html: Raw page HTML.

        Returns:
            The colophon.

        Raises:
            RuntimeError: If the heading is not ``Colophon`` or there are no paragraphs.
        """
        heading, body = cls._split_page(raw_html)
        if heading != "Colophon":
            raise RuntimeError(f"Unexpected Kebra Nagast colophon heading: {heading}")
        paragraphs = cls._paragraphs(body)
        if not paragraphs:
            raise RuntimeError("No paragraphs parsed for the Kebra Nagast colophon")
        return Colophon(title=heading, paragraphs=paragraphs)

    @staticmethod
    def generate_osis(book: Book) -> pyosis.OsisXML:
        """Build the OSIS document for the book.

        Args:
            book: The parsed book.

        Returns:
            An OSIS document with an optional non-canonical invocation, one canonical chapter
            div per chapter (verse ids ``Kebra-Nagast.<chapter>.<verse>``) and a
            non-canonical colophon.
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

        if book.invocation:
            book_div.content.append(
                pyosis.DivCt(
                    type_value=pyosis.OsisDivs.INTRODUCTION,
                    canonical=False,
                    content=[
                        pyosis.TitleCt(
                            type_value=pyosis.OsisTitles.MAIN,
                            canonical=False,
                            content=["Invocation"],
                        ),
                        *[pyosis.PCt(content=[paragraph]) for paragraph in book.invocation],
                    ],
                )
            )

        for chapter in book.chapters:
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
            for number, text in enumerate(chapter.verses, start=1):
                chapter_div.content.append(
                    pyosis.VerseCt(
                        osis_id=[f"{OSIS_WORK_ID}.{chapter.number}.{number}"],
                        canonical=True,
                        content=[text],
                    )
                )
            book_div.content.append(chapter_div)

        book_div.content.append(
            pyosis.DivCt(
                type_value=pyosis.OsisDivs.COLOPHON,
                canonical=False,
                content=[
                    pyosis.TitleCt(
                        type_value=pyosis.OsisTitles.MAIN,
                        canonical=False,
                        content=[book.colophon.title],
                    ),
                    *[pyosis.PCt(content=[paragraph]) for paragraph in book.colophon.paragraphs],
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
                                "Scraped from https://sacred-texts.com/chr/kn/ and converted to OSIS by the open-canon-site scrapers. Each source paragraph is one verse."
                            ]
                        )
                    ],
                ),
                pyosis.RevisionDescCt(
                    date=pyosis.DateCt(
                        event=pyosis.OsisEvents.EDITION,
                        type_value="ISO",
                        lang="en",
                        content=["1932"],
                    ),
                    p=[
                        pyosis.PCt(
                            content=[
                                "The Queen of Sheba and her only son Menyelek (I): being the Book of the Glory of Kings (Kebra Nagast), translated by E. A. Wallis Budge, Oxford University Press, 1932 (first published 1922)."
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
                            value="The Kebra Nagast (Book of the Glory of Kings) in E. A. Wallis Budge's English translation. Transcribed at sacred-texts.com and converted to OSIS by the open-canon-site scrapers; verses are the source paragraphs."
                        )
                    ],
                    type_value=[pyosis.TypeCt(type_value="OSIS", content=["Bible"])],
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
            RuntimeError: If the index does not link exactly pages 1 through 118, or any page
                fails validation or parsing.
        """
        pages = self.extract_pages(self.fetch_index_text())
        if pages != EXPECTED_PAGES:
            raise RuntimeError(
                f"Unexpected Kebra Nagast page sequence: expected {len(EXPECTED_PAGES)} pages "
                f"(1 to {COLOPHON_PAGE}), got {pages}"
            )

        first_page = self.fetch_page_text(1)
        chapters = [self.parse_chapter(1, first_page)]
        chapters.extend(
            self.parse_chapter(number, self.fetch_page_text(number))
            for number in range(2, CHAPTER_COUNT + 1)
        )
        book = Book(
            invocation=self.parse_invocation(first_page),
            chapters=chapters,
            colophon=self.parse_colophon(self.fetch_page_text(COLOPHON_PAGE)),
        )
        return self.generate_osis(book)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register scraper-specific options; the Kebra Nagast has none.

    Args:
        parser: Sub-parser to extend (left unchanged).
    """


def run(args: argparse.Namespace) -> list[Path]:
    """Scrape the Kebra Nagast and write ``kebra-nagast.xml``.

    Args:
        args: Parsed CLI arguments providing ``cache_dir``, ``delay`` and ``output_dir``.

    Returns:
        A one-element list with the written file's path.
    """
    parser = KebraNagastParser(cache_dir=args.cache_dir, delay=args.delay)
    try:
        osis_doc = parser.process()
        output_path = Path(args.output_dir) / OUTPUT_FILENAME
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(osis_doc.to_xml(), encoding="utf-8")
    finally:
        parser.close()
    return [output_path]


SPEC = ScraperSpec(
    name="kebra-nagast",
    help="Kebra Nagast (Budge's English translation) to OSIS",
    source="https://archive.sacred-texts.com/chr/kn/",
    outputs=(OUTPUT_FILENAME,),
    run=run,
    add_arguments=add_arguments,
)
"""Registry entry that exposes this scraper to the CLI."""
