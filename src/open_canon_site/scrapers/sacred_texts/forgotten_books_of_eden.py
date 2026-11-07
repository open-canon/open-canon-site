# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "beautifulsoup4",
#     "fire",
#     "httpx",
#     "pyosis",
#     "tqdm",
# ]
# ///
"""Download and parse The Forgotten Books of Eden from sacred-texts.com to OSIS XML.

Scrapes https://sacred-texts.com/bib/fbe/ and produces OSIS XML files for the
following works:
    - The First and Second Books of Adam and Eve (in one document with two books)
  - The Book of the Secrets of Enoch (2 Enoch)
  - The Psalms of Solomon
  - The Odes of Solomon
  - The Letter of Aristeas
  - Fourth Book of Maccabees (4 Maccabees)
  - The Story of Ahikar
  - The Testaments of the Twelve Patriarchs (with 12 sub-books)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

import fire
import pyosis
from bs4 import BeautifulSoup, NavigableString, Tag
from tqdm import tqdm

from .http_client import CachedHttpFetcher
from .osis_parsing import (
    InlinePart,
    consolidate_inline_strings,
    extract_plain_text,
    is_navigation_text,
    parse_page_marker_text,
)
from .osis_parsing import (
    roman_to_int as shared_roman_to_int,
)

LOGGER = logging.getLogger(__name__)

BASE_URL: Final[str] = "https://sacred-texts.com/bib/fbe/"
FILE_PREFIX: Final[str] = "fbe"
FILE_RANGE: Final[tuple[int, int]] = (0, 295)
DEFAULT_OUTPUT_DIR: Final[str] = "documents"


# ---------------------------------------------------------------------------
# Book / work definitions
# ---------------------------------------------------------------------------


@dataclass
class WorkDef:
    """Definition of a single work within the FBE collection."""

    osis_id: str
    title: str
    short: str
    intro_pages: list[int]
    chapter_pages: list[int]  # In order; chapter_pages[0] = chapter 1, etc.
    output_stem: str | None = None
    intro_title: str | None = None
    intro_subtitle: str | None = None
    intro_headings_as_subtitles: bool = False


@dataclass
class TestamentDef:
    """Definition of one Testament within the Twelve Patriarchs."""

    osis_id: str
    title: str
    short: str
    chapter_pages: list[int]


# Global front matter pages (title page, contents, illustrations, preface, introduction)
FRONT_MATTER_PAGES: Final[list[int]] = list(range(0, 5))  # fbe000–fbe004

WORKS: Final[list[WorkDef]] = [
    WorkDef(
        osis_id="1-adam-and-eve",
        title="The First Book of Adam and Eve",
        short="1 Adam and Eve",
        intro_pages=[5],
        chapter_pages=list(range(6, 85)),  # 79 chapters
        intro_title="Introduction",
    ),
    WorkDef(
        osis_id="2-adam-and-eve",
        title="The Second Book of Adam and Eve",
        short="2 Adam and Eve",
        intro_pages=[],
        chapter_pages=list(range(85, 107)),  # 22 chapters
    ),
    WorkDef(
        osis_id="2En",
        title="The Book of the Secrets of Enoch",
        short="2 Enoch",
        intro_pages=[107],
        chapter_pages=list(range(108, 176)),  # 68 chapters
        output_stem="2-enoch",
        intro_title="Introduction",
        intro_subtitle="THE BOOK OF THE SECRETS OF ENOCH.",
    ),
    WorkDef(
        osis_id="psalms-of-solomon",
        title="The Psalms of Solomon",
        short="Psalms of Solomon",
        intro_pages=[176],
        chapter_pages=list(range(177, 195)),  # 18 psalms
        intro_title="Introduction",
        intro_headings_as_subtitles=True,
    ),
    WorkDef(
        osis_id="odes-of-solomon",
        title="The Odes of Solomon",
        short="Odes of Solomon",
        intro_pages=[195],
        chapter_pages=list(range(196, 237)),  # 41 odes (Ode 6 absent from this edition)
        intro_title="Introduction",
        intro_headings_as_subtitles=True,
    ),
    WorkDef(
        osis_id="letter-of-aristeas",
        title="The Letter of Aristeas",
        short="Letter of Aristeas",
        intro_pages=[237],
        chapter_pages=list(range(238, 249)),  # 11 chapters
        intro_title="Introduction",
        intro_headings_as_subtitles=True,
    ),
    WorkDef(
        osis_id="4Macc",
        title="Fourth Book of Maccabees",
        short="4 Maccabees",
        output_stem="4-maccabees",
        intro_pages=[249],
        chapter_pages=list(range(250, 258)),  # 8 chapters
        intro_title="Introduction",
        intro_headings_as_subtitles=True,
    ),
    WorkDef(
        osis_id="story-of-ahikar",
        title="The Story of Ahikar",
        short="Story of Ahikar",
        intro_pages=[258],
        chapter_pages=list(range(259, 266)),  # 7 chapters
        intro_title="Introduction",
        intro_headings_as_subtitles=True,
    ),
]

TESTAMENTS_INTRO_PAGES: Final[list[int]] = [266]

TESTAMENTS: Final[list[TestamentDef]] = [
    TestamentDef("T12Patr.TReu", "The Testament of Reuben", "Test. Reuben", [267, 268]),
    TestamentDef(
        "T12Patr.TSim", "The Testament of Simeon", "Test. Simeon", [269, 270, 271]
    ),
    TestamentDef(
        "T12Patr.TLevi",
        "The Testament of Levi",
        "Test. Levi",
        [272, 273, 274, 275, 276],
    ),
    TestamentDef(
        "T12Patr.TJud", "The Testament of Judah", "Test. Judah", [277, 278, 279, 280]
    ),
    TestamentDef(
        "T12Patr.TIss", "The Testament of Issachar", "Test. Issachar", [281, 282]
    ),
    TestamentDef(
        "T12Patr.TZeb", "The Testament of Zebulun", "Test. Zebulun", [283, 284]
    ),
    TestamentDef("T12Patr.TDan", "The Testament of Dan", "Test. Dan", [285, 286]),
    TestamentDef(
        "T12Patr.TNaph", "The Testament of Naphtali", "Test. Naphtali", [287, 288]
    ),
    TestamentDef("T12Patr.TGad", "The Testament of Gad", "Test. Gad", [289, 290]),
    TestamentDef("T12Patr.TAsh", "The Testament of Asher", "Test. Asher", [291]),
    TestamentDef("T12Patr.TJos", "The Testament of Joseph", "Test. Joseph", [292, 293]),
    TestamentDef(
        "T12Patr.TBenj", "The Testament of Benjamin", "Test. Benjamin", [294, 295]
    ),
]

ADAM_EVE_WORK_IDS: Final[tuple[str, str]] = ("1-adam-and-eve", "2-adam-and-eve")
ADAM_EVE_OSIS_ID: Final[str] = "adam-and-eve"
ADAM_EVE_OUTPUT_STEM: Final[str] = "adam-and-eve"
ADAM_EVE_TITLE: Final[str] = "The First and Second Books of Adam and Eve"
ADAM_EVE_REF_WORK: Final[str] = "Adam and Eve"


# ---------------------------------------------------------------------------
# Parsed data containers
# ---------------------------------------------------------------------------


@dataclass
class VerseContent:
    """Parsed content of a single verse."""

    text: str
    content_parts: list[str | pyosis.HiCt | pyosis.MilestoneCt]
    has_poetry: bool = False
    poetry_lines: list[list[str | pyosis.HiCt | pyosis.MilestoneCt]] | None = None


# ---------------------------------------------------------------------------
# FBE Parser
# ---------------------------------------------------------------------------


class FBEParser:
    """Parse The Forgotten Books of Eden from sacred-texts.com pages."""

    def __init__(
        self,
        cache_dir: str | None = None,
        delay: float = 1.5,
    ) -> None:
        self.http = CachedHttpFetcher(cache_dir=cache_dir, delay=delay, logger=LOGGER)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            LOGGER.info("Using cache directory: %s", self.cache_dir)

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------

    def fetch_page(self, page_num: int, retry_count: int = 3) -> str:
        """Fetch a single FBE page."""
        url = f"{BASE_URL}{FILE_PREFIX}{page_num:03d}.htm"
        return self.http.fetch_text(url=url, retry_count=retry_count)

    def close(self) -> None:
        self.http.close()

    # ------------------------------------------------------------------
    # Text / annotation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_nav_text(text: str) -> bool:
        """Return True if the text is a navigation snippet to be skipped."""
        return is_navigation_text(text)

    @staticmethod
    def _is_standalone_page_marker(p_tag: Tag) -> bool:
        """Return True if this <p> contains only a page-marker anchor."""
        children = [
            c
            for c in p_tag.children
            if not isinstance(c, NavigableString) or str(c).strip()
        ]
        if len(children) == 1 and isinstance(children[0], Tag):
            a = children[0]
            if a.name == "a" and a.get("name", "").startswith("page_"):
                return True
        return False

    def consolidate_strings(
        self,
        content: list[InlinePart],
    ) -> list[InlinePart]:
        """Merge consecutive strings to work around pyosis serialisation quirk."""
        return consolidate_inline_strings(content)

    def parse_inline_annotations(
        self,
        element: Tag | NavigableString,
        is_green_font: bool = False,
    ) -> list[InlinePart]:
        """Recursively parse inline HTML, converting formatting to OSIS equivalents."""
        if isinstance(element, NavigableString):
            text = str(element)
            if is_green_font:
                return parse_page_marker_text(text)
            return [text] if text.strip() else []

        result: list[InlinePart] = []
        skip_set: set[Tag] = set()

        for child in element.children:
            if isinstance(child, NavigableString):
                result.extend(
                    self.parse_inline_annotations(child, is_green_font=is_green_font)
                )
            elif isinstance(child, Tag):
                if child in skip_set:
                    continue

                is_child_green = (
                    child.name == "font" and child.get("color", "").lower() == "green"
                )
                child_content = self.parse_inline_annotations(
                    child, is_green_font=is_child_green
                )

                if child.name in ("i", "em"):
                    if child_content:
                        result.append(
                            pyosis.HiCt(
                                type_value=pyosis.OsisHi.ITALIC, content=child_content
                            )
                        )
                elif child.name in ("b", "strong"):
                    if child_content:
                        result.append(
                            pyosis.HiCt(
                                type_value=pyosis.OsisHi.BOLD, content=child_content
                            )
                        )
                elif child.name == "sup":
                    if child_content:
                        result.append(
                            pyosis.HiCt(
                                type_value=pyosis.OsisHi.SUPER, content=child_content
                            )
                        )
                elif child.name == "sub":
                    if child_content:
                        result.append(
                            pyosis.HiCt(
                                type_value=pyosis.OsisHi.SUB, content=child_content
                            )
                        )
                elif child.name == "br":
                    continue
                else:
                    # a, font, span, div, etc. — pass through content
                    result.extend(child_content)

        return self.consolidate_strings(result)

    def _extract_text(
        self,
        parts: list[InlinePart],
    ) -> str:
        """Flatten annotation parts to plain text."""
        return extract_plain_text(parts)

    # ------------------------------------------------------------------
    # Chapter-number extraction
    # ------------------------------------------------------------------

    @staticmethod
    def roman_to_int(s: str) -> int:
        """Convert a Roman numeral string to an integer."""
        return shared_roman_to_int(s)

    def extract_chapter_number(self, heading_text: str) -> int | None:
        """Extract chapter number from an <h3> heading.

        Handles formats: "CHAP. I.", "CHAP. II", "I", "XVII", "ODE 1.", "ODE 42."
        """
        t = heading_text.strip()

        # "CHAP. <Roman>." or "CHAP. <Roman>"
        m = re.match(r"CHAP\.\s+([IVXLCDM]+)\.?$", t, re.IGNORECASE)
        if m:
            return self.roman_to_int(m.group(1))

        # "ODE <number>."
        m = re.match(r"ODE\s+(\d+)\.?$", t, re.IGNORECASE)
        if m:
            return int(m.group(1))

        # Pure Roman numeral (Psalms)
        m = re.match(r"^([IVXLCDM]+)\.?$", t, re.IGNORECASE)
        if m:
            try:
                n = self.roman_to_int(m.group(1))
                if n > 0:
                    return n
            except Exception:
                pass

        # Pure Arabic numeral
        m = re.match(r"^(\d+)\.?$", t)
        if m:
            return int(m.group(1))

        return None

    # ------------------------------------------------------------------
    # Verse parsing helpers
    # ------------------------------------------------------------------

    def _parse_verse_content(self, p_tag: Tag) -> VerseContent:
        """Parse a <p> tag into a VerseContent (plain + annotated + poetry)."""
        parts = self.parse_inline_annotations(p_tag)

        # Plain text (for analysis)
        plain = self._extract_text(parts)

        has_poetry = bool(p_tag.find_all("br"))
        poetry_lines: list[list[str | pyosis.HiCt | pyosis.MilestoneCt]] | None = None

        if has_poetry:
            raw_html = str(p_tag)
            chunks = re.split(r"<br\s*/?>", raw_html, flags=re.IGNORECASE)
            lines = []
            for chunk_html in chunks:
                chunk_soup = BeautifulSoup(chunk_html, "html.parser")
                chunk_parts = self.parse_inline_annotations(chunk_soup)
                chunk_text = self._extract_text(chunk_parts).strip()
                if chunk_text and not self._is_nav_text(chunk_text):
                    # Strip leading whitespace from first text element in the line
                    chunk_parts = self._strip_leading_whitespace(chunk_parts)
                    lines.append(chunk_parts)
            poetry_lines = lines if lines else None

        return VerseContent(
            text=plain.strip(),
            content_parts=parts,
            has_poetry=has_poetry,
            poetry_lines=poetry_lines,
        )

    @staticmethod
    def _strip_leading_whitespace(
        content: list[str | pyosis.HiCt | pyosis.MilestoneCt],
    ) -> list[str | pyosis.HiCt | pyosis.MilestoneCt]:
        """Return a copy of content with leading whitespace removed from the first text element."""
        if not content:
            return []
        result = list(content)
        if isinstance(result[0], str):
            result[0] = result[0].lstrip()
        return result

    @staticmethod
    def _strip_verse_number(
        content: list[str | pyosis.HiCt | pyosis.MilestoneCt],
    ) -> list[str | pyosis.HiCt | pyosis.MilestoneCt]:
        """Return a copy of content with a leading verse number ('N ' or 'N. ') removed."""
        if not content:
            return []
        result = list(content)
        if isinstance(result[0], str):
            result[0] = re.sub(r"^\d+\.?\s+", "", result[0])
        return result

    def _build_verse(
        self,
        osis_id: str,
        verse_content: VerseContent,
        *,
        canonical: bool = True,
    ) -> pyosis.VerseCt:
        """Wrap VerseContent in a VerseCt OSIS element."""
        if verse_content.has_poetry and verse_content.poetry_lines:
            lg = pyosis.LgCt(
                l=[pyosis.LCt(content=line) for line in verse_content.poetry_lines]
            )
            content: list = [lg]
        else:
            content = (
                verse_content.content_parts
                if verse_content.content_parts
                else [verse_content.text]
            )

        return pyosis.VerseCt(osis_id=[osis_id], canonical=canonical, content=content)

    # ------------------------------------------------------------------
    # Page parsing
    # ------------------------------------------------------------------

    def _skip_paragraph(self, p_tag: Tag) -> bool:
        """Return True if this <p> should be ignored entirely."""
        text = p_tag.get_text().strip()
        if not text:
            return True
        if self._is_nav_text(text):
            return True
        if self._is_standalone_page_marker(p_tag):
            return True
        return False

    def _extract_intro_headings(self, html: str) -> list[str]:
        """Extract heading lines that appear before the first intro paragraph."""
        soup = BeautifulSoup(html, "html.parser")
        body = soup.find("body")
        root = body if body else soup

        headings: list[str] = []
        seen: set[str] = set()

        for element in root.find_all(
            ["h1", "h2", "h3", "h4", "h5", "h6", "p"], recursive=True
        ):
            if element.name == "p":
                if self._skip_paragraph(element):
                    continue
                break

            heading_text = element.get_text().strip()
            if (
                not heading_text
                or self._is_nav_text(heading_text)
                or heading_text in seen
            ):
                continue

            headings.append(heading_text)
            seen.add(heading_text)

        return headings

    def _extract_intro_subtitle(self, html: str) -> str | None:
        """Extract an intro-page subtitle such as an “also called” line."""
        headings = self._extract_intro_headings(html)
        for idx, heading in enumerate(headings):
            if heading.strip().upper() == "ALSO CALLED" and idx + 1 < len(headings):
                return headings[idx + 1].rstrip(".")
        return None

    def _parse_intro_page(
        self,
        html: str,
        *,
        title_override: str | None = None,
        subtitle_override: str | None = None,
        headings_as_subtitles: bool = False,
        include_headings: bool = True,
    ) -> list[pyosis.TitleCt | pyosis.PCt | pyosis.HeadCt | pyosis.MilestoneCt]:
        """Parse an intro / front-matter page into OSIS paragraph elements."""
        soup = BeautifulSoup(html, "html.parser")
        elements: list[
            pyosis.TitleCt | pyosis.PCt | pyosis.HeadCt | pyosis.MilestoneCt
        ] = []
        intro_headings = self._extract_intro_headings(html)

        if title_override:
            elements.append(
                pyosis.TitleCt(
                    type_value=pyosis.OsisTitles.MAIN,
                    canonical=False,
                    content=[title_override],
                )
            )

        if subtitle_override:
            elements.append(
                pyosis.TitleCt(
                    type_value=pyosis.OsisTitles.SUB,
                    canonical=False,
                    content=[subtitle_override],
                )
            )

        if headings_as_subtitles:
            for heading_text in intro_headings:
                elements.append(
                    pyosis.TitleCt(
                        type_value=pyosis.OsisTitles.SUB,
                        canonical=False,
                        content=[heading_text],
                    )
                )

        if include_headings:
            for heading_text in intro_headings:
                elements.append(pyosis.HeadCt(content=[heading_text]))

        for p in soup.find_all("p"):
            if self._skip_paragraph(p):
                continue
            parts = self.parse_inline_annotations(p)
            if not parts:
                continue
            # Standalone milestone (page marker)?
            if len(parts) == 1 and isinstance(parts[0], pyosis.MilestoneCt):
                elements.append(parts[0])
            else:
                elements.append(pyosis.PCt(content=parts))

        return elements

    def _parse_chapter_page(
        self,
        html: str,
        book_osis_id: str,
        chapter_num: int,
    ) -> pyosis.DivCt:
        """Parse a chapter page and return a chapter DivCt."""
        soup = BeautifulSoup(html, "html.parser")
        chapter_osis_id = f"{book_osis_id}.{chapter_num}"

        # Collect all top-level content elements from the body
        body = soup.find("body")
        if not body:
            body = soup

        chapter_content: list = []

        # ---- Detect chapter summary (italic <p> or <i><p>) ----
        # Find the <h3> chapter heading first
        h3 = soup.find("h3")
        chapter_summary_text: str | None = None
        chapter_summary_parts: list | None = None

        if h3:
            # Look for an immediately following <i> or <em> element
            sib = h3.find_next_sibling()
            while sib and isinstance(sib, NavigableString):
                sib = sib.find_next_sibling()

            if sib and sib.name in ("i", "em"):
                # The <i> may directly contain a <p> or be inline text
                inner_p = sib.find("p")
                if inner_p:
                    chapter_summary_parts = self.parse_inline_annotations(inner_p)
                    chapter_summary_text = self._extract_text(
                        chapter_summary_parts
                    ).strip()
                else:
                    chapter_summary_parts = self.parse_inline_annotations(sib)
                    chapter_summary_text = self._extract_text(
                        chapter_summary_parts
                    ).strip()

        if chapter_summary_text:
            summary_div = pyosis.DivCt(
                type_value=pyosis.OsisDivs.SUMMARY,
                canonical=False,
                content=[pyosis.PCt(content=chapter_summary_parts)],
            )
            chapter_content.append(summary_div)

        # ---- Collect verse paragraphs ----
        # Identify which <p> elements are the chapter-summary paragraph to skip
        summary_p_set: set[Tag] = set()
        if h3 and chapter_summary_text:
            sib = h3.find_next_sibling()
            while sib and isinstance(sib, NavigableString):
                sib = sib.find_next_sibling()
            if sib and sib.name in ("i", "em"):
                inner_p = sib.find("p")
                if inner_p:
                    summary_p_set.add(inner_p)

        # Also skip any italic <p> paragraphs that appear BEFORE the <h3>
        # (these are testament/book subtitles like "The First-Born Son of Jacob and Leah")
        if h3:
            for pre_tag in h3.find_all_previous(["i", "em"]):
                inner_p = pre_tag.find("p")
                if inner_p:
                    summary_p_set.add(inner_p)

        current_verse_num: int | None = None
        current_verse_parts: list[str | pyosis.HiCt | pyosis.MilestoneCt] = []
        current_verse_poetry: list[list] = []
        current_verse_has_poetry: bool = False
        verse_divs: list[pyosis.VerseCt] = []

        def flush_verse() -> None:
            nonlocal \
                current_verse_num, \
                current_verse_parts, \
                current_verse_poetry, \
                current_verse_has_poetry
            if current_verse_num is None:
                return
            vc = VerseContent(
                text=self._extract_text(current_verse_parts).strip(),
                content_parts=self.consolidate_strings(current_verse_parts),
                has_poetry=current_verse_has_poetry,
                poetry_lines=current_verse_poetry if current_verse_has_poetry else None,
            )
            v_id = f"{chapter_osis_id}.{current_verse_num}"
            verse_divs.append(self._build_verse(v_id, vc))
            current_verse_num = None
            current_verse_parts = []
            current_verse_poetry = []
            current_verse_has_poetry = False

        all_paragraphs = soup.find_all("p")
        first_content_seen = False

        for p in all_paragraphs:
            if p in summary_p_set:
                continue
            if self._skip_paragraph(p):
                continue

            text = p.get_text().strip()
            if not text:
                continue

            # Check for verse number at the start: "N " or "N. "
            verse_match = re.match(r"^(\d+)\.?\s+", text)

            if verse_match:
                flush_verse()
                current_verse_num = int(verse_match.group(1))
                vc = self._parse_verse_content(p)
                # Strip the verse number from the content
                stripped = self._strip_verse_number(list(vc.content_parts))
                current_verse_parts = stripped
                current_verse_has_poetry = vc.has_poetry
                if vc.has_poetry and vc.poetry_lines:
                    # Strip verse number from first line too
                    if vc.poetry_lines and vc.poetry_lines[0]:
                        first_line = list(vc.poetry_lines[0])
                        first_line = self._strip_verse_number(first_line)
                        current_verse_poetry = [first_line] + list(vc.poetry_lines[1:])
                    else:
                        current_verse_poetry = list(vc.poetry_lines)
                first_content_seen = True
            elif not first_content_seen:
                # First un-numbered paragraph → verse 1
                first_content_seen = True
                flush_verse()
                current_verse_num = 1
                vc = self._parse_verse_content(p)
                current_verse_parts = list(vc.content_parts)
                current_verse_has_poetry = vc.has_poetry
                if vc.has_poetry and vc.poetry_lines:
                    current_verse_poetry = list(vc.poetry_lines)
            else:
                # Continuation of the current verse (e.g., after a page-break para)
                if current_verse_num is not None:
                    vc = self._parse_verse_content(p)
                    # Add a space separator before continuation
                    current_verse_parts.append(" ")
                    current_verse_parts.extend(vc.content_parts)
                    if vc.has_poetry and vc.poetry_lines:
                        current_verse_has_poetry = True
                        current_verse_poetry.extend(vc.poetry_lines)

        flush_verse()
        chapter_content.extend(verse_divs)

        return pyosis.DivCt(
            type_value=pyosis.OsisDivs.CHAPTER,
            osis_id=[chapter_osis_id],
            canonical=True,
            content=chapter_content,
        )

    def _parse_odes_chapter_page(
        self,
        html: str,
        book_osis_id: str,
        chapter_num: int,
    ) -> pyosis.DivCt:
        """Parse an Odes of Solomon chapter page.

        In this edition the entire Ode is in one <p> with <br>-separated
        numbered verses (e.g. "1 text<br>2 text<br>…").  We split by <br>,
        detect the verse number, and emit individual VerseCts.
        """
        soup = BeautifulSoup(html, "html.parser")
        chapter_osis_id = f"{book_osis_id}.{chapter_num}"
        chapter_content: list = []

        # Check for chapter summary (italic paragraph after h3)
        h3 = soup.find("h3")
        summary_p_set: set[Tag] = set()
        if h3:
            sib = h3.find_next_sibling()
            while sib and isinstance(sib, NavigableString):
                sib = sib.find_next_sibling()
            if sib and sib.name in ("i", "em"):
                inner_p = sib.find("p")
                ref = inner_p if inner_p else sib
                parts = self.parse_inline_annotations(ref)
                summary_text = self._extract_text(parts).strip()
                if summary_text:
                    chapter_content.append(
                        pyosis.DivCt(
                            type_value=pyosis.OsisDivs.SUMMARY,
                            canonical=False,
                            content=[pyosis.PCt(content=parts)],
                        )
                    )
                if inner_p:
                    summary_p_set.add(inner_p)

        verse_divs: list[pyosis.VerseCt] = []

        for p in soup.find_all("p"):
            if p in summary_p_set or self._skip_paragraph(p):
                continue

            # Split paragraph into <br>-separated chunks
            raw_html = str(p)
            chunks = re.split(r"<br\s*/?>", raw_html, flags=re.IGNORECASE)

            current_verse_num: int | None = None
            current_lines: list[list] = []

            def flush() -> None:
                nonlocal current_verse_num, current_lines
                if current_verse_num is None or not current_lines:
                    return
                v_id = f"{chapter_osis_id}.{current_verse_num}"
                if len(current_lines) == 1:
                    vc = VerseContent(
                        text=self._extract_text(current_lines[0]),
                        content_parts=self.consolidate_strings(current_lines[0]),
                    )
                    verse_divs.append(self._build_verse(v_id, vc))
                else:
                    lg = pyosis.LgCt(l=[pyosis.LCt(content=ln) for ln in current_lines])
                    verse_divs.append(
                        pyosis.VerseCt(osis_id=[v_id], canonical=True, content=[lg])
                    )
                current_verse_num = None
                current_lines = []

            for chunk_html in chunks:
                csoup = BeautifulSoup(chunk_html, "html.parser")
                chunk_parts = self.parse_inline_annotations(csoup)
                chunk_text = self._extract_text(chunk_parts).strip()
                if not chunk_text or self._is_nav_text(chunk_text):
                    continue

                chunk_parts = self._strip_leading_whitespace(chunk_parts)
                verse_m = re.match(r"^(\d+)\.?\s+", chunk_text)
                if verse_m:
                    flush()
                    current_verse_num = int(verse_m.group(1))
                    stripped = self._strip_verse_number(list(chunk_parts))
                    current_lines = [stripped]
                elif current_verse_num is not None:
                    current_lines.append(chunk_parts)
                else:
                    # No verse number yet — treat as verse 1
                    current_verse_num = 1
                    current_lines = [chunk_parts]

            flush()

        # If no numbered verses found but there are content paragraphs,
        # fall back to the standard chapter parser
        if not verse_divs:
            return self._parse_chapter_page(html, book_osis_id, chapter_num)

        chapter_content.extend(verse_divs)
        return pyosis.DivCt(
            type_value=pyosis.OsisDivs.CHAPTER,
            osis_id=[chapter_osis_id],
            canonical=True,
            content=chapter_content,
        )

    def _parse_psalms_chapter_page(
        self,
        html: str,
        book_osis_id: str,
        chapter_num: int,
    ) -> pyosis.DivCt:
        """Parse a Psalms of Solomon chapter page.

        Psalms in this edition have no verse numbers; the entire psalm text is
        one block of poetry with <br>-separated lines.  Produces a single
        verse containing a linegroup.
        """
        soup = BeautifulSoup(html, "html.parser")
        chapter_osis_id = f"{book_osis_id}.{chapter_num}"
        chapter_content: list = []

        # Italic "motto" quote after <h3> → chapter summary
        h3 = soup.find("h3")
        summary_p_set: set[Tag] = set()
        if h3:
            sib = h3.find_next_sibling()
            while sib and isinstance(sib, NavigableString):
                sib = sib.find_next_sibling()
            if sib and sib.name in ("i", "em"):
                inner_p = sib.find("p")
                ref = inner_p if inner_p else sib
                parts = self.parse_inline_annotations(ref)
                summary_text = self._extract_text(parts).strip()
                if summary_text:
                    chapter_content.append(
                        pyosis.DivCt(
                            type_value=pyosis.OsisDivs.SUMMARY,
                            canonical=False,
                            content=[pyosis.PCt(content=parts)],
                        )
                    )
                if inner_p:
                    summary_p_set.add(inner_p)
            # Also handle a plain centered <p> that acts as a motto quote
            elif sib and sib.name == "p":
                inner_text = sib.get_text().strip()
                # Treat as summary if it looks like a quoted motto (starts/ends with " or «»)
                if inner_text.startswith('"') or inner_text.startswith("\u201c"):
                    parts = self.parse_inline_annotations(sib)
                    chapter_content.append(
                        pyosis.DivCt(
                            type_value=pyosis.OsisDivs.SUMMARY,
                            canonical=False,
                            content=[pyosis.PCt(content=parts)],
                        )
                    )
                    summary_p_set.add(sib)

        # Gather all poetry lines from non-skipped paragraphs
        all_lines: list[list] = []
        for p in soup.find_all("p"):
            if p in summary_p_set or self._skip_paragraph(p):
                continue

            raw_html = str(p)
            br_chunks = re.split(r"<br\s*/?>", raw_html, flags=re.IGNORECASE)

            if len(br_chunks) > 1:
                # Poetry paragraph
                for chunk_html in br_chunks:
                    csoup = BeautifulSoup(chunk_html, "html.parser")
                    chunk_parts = self.parse_inline_annotations(csoup)
                    chunk_text = self._extract_text(chunk_parts).strip()
                    if chunk_text and not self._is_nav_text(chunk_text):
                        chunk_parts = self._strip_leading_whitespace(chunk_parts)
                        all_lines.append(chunk_parts)
            else:
                # Non-poetry paragraph — check if numbered verse
                text = p.get_text().strip()
                verse_m = re.match(r"^(\d+)\.?\s+", text)
                if verse_m:
                    # Fall back to standard parser if there are numbered verses
                    return self._parse_chapter_page(html, book_osis_id, chapter_num)
                parts = self.parse_inline_annotations(p)
                if self._extract_text(parts).strip():
                    all_lines.append(parts)

        if all_lines:
            lg = pyosis.LgCt(l=[pyosis.LCt(content=ln) for ln in all_lines])
            verse = pyosis.VerseCt(
                osis_id=[f"{chapter_osis_id}.1"],
                canonical=True,
                content=[lg],
            )
            chapter_content.append(verse)

        return pyosis.DivCt(
            type_value=pyosis.OsisDivs.CHAPTER,
            osis_id=[chapter_osis_id],
            canonical=True,
            content=chapter_content,
        )

    # ------------------------------------------------------------------
    # Building OSIS book divs
    # ------------------------------------------------------------------

    def _build_intro_div(
        self,
        html: str,
        *,
        title_override: str | None = None,
        subtitle_override: str | None = None,
        headings_as_subtitles: bool = False,
        include_headings: bool = True,
    ) -> pyosis.DivCt:
        """Build a non-canonical introduction div from an intro page."""
        elements = self._parse_intro_page(
            html,
            title_override=title_override,
            subtitle_override=subtitle_override,
            headings_as_subtitles=headings_as_subtitles,
            include_headings=include_headings,
        )
        return pyosis.DivCt(
            type_value=pyosis.OsisDivs.INTRODUCTION,
            canonical=False,
            content=elements,
        )

    def _build_book_div(
        self,
        work: WorkDef,
        page_html: dict[int, str],
    ) -> pyosis.DivCt:
        """Build the complete OSIS book div for a single work."""
        book_content: list = [
            pyosis.TitleCt(
                type_value=pyosis.OsisTitles.MAIN,
                canonical=True,
                short=work.short,
                content=[work.title],
            )
        ]

        if work.intro_pages:
            subtitle = self._extract_intro_subtitle(page_html[work.intro_pages[0]])
            if subtitle:
                book_content.append(
                    pyosis.TitleCt(
                        type_value=pyosis.OsisTitles.SUB,
                        canonical=False,
                        content=[subtitle],
                    )
                )

        # Intro pages
        for pg in work.intro_pages:
            html = page_html[pg]
            book_content.append(
                self._build_intro_div(
                    html,
                    title_override=work.intro_title,
                    subtitle_override=work.intro_subtitle,
                    headings_as_subtitles=work.intro_headings_as_subtitles,
                    include_headings=work.intro_title is None,
                )
            )

        # Chapter pages
        is_psalms = work.osis_id == "psalms-of-solomon"
        is_odes = work.osis_id == "odes-of-solomon"

        for idx, pg in enumerate(work.chapter_pages):
            html = page_html[pg]
            chapter_num = self._detect_chapter_number(html, idx + 1)

            if is_psalms:
                chapter_div = self._parse_psalms_chapter_page(
                    html, work.osis_id, chapter_num
                )
            elif is_odes:
                chapter_div = self._parse_odes_chapter_page(
                    html, work.osis_id, chapter_num
                )
            else:
                chapter_div = self._parse_chapter_page(html, work.osis_id, chapter_num)

            book_content.append(chapter_div)

        return pyosis.DivCt(
            type_value=pyosis.OsisDivs.BOOK,
            osis_id=[work.osis_id],
            canonical=True,
            content=book_content,
        )

    def _detect_chapter_number(self, html: str, fallback: int) -> int:
        """Extract the chapter number from a page's <h3> heading."""
        soup = BeautifulSoup(html, "html.parser")
        h3 = soup.find("h3")
        if h3:
            n = self.extract_chapter_number(h3.get_text().strip())
            if n:
                return n
        return fallback

    def _extract_pre_h3_italic(self, html: str) -> str | None:
        """Extract the italic subtitle that appears between <h1> and <h3> on some pages.

        This handles testament pages where a subtitle like "The First-Born Son of
        Jacob and Leah" appears in an <i><p> block after the <h1> testament name
        and before the <h3> chapter heading.
        """
        soup = BeautifulSoup(html, "html.parser")
        h3 = soup.find("h3")
        if not h3:
            return None
        for i_tag in h3.find_all_previous(["i", "em"]):
            inner_p = i_tag.find("p")
            ref = inner_p if inner_p else i_tag
            text = ref.get_text().strip().rstrip(".")
            if text:
                return text
        return None

    def _build_testaments_div(
        self,
        page_html: dict[int, str],
    ) -> pyosis.DivCt:
        """Build the combined Testaments of the Twelve Patriarchs book div."""
        parent_content: list = [
            pyosis.TitleCt(
                type_value=pyosis.OsisTitles.MAIN,
                canonical=True,
                short="Testaments of the Twelve Patriarchs",
                content=["The Testaments of the Twelve Patriarchs"],
            )
        ]

        # Collection-level introduction
        for pg in TESTAMENTS_INTRO_PAGES:
            html = page_html[pg]
            parent_content.append(
                self._build_intro_div(
                    html,
                    title_override="Introduction",
                    headings_as_subtitles=True,
                    include_headings=False,
                )
            )

        # Individual testaments as sub-books
        for t in TESTAMENTS:
            sub_content: list = [
                pyosis.TitleCt(
                    type_value=pyosis.OsisTitles.MAIN,
                    canonical=True,
                    short=t.short,
                    content=[t.title],
                )
            ]
            # Extract optional subtitle from the first chapter page
            # (e.g., "The First-Born Son of Jacob and Leah" in an <i><p> before <h3>)
            if t.chapter_pages:
                subtitle = self._extract_pre_h3_italic(page_html[t.chapter_pages[0]])
                if subtitle:
                    sub_content.append(
                        pyosis.TitleCt(
                            type_value=pyosis.OsisTitles.SUB,
                            canonical=False,
                            content=[subtitle],
                        )
                    )
            for idx, pg in enumerate(t.chapter_pages):
                html = page_html[pg]
                chapter_num = self._detect_chapter_number(html, idx + 1)
                chapter_div = self._parse_chapter_page(html, t.osis_id, chapter_num)
                sub_content.append(chapter_div)

            sub_book = pyosis.DivCt(
                type_value=pyosis.OsisDivs.BOOK,
                osis_id=[t.osis_id],
                canonical=True,
                content=sub_content,
            )
            parent_content.append(sub_book)

        return pyosis.DivCt(
            type_value=pyosis.OsisDivs.BOOK,
            osis_id=["T12Patr"],
            canonical=True,
            content=parent_content,
        )

    # ------------------------------------------------------------------
    # OSIS header
    # ------------------------------------------------------------------

    @staticmethod
    def _build_header(
        osis_work_id: str,
        title: str,
        description: str,
    ) -> pyosis.HeaderCt:
        current_datetime = datetime.now().strftime("%Y.%m.%dT%H:%M:%S")

        return pyosis.HeaderCt(
            canonical=False,
            revision_desc=[
                pyosis.RevisionDescCt(
                    date=pyosis.DateCt(
                        event=pyosis.OsisEvents.EVERSION,
                        type_value="ISO",
                        lang="en",
                        content=[current_datetime],
                    ),
                    p=[
                        pyosis.PCt(
                            content=[
                                "Scraped from https://sacred-texts.com/bib/fbe/, "
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
                        content=["1926"],
                    ),
                    p=[
                        pyosis.PCt(
                            content=[
                                "The Forgotten Books of Eden, edited by Rutherford H. Platt, Jr., 1926."
                            ]
                        )
                    ],
                ),
            ],
            work=[
                pyosis.WorkCt(
                    osis_work=osis_work_id,
                    lang="en",
                    title=[pyosis.TitleCt(canonical=True, content=[title])],
                    description=[pyosis.DescriptionCt(value=description)],
                    type_value=[pyosis.TypeCt(type_value="OSIS", content=["Bible"])],
                    creator=[
                        pyosis.CreatorCt(
                            role=pyosis.OsisRoles.EDT,
                            value="Rutherford H. Platt, Jr.",
                        )
                    ],
                    publisher=[pyosis.PublisherCt(value="Alpha House, Inc.")],
                ),
            ],
        )

    # ------------------------------------------------------------------
    # Top-level orchestration
    # ------------------------------------------------------------------

    def build_osis_for_work(
        self,
        work: WorkDef,
        page_html: dict[int, str],
    ) -> pyosis.OsisXML:
        """Generate a complete OSIS document for a single work."""
        header = self._build_header(
            osis_work_id=work.osis_id,
            title=work.title,
            description=(
                'Text from "The Forgotten Books of Eden," edited by Rutherford H. Platt, Jr., 1926. '
                "Scraped from sacred-texts.com and converted to OSIS."
            ),
        )
        book_div = self._build_book_div(work, page_html)
        osis_text = pyosis.OsisTextCt(
            lang="en",
            osis_idwork=work.osis_id,
            osis_ref_work=work.short,
            canonical=True,
            header=header,
            div=[book_div],
        )
        return pyosis.OsisXML(pyosis.Osis(osis_text=osis_text))

    def build_osis_for_adam_and_eve(
        self,
        page_html: dict[int, str],
    ) -> pyosis.OsisXML:
        """Generate a combined OSIS document for 1 and 2 Adam and Eve."""
        adam_eve_works = [work for work in WORKS if work.osis_id in ADAM_EVE_WORK_IDS]
        header = self._build_header(
            osis_work_id=ADAM_EVE_OSIS_ID,
            title=ADAM_EVE_TITLE,
            description=(
                'Texts from "The Forgotten Books of Eden," edited by Rutherford H. Platt, Jr., 1926. '
                "Includes the First and Second Books of Adam and Eve, scraped from sacred-texts.com and converted to OSIS."
            ),
        )
        osis_text = pyosis.OsisTextCt(
            lang="en",
            osis_idwork=ADAM_EVE_OSIS_ID,
            osis_ref_work=ADAM_EVE_REF_WORK,
            canonical=True,
            header=header,
            div=[self._build_book_div(work, page_html) for work in adam_eve_works],
        )
        return pyosis.OsisXML(pyosis.Osis(osis_text=osis_text))

    def build_osis_for_testaments(
        self,
        page_html: dict[int, str],
    ) -> pyosis.OsisXML:
        """Generate a complete OSIS document for the Testaments of the Twelve Patriarchs."""
        osis_id = "T12Patr"
        header = self._build_header(
            osis_work_id=osis_id,
            title="The Testaments of the Twelve Patriarchs",
            description=(
                'Text from "The Forgotten Books of Eden," edited by Rutherford H. Platt, Jr., 1926. '
                "Scraped from sacred-texts.com and converted to OSIS."
            ),
        )
        t_div = self._build_testaments_div(page_html)
        osis_text = pyosis.OsisTextCt(
            lang="en",
            osis_idwork=osis_id,
            osis_ref_work="Testaments of the Twelve Patriarchs",
            canonical=True,
            header=header,
            div=[t_div],
        )
        return pyosis.OsisXML(pyosis.Osis(osis_text=osis_text))

    def process_all(
        self,
        output_dir: str = ".",
        start_page: int = FILE_RANGE[0],
        end_page: int = FILE_RANGE[1],
    ) -> None:
        """Fetch all needed pages and write one XML file per work."""
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        # Determine which page numbers are needed
        needed: set[int] = set()
        for work in WORKS:
            needed.update(work.intro_pages)
            needed.update(work.chapter_pages)
        needed.update(TESTAMENTS_INTRO_PAGES)
        for t in TESTAMENTS:
            needed.update(t.chapter_pages)
        # Apply range filter
        needed = {n for n in needed if start_page <= n <= end_page}

        LOGGER.info("Fetching %d pages…", len(needed))
        page_html: dict[int, str] = {}
        for pg in tqdm(sorted(needed), desc="Fetching pages"):
            try:
                page_html[pg] = self.fetch_page(pg)
            except Exception as exc:
                LOGGER.error("Failed to fetch page %d: %s", pg, exc)

        # Generate the combined Adam and Eve document
        adam_eve_works = [work for work in WORKS if work.osis_id in ADAM_EVE_WORK_IDS]
        adam_eve_pages = [
            p for work in adam_eve_works for p in work.intro_pages + work.chapter_pages
        ]
        missing_adam_eve = [p for p in adam_eve_pages if p not in page_html]
        if missing_adam_eve:
            LOGGER.warning(
                "Skipping %s: missing pages %s",
                ADAM_EVE_OUTPUT_STEM,
                missing_adam_eve,
            )
        else:
            LOGGER.info("Generating %s.xml", ADAM_EVE_OUTPUT_STEM)
            try:
                osis_doc = self.build_osis_for_adam_and_eve(page_html)
                xml_path = out_path / f"{ADAM_EVE_OUTPUT_STEM}.xml"
                xml_path.write_text(osis_doc.to_xml(), encoding="utf-8")
                LOGGER.info("Wrote %s", xml_path)
            except Exception as exc:
                LOGGER.error(
                    "Error generating %s: %s",
                    ADAM_EVE_OUTPUT_STEM,
                    exc,
                    exc_info=True,
                )

        # Generate XML for each standalone work
        standalone_works = [
            work for work in WORKS if work.osis_id not in ADAM_EVE_WORK_IDS
        ]
        for work in tqdm(standalone_works, desc="Generating XML files"):
            missing = [
                p for p in work.intro_pages + work.chapter_pages if p not in page_html
            ]
            if missing:
                LOGGER.warning("Skipping %s: missing pages %s", work.osis_id, missing)
                continue
            output_stem = work.output_stem or work.osis_id
            LOGGER.info("Generating %s.xml", output_stem)
            try:
                osis_doc = self.build_osis_for_work(work, page_html)
                xml_path = out_path / f"{output_stem}.xml"
                xml_path.write_text(osis_doc.to_xml(), encoding="utf-8")
                LOGGER.info("Wrote %s", xml_path)
            except Exception as exc:
                LOGGER.error("Error generating %s: %s", output_stem, exc, exc_info=True)

        # Testaments
        t_pages = TESTAMENTS_INTRO_PAGES + [
            p for t in TESTAMENTS for p in t.chapter_pages
        ]
        missing_t = [p for p in t_pages if p not in page_html]
        if missing_t:
            LOGGER.warning("Skipping testaments: missing pages %s", missing_t)
        else:
            LOGGER.info("Generating testaments-twelve-patriarchs.xml")
            try:
                osis_doc = self.build_osis_for_testaments(page_html)
                xml_path = out_path / "testaments-twelve-patriarchs.xml"
                xml_path.write_text(osis_doc.to_xml(), encoding="utf-8")
                LOGGER.info("Wrote %s", xml_path)
            except Exception as exc:
                LOGGER.error("Error generating testaments: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(
    output_dir: str = DEFAULT_OUTPUT_DIR,
    start_page: int = FILE_RANGE[0],
    end_page: int = FILE_RANGE[1],
    delay: float = 1.5,
    cache_dir: str = ".cache/html",
    log_level: str = "INFO",
) -> None:
    """Download and convert The Forgotten Books of Eden to OSIS XML.

    Args:
        output_dir: Directory to write output XML files (default: documents)
        start_page: First page number to fetch (default: 0)
        end_page: Last page number to fetch (default: 295)
        delay: Delay in seconds between HTTP requests (default: 1.5)
        cache_dir: Directory for caching downloaded HTML (default: .cache/html, '' to disable)
        log_level: Logging level: DEBUG, INFO, WARNING, ERROR
    """
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = FBEParser(cache_dir=cache_dir if cache_dir else None, delay=delay)

    try:
        LOGGER.info(
            "Processing pages %d–%d with %.1fs delay", start_page, end_page, delay
        )
        parser.process_all(
            output_dir=output_dir,
            start_page=start_page,
            end_page=end_page,
        )
        LOGGER.info("Done!")
    finally:
        parser.close()


if __name__ == "__main__":
    fire.Fire(main)
