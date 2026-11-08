"""Unit tests for ``churchofjesuschrist.book_of_mormon`` against a tiny mocked Study API."""

from __future__ import annotations

import re

import pyosis.generated as osis
import pytest
from lds_fake_site import FakeSite
from open_canon_site.scrapers.churchofjesuschrist import book_of_mormon as bom
from open_canon_site.scrapers.churchofjesuschrist import models

_PAGE = (
    '<p id="title1">Testimony</p><p id="subtitle1">Of Witnesses</p>'
    "<header><p>Header intro</p>   </header>"
    '<div class="body-block"><p>Body text</p></div>'
    '<div class="closing-block"><p class="signature">Oliver Cowdery</p>'
    '<p class="signature">David Whitmer</p>'
    '<p id="closing1">Translated by <span class="uppercase">Joseph Smith</span></p></div>'
)


@pytest.mark.asyncio
async def test_build_bom_front_matter_div_full_page(site: FakeSite, make_client) -> None:
    """A page with title, subtitle, header, body and closing block yields head, title, intro div, body, signed, closing."""
    site.pages["/scriptures/bofm/three"] = _PAGE
    async with make_client(site) as client:
        div = await bom._build_bom_front_matter_div("eng", "three", client, canonical=True)
    assert div.canonical is True
    assert div.type_value == osis.OsisDivs.PREFACE
    head, subtitle, intro, body, signed, closing = div.content
    assert isinstance(head, osis.HeadCt) and head.content == ["Testimony"]
    assert isinstance(subtitle, osis.TitleCt) and subtitle.content == ["Of Witnesses"]
    assert isinstance(intro, osis.DivCt) and intro.type_value == osis.OsisDivs.INTRODUCTION
    assert isinstance(body, osis.PCt) and body.content == ["Body text"]
    assert isinstance(signed, osis.SignedCt)
    assert [n.content for n in signed.content] == [["Oliver Cowdery"], ["David Whitmer"]]
    assert isinstance(closing, osis.PCt)
    assert site.uris() == ["/scriptures/bofm/three"]


@pytest.mark.asyncio
async def test_build_bom_front_matter_div_minimal_page_and_type(
    site: FakeSite, make_client
) -> None:
    """Only a body block is required; the front matter type value is passed through."""
    site.pages["/scriptures/bofm/js"] = '<div class="body-block"><p>Just body</p></div>'
    async with make_client(site) as client:
        div = await bom._build_bom_front_matter_div(
            "eng",
            "js",
            client,
            canonical=False,
            front_matter_type_value=osis.OsisDivs.APPENDIX,
        )
    assert div.type_value == osis.OsisDivs.APPENDIX
    assert div.canonical is False
    assert len(div.content) == 1


@pytest.mark.asyncio
async def test_build_bom_front_matter_div_closing_without_signatures(
    site: FakeSite, make_client
) -> None:
    """A closing block with only ``p#closing1`` adds no ``signed`` element."""
    site.pages["/scriptures/bofm/js"] = (
        '<div class="body-block"><p>b</p></div><div class="closing-block"><p id="closing1">End</p></div>'
    )
    async with make_client(site) as client:
        div = await bom._build_bom_front_matter_div("eng", "js", client, canonical=False)
    assert [type(c) for c in div.content] == [osis.PCt, osis.PCt]


@pytest.mark.asyncio
async def test_build_bom_front_matter_div_empty_body_raises(site: FakeSite, make_client) -> None:
    """An empty body block raises ValueError."""
    site.pages["/scriptures/bofm/js"] = '<div class="body-block"></div>'
    async with make_client(site) as client:
        with pytest.raises(ValueError, match="No contents"):
            await bom._build_bom_front_matter_div("eng", "js", client, canonical=False)


@pytest.mark.asyncio
async def test_build_book_of_mormon_front_matter_has_eight_pages(
    site: FakeSite, make_client
) -> None:
    """The front matter fetches the eight front pages and tags canonical/type values per page."""
    async with make_client(site) as client:
        front = await bom.build_book_of_mormon_front_matter("eng", client)
    assert front.type_value == osis.OsisDivs.FRONT and front.canonical is False
    assert sorted(site.uris()) == sorted(
        f"/scriptures/bofm/{slug}"
        for slug in (
            "title-page",
            "bofm-title",
            "introduction",
            "three",
            "eight",
            "js",
            "explanation",
            "illustrations",
        )
    )
    types = [d.type_value for d in front.content]  # type: ignore[attr-defined]
    assert types[:2] == [osis.OsisDivs.COVER_PAGE, osis.OsisDivs.TITLE_PAGE]
    assert set(types[2:]) == {osis.OsisDivs.PREFACE}
    assert [d.canonical for d in front.content] == [False, True] + [False] * 6  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_build_book_of_mormon_back_matter_is_pronunciation_appendix(
    site: FakeSite, make_client
) -> None:
    """The back matter holds the pronunciation guide as an appendix."""
    async with make_client(site) as client:
        back = await bom.build_book_of_mormon_back_matter("eng", client)
    assert back.type_value == osis.OsisDivs.BACK
    (guide,) = back.content
    assert guide.type_value == osis.OsisDivs.APPENDIX  # type: ignore[attr-defined]
    assert site.uris() == ["/scriptures/bofm/pronunciation"]


@pytest.mark.asyncio
async def test_build_book_of_mormon_header_reads_publisher_and_edition(
    site: FakeSite, make_client
) -> None:
    """The header takes publisher text and the edition date from the title page."""
    async with make_client(site) as client:
        header = await bom.build_book_of_mormon_header("eng", client)
    assert header.work[0].osis_work == "BOM"
    assert header.work[0].publisher[0].value == "Published by Test Press"
    scraped, edition, first = header.revision_desc
    assert re.fullmatch(r"\d{4}\.\d{2}\.\d{2}T\d{2}:\d{2}:\d{2}", scraped.date.content[0])
    assert edition.date.content == ["2013.10"]
    assert "Source: 2013/10" in edition.p[0].content[0]
    assert first.date.content == ["1830.03.26"]
    assert [t.content for t in header.work[0].title] == [
        ["The Book of Mormon"],
        ["Another Testament of Jesus Christ"],
    ]


@pytest.mark.asyncio
async def test_build_book_of_mormon_header_without_publish_or_source(
    site: FakeSite, make_client
) -> None:
    """Missing publish/copyright info gives empty publisher and edition date instead of failing."""
    site.pages["/scriptures/bofm/title-page"] = '<div class="body-block"></div>'
    async with make_client(site) as client:
        header = await bom.build_book_of_mormon_header("eng", client)
    assert header.work[0].publisher[0].value == ""
    assert header.revision_desc[1].date.content == [""]


@pytest.mark.asyncio
async def test_build_book_of_mormon_end_to_end(site: FakeSite, make_client) -> None:
    """build_book_of_mormon assembles front matter, the fifteen books and back matter into OSIS XML."""
    async with make_client(site) as client:
        xml = await bom.build_book_of_mormon("eng", client)
    text = xml.osis.osis_text
    assert text.osis_idwork == "bom" and text.lang == "eng"
    front, *books, back = text.div
    assert front.type_value == osis.OsisDivs.FRONT
    assert back.type_value == osis.OsisDivs.BACK
    assert [b.osis_id[0] for b in books] == list(models.BookOfMormonBooksUri)
    rendered = xml.to_xml()
    assert 'osisID="1 Nephi.1.1"' in rendered
    assert "Verse /scriptures/bofm/1-ne/1" in rendered
