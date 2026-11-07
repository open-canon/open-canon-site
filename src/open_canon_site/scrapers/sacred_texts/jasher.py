# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "beautifulsoup4",
#     "fire",
#     "httpx",
#     "pyosis",
# ]
# ///
"""Download and parse the Book of Jasher to OSIS XML."""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

import fire
import pyosis
from bs4 import BeautifulSoup

from .http_client import CachedHttpFetcher
from .osis_parsing import normalize_whitespace

LOGGER = logging.getLogger(__name__)

INDEX_URL: Final[str] = "https://sacred-texts.com/chr/apo/jasher/index.htm"
CHAPTER_URL_TEMPLATE: Final[str] = "https://sacred-texts.com/chr/apo/jasher/{page}.htm"
DEFAULT_OUTPUT: Final[str] = str(Path("documents") / "jasher.xml")
OSIS_WORK_ID: Final[str] = "Jasher"
BOOK_TITLE: Final[str] = "The Book of Jasher"
BOOK_SHORT_TITLE: Final[str] = "Jasher"
EXPECTED_CHAPTERS: Final[list[int]] = list(range(1, 92))

CHAPTER_HEADING_RE: Final[re.Pattern[str]] = re.compile(
    r"Book of Jasher,\s*Chapter\s*(?P<chapter>\d+)",
    re.IGNORECASE,
)
VERSE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<verse>\d+)\s+(?P<text>.+)$",
    re.DOTALL,
)
PARAGRAPH_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"(?i)<p(?:\s+[^>]*)?>")
TAG_RE: Final[re.Pattern[str]] = re.compile(r"<[^>]+>")
BODY_AFTER_H1_RE: Final[re.Pattern[str]] = re.compile(
    r"(?is)<h1[^>]*>\s*(?P<heading>.*?)\s*</h1>(?P<body>.*)"
)


@dataclass
class FrontMatterSection:
    title: str
    div_type: pyosis.OsisDivs
    paragraphs: list[str]


@dataclass
class Verse:
    number: int
    text: str


@dataclass
class Chapter:
    number: int
    verses: list[Verse]


class JasherParser:
    def __init__(self, cache_dir: str | None = None, delay: float = 1.0) -> None:
        self.http = CachedHttpFetcher(cache_dir=cache_dir, delay=delay, logger=LOGGER)

    def close(self) -> None:
        self.http.close()

    def fetch_index_text(self) -> str:
        return self._fetch_validated_page(
            url=INDEX_URL,
            validator=self.is_valid_index,
            invalid_error=(
                "Source page did not contain the Book of Jasher index; direct access "
                "to sacred-texts.com may be blocked in this environment"
            ),
        )

    def fetch_chapter_text(self, chapter_number: int) -> str:
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
        return (
            "The Book of Jasher" in text
            and "Faithfully Translated" in text
            and '<A HREF="91.htm">Chapter 91</A>' in text
            and "Just a moment" not in text
        )

    @staticmethod
    def is_valid_chapter_page(text: str, chapter_number: int) -> bool:
        return (
            f"Book of Jasher, Chapter {chapter_number}" in text
            and "Just a moment" not in text
            and bool(re.search(r"(?i)<p(?:\s+[^>]*)?>\s*1\s+", text))
        )

    @staticmethod
    def _strip_tags(fragment: str) -> str:
        text = re.sub(r"(?i)<br\s*/?>", "\n", fragment)
        text = re.sub(r"(?i)</p>", "\n", text)
        text = TAG_RE.sub("", text)
        return html.unescape(text)

    @classmethod
    def _extract_content_after_heading(cls, raw_html: str) -> tuple[str, str]:
        match = BODY_AFTER_H1_RE.search(raw_html)
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
        text = cls._strip_tags(raw_html_fragment)
        return [
            normalized
            for raw_line in text.splitlines()
            if (normalized := normalize_whitespace(raw_line))
        ]

    @classmethod
    def parse_front_matter(cls, raw_index_html: str) -> list[FrontMatterSection]:
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

    @staticmethod
    def extract_chapter_numbers(raw_index_html: str) -> list[int]:
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
        heading, content_html = cls._extract_content_after_heading(raw_html)
        heading_match = CHAPTER_HEADING_RE.search(heading)
        if not heading_match:
            raise RuntimeError(
                f"Could not determine Jasher chapter from heading: {heading}"
            )

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
                        *[
                            pyosis.PCt(content=[paragraph])
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
                            value="The Book of Jasher from the 1887 English edition published by J.H. Parry & Company. Transcribed at sacred-texts.com and converted to OSIS in this repository."
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


def main(
    output: str = DEFAULT_OUTPUT,
    delay: float = 1.5,
    cache_dir: str = ".cache/html",
    log_level: str = "INFO",
) -> None:
    """Download and convert the Book of Jasher to OSIS XML."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = JasherParser(cache_dir=cache_dir if cache_dir else None, delay=delay)
    try:
        osis_doc = parser.process()
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(osis_doc.to_xml(), encoding="utf-8")
    finally:
        parser.close()


if __name__ == "__main__":
    fire.Fire(main)
