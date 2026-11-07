"""Build the OSIS file format for the Book of Mormon."""

import asyncio
import datetime

import bs4
import bs4.element
import httpx
import pyosis.generated
import pyosis.serialization
from churchstudy_to_osis import church_website_models
from churchstudy_to_osis.build_osis import build_book, clean_up_html, extract_markup


async def _build_bom_front_matter_div(
    lang: str,
    book_uri: str,
    client: httpx.AsyncClient,
    canonical: bool,
    front_matter_type_value: pyosis.generated.OsisDivs = pyosis.generated.OsisDivs.PREFACE,
) -> pyosis.generated.DivCt:
    """Asynchronously builds the OSIS front matter division for the Book of Mormon.

    This function retrieves and processes the front matter content (such as title, subtitle, headers, body, and closing
    signatures) from the church website for the Book of Mormon, cleans and parses the HTML, and constructs the
    corresponding OSIS XML structure.

    Args:
        lang: The language code for the scripture content.
        book_uri: The URI identifying the Book of Mormon resource.
        client: An asynchronous HTTP client used to fetch scripture content.
        canonical: Whether the division should be marked as canonical in the OSIS output.
        front_matter_type_value: The OSIS division type for the front matter (default is INTRODUCTION).

    Returns:
        An OSIS DivCt object representing the structured front matter for the Book of Mormon.

    Raises:
        ValueError: If the body block of the front matter contains no content.
    """
    scripture_content = await church_website_models.get_scripture_content(
        lang, "BookOfMormon", book=None, chapter=None, client=client, book_uri=book_uri
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
        # We have to remove the title tag from the soup so it doesn't get duplicated in the header
        title_tag.extract()
    subtitle_tag = soup.find("p", id="subtitle1")
    if subtitle_tag:
        osis_contents.append(pyosis.generated.TitleCt(content=[subtitle_tag.get_text()]))
        # We have to remove the title tag from the soup so it doesn't get duplicated in the header
        subtitle_tag.extract()
    header_tag = soup.find("header")
    if header_tag:
        header_contents = extract_markup(
            tag=header_tag, footnotes_dict=scripture_content.content.footnotes, no_container=True
        )
        # Only include contents if they are not empty. Strings that are empty or only contain whitespace are not
        # included in the list.
        header_contents = [
            content
            for content in header_contents
            if not isinstance(content, str) or content.strip()
        ]
        if header_contents:
            osis_contents.append(
                pyosis.generated.DivCt(
                    type_value=pyosis.generated.OsisDivs.INTRODUCTION,
                    content=header_contents,
                )
            )

    # The closing tag needs special treatment, so let's extract it from the tree before doing the body
    closing_tag = soup.find("div", class_="closing-block")
    assert not isinstance(closing_tag, bs4.element.NavigableString)
    if closing_tag:
        closing_tag = closing_tag.extract()

    body_block = soup.find("div", class_="body-block")
    assert body_block is not None

    # TODO: parse properly table, td, tr, tbody tags in pronunciation guide
    body_block_contents = extract_markup(
        tag=body_block, footnotes_dict=scripture_content.content.footnotes, no_container=True
    )
    if not body_block_contents:
        raise ValueError("No contents!")
    osis_contents.extend(body_block_contents)

    if closing_tag:
        assert isinstance(closing_tag, bs4.element.Tag)
        closing_signatures_tags = closing_tag.find_all("p", class_="signature")
        if len(closing_signatures_tags):
            osis_contents.append(
                pyosis.generated.SignedCt(
                    content=[
                        pyosis.generated.NameCt(content=[p.get_text()])
                        for p in closing_signatures_tags
                    ]
                )
            )

        closing1_tag = closing_tag.find("p", id="closing1")
        if closing1_tag:
            # TODO: Parse properly the uppercase/small caps around "translated by" and Joseph Smith's name
            # osis_contents.append(pyosis.generated.PCt(content=[closing1_tag.get_text()]))
            osis_contents.extend(extract_markup(closing1_tag, scripture_content.content.footnotes))

    title_page = pyosis.generated.DivCt(
        canonical=canonical,
        type_value=front_matter_type_value,
        content=osis_contents,
    )

    return title_page


async def build_book_of_mormon_front_matter(
    lang: str, client: httpx.AsyncClient
) -> pyosis.generated.DivCt:
    """Asynchronously builds the front matter section for the Book of Mormon in OSIS format.

    This function gathers various front matter components such as title pages, introduction,
    testimonies, explanations, and illustrations, and assembles them into a single OSIS DivCt object.

    Args:
        lang: The language code for the content to be retrieved.
        client: An asynchronous HTTP client used to fetch the front matter content.

    Returns:
        An OSIS DivCt object containing the assembled front matter sections for the Book of Mormon.
    """
    contents = await asyncio.gather(
        # Title Page (Not the one by Mormon)
        _build_bom_front_matter_div(
            lang=lang,
            book_uri="title-page",
            client=client,
            canonical=False,
            front_matter_type_value=pyosis.generated.OsisDivs.COVER_PAGE,
        ),
        # Title Page of the Book of Mormon
        _build_bom_front_matter_div(
            lang=lang,
            book_uri="bofm-title",
            client=client,
            canonical=True,
            front_matter_type_value=pyosis.generated.OsisDivs.TITLE_PAGE,
        ),
        # Introduction
        _build_bom_front_matter_div(
            lang=lang, book_uri="introduction", client=client, canonical=False
        ),
        # Testimony of Three Witnesses
        _build_bom_front_matter_div(lang=lang, book_uri="three", client=client, canonical=False),
        # Testimony of Eight Witnesses
        _build_bom_front_matter_div(lang=lang, book_uri="eight", client=client, canonical=False),
        # Testimony of the Prophet Joseph Smith
        _build_bom_front_matter_div(lang=lang, book_uri="js", client=client, canonical=False),
        # Brief Explanations about the Book of Mormon
        _build_bom_front_matter_div(
            lang=lang, book_uri="explanation", client=client, canonical=False
        ),
        # Illustrations
        _build_bom_front_matter_div(
            lang=lang, book_uri="illustrations", client=client, canonical=False
        ),
    )

    # Assemble them all
    return pyosis.generated.DivCt(
        canonical=False,
        type_value=pyosis.generated.OsisDivs.FRONT,
        content=list(contents),
    )


async def build_book_of_mormon_back_matter(
    lang: str, client: httpx.AsyncClient
) -> pyosis.generated.DivCt:
    """Asynchronously builds the back matter section for the Book of Mormon.

    This function gathers and constructs the back matter content, such as the Pronunciation Guide,
    by calling helper functions to generate the appropriate OSIS divs. The resulting content is
    returned as a DivCt object representing the back matter section.

    Args:
        lang: The language code for the content to be generated.
        client: An asynchronous HTTP client used to fetch required data.

    Returns:
        A DivCt object containing the assembled back matter content for the Book of Mormon.
    """
    contents = await asyncio.gather(
        # Pronunciation Guide
        _build_bom_front_matter_div(
            lang=lang,
            book_uri="pronunciation",
            client=client,
            canonical=False,
            front_matter_type_value=pyosis.generated.OsisDivs.APPENDIX,
        ),
        # TODO: Reference Guide to the Book of Mormon
    )
    return pyosis.generated.DivCt(
        canonical=False,
        type_value=pyosis.generated.OsisDivs.BACK,
        content=list(contents),
    )


async def build_book_of_mormon_header(
    lang: str, client: httpx.AsyncClient
) -> pyosis.generated.HeaderCt:
    """Asynchronously builds the OSIS header for the Book of Mormon.

    This function fetches the title page content for the Book of Mormon from the church website,
    extracts publisher and copyright information, and constructs a header object in OSIS format.
    It includes revision descriptions for the current version, the edition date, and the original
    1830 English edition. The header also contains work metadata such as titles, contributors,
    and publisher information.

    Args:
        lang: The language code to fetch the scripture content in.
        client: An asynchronous HTTP client used to make requests.

    Returns:
        An OSIS HeaderCt object populated with metadata for the Book of Mormon.
    """
    scripture_content = await church_website_models.get_scripture_content(
        lang, "BookOfMormon", book=None, chapter=None, client=client, book_uri="title-page"
    )
    soup = clean_up_html(bs4.BeautifulSoup(scripture_content.content.body, "html.parser"))

    publish_info_tag = soup.find("div", class_="publish-info")
    publisher_info = publish_info_tag.get_text().strip() if publish_info_tag else ""

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
        pyosis.generated.RevisionDescCt(
            date=pyosis.generated.DateCt(
                event=pyosis.generated.OsisEvents.EDITION,
                content=[date_str_to_osis_format],
                lang=lang,
            ),
            p=[pyosis.generated.PCt(content=[copyright_info])],
        ),
        pyosis.generated.RevisionDescCt(
            date=pyosis.generated.DateCt(
                event=pyosis.generated.OsisEvents.EDITION, lang="en", content=["1830.03.26"]
            ),
            p=[
                pyosis.generated.PCt(
                    content=["First English edition published in Palmyra, New York, USA, in 1830"]
                )
            ],
        ),
    ]

    return pyosis.generated.HeaderCt(
        revision_desc=revision_desc,
        work=[
            pyosis.generated.WorkCt(
                osis_work="BOM",
                title=[
                    pyosis.generated.TitleCt(
                        canonical=True,
                        type_value=pyosis.generated.OsisTitles.MAIN,
                        content=["The Book of Mormon"],
                    ),
                    pyosis.generated.TitleCt(
                        canonical=True,
                        type_value=pyosis.generated.OsisTitles.SUB,
                        content=["Another Testament of Jesus Christ"],
                    ),
                ],
                contributor=[
                    pyosis.generated.ContributorCt(
                        role=pyosis.generated.OsisRoles.TRL, value="Joseph Smith, Jr."
                    ),
                    pyosis.generated.ContributorCt(
                        role=pyosis.generated.OsisRoles.COM, value="Mormon"
                    ),
                    pyosis.generated.ContributorCt(
                        role=pyosis.generated.OsisRoles.COM, value="Moroni"
                    ),
                ],
                publisher=[
                    pyosis.generated.PublisherCt(
                        value=publisher_info,
                    )
                ],
            )
        ],
    )


async def build_book_of_mormon(
    lang: str, client: httpx.AsyncClient
) -> pyosis.serialization.OsisXML:
    """Asynchronously builds the OSIS XML representation of the Book of Mormon.

    This function gathers the front matter, each book's content, and back matter for the Book of Mormon
    in the specified language, using the provided asynchronous HTTP client. It then constructs and returns
    a `pyosis.serialization.OsisXML` object containing the complete OSIS XML structure.

    Args:
        lang: The language code for the content to be fetched and built.
        client: An asynchronous HTTP client used to fetch data.

    Returns:
        The OSIS XML representation of the Book of Mormon.
    """
    book_names = church_website_models.BookOfMormonBooksUri.keys()
    front_matter = await build_book_of_mormon_front_matter(lang, client)
    osis_books = await asyncio.gather(
        *[build_book(lang, "BookOfMormon", book_name, client) for book_name in book_names]
    )
    back_matter = await build_book_of_mormon_back_matter(lang, client)

    header = await build_book_of_mormon_header(lang, client)

    return pyosis.serialization.OsisXML(
        osis=pyosis.generated.Osis(
            osis_text=pyosis.generated.OsisTextCt(
                header=header,
                osis_idwork="bom",
                lang=lang,
                osis_ref_work="The Book of Mormon",
                div=[
                    front_matter,
                    *osis_books,
                    back_matter,
                ],
            )
        )
    )
