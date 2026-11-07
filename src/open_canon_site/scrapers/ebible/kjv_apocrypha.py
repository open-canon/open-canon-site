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

DOWNLOAD_URL = "https://ebible.org/Scriptures/eng-kjv_vpl.zip"
XML_FILENAME = "eng-kjv_vpl.xml"

# Mapping: VPL book code -> (display name, OSIS ID), in canonical KJV order
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


def download_xml() -> bytes:
    logger.info("Downloading %s ...", DOWNLOAD_URL)
    response = httpx.get(DOWNLOAD_URL, follow_redirects=True)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        return zf.read(XML_FILENAME)


def parse_books(xml_bytes: bytes) -> dict[str, pyosis.DivCt]:
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
    """Legacy per-book output filename, e.g. ``1_Esdras.xml``."""
    return "_".join(book_name.split()) + ".xml"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--per-book",
        action="store_true",
        help="also write one OSIS file per book (off by default: the site build "
        "globs every *.xml in the output directory)",
    )


def run(args: argparse.Namespace) -> list[pathlib.Path]:
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
