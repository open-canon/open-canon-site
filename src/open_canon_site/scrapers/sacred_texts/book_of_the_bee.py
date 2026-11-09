"""Download and parse E. A. Wallis Budge's *The Book of the Bee* to OSIS XML.

Source: ``https://sacred-texts.com/chr/bb/`` (Budge's 1886 Clarendon Press edition: the
Syriac text of Solomon of Basra with an English translation). The pages are fetched from
``archive.sacred-texts.com``, which still serves the original markup. Only the English
translation is on the site.

This scraper is the sibling of :mod:`.cave_of_treasures` (the same Syriac/Budge family, the
same markup) and reuses its page parser. The reference scheme matches it:

* **Chapter** = one of the sixty chapters of the book, numbered 1 to 60 as the author
  numbers them (``Bee.<chapter>.<verse>``).
* **Verse** = one paragraph of the translation, numbered consecutively from 1 within its
  chapter. The book has no verse numbers of its own.
* **Headings** (``CHAPTER I.`` and the title that follows it) are non-canonical sub-titles.
* **Page markers** (``p. 6``, the printed page of the 1886 edition) become
  ``<milestone type="page">`` elements; Budge's footnotes become inline ``<note>`` elements.

Front matter (title page, preface and the introduction with the author's apology) is kept as
non-canonical divs before the chapters. The transcriber's "note to the hypertext
transcription" page is not scraped.
"""

from __future__ import annotations

import argparse
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Final

import pyosis

from open_canon_site.scrapers.base import ScraperSpec
from open_canon_site.scrapers.sacred_texts.cave_of_treasures import (
    DIV_TYPES,
    CaveOfTreasuresParser,
    Chapter,
    ChapterSource,
)

LOGGER = logging.getLogger(__name__)
"""Module logger."""

OUTPUT_FILENAME: Final[str] = "book-of-the-bee.xml"
"""Name of the OSIS file written into the output directory."""
SOURCE_URL: Final[str] = "https://sacred-texts.com/chr/bb/index.htm"
"""Human-facing URL of the book, recorded in the OSIS header and ``SPEC.source``."""
PAGE_URL_TEMPLATE: Final[str] = "https://archive.sacred-texts.com/chr/bb/{page}.htm"
"""``str.format`` template for a page URL; ``{page}`` is the page stem such as ``bb01``."""
OSIS_WORK_ID: Final[str] = "Bee"
"""OSIS work identifier, also the book id prefix (``Bee.<chapter>.<verse>``)."""
BOOK_TITLE: Final[str] = "The Book of the Bee"
"""Full title of the book."""
BOOK_SHORT_TITLE: Final[str] = "Bee"
"""Short title used for the OSIS main title and ``osisRefWork``."""

CHAPTER_TITLES: Final[tuple[str, ...]] = (
    "Of God's Eternal Intention in Respect of the Creation of the Universe",
    "Of the Creation of the Seven Natures (Substances) in Silence",
    "Of Earth, Water, Air, and Fire",
    "Of Heaven",
    "Of the Angels",
    "Of Darkness",
    "Of Effused (Circumambient) Light",
    "Of the Firmament",
    "Of the Creation of Trees and Plants, and the Making of Seas and Rivers",
    "Of the Making of the Luminaries",
    "Of the Creation of Sea-Monsters, Fish, Winged Fowl, and the Reptiles that are in the Seas",
    "Of the Creation of Beasts and Animals",
    "Of the Formation of Adam",
    "Of the Making of Eve",
    "Of Paradise",
    "Of the Sin of Adam",
    "Of the Expulsion of Adam and Eve from Paradise",
    "Of Adam's Knowing Eve",
    "Of the Invention of the Instruments for Working in Iron",
    "Of Noah and the Flood",
    "Of Melchizedek",
    "Of the Generations of Noah",
    "Of the Succession of Generations from the Flood until Now",
    "Of the Building of the Tower and the Division of Tongues",
    "Of Abraham",
    "Of the Temptation of Job",
    "Of the Blessings of Isaac",
    "Of Joseph",
    "Of Moses and the Children of Israel",
    "The History of Moses' Rod",
    "Of Joshua the Son of Nun, and Brief Notices of the Years of the Judges and the Kings of "
    "the Children of Israel",
    "Of the Death of the Prophets; How They Died, and (Where) Each One of Them Was Buried",
    "Of the Messianic Generations",
    "Of the Annunciation of the Angel to Yônâkîr (Joachim) in Respect of Mary",
    "Of the Annunciation by Gabriel to Mary of the Conception of Our Lord",
    "Of the Birth of Our Lord in the Flesh",
    "The Prophecy of Zârâdôsht Concerning Our Lord",
    "Of the Star which Appeared in the East on the Day of the Birth of Our Lord",
    "Of the Coming of the Magi from Persia",
    "Of Our Lord's Going Down into Egypt",
    "Of John the Baptist, and of the Baptism of Our Lord",
    "Of Our Lord's Fast; of the Strife which He Waged with the Devil",
    "Of the Passover of Our Lord",
    "Of the Passion of Our Lord",
    "Of the Resurrection of Our Lord",
    "Of the Ascension of Our Lord to Heaven",
    "Of the Descent of the Holy Spirit upon the Apostles in the Upper Chamber",
    "Of the Teaching of the Apostles, and of the Places of Each One of Them, and of Their Deaths",
    "The Names of the Apostles in Order",
    "Of Some Minor Matters",
    "The Names of the Eastern Catholics, the Successors of the Apostles Addai and Mârî",
    "The Names of the Kings Who Have Reigned in the World from the Flood until Now",
    "Of the End of Times and the Change of Kingdoms",
    "Of Gog and Magog, Who Are Imprisoned in the North",
    "Of the Coming of the Antichrist, the Son of Perdition",
    "Of Death and the Departure of the Soul from the Body",
    "Of the Quickening and the General Resurrection, the Consummation of the Material World "
    "and the Beginning of the New World",
    "Of the Manner and State in which Men Will Rise in the Day of the Resurrection",
    "Of the Happiness of the Righteous and the Torment of Sinners, and in What State They "
    "Are There",
    "Whether Mercy Will Be Shewn to Sinners and the Devils in Gehenna, after They Have Been "
    "Tormented and Suffered and Been Punished, or not? And if Mercy Is to Be Shewn to Them, "
    "When Will It Be?",
)
"""Chapter titles in order, as the site's index lists them (chapter ``n`` is item ``n - 1``)."""


def _roman(number: int) -> str:
    """Return a number as an upper-case Roman numeral.

    Args:
        number: Positive integer.

    Returns:
        Its Roman numeral, e.g. ``XXXIX`` for 39.
    """
    out = ""
    for value, symbol in (
        (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ):  # fmt: skip
        while number >= value:
            out += symbol
            number -= value
    return out


FRONT_MATTER: Final[tuple[ChapterSource, ...]] = (
    ChapterSource("bbtp", "Title Page", re.compile(r"BOOK OF THE BEE"), "titlePage"),
    ChapterSource("bbpref", "Preface", re.compile(r"PREFACE"), "preface"),
    ChapterSource("bb00", "Introduction", re.compile(r"THE APOLOGY"), "introduction"),
)
"""The unnumbered front matter, in book order."""
CHAPTERS: Final[tuple[ChapterSource, ...]] = tuple(
    ChapterSource(f"bb{n:02d}", title, re.compile(rf"CHAPTER {_roman(n)}\b"))
    for n, title in enumerate(CHAPTER_TITLES, start=1)
)
"""The sixty numbered chapters; chapter ``n`` is ``CHAPTERS[n - 1]``."""
SECTIONS: Final[tuple[ChapterSource, ...]] = (*FRONT_MATTER, *CHAPTERS)
"""Every scraped page in book order."""


class BookOfTheBeeParser(CaveOfTreasuresParser):
    """Fetch and parse the Book of the Bee, reusing the Cave of Treasures page parser."""

    def fetch_page_text(self, source: ChapterSource) -> str:
        """Return the validated HTML of one page, from cache or the network.

        Args:
            source: Section to fetch.

        Returns:
            Raw HTML of the page.
        """
        return self._fetch_validated(
            PAGE_URL_TEMPLATE.format(page=source.page),
            lambda text: self.is_valid_page(text, source),
            repr(source.title),
        )

    def generate_osis(self, chapters: list[Chapter], plates: object = None) -> pyosis.OsisXML:
        """Build the OSIS document for the book.

        Args:
            chapters: Front matter and chapters in book order.
            plates: Unused; the book has no plates.

        Returns:
            An OSIS document with one canonical chapter div per chapter and verse ids
            ``Bee.<chapter>.<verse>``; headings and front matter are non-canonical.
        """
        del plates
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
        for chapter in chapters:
            numbered = chapter.role == "chapter"
            chapter_div = pyosis.DivCt(
                type_value=pyosis.OsisDivs.CHAPTER if numbered else DIV_TYPES[chapter.role],
                osis_id=[f"{OSIS_WORK_ID}.{chapter.number}"] if numbered else [],
                canonical=numbered,
                content=[
                    pyosis.TitleCt(
                        type_value=pyosis.OsisTitles.CHAPTER
                        if numbered
                        else pyosis.OsisTitles.MAIN,
                        canonical=False,
                        content=[chapter.title],
                    )
                ],
            )
            verse_number = 0
            for block in chapter.blocks:
                if block.kind == "heading":
                    title = pyosis.TitleCt(
                        type_value=pyosis.OsisTitles.SUB,
                        canonical=False,
                        content=self._heading_content(block.parts),
                    )
                    chapter_div.content.append(
                        title
                        if numbered
                        else pyosis.DivCt(
                            type_value=pyosis.OsisDivs.SECTION, canonical=False, content=[title]
                        )
                    )
                elif block.kind == "figures":
                    continue
                elif not numbered:
                    chapter_div.content.append(pyosis.PCt(content=block.parts))
                else:
                    verse_number += 1
                    chapter_div.content.append(
                        pyosis.VerseCt(
                            osis_id=[f"{OSIS_WORK_ID}.{chapter.number}.{verse_number}"],
                            canonical=True,
                            content=block.parts,
                        )
                    )
            book_div.content.append(chapter_div)

        current_date = datetime.now().strftime("%Y.%m.%dT%H:%M:%S")
        description = (
            "The Book of the Bee by Solomon of Basra, translated from the Syriac by E. A. "
            "Wallis Budge, 1886. Transcribed at sacred-texts.com and converted to OSIS by the "
            "open-canon-site scrapers."
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
                                f"Scraped from {SOURCE_URL} and converted to OSIS by Andrew P. Sansom."
                            ]
                        )
                    ],
                ),
                pyosis.RevisionDescCt(
                    date=pyosis.DateCt(
                        event=pyosis.OsisEvents.EDITION,
                        type_value="ISO",
                        lang="en",
                        content=["1886"],
                    ),
                    p=[
                        pyosis.PCt(
                            content=[
                                "The Book of the Bee, the Syriac text edited from the manuscripts "
                                "in London, Oxford and Munich with an English translation by "
                                "Ernest A. Wallis Budge, Oxford: At the Clarendon Press, 1886."
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
                    description=[pyosis.DescriptionCt(value=description)],
                    type_value=[pyosis.TypeCt(type_value="OSIS", content=["Bible"])],
                    creator=[
                        pyosis.CreatorCt(role=pyosis.OsisRoles.TRL, value="E. A. Wallis Budge"),
                        pyosis.CreatorCt(role=pyosis.OsisRoles.AUT, value="Solomon of Basra"),
                    ],
                    publisher=[pyosis.PublisherCt(value="Clarendon Press")],
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
        """Run the full pipeline: fetch every page, parse and convert.

        Returns:
            The OSIS document.
        """
        numbers = {source.page: n for n, source in enumerate(CHAPTERS, start=1)}
        chapters = [
            self.parse_section(self.fetch_page_text(source), source, numbers.get(source.page, 0))
            for source in SECTIONS
        ]
        return self.generate_osis(chapters)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register scraper-specific options; the Book of the Bee has none.

    Args:
        parser: Sub-parser to extend (left unchanged).
    """


def run(args: argparse.Namespace) -> list[Path]:
    """Scrape the Book of the Bee and write ``book-of-the-bee.xml``.

    Args:
        args: Parsed CLI arguments providing ``cache_dir``, ``delay`` and ``output_dir``.

    Returns:
        A one-element list with the written file's path.
    """
    parser = BookOfTheBeeParser(cache_dir=args.cache_dir, delay=args.delay)
    try:
        osis_doc = parser.process()
        output_path = Path(args.output_dir) / OUTPUT_FILENAME
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(osis_doc.to_xml(), encoding="utf-8")
    finally:
        parser.close()
    return [output_path]


SPEC = ScraperSpec(
    name="book-of-the-bee",
    help="The Book of the Bee (E. A. Wallis Budge, 1886) to OSIS",
    source=SOURCE_URL,
    outputs=(OUTPUT_FILENAME,),
    run=run,
    add_arguments=add_arguments,
)
"""Registry entry that exposes this scraper to the CLI."""
