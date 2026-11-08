"""Unit tests for ``churchofjesuschrist.living_christ`` against a tiny mocked Study API."""

from __future__ import annotations

import argparse

import pyosis.generated as osis
import pytest
from lds_fake_site import FakeSite
from open_canon_site.scrapers import registry
from open_canon_site.scrapers.churchofjesuschrist import living_christ as lc

_PAGE = (
    '<p class="reference">“The Living Christ,” <cite>The Living Christ</cite> (2000)</p>'
    '<header><h1 id="title1">The Living Christ</h1><p class="subtitle">The Testimony of the Apostles</p>'
    '<div class="byline"><p id="p1">The Church of Jesus Christ of Latter-day Saints</p></div></header>'
    '<div class="body-block">'
    '<p id="p2">As we commemorate the birth of Jesus Christ.</p>'
    '<p id="p3">“All things were made by him” (<a class="scripture-ref" '
    'href="/study/scriptures/nt/john/1.3?lang=eng#p3">John 1:3</a>).</p>'
    '<figure class="image no-print" id="figure1"><header><p class="title">The First Presidency</p></header>'
    '<img src="https://example.org/a.jpeg" alt="Signatures"/><figcaption><p>January 1, 2000</p></figcaption>'
    "</figure>"
    '<figure class="image no-print" id="figure2"><header><p class="title">The Quorum of the Twelve</p></header>'
    '<img src="https://example.org/b.jpeg" alt="Signatures"/></figure>'
    '<div class="copyright-info"><p id="p15">© 2000 by Intellectual Reserve, Inc.</p></div>'
    "</div>"
)


@pytest.mark.asyncio
async def test_build_living_christ_structure(site: FakeSite, make_client) -> None:
    """Paragraphs become verses with references; signatures become a colophon; copyright is dropped."""
    site.pages[lc.LIVING_CHRIST.uri] = _PAGE
    async with make_client(site) as client:
        xml = await lc.build_living_christ("eng", client)
    assert site.uris() == [lc.LIVING_CHRIST.uri]
    text = xml.osis.osis_text
    assert text.osis_idwork == "LivingChrist"
    (book,) = text.div
    assert book.osis_id == ["LivingChrist"]
    main, sub, chapter = book.content
    assert main.content == ["The Living Christ"]
    assert sub.content == ["The Testimony of the Apostles"]
    byline, v1, v2, colophon = chapter.content
    assert byline.type_value == osis.OsisDivs.INTRODUCTION
    assert [v1.osis_id, v2.osis_id] == [["LivingChrist.1.1"], ["LivingChrist.1.2"]]
    assert any(isinstance(c, osis.ReferenceCt) for c in v2.content)
    assert colophon.type_value == osis.OsisDivs.COLOPHON and colophon.canonical is False
    assert [p.content for p in colophon.content] == [
        ["The First Presidency"],
        ["January 1, 2000"],
        ["The Quorum of the Twelve"],
    ]
    rendered = xml.to_xml()
    assert "Intellectual Reserve" not in rendered and "example.org" not in rendered


@pytest.mark.asyncio
async def test_write_living_christ_writes_file(site: FakeSite, make_client, tmp_path) -> None:
    """The OSIS file lands in the output directory."""
    site.pages[lc.LIVING_CHRIST.uri] = _PAGE
    async with make_client(site) as client:
        written = await lc.write_living_christ("eng", tmp_path / "out", client)
    assert written == [tmp_path / "out" / "the_living_christ.xml"]
    assert "LivingChrist.1.2" in written[0].read_text("utf-8")


def test_spec_is_registered() -> None:
    """The spec is registered and declares its output file and ``--lang`` option."""
    assert registry.get_scraper("lds-living-christ") is lc.SPEC
    assert lc.SPEC.outputs == ("the_living_christ.xml",)
    parser = argparse.ArgumentParser()
    lc.SPEC.add_arguments(parser)
    assert parser.parse_args([]).lang == "eng"


@pytest.mark.asyncio
async def test_signature_block_renders_after_the_verses(
    site: FakeSite, make_client, tmp_path
) -> None:
    """On the generated reading page the byline precedes verse 1 and the signature block follows the last verse."""
    from open_canon_site.generator import generate_site

    site.pages[lc.LIVING_CHRIST.uri] = _PAGE
    async with make_client(site) as client:
        (path,) = await lc.write_living_christ("eng", tmp_path / "osis", client)
    generate_site([path], tmp_path / "site")
    html = (tmp_path / "site" / "livingchrist" / "livingchrist" / "livingchrist-1.html").read_text(
        "utf-8"
    )
    byline = html.index("The Church of Jesus Christ of Latter-day Saints</p>")
    first_verse = html.index('id="v-LivingChrist.1.1"')
    last_verse = html.index('id="v-LivingChrist.1.2"')
    signature = html.index("The Quorum of the Twelve")
    assert byline < first_verse < last_verse < signature
