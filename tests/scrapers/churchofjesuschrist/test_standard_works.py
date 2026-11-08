"""Tests for the ``lds-standard-works`` orchestration, argument parsing and CLI registration."""

from __future__ import annotations

import argparse
import asyncio
import itertools
import pathlib
import tempfile
from typing import Any
from unittest import mock

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st
from lds_fake_site import FakeSite
from open_canon_site.scrapers import cli, registry
from open_canon_site.scrapers.churchofjesuschrist import standard_works
from open_canon_site.scrapers.churchofjesuschrist.standard_works import (
    SPEC,
    WORK_NAMES,
    AvailableStandardWorks,
    add_arguments,
    build_standard_works,
    gather_dict,
    parse_works,
)

_BUILDER_ATTRS = {
    AvailableStandardWorks.BOOK_OF_MORMON: ("book_of_mormon", "build_book_of_mormon"),
    AvailableStandardWorks.DOCTRINE_AND_COVENANTS: (
        "doctrine_and_covenants",
        "build_doctrine_and_covenants",
    ),
    AvailableStandardWorks.NEW_TESTAMENT: ("new_testament", "build_new_testament"),
    AvailableStandardWorks.OLD_TESTAMENT: ("old_testament", "build_old_testament"),
    AvailableStandardWorks.PEARL_OF_GREAT_PRICE: (
        "pearl_of_great_price",
        "build_pearl_of_great_price",
    ),
}
_FILE_NAMES = {
    AvailableStandardWorks.BOOK_OF_MORMON: "book_of_mormon.xml",
    AvailableStandardWorks.DOCTRINE_AND_COVENANTS: "doctrine_and_covenants.xml",
    AvailableStandardWorks.NEW_TESTAMENT: "new_testament.xml",
    AvailableStandardWorks.OLD_TESTAMENT: "old_testament.xml",
    AvailableStandardWorks.PEARL_OF_GREAT_PRICE: "pearl_of_great_price.xml",
}


class _FakeOsis:
    """Stand-in for ``OsisXML`` whose ``to_xml`` returns a recognisable string."""

    def __init__(self, name: str) -> None:
        """Remember the work name used to build the XML text."""
        self.name = name

    def to_xml(self) -> str:
        """Return placeholder XML naming the work."""
        return f"<osis work='{self.name}'/>"


def _patch_builders(calls: list[tuple[str, str]]) -> list[Any]:
    """Patch every standard-works builder with a fake that records ``(work, lang)`` calls."""
    patches = []
    for flag, (module, attr) in _BUILDER_ATTRS.items():

        async def fake(lang: str, client: httpx.AsyncClient, _flag: Any = flag) -> _FakeOsis:
            """Record the call and return a fake OSIS document."""
            calls.append((_FILE_NAMES[_flag], lang))
            await asyncio.sleep(0)
            return _FakeOsis(_FILE_NAMES[_flag])

        target = getattr(standard_works.open_canon_site.scrapers.churchofjesuschrist, module)
        patches.append(mock.patch.object(target, attr, fake))
    return patches


def test_spec_registered() -> None:
    """The scraper is registered under ``lds-standard-works`` with its five output files."""
    assert registry.get_scraper("lds-standard-works") is SPEC
    assert len(SPEC.outputs) == 5


def test_available_standard_works_all_is_union_of_members() -> None:
    """ALL equals the union of the five individual works, whose bit values are distinct."""
    singles = [m for m in AvailableStandardWorks if m is not AvailableStandardWorks.ALL]
    assert len(singles) == 5
    union = AvailableStandardWorks(0)
    for member in singles:
        assert not union & member
        union |= member
    assert union == AvailableStandardWorks.ALL


def test_work_names_cover_every_member() -> None:
    """WORK_NAMES maps a kebab-case name to every individual work."""
    assert set(WORK_NAMES.values()) == {
        m for m in AvailableStandardWorks if m is not AvailableStandardWorks.ALL
    }
    for name, flag in WORK_NAMES.items():
        assert name == flag.name.lower().replace("_", "-")


@pytest.mark.asyncio
async def test_gather_dict_awaits_values_and_keeps_keys() -> None:
    """gather_dict returns a dict with the same keys (in order) and the awaited values."""

    async def value(n: int) -> int:
        """Return ``n`` after yielding to the loop."""
        await asyncio.sleep(0)
        return n * 2

    result = await gather_dict({"a": value(1), "b": value(2), "c": value(3)})
    assert result == {"a": 2, "b": 4, "c": 6}
    assert list(result) == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_gather_dict_empty() -> None:
    """gather_dict of an empty dict is an empty dict."""
    assert await gather_dict({}) == {}


@pytest.mark.asyncio
async def test_gather_dict_runs_concurrently() -> None:
    """Awaitables run concurrently: a later one can unblock an earlier one."""
    gate = asyncio.Event()

    async def waiter() -> str:
        """Wait for the gate."""
        await gate.wait()
        return "waited"

    async def opener() -> str:
        """Open the gate."""
        gate.set()
        return "opened"

    result = await asyncio.wait_for(gather_dict({"w": waiter(), "o": opener()}), timeout=2)
    assert result == {"w": "waited", "o": "opened"}


@pytest.mark.asyncio
async def test_gather_dict_propagates_exceptions() -> None:
    """An exception raised by an awaitable propagates to the caller."""

    async def boom() -> int:
        """Raise an error."""
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await gather_dict({"x": boom()})


@pytest.mark.asyncio
async def test_build_standard_works_writes_selected_works(tmp_path: pathlib.Path) -> None:
    """Only the requested works are built; each is written to its own file under root_dir."""
    calls: list[tuple[str, str]] = []
    out = tmp_path / "nested" / "out"
    patches = _patch_builders(calls)
    for p in patches:
        p.start()
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(FakeSite())) as client:
            paths = await build_standard_works(
                lang="spa",
                standard_works_to_build=AvailableStandardWorks.NEW_TESTAMENT
                | AvailableStandardWorks.BOOK_OF_MORMON,
                root_dir=str(out),
                client=client,
            )
            assert not client.is_closed
    finally:
        for p in patches:
            p.stop()
    assert paths == [out / "book_of_mormon.xml", out / "new_testament.xml"]
    assert sorted(calls) == [("book_of_mormon.xml", "spa"), ("new_testament.xml", "spa")]
    assert (out / "new_testament.xml").read_text("utf-8") == "<osis work='new_testament.xml'/>"


@pytest.mark.asyncio
async def test_build_standard_works_closes_client_it_created(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When no client is given, one is created with a 60 s timeout and closed afterwards."""
    created: list[httpx.AsyncClient] = []
    real = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        """Build a mock-transport client and remember it and its timeout."""
        client = real(transport=httpx.MockTransport(FakeSite()))
        client.extra_timeout = kwargs["timeout"]  # type: ignore[attr-defined]
        created.append(client)
        return client

    monkeypatch.setattr(standard_works.httpx, "AsyncClient", factory)
    patches = _patch_builders([])
    for p in patches:
        p.start()
    try:
        paths = await build_standard_works(
            standard_works_to_build=AvailableStandardWorks.OLD_TESTAMENT, root_dir=tmp_path
        )
    finally:
        for p in patches:
            p.stop()
    assert [p.name for p in paths] == ["old_testament.xml"]
    (client,) = created
    assert client.is_closed
    assert client.extra_timeout.read == 60.0  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_build_standard_works_closes_created_client_on_error(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A builder failure still closes the client the function created and writes nothing."""
    real = httpx.AsyncClient
    created: list[httpx.AsyncClient] = []

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        """Build a mock-transport client and remember it."""
        created.append(real(transport=httpx.MockTransport(FakeSite())))
        return created[-1]

    async def failing(lang: str, client: httpx.AsyncClient) -> None:
        """Always fail."""
        raise RuntimeError("scrape failed")

    monkeypatch.setattr(standard_works.httpx, "AsyncClient", factory)
    monkeypatch.setattr(
        standard_works.open_canon_site.scrapers.churchofjesuschrist.pearl_of_great_price,
        "build_pearl_of_great_price",
        failing,
    )
    with pytest.raises(RuntimeError, match="scrape failed"):
        await build_standard_works(
            standard_works_to_build=AvailableStandardWorks.PEARL_OF_GREAT_PRICE, root_dir=tmp_path
        )
    assert created[0].is_closed
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_build_standard_works_end_to_end_against_mock_site(tmp_path: pathlib.Path) -> None:
    """Building the New Testament through the mocked site writes a parseable OSIS file."""
    site = FakeSite()
    async with httpx.AsyncClient(transport=httpx.MockTransport(site)) as client:
        paths = await build_standard_works(
            standard_works_to_build=AvailableStandardWorks.NEW_TESTAMENT,
            root_dir=tmp_path,
            client=client,
        )
    (path,) = paths
    assert path == tmp_path / "new_testament.xml"
    assert 'osisIDWork="nt"' in path.read_text("utf-8")


@given(st.sets(st.sampled_from(sorted(_FILE_NAMES, key=lambda f: f.value)), min_size=1))
def test_build_standard_works_builds_exactly_the_selected_flags(
    selected: set[AvailableStandardWorks],
) -> None:
    """For any non-empty subset of works, exactly those files are built and returned in canonical order."""
    calls: list[tuple[str, str]] = []
    flag = AvailableStandardWorks(0)
    for member in selected:
        flag |= member
    patches = _patch_builders(calls)
    with tempfile.TemporaryDirectory() as tmp:
        for p in patches:
            p.start()
        try:
            paths = asyncio.run(
                build_standard_works(
                    standard_works_to_build=flag,
                    root_dir=tmp,
                    client=httpx.AsyncClient(transport=httpx.MockTransport(FakeSite())),
                )
            )
        finally:
            for p in patches:
                p.stop()
        expected = sorted(_FILE_NAMES[m] for m in selected)
        assert sorted(p.name for p in paths) == expected
        assert sorted(name for name, _ in calls) == expected
        assert all(p.exists() for p in paths)


def test_parse_works_subset() -> None:
    """parse_works accepts names separated by commas and spaces."""
    works = parse_works("book-of-mormon, new-testament")
    assert works == AvailableStandardWorks.BOOK_OF_MORMON | AvailableStandardWorks.NEW_TESTAMENT


def test_parse_works_unknown_name() -> None:
    """parse_works rejects an unknown name, quoting it and listing the choices."""
    with pytest.raises(argparse.ArgumentTypeError, match="unknown work 'quran'") as info:
        parse_works("book-of-mormon,quran")
    assert "book-of-mormon" in str(info.value)


@pytest.mark.parametrize("value", ["", " ", ",", " , ,"])
def test_parse_works_empty_raises(value: str) -> None:
    """parse_works rejects input with no names at all."""
    with pytest.raises(argparse.ArgumentTypeError, match="no works given"):
        parse_works(value)


def test_parse_works_ignores_empty_items_and_duplicates() -> None:
    """Trailing commas and repeated names do not change the result."""
    assert parse_works("old-testament,,old-testament,") == AvailableStandardWorks.OLD_TESTAMENT


@given(st.lists(st.sampled_from(sorted(WORK_NAMES)), min_size=1, max_size=12))
def test_parse_works_roundtrips_any_selection(names: list[str]) -> None:
    """For any ordering/repetition of names, the parsed flag is exactly the union of the named works."""
    expected = AvailableStandardWorks(0)
    for name in names:
        expected |= WORK_NAMES[name]
    assert parse_works(",".join(names)) == expected
    assert parse_works(" , ".join(names)) == expected


@given(st.permutations(sorted(WORK_NAMES)))
def test_parse_works_all_names_in_any_order_is_all(order: list[str]) -> None:
    """Naming every work in any order yields ``ALL``."""
    assert parse_works(",".join(order)) == AvailableStandardWorks.ALL


def test_parse_works_each_single_name() -> None:
    """Each individual name maps to just its own flag."""
    for name, flag in WORK_NAMES.items():
        assert parse_works(name) == flag
    assert len(list(itertools.chain(WORK_NAMES))) == 5


def test_add_arguments_defines_works_and_lang() -> None:
    """add_arguments adds ``--works`` (default ALL, parsed by parse_works) and ``--lang`` (default eng)."""
    parser = argparse.ArgumentParser()
    add_arguments(parser)
    defaults = parser.parse_args([])
    assert defaults.works == AvailableStandardWorks.ALL and defaults.lang == "eng"
    args = parser.parse_args(["--works", "pearl-of-great-price", "--lang", "fra"])
    assert args.works == AvailableStandardWorks.PEARL_OF_GREAT_PRICE and args.lang == "fra"


def test_cli_defaults_and_bad_works(capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI subcommand defaults to all works and reports a bad ``--works`` value."""
    args = cli.build_parser().parse_args(["lds-standard-works"])
    assert args.works == AvailableStandardWorks.ALL
    assert args.lang == "eng"
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["lds-standard-works", "--works", "nope"])
    assert "unknown work 'nope'" in capsys.readouterr().err


def test_run_passes_options(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    """SPEC.run forwards lang, works and output dir to build_standard_works and returns its paths."""
    seen: dict[str, Any] = {}

    async def fake_build(**kwargs: Any) -> list[pathlib.Path]:
        """Record keyword arguments and return one path."""
        seen.update(kwargs)
        return [tmp_path / "book_of_mormon.xml"]

    monkeypatch.setattr(
        "open_canon_site.scrapers.churchofjesuschrist.standard_works.build_standard_works",
        fake_build,
    )
    args = cli.build_parser().parse_args([
        "lds-standard-works",
        "--works",
        "book-of-mormon",
        "--lang",
        "spa",
        "-o",
        str(tmp_path),
    ])
    assert SPEC.run(args) == [tmp_path / "book_of_mormon.xml"]
    assert seen == {
        "lang": "spa",
        "standard_works_to_build": AvailableStandardWorks.BOOK_OF_MORMON,
        "root_dir": tmp_path,
    }


def test_run_function_is_spec_entry_point() -> None:
    """SPEC wires add_arguments and run and advertises the source site."""
    assert SPEC.run is standard_works.run
    assert SPEC.add_arguments is add_arguments
    assert "churchofjesuschrist.org" in SPEC.source


@pytest.mark.network
@pytest.mark.asyncio
async def test_standard_works(tmp_path: pathlib.Path) -> None:
    """Test that building the standard works does not raise any errors."""
    paths = await standard_works.build_standard_works(root_dir=tmp_path)
    assert {p.name for p in paths} == set(SPEC.outputs)
