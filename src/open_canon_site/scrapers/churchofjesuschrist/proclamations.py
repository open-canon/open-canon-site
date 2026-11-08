"""Build an OSIS file of the official proclamations that the Church publishes in Gospel Library.

The Church of Jesus Christ of Latter-day Saints has issued six official proclamations (1841, 1845, 1865, 1980, 1995 and
2020). Only the last three are available through the Study API, so only those are scraped here:

- "Proclamation" (6 April 1980), served as the conference talk ``/general-conference/1980/04/proclamation``;
- "The Family: A Proclamation to the World" (1995), ``/scriptures/the-family-a-proclamation-to-the-world/...``;
- "The Restoration of the Fulness of the Gospel of Jesus Christ: A Bicentennial Proclamation to the World" (2020),
  ``/scriptures/the-restoration-of-the-fulness-of-the-gospel-of-jesus-christ/...``.

The 1841, 1845 and 1865 proclamations survive only in newspaper archives and third-party sites and are not scraped.
"The Living Christ" (2000) is a testimony, not one of the six proclamations, and is also left out.

Each proclamation becomes a book division (``Proc1980``, ``Proc1995``, ``Proc2020``) with a single chapter whose
paragraphs are verses, mirroring the Official Declarations in ``doctrine_and_covenants``. These are not standard works,
so they get their own output file and ``open-canon-scrape lds-proclamations`` subcommand instead of a flag of
``lds-standard-works``.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime
import pathlib

import bs4
import bs4.element
import httpx
import pyosis.generated
import pyosis.serialization

from open_canon_site.scrapers.base import ScraperSpec
from open_canon_site.scrapers.churchofjesuschrist import models as church_website_models
from open_canon_site.scrapers.churchofjesuschrist.build_osis import clean_up_html, extract_markup


@dataclasses.dataclass(frozen=True)
class Proclamation:
    """One proclamation available through the Study API."""

    osis_id: str
    """OSIS book id, e.g. ``"Proc1995"``."""
    uri: str
    """Site-relative Study API URI of the page."""
    year: int
    """Year the proclamation was issued."""


PROCLAMATIONS: tuple[Proclamation, ...] = (
    Proclamation("Proc1980", "/general-conference/1980/04/proclamation", 1980),
    Proclamation(
        "Proc1995",
        "/scriptures/the-family-a-proclamation-to-the-world/the-family-a-proclamation-to-the-world",
        1995,
    ),
    Proclamation(
        "Proc2020",
        "/scriptures/the-restoration-of-the-fulness-of-the-gospel-of-jesus-christ/"
        "a-bicentennial-proclamation-to-the-world",
        2020,
    ),
)
"""The proclamations scraped, in chronological order."""


def _title_text(tag: bs4.element.Tag | None) -> str:
    """Return the stripped text of an optional tag.

    Args:
        tag: Tag to read, or None.

    Returns:
        The tag's text, or an empty string for None.
    """
    return tag.get_text().strip() if tag else ""


def build_proclamation(
    proclamation: Proclamation, content: church_website_models.ScriptureStudyContent
) -> pyosis.generated.DivCt:
    """Convert one proclamation page into an OSIS book division.

    The page has a ``header`` (``h1#title1``, optional ``p.subtitle``, optional ``div.byline``), a ``div.body-block`` of
    plain paragraphs and, for the 1995 and 2020 texts, a trailing ``div.event`` note on when it was read. Title and
    subtitle become the book's titles, the byline a non-canonical introduction, every body paragraph a verse
    ``<osis_id>.1.<n>`` and the event note a non-canonical colophon.

    Args:
        proclamation: Which proclamation the page is.
        content: The parsed Study API response.

    Returns:
        A book-level division holding one chapter.

    Raises:
        ValueError: If the page has no ``div.body-block`` or it contains no paragraphs.
    """
    footnotes = content.content.footnotes
    soup = clean_up_html(bs4.BeautifulSoup(content.content.body, "html.parser"))

    body = soup.find("div", class_="body-block")
    if not isinstance(body, bs4.element.Tag):
        raise ValueError(f"{proclamation.uri} has no body block")

    front: list[object] = []
    title = _title_text(soup.find("h1", id="title1"))
    if title:
        front.append(
            pyosis.generated.TitleCt(
                canonical=True, type_value=pyosis.generated.OsisTitles.MAIN, content=[title]
            )
        )
    subtitle = _title_text(soup.find("p", class_="subtitle"))
    if subtitle:
        front.append(
            pyosis.generated.TitleCt(
                canonical=True, type_value=pyosis.generated.OsisTitles.SUB, content=[subtitle]
            )
        )
    byline = _title_text(soup.find("div", class_="byline"))
    if byline:
        front.append(
            pyosis.generated.DivCt(
                canonical=False,
                type_value=pyosis.generated.OsisDivs.INTRODUCTION,
                content=[pyosis.generated.PCt(content=[byline])],
            )
        )

    event = body.find("div", class_="event") or soup.find("div", class_="event")
    colophon: list[object] = []
    if isinstance(event, bs4.element.Tag):
        colophon_text = event.get_text(" ", strip=True)
        event.extract()
        colophon.append(
            pyosis.generated.DivCt(
                canonical=False,
                type_value=pyosis.generated.OsisDivs.COLOPHON,
                content=[pyosis.generated.PCt(content=[colophon_text])],
            )
        )

    chapter_id = f"{proclamation.osis_id}.1"
    verses: list[object] = []
    for number, paragraph in enumerate(body.find_all("p", recursive=False), start=1):
        verse_id = f"{chapter_id}.{number}"
        verses.append(
            pyosis.generated.VerseCt(
                s_id=verse_id,
                e_id=verse_id,
                osis_id=[verse_id],
                content=extract_markup(paragraph, footnotes, no_container=True),
            )
        )
    if not verses:
        raise ValueError(f"{proclamation.uri} has no paragraphs")

    chapter = pyosis.generated.ChapterCt(canonical=False, osis_id=[chapter_id], content=verses)
    return pyosis.generated.DivCt(
        canonical=True,
        type_value=pyosis.generated.OsisDivs.BOOK,
        osis_id=[proclamation.osis_id],
        content=[*front, chapter, *colophon],
    )


async def build_proclamations(lang: str, client: httpx.AsyncClient) -> pyosis.serialization.OsisXML:
    """Fetch every available proclamation and assemble the OSIS document.

    Args:
        lang: Language code of the content to fetch.
        client: HTTP client used for the requests.

    Returns:
        The OSIS XML of the official proclamations, one book division each, in chronological order.
    """
    pages = await asyncio.gather(*[
        church_website_models.get_scripture_content_from_uri(lang, p.uri, client)
        for p in PROCLAMATIONS
    ])
    divs = [build_proclamation(p, page) for p, page in zip(PROCLAMATIONS, pages)]

    header = pyosis.generated.HeaderCt(
        revision_desc=[
            pyosis.generated.RevisionDescCt(
                date=pyosis.generated.DateCt(
                    event=pyosis.generated.OsisEvents.EVERSION,
                    content=[datetime.datetime.now().strftime("%Y.%m.%dT%H:%M:%S")],
                    lang=lang,
                ),
                p=[
                    pyosis.generated.PCt(
                        content=[
                            "Scraped from churchofjesuschrist.org, and converted to OSIS by the"
                            " open-canon-site scrapers."
                        ]
                    )
                ],
            )
        ],
        work=[
            pyosis.generated.WorkCt(
                osis_work="Proclamations",
                title=[
                    pyosis.generated.TitleCt(
                        canonical=True,
                        type_value=pyosis.generated.OsisTitles.MAIN,
                        content=[
                            "Official Proclamations of The Church of Jesus Christ of Latter-day Saints"
                        ],
                    )
                ],
                contributor=[
                    pyosis.generated.ContributorCt(
                        role=pyosis.generated.OsisRoles.AUT,
                        value="The First Presidency and the Quorum of the Twelve Apostles",
                    )
                ],
            )
        ],
    )
    return pyosis.serialization.OsisXML(
        osis=pyosis.generated.Osis(
            osis_text=pyosis.generated.OsisTextCt(
                header=header,
                osis_idwork="Proclamations",
                lang=lang,
                osis_ref_work="Official Proclamations of The Church of Jesus Christ of Latter-day Saints",
                div=divs,
            )
        )
    )


async def write_proclamations(
    lang: str, root_dir: str | pathlib.Path, client: httpx.AsyncClient | None = None
) -> list[pathlib.Path]:
    """Build the proclamations OSIS file and write it to ``root_dir/lds_proclamations.xml``.

    Args:
        lang: Language code of the content to fetch.
        root_dir: Directory to write into (created if missing).
        client: HTTP client to use; one is created and closed here when None.

    Returns:
        A one-element list holding the written path.
    """
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(timeout=60.0, pool=None))
    try:
        osis = await build_proclamations(lang, client)
    finally:
        if owns_client:
            await client.aclose()
    path = pathlib.Path(root_dir) / "lds_proclamations.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(osis.to_xml(), "utf-8")
    return [path]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the ``lds-proclamations`` options to its subcommand parser.

    Args:
        parser: Subcommand parser to add ``--lang`` (default ``eng``) to.
    """
    parser.add_argument(
        "--lang",
        default="eng",
        help="language code used on churchofjesuschrist.org (default: %(default)s)",
    )


def run(args: argparse.Namespace) -> list[pathlib.Path]:
    """Run the scraper for the parsed command-line arguments.

    Args:
        args: Parsed arguments; needs ``lang`` and ``output_dir`` attributes.

    Returns:
        The path of the OSIS file written.
    """
    return asyncio.run(write_proclamations(args.lang, args.output_dir))


SPEC = ScraperSpec(
    name="lds-proclamations",
    help="Scrape the 1980, 1995 and 2020 official proclamations from churchofjesuschrist.org",
    source="https://www.churchofjesuschrist.org/study/scriptures/the-family-a-proclamation-to-the-world",
    outputs=("lds_proclamations.xml",),
    run=run,
    add_arguments=add_arguments,
)
"""Registration entry for the ``lds-proclamations`` subcommand."""
