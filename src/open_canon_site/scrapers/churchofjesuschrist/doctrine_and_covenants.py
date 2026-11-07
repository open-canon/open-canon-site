"""Build the OSIS file format for the Doctrine and Covenants."""

import asyncio
import datetime

import bs4
import bs4.element
import httpx
import pyosis.generated
import pyosis.serialization

from churchstudy_to_osis import church_website_models
from churchstudy_to_osis.build_osis import build_chapter, clean_up_html, extract_markup

DC_SECTION_COUNT = 138
OD_COUNT = 2


async def _build_dc_front_matter_div(
    lang: str,
    book_uri: str,
    client: httpx.AsyncClient,
    canonical: bool,
    front_matter_type_value: pyosis.generated.OsisDivs = pyosis.generated.OsisDivs.PREFACE,
) -> pyosis.generated.DivCt:
    """Asynchronously builds an OSIS front matter division for the Doctrine and Covenants.

    Retrieves and processes a named front matter page from the church website for the Doctrine and
    Covenants, and constructs the appropriate OSIS division.

    Args:
        lang: The language code for the scripture content.
        book_uri: The URI path segment identifying the front matter page (e.g. "introduction").
        client: An asynchronous HTTP client used to fetch scripture content.
        canonical: Whether the division should be marked as canonical in the OSIS output.
        front_matter_type_value: The OSIS division type for the content (default is PREFACE).

    Returns:
        An OSIS DivCt object representing the structured front matter division.

    Raises:
        ValueError: If the body block of the page contains no content.
    """
    scripture_content = await church_website_models.get_scripture_content(
        lang, "DoctrineAndCovenants", book=None, chapter=None, client=client, book_uri=book_uri
    )
    soup = clean_up_html(bs4.BeautifulSoup(scripture_content.content.body, "html.parser"))

    osis_contents: list[object] = []

    title_tag = soup.find("p", id="title1") or soup.find("h1", id="title1")
    if title_tag:
        osis_contents.append(
            pyosis.generated.HeadCt(
                content=extract_markup(title_tag, scripture_content.content.footnotes, no_container=True)
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

    closing_tag = soup.find("div", class_="closing-block")
    assert not isinstance(closing_tag, bs4.element.NavigableString)
    if closing_tag:
        closing_tag = closing_tag.extract()

    body_block = soup.find("div", class_="body-block")
    assert body_block is not None

    body_block_contents = extract_markup(
        tag=body_block, footnotes_dict=scripture_content.content.footnotes, no_container=True
    )
    if not body_block_contents:
        raise ValueError("No contents!")
    osis_contents.extend(body_block_contents)

    if closing_tag:
        assert isinstance(closing_tag, bs4.element.Tag)
        closing_signatures_tags = closing_tag.find_all("p", class_="signature")
        if closing_signatures_tags:
            osis_contents.append(
                pyosis.generated.SignedCt(
                    content=[pyosis.generated.NameCt(content=[p.get_text()]) for p in closing_signatures_tags]
                )
            )

        closing1_tag = closing_tag.find("p", id="closing1")
        if closing1_tag:
            osis_contents.extend(extract_markup(closing1_tag, scripture_content.content.footnotes))

    return pyosis.generated.DivCt(
        canonical=canonical,
        type_value=front_matter_type_value,
        content=osis_contents,
    )


async def build_doctrine_and_covenants_front_matter(lang: str, client: httpx.AsyncClient) -> pyosis.generated.DivCt:
    """Asynchronously builds the front matter section for the Doctrine and Covenants in OSIS format.

    Gathers the introductory front matter content and assembles it into a single OSIS DivCt front
    matter object.

    Args:
        lang: The language code for the content to be retrieved.
        client: An asynchronous HTTP client used to fetch the front matter content.

    Returns:
        An OSIS DivCt object containing the assembled front matter for the Doctrine and Covenants.
    """
    contents = await asyncio.gather(
        _build_dc_front_matter_div(
            lang=lang,
            book_uri="introduction",
            client=client,
            canonical=False,
            front_matter_type_value=pyosis.generated.OsisDivs.PREFACE,
        ),
        _build_dc_front_matter_div(
            lang=lang,
            book_uri="chron-order",
            client=client,
            canonical=False,
            front_matter_type_value=pyosis.generated.OsisDivs.APPENDIX,
        ),
    )
    return pyosis.generated.DivCt(
        canonical=False,
        type_value=pyosis.generated.OsisDivs.FRONT,
        content=list(contents),
    )


async def _build_official_declaration(lang: str, od_number: int, client: httpx.AsyncClient) -> pyosis.generated.DivCt:
    """Asynchronously builds an OSIS division for a single Official Declaration.

    Fetches the content of the specified Official Declaration from the church website, builds the
    OSIS chapter structure, and wraps it in a book-level division.

    Args:
        lang: The language code for the scripture content.
        od_number: The number of the Official Declaration (1 or 2).
        client: An asynchronous HTTP client used to fetch scripture content.

    Returns:
        An OSIS DivCt object representing the Official Declaration as a book division.
    """
    scripture_content = await church_website_models.get_scripture_content(
        lang, "DoctrineAndCovenants", book=None, chapter=od_number, client=client, book_uri="od"
    )
    osis_chapter, front_matter = build_chapter(scripture_content, book_osis_id="OD", chapter_number=od_number)
    chapter_content: list[object] = list(front_matter) if front_matter else []
    chapter_content.append(osis_chapter)
    return pyosis.generated.DivCt(
        canonical=True,
        type_value=pyosis.generated.OsisDivs.BOOK,
        osis_id=[f"OD.{od_number}"],
        content=chapter_content,
    )


async def build_doctrine_and_covenants_sections(lang: str, client: httpx.AsyncClient) -> pyosis.generated.DivCt:
    """Asynchronously builds the main body of the Doctrine and Covenants (sections 1-138).

    Fetches all sections concurrently, builds OSIS chapter elements for each, and assembles them
    into a single book-level division.

    Args:
        lang: The language code for the scripture content.
        client: An asynchronous HTTP client used to fetch scripture content.

    Returns:
        An OSIS DivCt object representing the complete Doctrine and Covenants text.
    """
    section_nums = list(range(1, DC_SECTION_COUNT + 1))
    section_contents = await asyncio.gather(*[
        church_website_models.get_scripture_content(
            lang, "DoctrineAndCovenants", "Doctrine and Covenants", section_num, client
        )
        for section_num in section_nums
    ])

    osis_chapters: list[object] = []
    for section_num, section_content in zip(section_nums, section_contents):
        osis_chapter, front_matter = build_chapter(section_content, book_osis_id="DC", chapter_number=section_num)
        if front_matter:
            osis_chapters.extend(front_matter)
        osis_chapters.append(osis_chapter)

    return pyosis.generated.DivCt(
        canonical=True,
        type_value=pyosis.generated.OsisDivs.BOOK,
        osis_id=["DC"],
        content=osis_chapters,
    )


async def build_doctrine_and_covenants_header(lang: str, client: httpx.AsyncClient) -> pyosis.generated.HeaderCt:
    """Asynchronously builds the OSIS header for the Doctrine and Covenants.

    Fetches the introduction page to extract edition and copyright metadata, then constructs a
    header object in OSIS format containing revision descriptions and work metadata.

    Args:
        lang: The language code to fetch the scripture content in.
        client: An asynchronous HTTP client used to make requests.

    Returns:
        An OSIS HeaderCt object populated with metadata for the Doctrine and Covenants.
    """
    scripture_content = await church_website_models.get_scripture_content(
        lang, "DoctrineAndCovenants", book=None, chapter=None, client=client, book_uri="introduction"
    )
    soup = clean_up_html(bs4.BeautifulSoup(scripture_content.content.body, "html.parser"))

    copyright_tag = soup.find("div", class_="copyright-info")
    copyright_info = copyright_tag.get_text().strip() if copyright_tag else ""
    if "Source:" in copyright_info:
        date_str = copyright_info.split("Source:")[-1].strip()
        date_str_to_osis_format = date_str.replace("/", ".")
    else:
        date_str_to_osis_format = ""

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
                        " churchstudy-to-osis Python package."
                    ]
                )
            ],
        ),
    ]
    if date_str_to_osis_format:
        revision_desc.append(
            pyosis.generated.RevisionDescCt(
                date=pyosis.generated.DateCt(
                    event=pyosis.generated.OsisEvents.EDITION, content=[date_str_to_osis_format], lang=lang
                ),
                p=[pyosis.generated.PCt(content=[copyright_info])],
            )
        )

    return pyosis.generated.HeaderCt(
        revision_desc=revision_desc,
        work=[
            pyosis.generated.WorkCt(
                osis_work="DC",
                title=[
                    pyosis.generated.TitleCt(
                        canonical=True,
                        type_value=pyosis.generated.OsisTitles.MAIN,
                        content=["The Doctrine and Covenants"],
                    ),
                ],
                contributor=[
                    pyosis.generated.ContributorCt(role=pyosis.generated.OsisRoles.COM, value="Joseph Smith, Jr."),
                ],
            )
        ],
    )


async def build_doctrine_and_covenants(lang: str, client: httpx.AsyncClient) -> pyosis.serialization.OsisXML:
    """Asynchronously builds the OSIS XML representation of the Doctrine and Covenants.

    Gathers the front matter, all 138 sections, both Official Declarations, and the header
    concurrently, then assembles and returns the complete OSIS XML structure.

    Args:
        lang: The language code for the content to be fetched and built.
        client: An asynchronous HTTP client used to fetch data.

    Returns:
        The OSIS XML representation of the Doctrine and Covenants.
    """
    front_matter, sections, header = await asyncio.gather(
        build_doctrine_and_covenants_front_matter(lang, client),
        build_doctrine_and_covenants_sections(lang, client),
        build_doctrine_and_covenants_header(lang, client),
    )
    od_divs = await asyncio.gather(*[
        _build_official_declaration(lang, od_num, client) for od_num in range(1, OD_COUNT + 1)
    ])

    return pyosis.serialization.OsisXML(
        osis=pyosis.generated.Osis(
            osis_text=pyosis.generated.OsisTextCt(
                header=header,
                osis_idwork="dc",
                lang=lang,
                osis_ref_work="The Doctrine and Covenants",
                div=[
                    front_matter,
                    sections,
                    *od_divs,
                ],
            )
        )
    )
