"""Build an OSIS file of the "Lectures on Faith" from lecturesonfaith.com, in its 1835 and revised editions.

The seven Lectures on Faith were delivered to the School of the Elders in Kirtland, Ohio, in the winter of 1834-35 and
printed as the "Doctrine" part of the 1835 Doctrine and Covenants, preceded by the book's preface. They were removed from
the Doctrine and Covenants in 1921.

lecturesonfaith.com is a single-page React app: the text is not in any HTML page but compiled into its JavaScript bundle
as literal arrays of lectures, ``{number, title, subtitle, paragraphs: [P(n, text), ...], qa: [Q(question, answer),
...], note?}``, where ``P`` and ``Q`` are tiny factory functions (``function P(e,t){return{number:e,text:t}}``). The site
has two such arrays: the 1835 edition (which starts with the preface, lecture ``0``) and a modernised "Revised Standard
Edition" (lectures 1-7, with its own, finer paragraph numbering). The names are minified and change between
deployments, so the arrays are found by their shape, the factories by their bodies, and the literals are read with a
small parser for the subset of JavaScript they use (arrays, objects with bare keys, strings, numbers and factory calls)
rather than by evaluating any code.

The result is a book group ``LoF`` holding one book per edition, ``LoF1835`` and ``LoFRSE``. The 1835 book starts with
the preface as a front-matter page. Each lecture is a chapter (``LoF1835.1`` ... ``LoF1835.7``) whose numbered
paragraphs are verses, followed by its closing note (lecture 6) and its "Questions and Answers on the Foregoing
Principles" (lectures 1-5).

Known source defect: the site's 1835 array omits most of Lecture Second's catechism (the Adam-to-Abraham chronology
questions); it has 16 questions where the Revised Standard Edition has 148. The text is scraped as served rather than
filled in from the revised edition.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import logging
import re
from pathlib import Path
from typing import Any, Final
from urllib.parse import urljoin

import pyosis

from open_canon_site.scrapers._http import CachedHttpFetcher
from open_canon_site.scrapers.base import ScraperSpec

LOGGER = logging.getLogger(__name__)
"""Module logger."""

SOURCE_URL: Final[str] = "https://lecturesonfaith.com/"
"""Home page of the site; its HTML names the current JavaScript bundle."""
OUTPUT_FILENAME: Final[str] = "lectures_on_faith.xml"
"""Name of the OSIS file written."""
OSIS_WORK_ID: Final[str] = "LoF"
"""OSIS work id, also the id of the book group holding both editions."""
BOOK_TITLE: Final[str] = "Lectures on Faith"
"""Title of the work."""
QA_HEADING: Final[str] = "Questions and Answers on the Foregoing Principles"
"""Heading the site prints above each lecture's catechism."""
LECTURE_COUNT: Final[int] = 7
"""Number of lectures in each edition."""


@dataclasses.dataclass(frozen=True)
class Edition:
    """One edition of the lectures on the site, scraped as its own book."""

    osis_id: str
    """OSIS book id."""
    title: str
    """Book title."""
    short_title: str
    """Short title shown in the library and sidebar under "Lectures on Faith"."""
    has_preface: bool
    """Whether the edition starts with the 1835 preface (lecture 0)."""


EDITION_1835: Final[Edition] = Edition(
    "LoF1835", "Lectures on Faith (1835)", "1835 Edition", has_preface=True
)
"""The text as printed in the 1835 Doctrine and Covenants."""
EDITION_RSE: Final[Edition] = Edition(
    "LoFRSE",
    "Lectures on Faith (Revised Standard Edition)",
    "Revised Standard Edition",
    has_preface=False,
)
"""The site's modernised edition, with its own paragraph numbering and no preface."""
EDITIONS: Final[tuple[Edition, ...]] = (EDITION_1835, EDITION_RSE)
"""Both editions, in the order their books appear."""

_BUNDLE_RE: Final[re.Pattern[str]] = re.compile(
    r'<script[^>]*\bsrc="([^"]*/assets/index-[^"]+\.js)"'
)
"""The module script tag of the site's main bundle."""
_ARRAY_RE: Final[re.Pattern[str]] = re.compile(r"\b[\w$]+=\[\{number:\d+,title:")
"""Start of an edition's array of lectures."""
_FACTORY_RE: Final[re.Pattern[str]] = re.compile(
    r"function ([\w$]+)\(([\w$]+),([\w$]+)\)\{return\{([\w$]+):\2,([\w$]+):\3\}\}"
)
"""A two-argument factory returning ``{key1: arg1, key2: arg2}``."""


@dataclasses.dataclass(frozen=True)
class Paragraph:
    """One numbered paragraph of a lecture or the preface."""

    number: int
    """Paragraph number as printed."""
    text: str
    """Paragraph text; line breaks separate the lines of a signature block."""


@dataclasses.dataclass(frozen=True)
class QuestionAnswer:
    """One question and its answer from a lecture's catechism."""

    question: str
    """The question."""
    answer: str
    """The answer, with its scripture and paragraph references."""


@dataclasses.dataclass(frozen=True)
class Lecture:
    """A lecture (or, as number 0, the preface) of the 1835 edition."""

    number: int
    """Lecture number; ``0`` is the preface."""
    subtitle: str
    """Printed heading, e.g. ``"Lecture First"``; empty for the preface."""
    paragraphs: tuple[Paragraph, ...]
    """Numbered paragraphs, in order."""
    qa: tuple[QuestionAnswer, ...] = ()
    """The catechism that follows the lecture, if any."""
    note: str = ""
    """A closing note (lecture 6 has one in place of a catechism)."""


class JsLiteralParser:
    """Reads one JavaScript literal (arrays, objects, strings, numbers, factory calls) from minified source.

    Factory calls such as ``T(1,"text")`` are resolved through ``factories``, which maps a function name to the keys
    its arguments are assigned to; the call becomes a dict of those keys. Anything else (identifiers, operators,
    template literals with substitutions) raises ``ValueError``, so a change in the bundle's shape fails loudly instead
    of producing wrong text.
    """

    _IDENT_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_$][\w$]*")
    """A bare object key or function name."""
    _NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"-?\d+(?:\.\d+)?")
    """A decimal number literal."""
    _ESCAPES: Final[dict[str, str]] = {
        "n": "\n",
        "t": "\t",
        "r": "\r",
        "b": "\b",
        "f": "\f",
        "v": "\v",
        "0": "\0",
        "\n": "",
    }
    """Single-character escapes; any other escaped character stands for itself."""

    def __init__(self, source: str, factories: dict[str, tuple[str, ...]]) -> None:
        """Create a parser over ``source``.

        Args:
            source: The JavaScript source text.
            factories: Factory function names mapped to the keys their arguments become.
        """
        self.source = source
        """The JavaScript source being read."""
        self.factories = factories
        """Factory names mapped to the keys of the objects they build."""
        self.pos = 0
        """Index of the next unread character."""

    def parse(self, start: int) -> tuple[Any, int]:
        """Parse the literal starting at ``start``.

        Args:
            start: Index of the literal's first character.

        Returns:
            The parsed value and the index just past it.
        """
        self.pos = start
        value = self._value()
        return value, self.pos

    def _error(self, message: str) -> ValueError:
        """Build a ``ValueError`` quoting the source around the current position.

        Args:
            message: What went wrong.

        Returns:
            The error to raise.
        """
        context = self.source[max(0, self.pos - 60) : self.pos + 60]
        return ValueError(f"{message} at offset {self.pos}: {context!r}")

    def _skip_whitespace(self) -> None:
        """Advance past whitespace."""
        while self.pos < len(self.source) and self.source[self.pos].isspace():
            self.pos += 1

    def _peek(self) -> str:
        """Return the next non-whitespace character without consuming it.

        Returns:
            The character, or an empty string at the end of the source.
        """
        self._skip_whitespace()
        return self.source[self.pos : self.pos + 1]

    def _expect(self, char: str) -> None:
        """Consume ``char``, after any whitespace.

        Args:
            char: The character required next.
        """
        if self._peek() != char:
            raise self._error(f"Expected {char!r}")
        self.pos += 1

    def _sequence(self, close: str, item: Any) -> list[Any]:
        """Read comma-separated items up to and including ``close``.

        Args:
            close: The closing bracket.
            item: Callable reading one item.

        Returns:
            The items read.
        """
        items: list[Any] = []
        while self._peek() != close:
            items.append(item())
            if self._peek() == ",":
                self.pos += 1
            elif self._peek() != close:
                raise self._error(f"Expected ',' or {close!r}")
        self.pos += 1
        return items

    def _value(self) -> Any:
        """Read one value.

        Returns:
            A list, dict, string, number or boolean.
        """
        char = self._peek()
        if char == "[":
            self.pos += 1
            return self._sequence("]", self._value)
        if char == "{":
            self.pos += 1
            return dict(self._sequence("}", self._property))
        if char in "\"'`":
            return self._string(char)
        if self.source.startswith("!0", self.pos):
            self.pos += 2
            return True
        if self.source.startswith("!1", self.pos):
            self.pos += 2
            return False
        number = self._NUMBER_RE.match(self.source, self.pos)
        if number:
            self.pos = number.end()
            text = number.group(0)
            return float(text) if "." in text else int(text)
        ident = self._IDENT_RE.match(self.source, self.pos)
        if ident and ident.group(0) in self.factories:
            self.pos = ident.end()
            self._expect("(")
            args = self._sequence(")", self._value)
            keys = self.factories[ident.group(0)]
            if len(args) != len(keys):
                raise self._error(f"{ident.group(0)}() takes {len(keys)} arguments")
            return dict(zip(keys, args))
        raise self._error("Unsupported JavaScript")

    def _property(self) -> tuple[str, Any]:
        """Read one ``key: value`` property with a bare or quoted key.

        Returns:
            The key and its value.
        """
        char = self._peek()
        if char in "\"'":
            key = self._string(char)
        else:
            ident = self._IDENT_RE.match(self.source, self.pos)
            if not ident:
                raise self._error("Expected a property name")
            key = ident.group(0)
            self.pos = ident.end()
        self._expect(":")
        return key, self._value()

    def _string(self, quote: str) -> str:
        """Read a string literal opened by ``quote``, decoding escapes.

        Args:
            quote: The opening (and closing) quote character.

        Returns:
            The decoded string.
        """
        self.pos += 1
        out: list[str] = []
        source = self.source
        while True:
            if self.pos >= len(source):
                raise self._error("Unterminated string")
            char = source[self.pos]
            if char == quote:
                self.pos += 1
                return "".join(out)
            if quote == "`" and source.startswith("${", self.pos):
                raise self._error("Template substitution")
            if char != "\\":
                out.append(char)
                self.pos += 1
                continue
            escaped = source[self.pos + 1]
            if escaped == "u" and source[self.pos + 2] == "{":
                end = source.index("}", self.pos)
                out.append(chr(int(source[self.pos + 3 : end], 16)))
                self.pos = end + 1
            elif escaped == "u":
                out.append(chr(int(source[self.pos + 2 : self.pos + 6], 16)))
                self.pos += 6
            elif escaped == "x":
                out.append(chr(int(source[self.pos + 2 : self.pos + 4], 16)))
                self.pos += 4
            else:
                out.append(self._ESCAPES.get(escaped, escaped))
                self.pos += 2


def find_bundle_url(index_html: str, base_url: str = SOURCE_URL) -> str:
    """Return the absolute URL of the site's main JavaScript bundle.

    Args:
        index_html: The home page HTML.
        base_url: URL the home page was fetched from.

    Returns:
        The bundle URL.

    Raises:
        ValueError: If the page names no bundle.
    """
    match = _BUNDLE_RE.search(index_html)
    if not match:
        raise ValueError("lecturesonfaith.com home page names no /assets/index-*.js bundle")
    return urljoin(base_url, match.group(1))


def extract_editions(bundle: str) -> list[tuple[Edition, list[Lecture]]]:
    """Read both editions' lectures out of the JavaScript bundle.

    Every array literal of the shape ``NAME=[{number:N,title:...`` is read; the one starting with the preface
    (``number:0``) is the 1835 edition and the one starting with lecture 1 the Revised Standard Edition. The factory
    functions used by an array are the ones defined most recently before it, which keeps each edition's factories
    apart even if the minifier reuses a name.

    Args:
        bundle: The JavaScript bundle source.

    Returns:
        ``(edition, lectures)`` pairs in `EDITIONS` order. The 1835 lectures start with the preface (number 0).

    Raises:
        ValueError: If an array cannot be parsed, an edition is missing or found twice, or an edition's contents are
            not the expected lectures with consecutively numbered paragraphs.
    """
    found: dict[str, list[Lecture]] = {}
    for array in _ARRAY_RE.finditer(bundle):
        factories: dict[str, tuple[str, ...]] = {
            match.group(1): (match.group(4), match.group(5))
            for match in _FACTORY_RE.finditer(bundle, 0, array.start())
        }
        start = bundle.index("[", array.start())
        raw, _ = JsLiteralParser(bundle, factories).parse(start)
        lectures = [_lecture_from_raw(item) for item in raw]
        edition = EDITION_1835 if lectures and lectures[0].number == 0 else EDITION_RSE
        if edition.osis_id in found:
            raise ValueError(f"Found two lecture arrays for the {edition.title}")
        _validate(edition, lectures)
        found[edition.osis_id] = lectures

    missing = [edition.title for edition in EDITIONS if edition.osis_id not in found]
    if missing:
        raise ValueError(f"No lecture array in the bundle for: {', '.join(missing)}")
    return [(edition, found[edition.osis_id]) for edition in EDITIONS]


def _validate(edition: Edition, lectures: list[Lecture]) -> None:
    """Check an edition holds the expected lectures with consecutively numbered paragraphs.

    Args:
        edition: The edition the lectures were read for.
        lectures: The lectures read.

    Raises:
        ValueError: If lectures are missing or out of order, or a lecture's paragraphs skip a number.
    """
    expected = list(range(0 if edition.has_preface else 1, LECTURE_COUNT + 1))
    numbers = [lecture.number for lecture in lectures]
    if numbers != expected:
        raise ValueError(f"{edition.title}: expected lectures {expected}, got {numbers}")
    for lecture in lectures:
        paragraph_numbers = [paragraph.number for paragraph in lecture.paragraphs]
        if paragraph_numbers != list(range(1, len(paragraph_numbers) + 1)) or not paragraph_numbers:
            raise ValueError(
                f"{edition.title}: lecture {lecture.number} paragraphs are numbered {paragraph_numbers}"
            )


def _lecture_from_raw(item: Any) -> Lecture:
    """Convert one parsed array entry into a `Lecture`.

    Args:
        item: A dict with ``number``, ``subtitle``, ``paragraphs`` (dicts of ``number``/``text``), ``qa`` (dicts of
            ``question``/``answer``) and optionally ``note``.

    Returns:
        The lecture.

    Raises:
        ValueError: If a field is missing or of the wrong type.
    """
    try:
        return Lecture(
            number=int(item["number"]),
            subtitle=str(item["subtitle"]).strip(),
            paragraphs=tuple(
                Paragraph(number=int(p["number"]), text=_require_str(p["text"]))
                for p in item["paragraphs"]
            ),
            qa=tuple(
                QuestionAnswer(
                    question=_require_str(q["question"]), answer=_require_str(q["answer"])
                )
                for q in item.get("qa", [])
            ),
            note=_require_str(item.get("note", "")),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Unexpected lecture entry: {str(item)[:200]}") from exc


def _require_str(value: Any) -> str:
    """Return ``value`` stripped, insisting it is a string.

    Args:
        value: A parsed value.

    Returns:
        The stripped string.

    Raises:
        TypeError: If ``value`` is not a string.
    """
    if not isinstance(value, str):
        raise TypeError(f"Expected a string, got {value!r}")
    return value.strip()


def _paragraphs_of(text: str) -> list[pyosis.PCt]:
    """Split text on line breaks into one paragraph per non-empty line.

    Args:
        text: Text whose lines (e.g. of a signature block) are printed separately.

    Returns:
        One ``PCt`` per line.
    """
    return [pyosis.PCt(content=[line.strip()]) for line in text.splitlines() if line.strip()]


def _preface_div(edition: Edition, preface: Lecture) -> pyosis.DivCt:
    """Build the preface's front-matter division.

    The site numbers the preface's paragraphs, but the 1835 printing does not, so they become plain paragraphs.

    Args:
        edition: The edition the preface belongs to.
        preface: Lecture 0.

    Returns:
        A ``preface`` division ``<book>.Preface`` titled "Preface".
    """
    content: list[Any] = [pyosis.TitleCt(type_value=pyosis.OsisTitles.MAIN, content=["Preface"])]
    for paragraph in preface.paragraphs:
        content.extend(_paragraphs_of(paragraph.text))
    return pyosis.DivCt(
        type_value=pyosis.OsisDivs.PREFACE,
        osis_id=[f"{edition.osis_id}.Preface"],
        canonical=True,
        content=content,
    )


def _qa_div(lecture: Lecture) -> pyosis.DivCt:
    """Build a lecture's catechism: the heading, then each question (in bold) followed by its answer.

    Args:
        lecture: A lecture with a non-empty ``qa``.

    Returns:
        A ``section`` division.
    """
    content: list[Any] = [pyosis.TitleCt(type_value=pyosis.OsisTitles.MAIN, content=[QA_HEADING])]
    for pair in lecture.qa:
        content.append(
            pyosis.PCt(
                content=[pyosis.HiCt(type_value=pyosis.OsisHi.BOLD, content=[pair.question])]
            )
        )
        content.append(pyosis.PCt(content=[pair.answer]))
    return pyosis.DivCt(type_value=pyosis.OsisDivs.SECTION, canonical=True, content=content)


def _lecture_div(edition: Edition, lecture: Lecture) -> pyosis.DivCt:
    """Build a lecture's chapter division.

    Args:
        edition: The edition the lecture belongs to.
        lecture: A lecture numbered 1 or more.

    Returns:
        A chapter ``<book>.<n>`` titled with the printed heading, its paragraphs as verses ``<book>.<n>.<p>``,
        followed by the closing note and catechism, if any.
    """
    chapter_id = f"{edition.osis_id}.{lecture.number}"
    content: list[Any] = [
        pyosis.TitleCt(type_value=pyosis.OsisTitles.MAIN, content=[lecture.subtitle])
    ]
    for paragraph in lecture.paragraphs:
        verse_id = f"{chapter_id}.{paragraph.number}"
        content.append(pyosis.VerseCt(osis_id=[verse_id], canonical=True, content=[paragraph.text]))
    if lecture.note:
        content.extend(_paragraphs_of(lecture.note))
    if lecture.qa:
        content.append(_qa_div(lecture))
    return pyosis.DivCt(
        type_value=pyosis.OsisDivs.CHAPTER, osis_id=[chapter_id], canonical=True, content=content
    )


def _book_div(edition: Edition, lectures: list[Lecture]) -> pyosis.DivCt:
    """Build one edition's book division.

    Args:
        edition: The edition.
        lectures: Its lectures, starting with the preface when the edition has one.

    Returns:
        A book ``<edition.osis_id>`` holding the preface page (if any) and one chapter per lecture.
    """
    content: list[Any] = [
        pyosis.TitleCt(
            type_value=pyosis.OsisTitles.MAIN, short=edition.short_title, content=[edition.title]
        )
    ]
    for lecture in lectures:
        if lecture.number == 0:
            content.append(_preface_div(edition, lecture))
        else:
            content.append(_lecture_div(edition, lecture))
    return pyosis.DivCt(
        type_value=pyosis.OsisDivs.BOOK, osis_id=[edition.osis_id], canonical=True, content=content
    )


def generate_osis(
    editions: list[tuple[Edition, list[Lecture]]], bundle_url: str = SOURCE_URL
) -> pyosis.OsisXML:
    """Assemble the OSIS document.

    Args:
        editions: ``(edition, lectures)`` pairs, as returned by `extract_editions`.
        bundle_url: Where the text was read from, recorded in the header.

    Returns:
        The OSIS document: a ``bookGroup`` ``LoF`` holding one book per edition.
    """
    book_group = pyosis.DivCt(
        type_value=pyosis.OsisDivs.BOOK_GROUP,
        osis_id=[OSIS_WORK_ID],
        canonical=True,
        content=[
            pyosis.TitleCt(type_value=pyosis.OsisTitles.MAIN, content=[BOOK_TITLE]),
            *(_book_div(edition, lectures) for edition, lectures in editions),
        ],
    )
    header = pyosis.HeaderCt(
        canonical=False,
        revision_desc=[
            pyosis.RevisionDescCt(
                date=pyosis.DateCt(
                    event=pyosis.OsisEvents.EVERSION,
                    type_value="ISO",
                    lang="en",
                    content=[datetime.datetime.now().strftime("%Y.%m.%dT%H:%M:%S")],
                ),
                p=[
                    pyosis.PCt(
                        content=[
                            f"Scraped from {SOURCE_URL} (the 1835 edition and the Revised Standard Edition, read"
                            f" from {bundle_url}) and converted to OSIS by the open-canon-site scrapers."
                        ]
                    )
                ],
            ),
            pyosis.RevisionDescCt(
                date=pyosis.DateCt(
                    event=pyosis.OsisEvents.EDITION, type_value="ISO", lang="en", content=["1835"]
                ),
                p=[
                    pyosis.PCt(
                        content=[
                            "Doctrine and Covenants of the Church of the Latter Day Saints, Kirtland, Ohio: F. G."
                            ' Williams & Co., 1835. Part first, "On the Doctrine of the Church of the Latter Day'
                            ' Saints."'
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
                        value="Seven lectures on faith delivered to the School of the Elders in Kirtland, Ohio, in"
                        " 1834-35, published with the preface of the 1835 Doctrine and Covenants and removed from it"
                        " in 1921. Includes the 1835 text and the modernised Revised Standard Edition published at"
                        " lecturesonfaith.com."
                    )
                ],
                type_value=[pyosis.TypeCt(type_value="OSIS", content=["Bible"])],
                creator=[
                    pyosis.CreatorCt(
                        role=pyosis.OsisRoles.AUT,
                        value="Joseph Smith, Sidney Rigdon and others",
                    )
                ],
                publisher=[pyosis.PublisherCt(value="F. G. Williams & Co.")],
            )
        ],
    )
    osis_text = pyosis.OsisTextCt(
        lang="en",
        osis_idwork=OSIS_WORK_ID,
        osis_ref_work=BOOK_TITLE,
        canonical=True,
        header=header,
        div=[book_group],
    )
    return pyosis.OsisXML(pyosis.Osis(osis_text=osis_text))


def scrape(fetcher: CachedHttpFetcher) -> pyosis.OsisXML:
    """Fetch the site's home page and bundle and convert both editions to OSIS.

    Args:
        fetcher: Fetcher used for both requests.

    Returns:
        The OSIS document.
    """
    bundle_url = find_bundle_url(fetcher.fetch_text(url=SOURCE_URL))
    LOGGER.info("Reading Lectures on Faith from %s", bundle_url)
    return generate_osis(extract_editions(fetcher.fetch_text(url=bundle_url)), bundle_url)


def run(args: argparse.Namespace) -> list[Path]:
    """Scrape the Lectures on Faith and write ``lectures_on_faith.xml``.

    Args:
        args: Parsed CLI arguments providing ``cache_dir``, ``delay`` and ``output_dir``.

    Returns:
        A one-element list with the written file's path.
    """
    fetcher = CachedHttpFetcher(cache_dir=args.cache_dir, delay=args.delay, logger=LOGGER)
    try:
        osis_doc = scrape(fetcher)
    finally:
        fetcher.close()
    output_path = Path(args.output_dir) / OUTPUT_FILENAME
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(osis_doc.to_xml(), encoding="utf-8")
    return [output_path]


SPEC = ScraperSpec(
    name="lectures-on-faith",
    help="Lectures on Faith (1835 and Revised Standard editions) from lecturesonfaith.com to OSIS",
    source=SOURCE_URL,
    outputs=(OUTPUT_FILENAME,),
    run=run,
)
"""Registry entry that exposes this scraper to the CLI."""
