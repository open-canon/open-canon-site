"""Pydantic models and URL helpers for the Scripture Content API of the churchofjesuschrist.org website.

The Study API (``/study/api/v3/language-pages/type/content?lang=eng&uri=/scriptures/...``) answers with JSON
describing one page: ``meta`` (title, canonical URL), ``content`` (HTML ``body`` and a ``footnotes`` dictionary) and
a few bookkeeping fields. This module models those responses, maps book names to URI segments and fetches pages.
"""

from __future__ import annotations

import re
from typing import Any, Optional, TypeVar, Union

import bs4
import httpx
import pydantic

# ruff: noqa: N815
# NOTE: pydantic evaluates annotations at runtime, so Optional/Union (not `X | Y`) are required on Python 3.9.


class RedirectionError(ValueError):
    """Redirected while attempting to access Scripture Content.

    Raised by `get_scripture_content_from_uri` when the API answers with a page whose
    ``meta.canonicalUrl`` differs from the requested URI. The Church site does this, for
    example, when a single-chapter book's table of contents is requested: it returns the
    parent book's table of contents instead.
    """


class Audio(pydantic.BaseModel):
    """Audio recording of a scripture chapter or verse, as listed in ``meta.audio``."""

    mediaUrl: str
    """Absolute URL of the audio file."""
    variant: str
    """Voice variant of the recording (for example ``"male"`` or ``"female"``)."""


class Meta(pydantic.BaseModel):
    """Metadata about a scripture chapter or verse (the ``meta`` object of the study API response)."""

    archived: bool
    """Whether the page is an archived (superseded) revision."""
    title: str
    """Human readable page title, e.g. ``"1 Nephi 6"``."""
    canonicalUrl: str
    """Canonical URI of the page, e.g. ``"/scriptures/bofm/1-ne/6"``; differs from the requested URI on redirects."""
    contentType: str  # "text/html"
    """MIME type of ``Content.body`` (always ``"text/html"`` for scriptures)."""
    audio: Optional[list[Audio]] = None  # noqa: UP007, UP045
    """Audio recordings available for the page, or ``None`` when the API omits the field."""
    pageAttributes: Any
    """Raw HTML attributes of the page root, such as ``data-uri``, ``data-content-type`` and ``lang``.

    Example: ``{"data-uri": "/scriptures/bofm/1-ne/6", "data-content-type": "chapter", "lang": "eng"}``.
    """
    scopedClassName: str  # "classic-scripture"
    """CSS scope class applied to the page body (``"classic-scripture"`` for scriptures)."""


class ReferenceUri(pydantic.BaseModel):
    """Represents a reference URI with its type, hyperlink, and display text."""

    type: str
    """Kind of reference, as labelled by the API (for example ``"scripture"``)."""
    href: str
    """Link target of the reference, usually a site-relative study URL."""
    text: str
    """Display text of the reference."""


class Footnote(pydantic.BaseModel):
    """Represents a footnote with associated metadata and references."""

    id: str
    """Footnote identifier, matching the ``#note...`` fragment of the ``<a class="study-note-ref">`` link."""
    marker: str = ""
    """Footnote marker letter shown in the text (e.g. ``"a"``); empty when absent."""
    pid: str = ""
    """Paragraph id of the verse that the footnote is attached to; empty when absent."""
    context: str = ""
    """Quoted phrase of the verse that the footnote annotates; empty when absent."""
    text: str
    """HTML fragment containing the footnote text (may include cross-reference links)."""
    referenceUris: list[ReferenceUri] = pydantic.Field(default_factory=list)
    """Cross references cited by the footnote."""

    def uris(self) -> list[str]:
        """Return the href of every reference cited by the footnote.

        Returns:
            A list of href strings extracted from each uri in referenceUris, in order.
        """
        return [uri.href for uri in self.referenceUris]


class Content(pydantic.BaseModel):
    """Represents the ``content`` object of a study API response: the page HTML and its footnotes."""

    head: Any
    """Page head data; not interpreted by the scrapers."""
    body: str
    """HTML body of the page (verses, titles, headers, tables and so on)."""
    footnotes: dict[str, Footnote]
    """Footnotes keyed by footnote id (as used in ``#note...`` link fragments of ``body``)."""


class ScriptureStudyContent(pydantic.BaseModel):
    """Content for a scripture chapter or verse (the full study API response)."""

    meta: Meta
    """Page metadata."""
    content: Content
    """Page HTML and footnotes."""
    pids: Any
    """Paragraph id data; not interpreted by the scrapers."""
    tableOfContentsUri: str
    """URI of the table of contents containing this page."""
    uri: str
    """URI of the page itself."""
    verified: bool
    """Whether the Church site marks the content as verified."""


class ContentApiContent(pydantic.BaseModel):
    """Represents content retrieved from the Content API."""

    id: str
    """Identifier of the content paragraph."""
    markup: str
    """HTML markup of the paragraph."""
    displayId: str = ""
    """Human readable identifier (e.g. verse number); empty when absent."""


class ContentApiResponse(pydantic.BaseModel):
    """Represents the response from the content API."""

    content: list[ContentApiContent]
    """Paragraphs returned for the requested reference."""
    headline: str
    """Headline of the page the content belongs to."""
    publication: str
    """Name of the publication the content belongs to."""
    referenceURIDisplayText: Union[str, Any]  # noqa: UP007, UP045
    """Display text of the reference URI."""
    referenceURI: Union[str, Any]  # noqa: UP007, UP045
    """URI of the reference that was requested."""
    type: str
    """Content type reported by the API."""
    uri: str
    """URI of the content."""
    image: Any
    """Image data attached to the response; not interpreted by the scrapers."""
    idNotationUri: Union[str, Any] = ""  # noqa: UP007, UP045
    """Identifier notation URI; empty when absent."""


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
"""Book of Mormon book names mapped to their URI path segment on churchofjesuschrist.org (e.g. ``"1 Nephi"`` -> ``"1-ne"``)."""

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
"""Old Testament book names mapped to their URI path segment (e.g. ``"Genesis"`` -> ``"gen"``)."""

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
"""New Testament book names mapped to their URI path segment (e.g. ``"Matthew"`` -> ``"matt"``)."""

DoctrineAndCovenantsBooksUri = {
    "Doctrine and Covenants": "dc",
}
"""Doctrine and Covenants "book" name mapped to its URI path segment; the whole work is a single book, ``dc``."""

PearlOfGreatPriceBooksUri = {
    "Moses": "moses",
    "Abraham": "abr",
    "Joseph Smith--Matthew": "js-m",
    "Joseph Smith--History": "js-h",
    "Articles of Faith": "a-of-f",
}
"""Pearl of Great Price book names mapped to their URI path segment (e.g. ``"Moses"`` -> ``"moses"``)."""

parent_book_uri_mapper: dict[str, tuple[str, dict[str, str]]] = {
    "BookOfMormon": ("bofm", BookOfMormonBooksUri),
    "OldTestament": ("ot", OldTestamentBooksUri),
    "NewTestament": ("nt", NewTestamentBooksUri),
    "DoctrineAndCovenants": ("dc-testament", DoctrineAndCovenantsBooksUri),
    "PearlOfGreatPrice": ("pgp", PearlOfGreatPriceBooksUri),
}
"""Standard work key (as passed to `prepare_uri`) mapped to its (URI path segment, book name mapping) pair."""


BASE_STUDY_CONTENT_URL = (
    "https://www.churchofjesuschrist.org/study/api/v3/language-pages/type/content"
)
"""Endpoint of the Study API that returns a scripture page (HTML body plus footnotes) as JSON."""
BASE_CONTENT_URL = "https://www.churchofjesuschrist.org/content/api/v3"
"""Base endpoint of the Content API (paragraph-level content lookups)."""
STUDY_CONTENT_URL_FORMAT = f"{BASE_STUDY_CONTENT_URL}?lang={{lang}}&uri={{uri}}"
"""Format string for a Study API request, filled with ``lang`` and ``uri``."""
BASE_CONTENT_URL_FORMAT = "/{lang}/scriptures/{parent_book_uri}/{book_uri}/{chapter}.{verse}"
"""Format string for a Content API verse reference path."""

NOTE_ID_REGEX = re.compile(r"note(\d+)(\w+)")
"""Matches footnote ids of the form ``note<number><marker>`` (e.g. ``note2b``)."""

T = TypeVar("T")
"""Generic type variable (currently unused)."""


def prepare_uri(
    parent_book: str, book: str | None, chapter: int | None, book_uri: str | None = None
) -> str:
    """Prepare the uri for a chapter or verse.

    Produces site-relative paths such as ``/scriptures/bofm/1-ne/6`` (chapter) or
    ``/scriptures/bofm/1-ne`` (book table of contents).

    Args:
        parent_book: The parent book of the chapter or verse.
        book: The book of the chapter or verse.
        chapter: The chapter of the chapter or verse.
        book_uri: Specific book uri to use (book is ignored if this is provided)

    Returns:
        The uri of the chapter or verse.

    Raises:
        ValueError: If ``parent_book`` is not a key of ``parent_book_uri_mapper``, if both ``book`` and ``book_uri``
            are None, or if ``book`` is not a known book of the parent book.
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
        The content of the chapter or verse. Invalid book arguments raise ``ValueError`` (see `prepare_uri`) and a
        redirect raises `RedirectionError` (see `get_scripture_content_from_uri`).
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
