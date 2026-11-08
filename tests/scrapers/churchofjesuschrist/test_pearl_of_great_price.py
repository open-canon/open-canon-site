"""Unit tests for ``churchofjesuschrist.pearl_of_great_price`` against a tiny mocked Study API."""

from __future__ import annotations

import re

import httpx
import pyosis.generated as osis
import pytest
from lds_fake_site import FakeSite
from open_canon_site.scrapers.churchofjesuschrist import models
from open_canon_site.scrapers.churchofjesuschrist import pearl_of_great_price as pgp


@pytest.mark.asyncio
async def test_build_pgp_front_matter_div_title_header_body(site: FakeSite, make_client) -> None:
    """A page's title, subtitle, non-blank header and body block are converted in that order."""
    site.pages["/scriptures/pgp/title-page"] = (
        '<h1 id="title1">PGP</h1><p id="subtitle1">Sub</p><header><p>Intro</p> </header>'
        '<div class="body-block"><p>Body</p></div>'
    )
    async with make_client(site) as client:
        div = await pgp._build_pgp_front_matter_div(
            "eng",
            "title-page",
            client,
            canonical=True,
            front_matter_type_value=osis.OsisDivs.TITLE_PAGE,
        )
    assert div.canonical is True and div.type_value == osis.OsisDivs.TITLE_PAGE
    head, sub, intro, body = div.content
    assert isinstance(head, osis.HeadCt) and head.content == ["PGP"]
    assert isinstance(sub, osis.TitleCt) and sub.content == ["Sub"]
    assert isinstance(intro, osis.DivCt) and intro.type_value == osis.OsisDivs.INTRODUCTION
    assert isinstance(body, osis.PCt)


@pytest.mark.asyncio
async def test_build_pgp_front_matter_div_defaults_to_preface(site: FakeSite, make_client) -> None:
    """Without an explicit type the division is a preface; a body-only page has just the body."""
    site.pages["/scriptures/pgp/x"] = '<div class="body-block"><p>b</p></div>'
    async with make_client(site) as client:
        div = await pgp._build_pgp_front_matter_div("eng", "x", client, canonical=False)
    assert div.type_value == osis.OsisDivs.PREFACE
    assert len(div.content) == 1


@pytest.mark.asyncio
async def test_build_pearl_of_great_price_front_matter_wraps_title_page(
    site: FakeSite, make_client
) -> None:
    """The front matter is a non-canonical front div holding the title page."""
    async with make_client(site) as client:
        front = await pgp.build_pearl_of_great_price_front_matter("eng", client)
    assert front.type_value == osis.OsisDivs.FRONT and front.canonical is False
    (title_page,) = front.content
    assert title_page.type_value == osis.OsisDivs.TITLE_PAGE  # type: ignore[attr-defined]
    assert site.uris() == ["/scriptures/pgp/title-page"]


def test_build_pearl_of_great_price_header_metadata() -> None:
    """The header names the work PGP and records the scrape time; the client is unused."""
    header = pgp.build_pearl_of_great_price_header("eng", None)  # type: ignore[arg-type]
    work = header.work[0]
    assert work.osis_work == "PGP"
    assert work.title[0].content == ["The Pearl of Great Price"]
    (revision,) = header.revision_desc
    assert re.fullmatch(r"\d{4}\.\d{2}\.\d{2}T\d{2}:\d{2}:\d{2}", revision.date.content[0])
    assert revision.date.lang == "eng"


@pytest.mark.asyncio
async def test_build_pearl_of_great_price_end_to_end(site: FakeSite, make_client) -> None:
    """build_pearl_of_great_price builds front matter and all five books into OSIS XML."""
    async with make_client(site) as client:
        xml = await pgp.build_pearl_of_great_price("eng", client)
    text = xml.osis.osis_text
    assert text.osis_idwork == "pgp" and text.osis_ref_work == "The Pearl of Great Price"
    front, *books = text.div
    assert front.type_value == osis.OsisDivs.FRONT
    assert [b.osis_id[0] for b in books] == list(models.PearlOfGreatPriceBooksUri)
    abraham = books[1]
    assert (
        sum(getattr(c, "type_value", None) == osis.OsisDivs.APPENDIX for c in abraham.content) == 3
    )
    assert "Verse /scriptures/pgp/moses/1" in xml.to_xml()


@pytest.mark.asyncio
async def test_build_pearl_of_great_price_propagates_http_json_errors(make_client) -> None:
    """A non-JSON response aborts the build with the decoder's error."""
    async with make_client(lambda request: httpx.Response(200, text="not json")) as client:
        with pytest.raises(ValueError):
            await pgp.build_pearl_of_great_price("eng", client)


@pytest.mark.asyncio
async def test_build_abraham_facsimile_div_reads_title_and_body(
    site: FakeSite, make_client
) -> None:
    """A facsimile page becomes a canonical appendix with id ``Abraham.Fac-<n>`` (title, subtitle, body)."""
    site.pages["/scriptures/pgp/abr/fac-2"] = (
        '<h1 id="title1">Facsimile 2</h1><p id="subtitle1">Explanation</p>'
        '<div class="body-block"><p>Figures</p></div>'
    )
    async with make_client(site) as client:
        div = await pgp._build_abraham_facsimile_div("eng", 2, client)
    assert div.canonical is True and div.type_value == osis.OsisDivs.APPENDIX
    assert div.osis_id == ["Abraham.Fac-2"]
    head, sub, body = div.content
    assert isinstance(head, osis.HeadCt) and head.content == ["Facsimile 2"]
    assert isinstance(sub, osis.TitleCt) and sub.content == ["Explanation"]
    assert isinstance(body, osis.PCt)
    assert site.uris() == ["/scriptures/pgp/abr/fac-2"]


@pytest.mark.asyncio
async def test_build_abraham_facsimile_div_accepts_paragraph_title(
    site: FakeSite, make_client
) -> None:
    """A facsimile title in ``p#title1`` is accepted as well as ``h1#title1``; no subtitle is fine."""
    site.pages["/scriptures/pgp/abr/fac-1"] = (
        '<p id="title1">Facsimile 1</p><div class="body-block"><p>x</p></div>'
    )
    async with make_client(site) as client:
        div = await pgp._build_abraham_facsimile_div("eng", 1, client)
    assert [type(c) for c in div.content] == [osis.HeadCt, osis.PCt]


@pytest.mark.asyncio
async def test_build_abraham_with_facsimiles_appends_three_appendices(
    site: FakeSite, make_client
) -> None:
    """Abraham's book division gets its three facsimile appendices after the chapters."""
    async with make_client(site) as client:
        book = await pgp._build_abraham_with_facsimiles("eng", client)
    assert book.osis_id == ["Abraham"]
    appendices = [
        c for c in book.content if getattr(c, "type_value", None) == osis.OsisDivs.APPENDIX
    ]
    assert [a.osis_id for a in appendices] == [  # type: ignore[attr-defined]
        ["Abraham.Fac-1"],
        ["Abraham.Fac-2"],
        ["Abraham.Fac-3"],
    ]
    assert isinstance(book.content[-1], osis.DivCt)
    assert any(isinstance(c, osis.ChapterCt) for c in book.content)
