"""Unit tests for ``churchofjesuschrist.new_testament`` against a tiny mocked Study API."""

from __future__ import annotations

import re

import httpx
import pyosis.generated as osis
import pytest
from lds_fake_site import FakeSite
from open_canon_site.scrapers.churchofjesuschrist import models
from open_canon_site.scrapers.churchofjesuschrist import new_testament as nt


@pytest.mark.asyncio
async def test_build_nt_front_matter_div_title_header_body(site: FakeSite, make_client) -> None:
    """A page's title, subtitle, non-blank header and body block are converted in that order."""
    site.pages["/scriptures/nt/title-page"] = (
        '<h1 id="title1">NT</h1><p id="subtitle1">Sub</p><header><p>Intro</p> </header>'
        '<div class="body-block"><p>Body</p></div>'
    )
    async with make_client(site) as client:
        div = await nt._build_nt_front_matter_div(
            "eng",
            "title-page",
            client,
            canonical=True,
            front_matter_type_value=osis.OsisDivs.TITLE_PAGE,
        )
    assert div.canonical is True and div.type_value == osis.OsisDivs.TITLE_PAGE
    head, sub, intro, body = div.content
    assert isinstance(head, osis.HeadCt) and head.content == ["NT"]
    assert isinstance(sub, osis.TitleCt) and sub.content == ["Sub"]
    assert isinstance(intro, osis.DivCt) and intro.type_value == osis.OsisDivs.INTRODUCTION
    assert isinstance(body, osis.PCt)


@pytest.mark.asyncio
async def test_build_nt_front_matter_div_defaults_to_preface(site: FakeSite, make_client) -> None:
    """Without an explicit type the division is a preface; a body-only page has just the body."""
    site.pages["/scriptures/nt/x"] = '<div class="body-block"><p>b</p></div>'
    async with make_client(site) as client:
        div = await nt._build_nt_front_matter_div("eng", "x", client, canonical=False)
    assert div.type_value == osis.OsisDivs.PREFACE
    assert len(div.content) == 1


@pytest.mark.asyncio
async def test_build_new_testament_front_matter_wraps_title_page(
    site: FakeSite, make_client
) -> None:
    """The front matter is a non-canonical front div holding the title page."""
    async with make_client(site) as client:
        front = await nt.build_new_testament_front_matter("eng", client)
    assert front.type_value == osis.OsisDivs.FRONT and front.canonical is False
    (title_page,) = front.content
    assert title_page.type_value == osis.OsisDivs.TITLE_PAGE  # type: ignore[attr-defined]
    assert site.uris() == ["/scriptures/nt/title-page"]


def test_build_new_testament_header_metadata() -> None:
    """The header names the work NT and records the scrape time; the client is unused."""
    header = nt.build_new_testament_header("eng", None)  # type: ignore[arg-type]
    work = header.work[0]
    assert work.osis_work == "NT"
    assert work.title[0].content == ["The New Testament"]
    (revision,) = header.revision_desc
    assert re.fullmatch(r"\d{4}\.\d{2}\.\d{2}T\d{2}:\d{2}:\d{2}", revision.date.content[0])
    assert revision.date.lang == "eng"


@pytest.mark.asyncio
async def test_build_new_testament_end_to_end(site: FakeSite, make_client) -> None:
    """build_new_testament builds front matter and all 27 books into OSIS XML."""
    async with make_client(site) as client:
        xml = await nt.build_new_testament("eng", client)
    text = xml.osis.osis_text
    assert text.osis_idwork == "nt" and text.osis_ref_work == "The New Testament"
    front, *books = text.div
    assert front.type_value == osis.OsisDivs.FRONT
    assert [b.osis_id[0] for b in books] == list(models.NewTestamentBooksUri)
    assert "Verse /scriptures/nt/matt/1" in xml.to_xml()


@pytest.mark.asyncio
async def test_build_new_testament_propagates_http_json_errors(make_client) -> None:
    """A non-JSON response aborts the build with the decoder's error."""
    async with make_client(lambda request: httpx.Response(200, text="not json")) as client:
        with pytest.raises(ValueError):
            await nt.build_new_testament("eng", client)
