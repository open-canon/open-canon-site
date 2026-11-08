"""Tests for ``open_canon_site.scrapers.ebible.kjv_apocrypha`` (offline, synthetic VPL data)."""

from __future__ import annotations

import argparse
import io
import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import httpx
import pyosis
import pytest
from hypothesis import given
from hypothesis import strategies as st
from open_canon_site.scrapers import registry
from open_canon_site.scrapers.ebible import kjv_apocrypha as mod

VPL = b"""<?xml version="1.0" encoding="UTF-8"?>
<vpl>
  <v b="GEN" c="1" v="1">Not apocrypha.</v>
  <v b="TOB" c="1" v="2">Second verse.</v>
  <v b="TOB" c="1" v="1">  First verse.  </v>
  <v b="TOB" c="2" v="1">Chapter two.</v>
  <v b="TOB" c="10" v="1">Chapter ten.</v>
  <v b="BEL" c="1" v="1">Bel verse.</v>
  <v b="SUS" c="1" v="1"/>
</vpl>
"""


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    """Build an in-memory zip archive from a name-to-bytes mapping."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _chapters(book: pyosis.DivCt) -> list[pyosis.ChapterCt]:
    """Return the chapter children of a book div."""
    return [c for c in book.content if isinstance(c, pyosis.ChapterCt)]


def _mock_get(monkeypatch, handler):
    """Route ``httpx.get`` in the module under test through a ``MockTransport``."""
    calls = []

    def fake_get(url, **kwargs):
        """Perform the request against the mock transport, recording kwargs."""
        calls.append((url, kwargs))
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            return client.get(url, follow_redirects=kwargs.get("follow_redirects", False))

    monkeypatch.setattr(mod.httpx, "get", fake_get)
    return calls


# --- constants -------------------------------------------------------------------------


def test_apocrypha_books_has_fourteen_unique_osis_ids():
    """The mapping lists fourteen books with unique codes and OSIS ids."""
    assert len(mod.APOCRYPHA_BOOKS) == 14
    osis_ids = [osis for _, osis in mod.APOCRYPHA_BOOKS.values()]
    assert len(set(osis_ids)) == 14
    assert list(mod.APOCRYPHA_BOOKS)[:2] == ["1ES", "2ES"]


# --- download_xml ----------------------------------------------------------------------


def test_download_xml_extracts_member_and_follows_redirects(monkeypatch):
    """The zip member's bytes are returned from the expected URL with redirects enabled."""
    archive = _zip_bytes({mod.XML_FILENAME: VPL, "other.txt": b"x"})
    calls = _mock_get(monkeypatch, lambda request: httpx.Response(200, content=archive))
    assert mod.download_xml() == VPL
    assert calls == [(mod.DOWNLOAD_URL, {"follow_redirects": True})]


def test_download_xml_http_error_propagates(monkeypatch):
    """An error status raises ``HTTPStatusError`` before any unzipping."""
    _mock_get(monkeypatch, lambda request: httpx.Response(404))
    with pytest.raises(httpx.HTTPStatusError):
        mod.download_xml()


def test_download_xml_missing_member_raises_keyerror(monkeypatch):
    """An archive lacking the expected member raises ``KeyError``."""
    archive = _zip_bytes({"other.xml": b"<a/>"})
    _mock_get(monkeypatch, lambda request: httpx.Response(200, content=archive))
    with pytest.raises(KeyError):
        mod.download_xml()


def test_download_xml_bad_zip_raises(monkeypatch):
    """A non-zip body raises ``zipfile.BadZipFile``."""
    _mock_get(monkeypatch, lambda request: httpx.Response(200, content=b"not a zip"))
    with pytest.raises(zipfile.BadZipFile):
        mod.download_xml()


# --- parse_books -----------------------------------------------------------------------


def test_parse_books_filters_sorts_and_strips():
    """Non-apocrypha books are skipped; chapters/verses sort numerically; text is stripped."""
    books = mod.parse_books(VPL)
    assert "GEN" not in books
    tobit = books["TOB"]
    assert tobit.osis_id == ["Tob"] and tobit.type_value == pyosis.OsisDivs.BOOK
    chapters = _chapters(tobit)
    assert [c.osis_id for c in chapters] == [["Tob.1"], ["Tob.2"], ["Tob.10"]]
    assert [v.osis_id for v in chapters[0].content] == [["Tob.1.1"], ["Tob.1.2"]]
    assert chapters[0].content[0].content == ["First verse."]


def test_parse_books_output_follows_canonical_order():
    """Result keys follow ``APOCRYPHA_BOOKS`` order regardless of document order."""
    assert list(mod.parse_books(VPL)) == ["TOB", "SUS", "BEL"]


def test_parse_books_first_child_is_head_with_display_name():
    """Each book div starts with a ``head`` holding the display name."""
    head = mod.parse_books(VPL)["BEL"].content[0]
    assert isinstance(head, pyosis.HeadCt) and head.content == ["Bel and the Dragon"]


def test_parse_books_empty_verse_text_becomes_empty_string():
    """A self-closing verse element yields empty text rather than ``None``."""
    verse = _chapters(mod.parse_books(VPL)["SUS"])[0].content[0]
    assert verse.content == [""]


def test_parse_books_warns_and_omits_missing_books(caplog):
    """Books with no verses are omitted and one warning is logged per missing book."""
    with caplog.at_level(logging.WARNING, logger=mod.logger.name):
        books = mod.parse_books(b"<vpl><v b='BEL' c='1' v='1'>x</v></vpl>")
    assert list(books) == ["BEL"]
    assert sum("No verses found" in r.message for r in caplog.records) == 13


def test_parse_books_empty_document_gives_no_books():
    """A document without matching verses yields an empty mapping."""
    assert mod.parse_books(b"<vpl/>") == {}


def test_parse_books_malformed_xml_raises():
    """Malformed XML propagates ``ElementTree.ParseError``."""
    with pytest.raises(ET.ParseError):
        mod.parse_books(b"<vpl><v")


def test_parse_books_non_integer_chapter_raises():
    """A non-numeric chapter attribute raises ``ValueError``."""
    with pytest.raises(ValueError):
        mod.parse_books(b"<vpl><v b='TOB' c='x' v='1'>t</v></vpl>")


def test_parse_books_missing_attribute_raises():
    """A matching element without chapter/verse attributes raises ``TypeError``."""
    with pytest.raises(TypeError):
        mod.parse_books(b"<vpl><v b='TOB' v='1'>t</v></vpl>")


_TEXT = st.text(alphabet=st.characters(whitelist_categories=("L", "N", "Zs")), max_size=20)
_STRUCTURE = st.dictionaries(
    st.sampled_from(list(mod.APOCRYPHA_BOOKS)),
    st.dictionaries(
        st.integers(1, 150),
        st.dictionaries(st.integers(1, 176), _TEXT, min_size=1, max_size=6),
        min_size=1,
        max_size=4,
    ),
    min_size=1,
)


@given(structure=_STRUCTURE, data=st.data())
def test_parse_books_every_verse_appears_exactly_once(structure, data):
    """Any shuffled synthetic verse set round-trips: each verse once, right id and text."""
    entries = [
        (code, c, v, text)
        for code, chapters in structure.items()
        for c, verses in chapters.items()
        for v, text in verses.items()
    ]
    entries = data.draw(st.permutations(entries))
    root = ET.Element("vpl")
    for code, c, v, text in entries:
        ET.SubElement(root, "v", b=code, c=str(c), v=str(v)).text = text
    books = mod.parse_books(ET.tostring(root))

    seen = {}
    for code, book in books.items():
        osis = mod.APOCRYPHA_BOOKS[code][1]
        for chapter in _chapters(book):
            for verse in chapter.content:
                assert verse.osis_id[0] not in seen
                seen[verse.osis_id[0]] = verse.content[0]
        assert osis == book.osis_id[0]
    expected = {
        f"{mod.APOCRYPHA_BOOKS[code][1]}.{c}.{v}": text.strip() for code, c, v, text in entries
    }
    assert seen == expected
    assert list(books) == [c for c in mod.APOCRYPHA_BOOKS if c in structure]


# --- books_to_osis_xml -----------------------------------------------------------------


def test_books_to_osis_xml_contains_header_and_books():
    """The document carries the work metadata, revision note, date and book divs."""
    books = list(mod.parse_books(VPL).values())
    xml = mod.books_to_osis_xml(books).to_xml()
    assert "kjv-apocrypha" in xml
    assert "King James Version--Apocrypha" in xml
    assert "open-canon-site scrapers" in xml
    assert re.search(r"\d{4}\.\d{2}\.\d{2}T\d{2}:\d{2}:\d{2}", xml)
    assert "Tob.1.1" in xml and "Bel.1.1" in xml
    assert mod.books_to_osis_xml(books).osis.osis_text.div == books


def test_books_to_osis_xml_empty_list_is_valid():
    """No books still produces a serialisable document."""
    assert "kjv-apocrypha" in mod.books_to_osis_xml([]).to_xml()


# --- book_file_name --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("1 Esdras", "1_Esdras.xml"),
        ("Tobit", "Tobit.xml"),
        ("Ecclesiasticus (Wisdom of Sirach)", "Ecclesiasticus_(Wisdom_of_Sirach).xml"),
        ("Bel  and\tthe Dragon", "Bel_and_the_Dragon.xml"),
    ],
)
def test_book_file_name_joins_words_with_underscores(name, expected):
    """Whitespace runs become single underscores and ``.xml`` is appended."""
    assert mod.book_file_name(name) == expected


@given(st.lists(st.text(alphabet="abcXYZ019", min_size=1), min_size=1, max_size=5))
def test_book_file_name_has_no_whitespace_and_keeps_words(words):
    """The result never contains whitespace and splits back into the original words."""
    name = mod.book_file_name(" ".join(words))
    assert not re.search(r"\s", name)
    assert name[: -len(".xml")].split("_") == words


# --- add_arguments ---------------------------------------------------------------------


def test_add_arguments_per_book_flag_defaults_false():
    """``--per-book`` is a store-true flag, off by default."""
    parser = argparse.ArgumentParser()
    mod.add_arguments(parser)
    assert parser.parse_args([]).per_book is False
    assert parser.parse_args(["--per-book"]).per_book is True


# --- run -------------------------------------------------------------------------------


@pytest.fixture
def fake_download(monkeypatch):
    """Replace ``download_xml`` with one returning the synthetic VPL document."""
    monkeypatch.setattr(mod, "download_xml", lambda: VPL)


def _args(tmp_path: Path, **extra) -> argparse.Namespace:
    """Build CLI-style arguments writing into ``tmp_path``."""
    return argparse.Namespace(output_dir=tmp_path, cache_dir=None, delay=0.0, **extra)


def test_run_default_writes_only_combined(tmp_path, fake_download):
    """Without ``--per-book`` only the combined file is written."""
    paths = mod.run(_args(tmp_path, per_book=False))
    assert paths == [tmp_path / "kjv_apocrypha.xml"]
    assert [p.name for p in tmp_path.iterdir()] == ["kjv_apocrypha.xml"]
    text = paths[0].read_text()
    assert "Tob.1.1" in text and "Bel.1.1" in text and "Sus.1.1" in text
    assert "Gen" not in text


def test_run_per_book_writes_each_book_then_combined(tmp_path, fake_download):
    """``per_book`` writes canonical-order per-book files followed by the combined one."""
    paths = mod.run(_args(tmp_path, per_book=True))
    assert [p.name for p in paths] == [
        "Tobit.xml",
        "Susanna.xml",
        "Bel_and_the_Dragon.xml",
        "kjv_apocrypha.xml",
    ]
    assert all(p.exists() for p in paths)
    assert "Bel.1.1" not in paths[0].read_text()


def test_run_without_per_book_attribute_defaults_to_combined_only(tmp_path, fake_download):
    """Arguments lacking ``per_book`` entirely behave as if it were false."""
    assert [p.name for p in mod.run(_args(tmp_path))] == ["kjv_apocrypha.xml"]


def test_run_creates_missing_output_dir(tmp_path, fake_download):
    """A nested, nonexistent output directory is created, and a string path is accepted."""
    target = tmp_path / "a" / "b"
    args = argparse.Namespace(output_dir=str(target), per_book=False)
    assert mod.run(args) == [target / "kjv_apocrypha.xml"]


# --- SPEC ------------------------------------------------------------------------------


def test_spec_is_registered_with_expected_metadata():
    """``SPEC`` is the registry's ``kjv-apocrypha`` entry wired to this module's functions."""
    assert registry.get_scraper("kjv-apocrypha") is mod.SPEC
    assert mod.SPEC.outputs == ("kjv_apocrypha.xml",)
    assert mod.SPEC.source == mod.DOWNLOAD_URL
    assert mod.SPEC.run is mod.run
    assert mod.SPEC.add_arguments is mod.add_arguments
