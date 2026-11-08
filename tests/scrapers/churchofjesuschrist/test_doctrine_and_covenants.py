"""Unit tests for ``churchofjesuschrist.doctrine_and_covenants`` against a tiny mocked Study API."""

from __future__ import annotations

import re

import pyosis.generated as osis
import pytest
from lds_fake_site import FakeSite
from open_canon_site.scrapers.churchofjesuschrist import doctrine_and_covenants as dc

_PAGE = (
    '<p id="title1">Intro</p><p id="subtitle1">Sub</p>'
    "<header><p>Header text</p>  </header>"
    '<div class="body-block"><p>Body</p></div>'
    '<div class="closing-block"><p class="signature">Joseph Smith</p>'
    '<p id="closing1">Closing words</p></div>'
)


def test_section_and_declaration_counts() -> None:
    """The module fetches 138 sections and 2 Official Declarations."""
    assert (dc.DC_SECTION_COUNT, dc.OD_COUNT) == (138, 2)


@pytest.mark.asyncio
async def test_build_dc_front_matter_div_full_page(site: FakeSite, make_client) -> None:
    """Title, subtitle, header, body, signatures and closing are converted in order."""
    site.pages["/scriptures/dc-testament/introduction"] = _PAGE
    async with make_client(site) as client:
        div = await dc._build_dc_front_matter_div("eng", "introduction", client, canonical=True)
    assert div.canonical is True and div.type_value == osis.OsisDivs.PREFACE
    head, sub, intro, body, signed, closing = div.content
    assert isinstance(head, osis.HeadCt) and head.content == ["Intro"]
    assert isinstance(sub, osis.TitleCt) and sub.content == ["Sub"]
    assert isinstance(intro, osis.DivCt) and intro.type_value == osis.OsisDivs.INTRODUCTION
    assert isinstance(body, osis.PCt)
    assert isinstance(signed, osis.SignedCt) and signed.content[0].content == ["Joseph Smith"]
    assert isinstance(closing, osis.PCt)


@pytest.mark.asyncio
async def test_build_dc_front_matter_div_body_only_with_type(site: FakeSite, make_client) -> None:
    """A body-only page yields one element and honours front_matter_type_value; empty closing block adds nothing."""
    site.pages["/scriptures/dc-testament/x"] = (
        '<div class="body-block"><p>b</p></div><div class="closing-block"></div>'
    )
    async with make_client(site) as client:
        div = await dc._build_dc_front_matter_div(
            "eng", "x", client, canonical=False, front_matter_type_value=osis.OsisDivs.APPENDIX
        )
    assert div.type_value == osis.OsisDivs.APPENDIX
    assert len(div.content) == 1


@pytest.mark.asyncio
async def test_build_dc_front_matter_div_empty_body_raises(site: FakeSite, make_client) -> None:
    """An empty body block raises ValueError."""
    site.pages["/scriptures/dc-testament/x"] = '<div class="body-block"></div>'
    async with make_client(site) as client:
        with pytest.raises(ValueError, match="No contents"):
            await dc._build_dc_front_matter_div("eng", "x", client, canonical=False)


@pytest.mark.asyncio
async def test_build_doctrine_and_covenants_front_matter(site: FakeSite, make_client) -> None:
    """Front matter is the introduction (preface) and chronological order (appendix) pages."""
    async with make_client(site) as client:
        front = await dc.build_doctrine_and_covenants_front_matter("eng", client)
    assert front.type_value == osis.OsisDivs.FRONT and front.canonical is False
    intro, chron = front.content
    assert intro.type_value == osis.OsisDivs.PREFACE  # type: ignore[attr-defined]
    assert chron.type_value == osis.OsisDivs.APPENDIX  # type: ignore[attr-defined]
    assert sorted(site.uris()) == [
        "/scriptures/dc-testament/chron-order",
        "/scriptures/dc-testament/introduction",
    ]


@pytest.mark.asyncio
async def test_build_official_declaration(site: FakeSite, make_client) -> None:
    """An Official Declaration becomes a book division ``OD.<n>`` holding its title and chapter."""
    async with make_client(site) as client:
        div = await dc._build_official_declaration("eng", 2, client)
    assert div.osis_id == ["OD.2"]
    assert div.type_value == osis.OsisDivs.BOOK and div.canonical is True
    title, chapter = div.content
    assert isinstance(title, osis.TitleCt)
    assert isinstance(chapter, osis.ChapterCt) and chapter.osis_id == ["OD.2"]
    assert site.uris() == ["/scriptures/dc-testament/od/2"]


@pytest.mark.asyncio
async def test_build_official_declaration_without_front_matter(site: FakeSite, make_client) -> None:
    """A declaration page with no title block contributes only the chapter."""
    site.pages["/scriptures/dc-testament/od/1"] = (
        '<div class="body-block"><p class="verse"><span class="verse-number">1</span>x</p></div>'
    )
    async with make_client(site) as client:
        div = await dc._build_official_declaration("eng", 1, client)
    assert [type(c) for c in div.content] == [osis.ChapterCt]


@pytest.mark.asyncio
async def test_build_doctrine_and_covenants_sections_fetches_all_138(
    site: FakeSite, make_client
) -> None:
    """All sections 1-138 are fetched and built as chapters of the ``DC`` book."""
    async with make_client(site) as client:
        book = await dc.build_doctrine_and_covenants_sections("eng", client)
    assert book.osis_id == ["DC"] and book.canonical is True
    chapters = [c for c in book.content if isinstance(c, osis.ChapterCt)]
    assert [c.osis_id[0] for c in chapters] == [f"DC.{n}" for n in range(1, 139)]
    assert len(site.requests) == 138
    assert "/scriptures/dc-testament/dc/138" in site.uris()


@pytest.mark.asyncio
async def test_build_doctrine_and_covenants_header_with_edition(
    site: FakeSite, make_client
) -> None:
    """The header records the scrape and, given a ``Source:`` date, the edition."""
    async with make_client(site) as client:
        header = await dc.build_doctrine_and_covenants_header("eng", client)
    assert header.work[0].osis_work == "DC"
    assert header.work[0].title[0].content == ["The Doctrine and Covenants"]
    scraped, edition = header.revision_desc
    assert re.fullmatch(r"\d{4}\.\d{2}\.\d{2}T\d{2}:\d{2}:\d{2}", scraped.date.content[0])
    assert edition.date.content == ["2013.10"]


@pytest.mark.asyncio
async def test_build_doctrine_and_covenants_header_without_source(
    site: FakeSite, make_client
) -> None:
    """Without a ``Source:`` date no edition revision is added."""
    site.pages["/scriptures/dc-testament/introduction"] = (
        '<div class="copyright-info">&copy; Test</div><div class="body-block"></div>'
    )
    async with make_client(site) as client:
        header = await dc.build_doctrine_and_covenants_header("eng", client)
    assert len(header.revision_desc) == 1


@pytest.mark.asyncio
async def test_build_doctrine_and_covenants_header_without_copyright_tag(
    site: FakeSite, make_client
) -> None:
    """A page with no ``div.copyright-info`` also gives just the scrape revision."""
    site.pages["/scriptures/dc-testament/introduction"] = '<div class="body-block"></div>'
    async with make_client(site) as client:
        header = await dc.build_doctrine_and_covenants_header("eng", client)
    assert len(header.revision_desc) == 1


@pytest.mark.asyncio
async def test_build_doctrine_and_covenants_end_to_end(site: FakeSite, make_client) -> None:
    """build_doctrine_and_covenants assembles front matter, sections and both declarations."""
    async with make_client(site) as client:
        xml = await dc.build_doctrine_and_covenants("eng", client)
    text = xml.osis.osis_text
    assert text.osis_idwork == "dc" and text.osis_ref_work == "The Doctrine and Covenants"
    front, sections, od1, od2 = text.div
    assert front.type_value == osis.OsisDivs.FRONT
    assert sections.osis_id == ["DC"]
    assert (od1.osis_id, od2.osis_id) == (["OD.1"], ["OD.2"])
    assert 'osisID="DC.138.1"' in xml.to_xml()
