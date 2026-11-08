"""Download and parse Vita Adae et Evae to OSIS XML."""

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

from open_canon_site.scrapers._http import CachedHttpFetcher
from open_canon_site.scrapers._osis import normalize_whitespace, roman_to_int
from open_canon_site.scrapers.base import ScraperSpec
from open_canon_site.scrapers.sacred_texts._layout import legacy_html

LOGGER = logging.getLogger(__name__)
"""Module logger; warns when an invalid cached page is discarded."""

OUTPUT_FILENAME: Final[str] = "vita-adae-et-evae.xml"
"""Name of the OSIS file written into the output directory."""

SOURCE_URL: Final[str] = "https://sacred-texts.com/chr/apo/adamnev.htm"
"""URL of the single page holding the whole book."""
OSIS_WORK_ID: Final[str] = "vita-adae-et-evae"
"""OSIS work identifier, also the book id prefix (``vita-adae-et-evae.<chapter>.<verse>``)."""
BOOK_TITLE: Final[str] = "Vita Adae et Evae"
"""Full title of the book."""
BOOK_SHORT_TITLE: Final[str] = "Vita Adae et Evae"
"""Short title used for the OSIS main title and ``osisRefWork``."""

CHAPTER_START_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<chapter>[ivxlcdm]+)\s+(?P<verses>[0-9I](?:,[0-9I])*)\s+(?P<text>.+)$",
    re.IGNORECASE,
)
"""Matches a line that opens a chapter: lower-case Roman numeral, verse token, then text,
e.g. ``i 1 When they were driven out`` or ``xxx 1,2 Then ...`` (``chapter``, ``verses``
and ``text`` groups). The verse token is digits or ``I`` (an OCR'd ``1``), comma-joined.
"""
VERSE_START_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<verses>[0-9I](?:,[0-9I])*)\s+(?P<text>.+)$",
    re.IGNORECASE,
)
"""Matches a line that opens a verse within the current chapter: a verse token (digits or
``I``, comma-joined for verse groups) followed by text (``verses`` and ``text`` groups).
"""


@dataclass
class VerseBlock:
    """One verse, or a group of verses printed together, from the source."""

    verse_numbers: list[int]
    """Verse numbers covered, e.g. ``[1, 2]`` for a ``1,2`` marker."""
    text: str
    """Verse text with whitespace normalised."""


@dataclass
class Chapter:
    """A parsed chapter."""

    number: int
    """Chapter number (1 through 51)."""
    verses: list[VerseBlock]
    """Verse blocks in source order."""


class VitaAdaeEtEvaeParser:
    """Fetch and parse sacred-texts.com's Vita Adae et Evae into OSIS.

    The whole book is one HTML page: an ``<h1>`` title, a bold source/edition line, then
    text lines carrying inline markers ``<roman chapter> <verse> text`` for the first verse
    of a chapter and ``<verse> text`` for the others, with ``I`` standing in for ``1``.
    Two chapters (32 and 37) lack a printed marker and are recognised by their opening words.
    """

    def __init__(self, cache_dir: str | None = None, delay: float = 1.0) -> None:
        """Create a parser with a caching HTTP fetcher.

        Args:
            cache_dir: Directory for cached pages, or ``None`` to disable caching.
            delay: Seconds to wait around each live request.
        """
        self.http = CachedHttpFetcher(cache_dir=cache_dir, delay=delay, logger=LOGGER)
        """Fetcher used for the source page."""
        self.cache_dir = Path(cache_dir) if cache_dir else None
        """Cache directory as a ``Path``, or ``None`` when caching is disabled."""

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self.http.close()

    def fetch_source_text(self) -> str:
        """Return the validated source page, from cache or the network.

        An invalid cached copy is logged and deleted; an invalid fetched page also removes
        its cache entry (for example a Cloudflare interstitial).

        Returns:
            Raw page text.

        Raises:
            RuntimeError: If the fetched page is not the Vita Adae et Evae page.
        """
        cache_path = self.http.cache_path_for(SOURCE_URL)
        if cache_path and cache_path.exists():
            cached = cache_path.read_text(encoding="utf-8")
            if self.is_valid_source(cached):
                return cached

            LOGGER.warning("Discarding invalid cached Vita source at %s", cache_path)
            cache_path.unlink()

        fetched = self.http.fetch_text(url=SOURCE_URL)
        if self.is_valid_source(fetched):
            return fetched

        if cache_path and cache_path.exists():
            cache_path.unlink()

        raise RuntimeError(
            "Source page did not contain Vita Adae et Evae; direct access to sacred-texts.com may be blocked in this environment"
        )

    @staticmethod
    def is_valid_source(text: str) -> bool:
        """Report whether text is the genuine Vita Adae et Evae page.

        Args:
            text: Raw page text.

        Returns:
            True if it has the upper-case title and the opening verse ``i 1 When they were
            driven out from paradise`` and is not a Cloudflare interstitial ("Just a moment").
        """
        return (
            "VITA ADAE ET EVAE" in text
            and "i 1 When they were driven out from paradise" in text
            and "Just a moment" not in text
        )

    @staticmethod
    def _normalize_content_lines(text: str) -> tuple[str, list[str]]:
        """Split text into the source/edition line and the numbered content lines.

        First inserts the missing markers for chapters 32 (``And Adam answered and said: 'Hear
        me, my sons.``) and 37 (``Then Seth and his mother``). Lines are whitespace-normalised and
        blank lines dropped; everything before the first ``CHAPTER_START_RE`` match is the
        source text.

        Args:
            text: Text containing the source line followed by the content.

        Returns:
            ``(source_text, content_lines)`` where the source lines are joined by spaces.
        """
        text = re.sub(
            r"(?m)^\s*And Adam answered and said:\s+'Hear me, my sons\.",
            "xxxii 1 And Adam answered and said: 'Hear me, my sons.",
            text,
        )
        text = re.sub(
            r"(?m)^\s*Then Seth and his mother\b",
            "xxxvii 1 Then Seth and his mother",
            text,
        )

        source_lines: list[str] = []
        content_lines: list[str] = []
        in_content = False

        for raw_line in text.splitlines():
            line = normalize_whitespace(raw_line.strip())
            if not line:
                continue

            if not in_content and CHAPTER_START_RE.match(line):
                in_content = True

            if in_content:
                content_lines.append(line)
            else:
                source_lines.append(line)

        return " ".join(source_lines), content_lines

    @staticmethod
    def _strip_html_fragment(fragment: str, *, line_breaks: bool) -> str:
        """Convert an HTML fragment to text.

        Args:
            fragment: HTML fragment.
            line_breaks: If true ``<br>`` becomes a newline, otherwise a space.
                Paragraph and ``<hr>`` tags always become newlines.

        Returns:
            Text with tags removed and entities unescaped.
        """
        cleaned = re.sub(r"(?i)<br\s*/?>", "\n" if line_breaks else " ", fragment)
        cleaned = re.sub(r"(?i)</?p\b[^>]*>", "\n", cleaned)
        cleaned = re.sub(r"(?i)<hr\s*/?>", "\n", cleaned)
        cleaned = re.sub(r"<[^>]+>", "", cleaned)
        return html.unescape(cleaned)

    @classmethod
    def extract_main_text(cls, raw_text: str) -> tuple[str, list[str]]:
        """Extract the source line and content lines from the page.

        The main content is isolated with ``legacy_html`` first, so a redesigned
        reader-layout page is handled like the old page. For original HTML the body lies between ``<h1>VITA ADAE ET EVAE</h1>`` and the
        ``Scanned and Edited by`` footer (or ``</body>``); the first ``<b>`` element is the
        source line. Mirror-derived Markdown text is also accepted: the part after the
        ``## VITA ADAE ET EVAE`` heading up to the footer markers, with emphasis markers removed.

        Args:
            raw_text: Raw page text (HTML or Markdown mirror).

        Returns:
            ``(source_text, content_lines)`` as from ``_normalize_content_lines``.

        Raises:
            RuntimeError: If the title, body or source heading cannot be located.
        """
        text = legacy_html(raw_text).replace("\r\n", "\n")

        if "<html" in text.lower():
            main_match = re.search(
                r"<h1>\s*VITA ADAE ET EVAE\s*</h1>(?P<body>.*?)(?:<h5>\s*Scanned and Edited by|</body>)",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if not main_match:
                raise RuntimeError("Could not locate Vita Adae et Evae body in source HTML")

            body = main_match.group("body")
            source_match = re.search(r"<b>(?P<source>.*?)</b>", body, re.IGNORECASE | re.DOTALL)
            if not source_match:
                raise RuntimeError("Could not locate Vita Adae et Evae source heading")

            source_text = normalize_whitespace(
                cls._strip_html_fragment(source_match.group("source"), line_breaks=False)
            )
            content_text = cls._strip_html_fragment(body[source_match.end() :], line_breaks=True)
            normalized_source, content_lines = cls._normalize_content_lines(
                f"{source_text}\n\n{content_text}"
            )
            return normalized_source, content_lines

        if "Markdown Content:" in text:
            text = text.split("Markdown Content:", 1)[1]

        title_marker = "## VITA ADAE ET EVAE"
        if title_marker not in text:
            raise RuntimeError("Could not locate Vita Adae et Evae title in source text")

        text = text.split(title_marker, 1)[1]

        end_positions = [
            position
            for marker in ("\n##### Scanned", "\nTitle:", "\nURL Source:")
            if (position := text.find(marker)) != -1
        ]
        if end_positions:
            text = text[: min(end_positions)]

        text = text.replace("**", "")
        text = text.replace("* * *", "")
        return cls._normalize_content_lines(text)

    @staticmethod
    def parse_verse_numbers(token: str) -> list[int]:
        """Parse a verse token into verse numbers.

        Args:
            token: Comma-separated verse numbers; ``I`` (any case) means ``1``.

        Returns:
            The verse numbers, e.g. ``"1,2"`` gives ``[1, 2]``.
        """
        verse_numbers = []
        for part in token.split(","):
            cleaned = part.strip().upper()
            verse_numbers.append(1 if cleaned == "I" else int(cleaned))
        return verse_numbers

    def parse_chapters(self, lines: list[str]) -> list[Chapter]:
        """Group content lines into chapters of verse blocks.

        A line matching a chapter or verse marker starts a new block; other lines continue the
        current block. A chapter marker also sets the current chapter.

        Args:
            lines: Content lines from ``extract_main_text``.

        Returns:
            Chapters 1 through 51 in order.

        Raises:
            RuntimeError: If a continuation precedes any marker, a block cannot be parsed, or
                the chapters found are not exactly 1 through 51.
        """
        chapters: dict[int, Chapter] = {}
        current_chapter: int | None = None
        current_block: list[str] = []

        def flush_block() -> None:
            """Parse the pending block into a verse and add it to its chapter.

            Raises:
                RuntimeError: If the block has neither a chapter marker nor a verse marker
                    within a chapter.
            """
            nonlocal current_block, current_chapter
            if not current_block:
                return

            joined = normalize_whitespace(" ".join(current_block))
            chapter_match = CHAPTER_START_RE.match(joined)
            verse_match = VERSE_START_RE.match(joined)

            if chapter_match:
                current_chapter = roman_to_int(chapter_match.group("chapter"))
                verse_numbers = self.parse_verse_numbers(chapter_match.group("verses"))
                verse_text = normalize_whitespace(chapter_match.group("text"))
            elif verse_match and current_chapter is not None:
                verse_numbers = self.parse_verse_numbers(verse_match.group("verses"))
                verse_text = normalize_whitespace(verse_match.group("text"))
            else:
                raise RuntimeError(f"Could not parse Vita block: {joined}")

            chapter = chapters.setdefault(
                current_chapter,
                Chapter(number=current_chapter, verses=[]),
            )
            chapter.verses.append(VerseBlock(verse_numbers=verse_numbers, text=verse_text))
            current_block = []

        for line in lines:
            if CHAPTER_START_RE.match(line) or VERSE_START_RE.match(line):
                flush_block()
                current_block = [line]
                continue

            if not current_block:
                raise RuntimeError(f"Unexpected continuation without verse marker: {line}")

            current_block.append(line)

        flush_block()

        expected_chapters = list(range(1, 52))
        actual_chapters = sorted(chapters)
        if actual_chapters != expected_chapters:
            raise RuntimeError(
                f"Unexpected Vita chapter sequence: expected {expected_chapters}, got {actual_chapters}"
            )

        return [chapters[number] for number in expected_chapters]

    @staticmethod
    def generate_osis(source_text: str, chapters: list[Chapter]) -> pyosis.OsisXML:
        """Build the OSIS document for the book.

        Args:
            source_text: Source/edition line, emitted as a front-matter ``Source`` div when non-empty.
            chapters: Chapters in order.

        Returns:
            An OSIS document with one canonical chapter div per chapter; verse ids
            ``vita-adae-et-evae.<chapter>.<verse>`` (several ids for grouped verses).
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

        if source_text:
            book_div.content.append(
                pyosis.DivCt(
                    type_value=pyosis.OsisDivs.FRONT,
                    canonical=False,
                    content=[
                        pyosis.TitleCt(
                            type_value=pyosis.OsisTitles.MAIN,
                            canonical=False,
                            content=["Source"],
                        ),
                        pyosis.PCt(content=[source_text]),
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
                verse_ids = [
                    f"{OSIS_WORK_ID}.{chapter.number}.{verse_number}"
                    for verse_number in verse.verse_numbers
                ]
                chapter_div.content.append(
                    pyosis.VerseCt(
                        osis_id=verse_ids,
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
                                "Scraped from https://www.sacred-texts.com/chr/apo/adamnev.htm and converted to OSIS by Andrew P. Sansom."
                            ]
                        )
                    ],
                ),
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
                    osis_work=OSIS_WORK_ID,
                    lang="en",
                    title=[pyosis.TitleCt(canonical=True, content=[BOOK_TITLE])],
                    description=[
                        pyosis.DescriptionCt(
                            value='Vita Adae et Evae from "The Apocrypha and Pseudepigrapha of the Old Testament in English : with introductions and critical and explanatory notes to the several books" by Robert Henry Charles, 1913. Transcribed at sacred-texts.com and converted to OSIS by the open-canon-site scrapers.'
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
        """Run the full pipeline: fetch, extract, parse and convert.

        Returns:
            The OSIS document.
        """
        raw_text = self.fetch_source_text()
        source_text, content_lines = self.extract_main_text(raw_text)
        chapters = self.parse_chapters(content_lines)
        return self.generate_osis(source_text, chapters)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register scraper-specific options; Vita Adae et Evae has none.

    Args:
        parser: Sub-parser to extend (left unchanged).
    """


def run(args: argparse.Namespace) -> list[Path]:
    """Scrape Vita Adae et Evae and write ``vita-adae-et-evae.xml``.

    Args:
        args: Parsed CLI arguments providing ``cache_dir``, ``delay`` and ``output_dir``.

    Returns:
        A one-element list with the written file's path.
    """
    parser = VitaAdaeEtEvaeParser(cache_dir=args.cache_dir, delay=args.delay)
    try:
        osis_doc = parser.process()
        output_path = Path(args.output_dir) / OUTPUT_FILENAME
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(osis_doc.to_xml(), encoding="utf-8")
    finally:
        parser.close()
    return [output_path]


SPEC = ScraperSpec(
    name="vita-adae-et-evae",
    help="Vita Adae et Evae (R. H. Charles, 1913) to OSIS",
    source="https://sacred-texts.com/chr/apo/adamnev.htm",
    outputs=(OUTPUT_FILENAME,),
    run=run,
    add_arguments=add_arguments,
)
"""Registry entry that exposes this scraper to the CLI."""
