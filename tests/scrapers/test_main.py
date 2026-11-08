"""Tests for the ``python -m open_canon_site.scrapers`` entry points."""

from __future__ import annotations

import runpy
import sys
import warnings

import pytest


def _run_as_main(module, monkeypatch, argv):
    """Execute ``module`` as ``__main__`` with ``argv`` and return the ``SystemExit`` code."""
    monkeypatch.setattr(sys, "argv", ["open-canon-scrape", *argv])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # module already imported
        with pytest.raises(SystemExit) as exc:
            runpy.run_module(module, run_name="__main__")
    return exc.value.code


def test_main_module_exits_with_cli_return_code(monkeypatch, capsys):
    """``python -m open_canon_site.scrapers list`` prints the listing and exits 0."""
    code = _run_as_main("open_canon_site.scrapers", monkeypatch, ["list"])
    assert code == 0
    assert capsys.readouterr().out.strip()


def test_main_module_propagates_argparse_errors(monkeypatch, capsys):
    """A bad subcommand makes the module exit through argparse with a non-zero code."""
    code = _run_as_main("open_canon_site.scrapers", monkeypatch, ["definitely-not-a-command"])
    assert code != 0
    assert "invalid choice" in capsys.readouterr().err


def test_cli_module_main_guard_exits_with_return_code(monkeypatch, capsys):
    """Running ``cli`` itself as a script also exits with ``main()``'s return value."""
    assert _run_as_main("open_canon_site.scrapers.cli", monkeypatch, ["list"]) == 0
    assert capsys.readouterr().out.strip()


def test_package_import_has_no_side_effects():
    """Importing the package docstring-only ``__init__`` exposes a docstring and no scrapers."""
    import open_canon_site.scrapers as pkg

    assert pkg.__doc__ and "open-canon-scrape" in pkg.__doc__
