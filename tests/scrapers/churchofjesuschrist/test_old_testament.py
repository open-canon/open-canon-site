"""Unit tests for ``churchofjesuschrist.old_testament`` against a tiny mocked Study API."""

from __future__ import annotations

import re

import httpx
import pyosis.generated as osis
import pytest
from lds_fake_site import FakeSite
from open_canon_site.scrapers.churchofjesuschrist import models
from open_canon_site.scrapers.churchofjesuschrist import old_testament as ot


@pytest.mark.asyncio
async def test_build_ot_front_matter_div_title_header_body(site: FakeSite, make_client) -> None:
    """A page's title, subtitle, non-blank header and body block are converted in that order."""
    site.pages["/scriptures/ot/title-page"] = (
        '<h1 id="title1">OT</h1><p id="subtitle1">Sub</p><header><p>Intro</p> </header>'
        '<div class="body-block"><p>Body</p></div>'
    )
    async with make_client(site) as client:
        div = await ot._build_ot_front_matter_div(
            "eng",
            "title-page",
            client,
            canonical=True,
            front_matter_type_value=osis.OsisDivs.TITLE_PAGE,
        )
    assert div.canonical is True and div.type_value == osis.OsisDivs.TITLE_PAGE
    head, sub, intro, body = div.content
    assert isinstance(head, osis.HeadCt) and head.content == ["OT"]
    assert isinstance(sub, osis.TitleCt) and sub.content == ["Sub"]
    assert isinstance(intro, osis.DivCt) and intro.type_value == osis.OsisDivs.INTRODUCTION
    assert isinstance(body, osis.PCt)


@pytest.mark.asyncio
async def test_build_ot_front_matter_div_defaults_to_preface(site: FakeSite, make_client) -> None:
    """Without an explicit type the division is a preface; a body-only page has just the body."""
    site.pages["/scriptures/ot/x"] = '<div class="body-block"><p>b</p></div>'
    async with make_client(site) as client:
        div = await ot._build_ot_front_matter_div("eng", "x", client, canonical=False)
    assert div.type_value == osis.OsisDivs.PREFACE
    assert len(div.content) == 1


@pytest.mark.asyncio
async def test_build_old_testament_front_matter_has_title_page_and_dedication(
    site: FakeSite, make_client
) -> None:
    """The front matter is a non-canonical front div holding the title page and the dedication."""
    async with make_client(site) as client:
        front = await ot.build_old_testament_front_matter("eng", client)
    assert front.type_value == osis.OsisDivs.FRONT and front.canonical is False
    title_page, dedication = front.content
    assert title_page.type_value == osis.OsisDivs.TITLE_PAGE  # type: ignore[attr-defined]
    assert dedication.type_value == osis.OsisDivs.DEDICATION  # type: ignore[attr-defined]
    assert sorted(site.uris()) == ["/scriptures/ot/dedication", "/scriptures/ot/title-page"]


def test_build_old_testament_header_metadata() -> None:
    """The header names the work OT and records the scrape time; the client is unused."""
    header = ot.build_old_testament_header("eng", None)  # type: ignore[arg-type]
    work = header.work[0]
    assert work.osis_work == "OT"
    assert work.title[0].content == ["The Old Testament"]
    (revision,) = header.revision_desc
    assert re.fullmatch(r"\d{4}\.\d{2}\.\d{2}T\d{2}:\d{2}:\d{2}", revision.date.content[0])
    assert revision.date.lang == "eng"


@pytest.mark.asyncio
async def test_build_old_testament_end_to_end(site: FakeSite, make_client) -> None:
    """build_old_testament builds front matter and all 39 books into OSIS XML."""
    async with make_client(site) as client:
        xml = await ot.build_old_testament("eng", client)
    text = xml.osis.osis_text
    assert text.osis_idwork == "ot" and text.osis_ref_work == "The Old Testament"
    front, *books = text.div
    assert front.type_value == osis.OsisDivs.FRONT
    assert [b.osis_id[0] for b in books] == list(models.OldTestamentBooksUri)
    assert "Verse /scriptures/ot/gen/1" in xml.to_xml()


@pytest.mark.asyncio
async def test_build_old_testament_propagates_http_json_errors(make_client) -> None:
    """A non-JSON response aborts the build with the decoder's error."""
    async with make_client(lambda request: httpx.Response(200, text="not json")) as client:
        with pytest.raises(ValueError):
            await ot.build_old_testament("eng", client)
