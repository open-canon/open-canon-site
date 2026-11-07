"""Pydantic models representing JSON responses from the Scripture Content API of the Church of Jesus Christ of
Latter-day Saints website.
"""

import re
from typing import Any, TypeVar

import bs4
import httpx
import pydantic

# ruff: noqa: N815


class RedirectionError(ValueError):
    """Redirected while attempting to access Scripture Content."""


class Audio(pydantic.BaseModel):
    """Audio for a scripture chapter or verse."""

    mediaUrl: str
    variant: str


class Meta(pydantic.BaseModel):
    """Metadata about a scripture chapter or verse."""

    archived: bool
    title: str
    canonicalUrl: str
    contentType: str  # "text/html"
    audio: list[Audio] | None = None
    pageAttributes: Any
    # "pageAttributes": {
    #     "data-asset-id": "34085354c9883ef35ff0623e36634ee00725eca2",  # pragma: allowlist secret
    #     "data-aid": "128345022",
    #     "data-aid-version": "6",
    #     "data-content-type": "chapter",
    #     "data-uri": "/scriptures/bofm/1-ne/6",
    #     "lang": "eng",
    #     "data-orig-id": "34085354c9883ef35ff0623e36634ee00725eca2",  # pragma: allowlist secret
    #     "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance"
    # },
    scopedClassName: str  # "classic-scripture"


class ReferenceUri(pydantic.BaseModel):
    """Represents a reference URI with its type, hyperlink, and display text."""

    type: str
    href: str
    text: str


class Footnote(pydantic.BaseModel):
    """Represents a footnote with associated metadata and references."""

    id: str
    marker: str = ""
    pid: str = ""
    context: str = ""
    text: str
    referenceUris: list[ReferenceUri] = pydantic.Field(default_factory=list)

    def uris(self) -> list[str]:
        """Returns a list of href strings from the referenceUris attribute.

        Returns:
            A list of href strings extracted from each uri in referenceUris.
        """
        return [uri.href for uri in self.referenceUris]


class Content(pydantic.BaseModel):
    """Represents the content structure for a church website."""

    head: Any
    body: str
    footnotes: dict[str, Footnote]


class ScriptureStudyContent(pydantic.BaseModel):
    """Content for a scripture chapter or verse."""

    meta: Meta
    content: Content
    pids: Any
    tableOfContentsUri: str
    uri: str
    verified: bool


class ContentApiContent(pydantic.BaseModel):
    """Represents content retrieved from the Content API."""

    id: str
    markup: str
    displayId: str = ""


class ContentApiResponse(pydantic.BaseModel):
    """Represents the response from the content API."""

    content: list[ContentApiContent]
    headline: str
    publication: str
    referenceURIDisplayText: str | Any
    referenceURI: str | Any
    type: str
    uri: str
    image: Any
    idNotationUri: str | Any = ""


BookOfMormonBooksUri = {
    "1 Nephi": "1-ne",
    "2 Nephi": "2-ne",
    "Jacob": "jacob",
    "Enos": "enos",
    "Jarom": "jarom",
    "Omni": "omni",
    "Words of Mormon": "w-of-m",
    "Mosiah": "mosiah",
    "Alma": "alma",
    "Helaman": "hel",
    "3 Nephi": "3-ne",
    "4 Nephi": "4-ne",
    "Mormon": "morm",
    "Ether": "ether",
    "Moroni": "moro",
}

OldTestamentBooksUri = {
    "Genesis": "gen",
    "Exodus": "ex",
    "Leviticus": "lev",
    "Numbers": "num",
    "Deuteronomy": "deut",
    "Joshua": "josh",
    "Judges": "judg",
    "Ruth": "ruth",
    "1 Samuel": "1-sam",
    "2 Samuel": "2-sam",
    "1 Kings": "1-kgs",
    "2 Kings": "2-kgs",
    "1 Chronicles": "1-chr",
    "2 Chronicles": "2-chr",
    "Ezra": "ezra",
    "Nehemiah": "neh",
    "Esther": "esth",
    "Job": "job",
    "Psalms": "ps",
    "Proverbs": "prov",
    "Ecclesiastes": "eccl",
    "Song of Solomon": "song",
    "Isaiah": "isa",
    "Jeremiah": "jer",
    "Lamentations": "lam",
    "Ezekiel": "ezek",
    "Daniel": "dan",
    "Hosea": "hosea",
    "Joel": "joel",
    "Amos": "amos",
    "Obadiah": "obad",
    "Jonah": "jonah",
    "Micah": "micah",
    "Nahum": "nahum",
    "Habakkuk": "hab",
    "Zephaniah": "zeph",
    "Haggai": "hag",
    "Zechariah": "zech",
    "Malachi": "mal",
}

NewTestamentBooksUri = {
    "Matthew": "matt",
    "Mark": "mark",
    "Luke": "luke",
    "John": "john",
    "Acts": "acts",
    "Romans": "rom",
    "1 Corinthians": "1-cor",
    "2 Corinthians": "2-cor",
    "Galatians": "gal",
    "Ephesians": "eph",
    "Philippians": "philip",
    "Colossians": "col",
    "1 Thessalonians": "1-thes",
    "2 Thessalonians": "2-thes",
    "1 Timothy": "1-tim",
    "2 Timothy": "2-tim",
    "Titus": "titus",
    "Philemon": "philem",
    "Hebrews": "heb",
    "James": "james",
    "1 Peter": "1-pet",
    "2 Peter": "2-pet",
    "1 John": "1-jn",
    "2 John": "2-jn",
    "3 John": "3-jn",
    "Jude": "jude",
    "Revelation": "rev",
}

DoctrineAndCovenantsBooksUri = {
    "Doctrine and Covenants": "dc",
}

PearlOfGreatPriceBooksUri = {
    "Moses": "moses",
    "Abraham": "abr",
    "Joseph Smith--Matthew": "js-m",
    "Joseph Smith--History": "js-h",
    "Articles of Faith": "a-of-f",
}

parent_book_uri_mapper: dict[str, tuple[str, dict[str, str]]] = {
    "BookOfMormon": ("bofm", BookOfMormonBooksUri),
    "OldTestament": ("ot", OldTestamentBooksUri),
    "NewTestament": ("nt", NewTestamentBooksUri),
    "DoctrineAndCovenants": ("dc-testament", DoctrineAndCovenantsBooksUri),
    "PearlOfGreatPrice": ("pgp", PearlOfGreatPriceBooksUri),
}


BASE_STUDY_CONTENT_URL = (
    "https://www.churchofjesuschrist.org/study/api/v3/language-pages/type/content"
)
BASE_CONTENT_URL = "https://www.churchofjesuschrist.org/content/api/v3"
STUDY_CONTENT_URL_FORMAT = f"{BASE_STUDY_CONTENT_URL}?lang={{lang}}&uri={{uri}}"
BASE_CONTENT_URL_FORMAT = "/{lang}/scriptures/{parent_book_uri}/{book_uri}/{chapter}.{verse}"

NOTE_ID_REGEX = re.compile(r"note(\d+)(\w+)")

T = TypeVar("T")


def prepare_uri(
    parent_book: str, book: str | None, chapter: int | None, book_uri: str | None = None
) -> str:
    """Prepare the uri for a chapter or verse.

    Args:
        parent_book: The parent book of the chapter or verse.
        book: The book of the chapter or verse.
        chapter: The chapter of the chapter or verse.
        book_uri: Specific book uri to use (book is ignored if this is provided)

    Returns:
        The uri of the chapter or verse.
    """
    if parent_book not in parent_book_uri_mapper:
        raise ValueError(f"Invalid parent book: {parent_book}")
    parent_book_uri, book_uri_mapper = parent_book_uri_mapper[parent_book]
    if book_uri is None:
        if book is None:
            raise ValueError("book cannot be None unless book_uri is manually specified")
        if book not in book_uri_mapper:
            raise ValueError(f"Invalid book: {book}")
        book_uri = book_uri_mapper[book]

    if chapter is not None:
        return f"/scriptures/{parent_book_uri}/{book_uri}/{chapter}"
    return f"/scriptures/{parent_book_uri}/{book_uri}"


async def get_scripture_content(
    lang: str,
    parent_book: str,
    book: str | None,
    chapter: int | None,
    client: httpx.AsyncClient,
    book_uri: str | None = None,
) -> ScriptureStudyContent:
    """Get the content of a scripture chapter or verse.

    Args:
        lang: The language of the content.
        parent_book: The parent book of the chapter or verse.
        book: The book of the chapter or verse.
        chapter: The chapter of the chapter or verse.
        client: Client to handle web traffic.
        book_uri: Specific book uri to use (book is ignored if this is provided)

    Returns:
        The content of the chapter or verse.
    """
    uri = prepare_uri(parent_book=parent_book, book=book, chapter=chapter, book_uri=book_uri)
    return await get_scripture_content_from_uri(lang, uri, client)


async def get_chapters_list(
    lang: str, parent_book: str, book: str, client: httpx.AsyncClient
) -> list[int]:
    """Fetches a list of chapter numbers for a given book from the church website.

    This asynchronous function retrieves the table of contents for a specified book and language,
    parses the HTML to extract chapter titles, and returns a list of chapter numbers. If the book
    contains only a single chapter and the website redirects to the main table of contents, the
    function returns a list containing only 1.

    Args:
        lang: The language code for the scripture content (e.g., 'eng').
        parent_book: The identifier for the parent book (e.g., 'ot' or 'nt').
        book: The identifier for the specific book (e.g., 'genesis').
        client: An instance of httpx.AsyncClient used to make HTTP requests.

    Returns:
        A list of integers representing the chapter numbers in the specified book.

    Raises:
        ValueError: If a chapter title does not match the expected format.
    """
    try:
        content = await get_scripture_content(lang, parent_book, book, None, client)
    except RedirectionError:
        # The church doesn't include a ToC for single chapter books and redirects to the main book ToC...
        return [1]

    body = content.content.body
    soup = bs4.BeautifulSoup(body, "html.parser")
    chapter_titles = soup.find_all("p", class_="title")
    # Chapter titles are of the form "Chapter {num}" where num is an integer
    # formatted as a string. We want to populate chapters with just the int.
    # Raise an error if the chapter title isn't formatted that way
    chapters: list[int] = []
    for chapter_title in chapter_titles:
        # Skip entries whose link doesn't point to a plain numeric chapter
        # (e.g. Abraham facsimiles link to /fac-1, /fac-2, /fac-3)
        parent = chapter_title.parent
        if isinstance(parent, bs4.element.Tag) and parent.name == "a":
            href = str(parent.attrs.get("href", ""))
            final_segment = href.split("?")[0].rstrip("/").split("/")[-1]
            if not final_segment.isdigit():
                continue

        match = re.search(r"(\d+)$", chapter_title.text.strip())
        if not match:
            raise ValueError(f"Invalid chapter title format: {chapter_title.text}")
        chapters.append(int(match.group(1)))
    return chapters


async def get_scripture_content_from_uri(
    lang: str, uri: str, client: httpx.AsyncClient
) -> ScriptureStudyContent:
    """Fetches scripture study content from a given URI asynchronously.

    This function constructs a URL using the provided language and URI, sends an asynchronous GET request
    using the provided HTTP client, and parses the response into a ScriptureStudyContent object. It also
    verifies that the canonical URL in the response matches the requested URI, raising a RedirectionError
    if a redirection is detected.

    Args:
        lang: The language code to use in the request.
        uri: The URI identifying the scripture content to fetch.
        client: An asynchronous HTTP client used to perform the request.

    Returns:
        A ScriptureStudyContent object parsed from the response.

    Raises:
        RedirectionError: If the response indicates a redirection to a different canonical URL.
    """
    url = STUDY_CONTENT_URL_FORMAT.format(lang=lang, uri=uri)
    response = await client.get(url)
    parsed = ScriptureStudyContent(**response.json())

    if parsed.meta.canonicalUrl not in (uri, uri + f"?lang={lang}"):
        raise RedirectionError(f"Request for {url} was redirect to {parsed.meta.canonicalUrl}")

    return parsed
