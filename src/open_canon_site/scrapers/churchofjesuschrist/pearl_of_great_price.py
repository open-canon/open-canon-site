"""Build the OSIS file format for the Pearl of Great Price."""

import asyncio
import datetime

import bs4
import httpx
import pyosis.generated
import pyosis.serialization
import tqdm.auto

from open_canon_site.scrapers.churchofjesuschrist import models as church_website_models
from open_canon_site.scrapers.churchofjesuschrist.build_osis import (
    build_book,
    clean_up_html,
    extract_markup,
)


async def _build_pgp_front_matter_div(
    lang: str,
    book_uri: str,
    client: httpx.AsyncClient,
    canonical: bool,
    front_matter_type_value: pyosis.generated.OsisDivs = pyosis.generated.OsisDivs.PREFACE,
) -> pyosis.generated.DivCt:
    """Build an OSIS front matter division for the Pearl of Great Price.

    Args:
        lang: The language code for the scripture content.
        book_uri: The URI path segment identifying the front matter page (e.g. "title-page").
        client: An asynchronous HTTP client used to fetch scripture content.
        canonical: Whether the division should be marked as canonical in the OSIS output.
        front_matter_type_value: The OSIS division type for the content.

    The page body is expected to contain an optional ``p#title1``/``h1#title1`` (-> head), optional ``p#subtitle1``
    (-> title), an optional ``header`` (-> introduction div) and a required ``div.body-block`` (converted as
    markup).

    Returns:
        An OSIS DivCt object representing the structured front matter division.
    """
    scripture_content = await church_website_models.get_scripture_content(
        lang, "PearlOfGreatPrice", book=None, chapter=None, client=client, book_uri=book_uri
    )
    soup = clean_up_html(bs4.BeautifulSoup(scripture_content.content.body, "html.parser"))

    osis_contents: list[object] = []

    title_tag = soup.find("p", id="title1") or soup.find("h1", id="title1")
    if title_tag:
        osis_contents.append(
            pyosis.generated.HeadCt(
                content=extract_markup(
                    title_tag, scripture_content.content.footnotes, no_container=True
                )
            )
        )
        title_tag.extract()

    subtitle_tag = soup.find("p", id="subtitle1")
    if subtitle_tag:
        osis_contents.append(pyosis.generated.TitleCt(content=[subtitle_tag.get_text()]))
        subtitle_tag.extract()

    header_tag = soup.find("header")
    if header_tag:
        header_contents = extract_markup(
            tag=header_tag, footnotes_dict=scripture_content.content.footnotes, no_container=True
        )
        header_contents = [c for c in header_contents if not isinstance(c, str) or c.strip()]
        if header_contents:
            osis_contents.append(
                pyosis.generated.DivCt(
                    type_value=pyosis.generated.OsisDivs.INTRODUCTION,
                    content=header_contents,
                )
            )

    body_block = soup.find("div", class_="body-block")
    assert body_block is not None

    body_block_contents = extract_markup(
        tag=body_block, footnotes_dict=scripture_content.content.footnotes, no_container=True
    )
    osis_contents.extend(body_block_contents)

    return pyosis.generated.DivCt(
        canonical=canonical,
        type_value=front_matter_type_value,
        content=osis_contents,
    )


async def build_pearl_of_great_price_front_matter(
    lang: str, client: httpx.AsyncClient
) -> pyosis.generated.DivCt:
    """Build the front matter section for the Pearl of Great Price in OSIS format.

    Args:
        lang: The language code for the content to be retrieved.
        client: An asynchronous HTTP client used to fetch the front matter content.

    Returns:
        An OSIS DivCt object containing the assembled front matter for the Pearl of Great Price.
    """
    title_page = await _build_pgp_front_matter_div(
        lang=lang,
        book_uri="title-page",
        client=client,
        canonical=False,
        front_matter_type_value=pyosis.generated.OsisDivs.TITLE_PAGE,
    )
    return pyosis.generated.DivCt(
        canonical=False,
        type_value=pyosis.generated.OsisDivs.FRONT,
        content=[title_page],
    )


def build_pearl_of_great_price_header(
    lang: str, client: httpx.AsyncClient
) -> pyosis.generated.HeaderCt:
    """Build the OSIS header for the Pearl of Great Price.

    Constructs a header object in OSIS format containing revision descriptions and work metadata
    for the Pearl of Great Price.

    Args:
        lang: The language code.
        client: An asynchronous HTTP client (unused but kept for interface consistency).

    Returns:
        An OSIS HeaderCt object populated with metadata for the Pearl of Great Price.
    """
    revision_desc = [
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
        ),
    ]

    return pyosis.generated.HeaderCt(
        revision_desc=revision_desc,
        work=[
            pyosis.generated.WorkCt(
                osis_work="PGP",
                title=[
                    pyosis.generated.TitleCt(
                        canonical=True,
                        type_value=pyosis.generated.OsisTitles.MAIN,
                        content=["The Pearl of Great Price"],
                    ),
                ],
            )
        ],
    )


async def _build_abraham_facsimile_div(
    lang: str,
    fac_num: int,
    client: httpx.AsyncClient,
) -> pyosis.generated.DivCt:
    """Build a canonical OSIS appendix division for one Abraham facsimile.

    Args:
        lang: The language code for the scripture content.
        fac_num: The facsimile number (1, 2, or 3).
        client: An asynchronous HTTP client used to fetch scripture content.

    The facsimile page lives at ``/scriptures/pgp/abr/fac-<n>``; it has an optional ``h1#title1``/``p#title1``
    (-> head), optional ``p#subtitle1`` (-> title) and a required ``div.body-block``.

    Returns:
        A canonical OSIS DivCt appendix with id ``Abraham.Fac-<n>`` representing the facsimile.
    """
    scripture_content = await church_website_models.get_scripture_content(
        lang,
        "PearlOfGreatPrice",
        book=None,
        chapter=None,
        client=client,
        book_uri=f"abr/fac-{fac_num}",
    )
    soup = clean_up_html(bs4.BeautifulSoup(scripture_content.content.body, "html.parser"))

    osis_contents: list[object] = []

    title_tag = soup.find("h1", id="title1") or soup.find("p", id="title1")
    if title_tag:
        osis_contents.append(
            pyosis.generated.HeadCt(
                content=extract_markup(
                    title_tag, scripture_content.content.footnotes, no_container=True
                )
            )
        )
        title_tag.extract()

    subtitle_tag = soup.find("p", id="subtitle1")
    if subtitle_tag:
        osis_contents.append(pyosis.generated.TitleCt(content=[subtitle_tag.get_text()]))
        subtitle_tag.extract()

    body_block = soup.find("div", class_="body-block")
    assert body_block is not None

    body_block_contents = extract_markup(
        tag=body_block, footnotes_dict=scripture_content.content.footnotes, no_container=True
    )
    osis_contents.extend(body_block_contents)

    return pyosis.generated.DivCt(
        canonical=True,
        type_value=pyosis.generated.OsisDivs.APPENDIX,
        osis_id=[f"Abraham.Fac-{fac_num}"],
        content=osis_contents,
    )


async def _build_abraham_with_facsimiles(
    lang: str, client: httpx.AsyncClient
) -> pyosis.generated.DivCt:
    """Build the Book of Abraham including its three facsimiles as canonical appendices.

    Args:
        lang: The language code for the scripture content.
        client: An asynchronous HTTP client used to fetch scripture content.

    The book content is built by `build_osis.build_book` and the three facsimile divisions are appended after the
    chapters.

    Returns:
        An OSIS DivCt book division for Abraham with facsimile appendices appended.
    """
    abraham_book, *facsimiles = await asyncio.gather(
        build_book(lang, "PearlOfGreatPrice", "Abraham", client),
        *[_build_abraham_facsimile_div(lang, n, client) for n in (1, 2, 3)],
    )
    assert isinstance(abraham_book, pyosis.generated.DivCt)
    abraham_book.content.extend(facsimiles)
    return abraham_book


async def build_pearl_of_great_price(
    lang: str, client: httpx.AsyncClient
) -> pyosis.serialization.OsisXML:
    """Asynchronously builds the OSIS XML representation of the Pearl of Great Price.

    Fetches all books of the Pearl of Great Price concurrently and assembles them into a complete
    OSIS XML structure.

    Args:
        lang: The language code for the content to be fetched and built.
        client: An asynchronous HTTP client used to fetch data.

    Returns:
        The OSIS XML representation of the Pearl of Great Price.
    """
    book_names = list(church_website_models.PearlOfGreatPriceBooksUri.keys())

    header = build_pearl_of_great_price_header(lang, client)
    front_matter = await build_pearl_of_great_price_front_matter(lang, client)
    osis_books = [
        await (
            _build_abraham_with_facsimiles(lang, client)
            if book_name == "Abraham"
            else build_book(lang, "PearlOfGreatPrice", book_name, client)
        )
        for book_name in tqdm.auto.tqdm(book_names, desc="Pearl of Great Price")
    ]

    return pyosis.serialization.OsisXML(
        osis=pyosis.generated.Osis(
            osis_text=pyosis.generated.OsisTextCt(
                header=header,
                osis_idwork="pgp",
                lang=lang,
                osis_ref_work="The Pearl of Great Price",
                div=[front_matter, *osis_books],
            )
        )
    )
