"""Unit tests for the Study API models and URL helpers in ``churchofjesuschrist.models``."""

from __future__ import annotations

import httpx
import pydantic
import pytest
from hypothesis import given
from hypothesis import strategies as st
from lds_fake_site import FakeSite, study_payload
from open_canon_site.scrapers.churchofjesuschrist import models

_ALL_BOOKS = [
    (parent, book, uri)
    for parent, (_seg, mapping) in models.parent_book_uri_mapper.items()
    for book, uri in mapping.items()
]


def _toc_body(*titles: str, hrefs: list[str] | None = None) -> str:
    """Build a table-of-contents body with one ``p.title`` per title, optionally wrapped in links."""
    parts = []
    for index, title in enumerate(titles):
        inner = f'<p class="title">{title}</p>'
        if hrefs is not None:
            inner = f'<a href="{hrefs[index]}">{inner}</a>'
        parts.append(f"<li>{inner}</li>")
    return "<ul>" + "".join(parts) + "</ul>"


def test_footnote_uris_returns_hrefs_in_order() -> None:
    """Footnote.uris lists the href of every reference URI in order."""
    note = models.Footnote(
        id="note1a",
        text="See",
        referenceUris=[
            models.ReferenceUri(type="scripture", href="/a", text="A"),
            models.ReferenceUri(type="scripture", href="/b", text="B"),
        ],
    )
    assert note.uris() == ["/a", "/b"]


def test_footnote_uris_empty_by_default() -> None:
    """Footnote.uris is empty and optional fields default to empty strings when omitted."""
    note = models.Footnote(id="note1a", text="x")
    assert note.uris() == []
    assert (note.marker, note.pid, note.context) == ("", "", "")


def test_scripture_study_content_parses_api_payload() -> None:
    """ScriptureStudyContent validates a real-shaped payload including nested footnotes and audio."""
    payload = study_payload(
        "/scriptures/bofm/1-ne/1",
        "<p>x</p>",
        footnotes={
            "note1a": {
                "id": "note1a",
                "marker": "a",
                "text": "<p>note</p>",
                "referenceUris": [{"type": "scripture", "href": "/h", "text": "H"}],
            }
        },
    )
    payload["meta"]["audio"] = [{"mediaUrl": "https://x/y.mp3", "variant": "male"}]
    parsed = models.ScriptureStudyContent(**payload)
    assert parsed.meta.audio is not None and parsed.meta.audio[0].variant == "male"
    assert parsed.content.footnotes["note1a"].uris() == ["/h"]
    assert parsed.content.body == "<p>x</p>"


def test_scripture_study_content_audio_defaults_to_none() -> None:
    """Meta.audio is None when the API omits it."""
    parsed = models.ScriptureStudyContent(**study_payload("/u", ""))
    assert parsed.meta.audio is None


def test_scripture_study_content_rejects_missing_fields() -> None:
    """A payload without required fields fails pydantic validation."""
    with pytest.raises(pydantic.ValidationError):
        models.ScriptureStudyContent(**{"meta": {}})


def test_content_api_response_defaults() -> None:
    """ContentApiResponse and ContentApiContent apply their empty-string defaults."""
    response = models.ContentApiResponse(
        content=[models.ContentApiContent(id="p1", markup="<p>x</p>")],
        headline="h",
        publication="p",
        referenceURIDisplayText="t",
        referenceURI="u",
        type="t",
        uri="/u",
        image=None,
    )
    assert response.idNotationUri == ""
    assert response.content[0].displayId == ""


def test_redirection_error_is_value_error() -> None:
    """RedirectionError can be caught as a ValueError."""
    assert issubclass(models.RedirectionError, ValueError)


def test_prepare_uri_chapter() -> None:
    """prepare_uri builds the chapter path from the parent book and book names."""
    assert models.prepare_uri("BookOfMormon", "1 Nephi", 6) == "/scriptures/bofm/1-ne/6"


def test_prepare_uri_without_chapter_is_book_toc() -> None:
    """prepare_uri omits the chapter segment when chapter is None."""
    assert models.prepare_uri("OldTestament", "Genesis", None) == "/scriptures/ot/gen"


def test_prepare_uri_book_uri_overrides_book() -> None:
    """prepare_uri uses book_uri verbatim and ignores book (which may be None or unknown)."""
    assert (
        models.prepare_uri("PearlOfGreatPrice", None, None, book_uri="abr/fac-1")
        == "/scriptures/pgp/abr/fac-1"
    )
    assert (
        models.prepare_uri("BookOfMormon", "Nonsense", 2, book_uri="od") == "/scriptures/bofm/od/2"
    )


def test_prepare_uri_invalid_parent_book() -> None:
    """prepare_uri rejects an unknown parent book."""
    with pytest.raises(ValueError, match="Invalid parent book"):
        models.prepare_uri("Quran", "Genesis", 1)


def test_prepare_uri_missing_book() -> None:
    """prepare_uri requires a book when no book_uri is given."""
    with pytest.raises(ValueError, match="book cannot be None"):
        models.prepare_uri("BookOfMormon", None, 1)


def test_prepare_uri_invalid_book() -> None:
    """prepare_uri rejects a book that is not part of the parent book."""
    with pytest.raises(ValueError, match="Invalid book"):
        models.prepare_uri("BookOfMormon", "Genesis", 1)


@given(st.sampled_from(_ALL_BOOKS), st.one_of(st.none(), st.integers(1, 150)))
def test_prepare_uri_matches_mapping_for_every_book(
    entry: tuple[str, str, str], chapter: int | None
) -> None:
    """prepare_uri yields /scriptures/<parent>/<book>[/<chapter>] for every known book."""
    parent, book, book_uri = entry
    parent_seg = models.parent_book_uri_mapper[parent][0]
    expected = f"/scriptures/{parent_seg}/{book_uri}" + ("" if chapter is None else f"/{chapter}")
    assert models.prepare_uri(parent, book, chapter) == expected


@pytest.mark.asyncio
async def test_get_scripture_content_from_uri_returns_parsed(site: FakeSite, make_client) -> None:
    """get_scripture_content_from_uri requests the study API URL and parses the response."""
    site.pages["/scriptures/bofm/1-ne/1"] = "<p>hi</p>"
    async with make_client(site) as client:
        parsed = await models.get_scripture_content_from_uri(
            "eng", "/scriptures/bofm/1-ne/1", client
        )
    assert parsed.content.body == "<p>hi</p>"
    request = site.requests[0]
    assert str(request.url).startswith(models.BASE_STUDY_CONTENT_URL)
    assert request.url.params["lang"] == "eng"


@pytest.mark.asyncio
async def test_get_scripture_content_from_uri_accepts_canonical_with_lang(make_client) -> None:
    """A canonicalUrl of ``<uri>?lang=<lang>`` is not treated as a redirect."""
    payload = study_payload("/u", "", canonical="/u?lang=eng")
    async with make_client(lambda r: httpx.Response(200, json=payload)) as client:
        parsed = await models.get_scripture_content_from_uri("eng", "/u", client)
    assert parsed.meta.canonicalUrl == "/u?lang=eng"


@pytest.mark.asyncio
async def test_get_scripture_content_from_uri_raises_on_redirect(make_client) -> None:
    """A different canonicalUrl raises RedirectionError naming both URLs."""
    payload = study_payload("/u", "", canonical="/other")
    async with make_client(lambda r: httpx.Response(200, json=payload)) as client:
        with pytest.raises(models.RedirectionError, match="redirect to /other"):
            await models.get_scripture_content_from_uri("eng", "/u", client)


@pytest.mark.asyncio
async def test_get_scripture_content_builds_uri_from_book(site: FakeSite, make_client) -> None:
    """get_scripture_content maps parent book/book/chapter to the requested uri."""
    async with make_client(site) as client:
        await models.get_scripture_content("eng", "NewTestament", "Matthew", 5, client)
        await models.get_scripture_content(
            "eng", "BookOfMormon", None, None, client, book_uri="introduction"
        )
    assert site.uris() == ["/scriptures/nt/matt/5", "/scriptures/bofm/introduction"]


@pytest.mark.asyncio
async def test_get_scripture_content_invalid_book_raises(site: FakeSite, make_client) -> None:
    """get_scripture_content propagates prepare_uri's ValueError without making a request."""
    async with make_client(site) as client:
        with pytest.raises(ValueError, match="Invalid book"):
            await models.get_scripture_content("eng", "NewTestament", "Genesis", 1, client)
    assert site.requests == []


@pytest.mark.asyncio
async def test_get_chapters_list_parses_chapter_titles(site: FakeSite, make_client) -> None:
    """get_chapters_list returns the trailing integer of every ``p.title`` in the table of contents."""
    site.pages["/scriptures/bofm/1-ne"] = _toc_body("Chapter 1", "Chapter 2", "Chapter 10")
    async with make_client(site) as client:
        assert await models.get_chapters_list("eng", "BookOfMormon", "1 Nephi", client) == [
            1,
            2,
            10,
        ]


@pytest.mark.asyncio
async def test_get_chapters_list_skips_non_numeric_links(site: FakeSite, make_client) -> None:
    """Entries whose link does not end in a number (Abraham facsimiles) are skipped."""
    site.pages["/scriptures/pgp/abr"] = _toc_body(
        "Chapter 1",
        "Facsimile 1",
        "Chapter 2",
        hrefs=[
            "/study/scriptures/pgp/abr/1?lang=eng",
            "/study/scriptures/pgp/abr/fac-1?lang=eng",
            "/study/scriptures/pgp/abr/2/",
        ],
    )
    async with make_client(site) as client:
        assert await models.get_chapters_list("eng", "PearlOfGreatPrice", "Abraham", client) == [
            1,
            2,
        ]


@pytest.mark.asyncio
async def test_get_chapters_list_redirect_means_single_chapter(site: FakeSite, make_client) -> None:
    """A redirect to the parent table of contents (single-chapter book) yields ``[1]``."""
    async with make_client(site) as client:
        assert await models.get_chapters_list("eng", "BookOfMormon", "Enos", client) == [1]


@pytest.mark.asyncio
async def test_get_chapters_list_invalid_title_raises(site: FakeSite, make_client) -> None:
    """A chapter title that does not end in a number raises ValueError."""
    site.pages["/scriptures/bofm/enos"] = '<p class="title">Introduction</p>'
    async with make_client(site) as client:
        with pytest.raises(ValueError, match="Invalid chapter title format"):
            await models.get_chapters_list("eng", "BookOfMormon", "Enos", client)


@given(st.lists(st.integers(1, 200), min_size=1, max_size=30))
def test_get_chapters_list_roundtrips_chapter_numbers(numbers: list[int]) -> None:
    """Any list of chapter numbers rendered as ``Chapter N`` titles is parsed back unchanged."""
    import asyncio

    site = FakeSite({"/scriptures/ot/gen": _toc_body(*[f"Chapter {n}" for n in numbers])})

    async def run() -> list[int]:
        """Fetch the chapters list through the mocked site."""
        async with httpx.AsyncClient(transport=httpx.MockTransport(site)) as client:
            return await models.get_chapters_list("eng", "OldTestament", "Genesis", client)

    assert asyncio.run(run()) == numbers
