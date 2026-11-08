"""Unit tests for ``churchofjesuschrist.proclamations`` against a tiny mocked Study API."""

from __future__ import annotations

import argparse

import pyosis.generated as osis
import pytest
from lds_fake_site import FakeSite, study_payload
from open_canon_site.scrapers import registry
from open_canon_site.scrapers.churchofjesuschrist import models as church_models
from open_canon_site.scrapers.churchofjesuschrist import proclamations as proc

_FULL_PAGE = (
    '<header><h1 id="title1">The Family</h1><p class="subtitle">A Proclamation</p>'
    '<div class="byline"><p class="author-name">The First Presidency</p></div></header>'
    '<div class="body-block"><p id="p1">First <a class="scripture-ref" '
    'href="/study/scriptures/ot/ps/127?lang=eng">Psalm 127:3</a>.</p>'
    '<p id="p2"><em>Second</em></p>'
    '<div class="event"><p id="p3">Read in 1995.</p></div></div>'
)


def _content(body: str) -> church_models.ScriptureStudyContent:
    """Wrap an HTML body in a parsed Study API payload."""
    return church_models.ScriptureStudyContent(**study_payload("/x", body))


def test_build_proclamation_structure() -> None:
    """Titles, byline, paragraph verses and the colophon are produced in order."""
    div = proc.build_proclamation(proc.PROCLAMATIONS[1], _content(_FULL_PAGE))
    assert div.osis_id == ["Proc1995"] and div.type_value == osis.OsisDivs.BOOK
    main, sub, byline, chapter, colophon = div.content
    assert main.content == ["The Family"] and sub.content == ["A Proclamation"]
    assert byline.type_value == osis.OsisDivs.INTRODUCTION and byline.canonical is False
    assert chapter.osis_id == ["Proc1995.1"]
    assert [v.osis_id for v in chapter.content] == [["Proc1995.1.1"], ["Proc1995.1.2"]]
    assert colophon.type_value == osis.OsisDivs.COLOPHON
    assert colophon.content[0].content == ["Read in 1995."]


def test_build_proclamation_minimal_page() -> None:
    """A page with only a body block yields just the chapter."""
    div = proc.build_proclamation(
        proc.PROCLAMATIONS[0], _content('<div class="body-block"><p>Only</p></div>')
    )
    assert len(div.content) == 1 and isinstance(div.content[0], osis.ChapterCt)


@pytest.mark.parametrize("body", ["<p>none</p>", '<div class="body-block"><div>no p</div></div>'])
def test_build_proclamation_errors(body: str) -> None:
    """A missing body block or a body with no paragraphs raises ValueError."""
    with pytest.raises(ValueError, match="has no"):
        proc.build_proclamation(proc.PROCLAMATIONS[0], _content(body))


@pytest.mark.asyncio
async def test_build_proclamations_fetches_each_uri(site: FakeSite, make_client) -> None:
    """Every proclamation URI is requested and one book division is emitted per page."""
    for p in proc.PROCLAMATIONS:
        site.pages[p.uri] = _FULL_PAGE
    async with make_client(site) as client:
        xml = await proc.build_proclamations("eng", client)
    assert sorted(site.uris()) == sorted(p.uri for p in proc.PROCLAMATIONS)
    divs = xml.osis.osis_text.div
    assert [d.osis_id[0] for d in divs] == ["Proc1980", "Proc1995", "Proc2020"]
    assert "Proc2020.1.2" in xml.to_xml()


@pytest.mark.asyncio
async def test_write_proclamations_writes_file(site: FakeSite, make_client, tmp_path) -> None:
    """The OSIS file lands in the output directory."""
    for p in proc.PROCLAMATIONS:
        site.pages[p.uri] = _FULL_PAGE
    async with make_client(site) as client:
        written = await proc.write_proclamations("eng", tmp_path / "out", client)
    assert written == [tmp_path / "out" / "lds_proclamations.xml"]
    assert "<osisText" in written[0].read_text("utf-8")


def test_spec_is_registered() -> None:
    """The spec is registered and declares its output file and ``--lang`` option."""
    assert registry.get_scraper("lds-proclamations") is proc.SPEC
    assert proc.SPEC.outputs == ("lds_proclamations.xml",)
    parser = argparse.ArgumentParser()
    proc.add_arguments(parser)
    assert parser.parse_args([]).lang == "eng"


def test_build_proclamation_dateline_is_front_matter() -> None:
    """A leading italic-only paragraph becomes an introduction and verses start after it."""
    body = '<div class="body-block"><p><em>From the Presidency, 1980</em></p><p>Text</p></div>'
    div = proc.build_proclamation(proc.PROCLAMATIONS[0], _content(body))
    intro, chapter = div.content
    assert intro.type_value == osis.OsisDivs.INTRODUCTION and intro.canonical is False
    assert [v.osis_id for v in chapter.content] == [["Proc1980.1.1"]]
