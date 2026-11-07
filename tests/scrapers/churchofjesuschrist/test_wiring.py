"""Offline tests for the lds-standard-works CLI wiring."""

import argparse

import pytest

from open_canon_site.scrapers import cli, registry
from open_canon_site.scrapers.churchofjesuschrist.standard_works import (
    SPEC,
    AvailableStandardWorks,
    parse_works,
)


def test_spec_registered() -> None:
    assert registry.get_scraper("lds-standard-works") is SPEC
    assert len(SPEC.outputs) == 5


def test_parse_works_subset() -> None:
    works = parse_works("book-of-mormon, new-testament")
    assert works == AvailableStandardWorks.BOOK_OF_MORMON | AvailableStandardWorks.NEW_TESTAMENT


def test_parse_works_unknown_name() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="unknown work 'quran'"):
        parse_works("book-of-mormon,quran")


def test_cli_defaults_and_bad_works(capsys) -> None:
    args = cli.build_parser().parse_args(["lds-standard-works"])
    assert args.works == AvailableStandardWorks.ALL
    assert args.lang == "eng"
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["lds-standard-works", "--works", "nope"])
    assert "unknown work 'nope'" in capsys.readouterr().err


def test_run_passes_options(monkeypatch, tmp_path) -> None:
    seen = {}

    async def fake_build(**kwargs):
        seen.update(kwargs)
        return [tmp_path / "book_of_mormon.xml"]

    monkeypatch.setattr(
        "open_canon_site.scrapers.churchofjesuschrist.standard_works.build_standard_works",
        fake_build,
    )
    args = cli.build_parser().parse_args(
        ["lds-standard-works", "--works", "book-of-mormon", "--lang", "spa", "-o", str(tmp_path)]
    )
    assert SPEC.run(args) == [tmp_path / "book_of_mormon.xml"]
    assert seen == {
        "lang": "spa",
        "standard_works_to_build": AvailableStandardWorks.BOOK_OF_MORMON,
        "root_dir": tmp_path,
    }
