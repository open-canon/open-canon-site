from __future__ import annotations

import argparse
import io
import zipfile
from pathlib import Path

import pyosis
import pytest

from open_canon_site.scrapers.ebible import kjv_apocrypha as mod

VPL = b"""<?xml version="1.0" encoding="UTF-8"?>
<vpl>
  <v b="GEN" c="1" v="1">Not apocrypha.</v>
  <v b="TOB" c="1" v="2">Second verse.</v>
  <v b="TOB" c="1" v="1">First verse.</v>
  <v b="TOB" c="2" v="1">Chapter two.</v>
  <v b="BEL" c="1" v="1">Bel verse.</v>
</vpl>
"""


def test_parse_books():
    books = mod.parse_books(VPL)
    assert list(books) == ["TOB", "BEL"]
    tobit = books["TOB"]
    assert tobit.osis_id == ["Tob"]
    chapters = [c for c in tobit.content if isinstance(c, pyosis.ChapterCt)]
    assert [c.osis_id for c in chapters] == [["Tob.1"], ["Tob.2"]]
    assert [v.osis_id for v in chapters[0].content] == [["Tob.1.1"], ["Tob.1.2"]]
    assert chapters[0].content[0].content == ["First verse."]


def _args(tmp_path: Path, per_book: bool) -> argparse.Namespace:
    return argparse.Namespace(output_dir=tmp_path, cache_dir=None, delay=0.0, per_book=per_book)


@pytest.fixture
def fake_download(monkeypatch):
    monkeypatch.setattr(mod, "download_xml", lambda: VPL)


def test_run_default_writes_only_combined(tmp_path, fake_download):
    paths = mod.run(_args(tmp_path, per_book=False))
    assert paths == [tmp_path / "kjv_apocrypha.xml"]
    assert [p.name for p in tmp_path.iterdir()] == ["kjv_apocrypha.xml"]
    text = (tmp_path / "kjv_apocrypha.xml").read_text()
    assert "Tob.1.1" in text and "Bel.1.1" in text
    assert "open-canon-site scrapers" in text


def test_run_per_book(tmp_path, fake_download):
    paths = mod.run(_args(tmp_path, per_book=True))
    names = sorted(p.name for p in paths)
    assert names == ["Bel_and_the_Dragon.xml", "Tobit.xml", "kjv_apocrypha.xml"]
    assert all(p.exists() for p in paths)
    assert paths[-1].name == "kjv_apocrypha.xml"


def test_download_xml_unzips(monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(mod.XML_FILENAME, VPL)

    class Resp:
        content = buf.getvalue()

        def raise_for_status(self):
            pass

    monkeypatch.setattr(mod.httpx, "get", lambda *a, **k: Resp())
    assert mod.download_xml() == VPL


def test_spec_registered():
    from open_canon_site.scrapers import registry

    assert registry.get_scraper("kjv-apocrypha") is mod.SPEC
    assert mod.SPEC.outputs == ("kjv_apocrypha.xml",)


@pytest.mark.network
def test_run_network(tmp_path):
    paths = mod.run(_args(tmp_path, per_book=False))
    assert [p.name for p in paths] == ["kjv_apocrypha.xml"]
    assert "Tob.1.1" in paths[0].read_text()
