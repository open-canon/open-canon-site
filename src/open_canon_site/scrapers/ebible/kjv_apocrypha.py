"""Scraper that converts the ebible.org KJV Apocrypha (verse-per-line XML) to OSIS XML.

The ebible.org ``eng-kjv_vpl.zip`` archive contains one XML file with a flat ``<v b= c= v=>``
element per verse. This module downloads it, keeps the fourteen Apocrypha books, groups the
verses into book/chapter/verse ``pyosis`` structures and writes a combined OSIS file (and
optionally one file per book).
"""

from __future__ import annotations

import argparse
import datetime
import io
import logging
import pathlib
import xml.etree.ElementTree as ET
import zipfile

import httpx
import pyosis

from open_canon_site.scrapers.base import ScraperSpec

logger = logging.getLogger(__name__)
"""Module logger for download and output progress messages."""

DOWNLOAD_URL = "https://ebible.org/Scriptures/eng-kjv_vpl.zip"
"""URL of the zip archive holding the KJV verse-per-line XML."""
XML_FILENAME = "eng-kjv_vpl.xml"
"""Name of the XML member inside the downloaded zip archive."""

APOCRYPHA_BOOKS: dict[str, tuple[str, str]] = {
    "1ES": ("1 Esdras", "1Esd"),
    "2ES": ("2 Esdras", "2Esd"),
    "TOB": ("Tobit", "Tob"),
    "JDT": ("Judith", "Jdt"),
    "ESG": ("Additions to Esther", "AddEsth"),
    "WIS": ("Wisdom of Solomon", "Wis"),
    "SIR": ("Ecclesiasticus (Wisdom of Sirach)", "Sir"),
    "BAR": ("Baruch", "Bar"),
    "S3Y": ("Prayer of Azariah", "PrAzar"),
    "SUS": ("Susanna", "Sus"),
    "BEL": ("Bel and the Dragon", "Bel"),
    "MAN": ("Prayer of Manasseh", "PrMan"),
    "1MA": ("1 Maccabees", "1Macc"),
    "2MA": ("2 Maccabees", "2Macc"),
}
"""Maps VPL book code to ``(display name, OSIS book ID)``, in canonical KJV order.

Books whose code is not a key here are ignored when parsing; iteration order is the output order.
"""


def download_xml() -> bytes:
    """Download the KJV zip from ebible.org and return the XML member's bytes.

    Returns:
        The raw contents of ``XML_FILENAME`` extracted from the archive at ``DOWNLOAD_URL``.

    Network and archive errors propagate unchanged: ``httpx.HTTPStatusError`` for an error
    status, ``zipfile.BadZipFile`` for a corrupt body and ``KeyError`` if the member is missing.
    """
    logger.info("Downloading %s ...", DOWNLOAD_URL)
    response = httpx.get(DOWNLOAD_URL, follow_redirects=True)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        return zf.read(XML_FILENAME)


def parse_books(xml_bytes: bytes) -> dict[str, pyosis.DivCt]:
    """Parse VPL XML into one OSIS book ``div`` per Apocrypha book present.

    Every ``<v b="CODE" c="N" v="M">`` element whose code is in ``APOCRYPHA_BOOKS`` becomes a
    verse with ``osisID`` ``<OsisId>.N.M``; other books are skipped. Chapters and verses are
    sorted numerically, verse text is whitespace-stripped (missing text becomes ``""``), and
    each book div starts with a ``head`` holding the display name. Books with no verses are
    omitted with a warning.

    Args:
        xml_bytes: Raw bytes of the verse-per-line XML document.

    Returns:
        Mapping of VPL book code to its book ``DivCt``, in ``APOCRYPHA_BOOKS`` order.

    Malformed input propagates ``ElementTree.ParseError``; a matching element with a missing
    or non-integer chapter/verse attribute raises ``TypeError``/``ValueError``.
    """
    root = ET.fromstring(xml_bytes)

    # Collect verses grouped by book code -> chapter number -> list of (verse num, text)
    raw: dict[str, dict[int, list[tuple[int, str]]]] = {}
    for elem in root.iter("v"):
        book_code = elem.get("b")
        if book_code not in APOCRYPHA_BOOKS:
            continue
        chapter_num = int(elem.get("c"))
        verse_num = int(elem.get("v"))
        text = (elem.text or "").strip()
        raw.setdefault(book_code, {}).setdefault(chapter_num, []).append((verse_num, text))

    books: dict[str, pyosis.DivCt] = {}
    for book_code, (book_name, osis_id) in APOCRYPHA_BOOKS.items():
        if book_code not in raw:
            logger.warning("No verses found for %s (%s)", book_name, book_code)
            continue

        chapters = []
        for chapter_num in sorted(raw[book_code]):
            verses = [
                pyosis.VerseCt(
                    osis_id=[f"{osis_id}.{chapter_num}.{verse_num}"],
                    content=[text],
                )
                for verse_num, text in sorted(raw[book_code][chapter_num])
            ]
            chapters.append(
                pyosis.ChapterCt(
                    osis_id=[f"{osis_id}.{chapter_num}"],
                    content=verses,
                )
            )

        books[book_code] = pyosis.DivCt(
            osis_id=[osis_id],
            type_value=pyosis.OsisDivs.BOOK,
            content=[
                pyosis.HeadCt(content=[book_name]),
                *chapters,
            ],
        )

    return books


def books_to_osis_xml(books: list[pyosis.DivCt]) -> pyosis.OsisXML:
    """Wrap book divs in a complete OSIS document with header metadata.

    The work is ``kjv-apocrypha`` (title "King James Version--Apocrypha", English) and the
    revision date is the current local time, so output differs between runs.

    Args:
        books: Book-level divs (as returned by ``parse_books``) to place in the OSIS text.

    Returns:
        A ``pyosis.OsisXML`` object ready for ``.to_xml()``.
    """
    return pyosis.OsisXML(
        osis=pyosis.Osis(
            osis_text=pyosis.OsisTextCt(
                header=pyosis.HeaderCt(
                    work=[
                        pyosis.WorkCt(
                            osis_work="King James Version Apocrypha",
                            title=[pyosis.TitleCt(content=["King James Version--Apocrypha"])],
                            type_value=[
                                pyosis.TypeCt(type_value=pyosis.OsisType.OSIS, value="Bible")
                            ],
                        )
                    ],
                    revision_desc=[
                        pyosis.RevisionDescCt(
                            date=pyosis.DateCt(
                                event=pyosis.OsisEvents.EVERSION,
                                content=[datetime.datetime.now().strftime("%Y.%m.%dT%H:%M:%S")],
                                lang="en",
                            ),
                            p=[
                                pyosis.PCt(
                                    content=[
                                        "Downloaded from ebible.org (eng-kjv_vpl.zip),"
                                        " and converted to OSIS by the"
                                        " open-canon-site scrapers."
                                    ]
                                )
                            ],
                        )
                    ],
                ),
                lang="en",
                div=books,
                osis_idwork="kjv-apocrypha",
            )
        )
    )


def book_file_name(book_name: str) -> str:
    """Return the legacy per-book output filename, e.g. ``1_Esdras.xml``.

    Args:
        book_name: Display name; runs of whitespace become single underscores.

    Returns:
        The name with underscores and an ``.xml`` suffix.
    """
    return "_".join(book_name.split()) + ".xml"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register this scraper's CLI options.

    Args:
        parser: Sub-parser to which the ``--per-book`` flag is added.
    """
    parser.add_argument(
        "--per-book",
        action="store_true",
        help="also write one OSIS file per book (off by default: the site build "
        "globs every *.xml in the output directory)",
    )


def run(args: argparse.Namespace) -> list[pathlib.Path]:
    """Download, convert and write the KJV Apocrypha OSIS files.

    Always writes ``kjv_apocrypha.xml`` containing every book found; with ``args.per_book``
    also writes one file per book (named by ``book_file_name``) before it.

    Args:
        args: Parsed CLI arguments. ``output_dir`` is created if missing; ``per_book``
            (optional, default false) enables per-book files.

    Returns:
        Paths written, per-book files first (canonical order) and the combined file last.
    """
    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    books = parse_books(download_xml())

    written: list[pathlib.Path] = []
    all_book_divs = []
    for book_code, (book_name, _) in APOCRYPHA_BOOKS.items():
        if book_code not in books:
            continue
        book_div = books[book_code]
        all_book_divs.append(book_div)

        if getattr(args, "per_book", False):
            path = output_dir / book_file_name(book_name)
            path.write_text(books_to_osis_xml([book_div]).to_xml())
            logger.info("Saved %s", path.name)
            written.append(path)

    combined = output_dir / "kjv_apocrypha.xml"
    combined.write_text(books_to_osis_xml(all_book_divs).to_xml())
    logger.info("Saved %s", combined.name)
    written.append(combined)
    return written


SPEC = ScraperSpec(
    name="kjv-apocrypha",
    help="Scrape the KJV Apocrypha from ebible.org into OSIS XML.",
    source="https://ebible.org/Scriptures/eng-kjv_vpl.zip",
    outputs=("kjv_apocrypha.xml",),
    run=run,
    add_arguments=add_arguments,
)
"""Registry entry that exposes this scraper to the ``open-canon-scrape`` CLI."""
