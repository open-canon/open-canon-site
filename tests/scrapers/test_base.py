"""Tests for ``open_canon_site.scrapers.base``."""

from __future__ import annotations

import argparse
import dataclasses

import pytest
from open_canon_site.scrapers import base
from open_canon_site.scrapers.base import ScraperSpec


def _run(args):
    """Return no paths; stand-in for ``ScraperSpec.run``."""
    return []


def test_no_arguments_adds_no_options():
    """``_no_arguments`` leaves the parser without any option besides help."""
    parser = argparse.ArgumentParser(add_help=False)
    assert base._no_arguments(parser) is None
    assert parser.parse_args([]) == argparse.Namespace()
    with pytest.raises(SystemExit):
        parser.parse_args(["--anything"])


def test_scraperspec_defaults_add_arguments_to_no_arguments():
    """A spec built without ``add_arguments`` uses the no-op default."""
    spec = ScraperSpec(name="n", help="h", source="s", outputs=("a.xml",), run=_run)
    assert spec.add_arguments is base._no_arguments


def test_scraperspec_is_frozen():
    """Assigning to a field of a constructed spec raises ``FrozenInstanceError``."""
    spec = ScraperSpec(name="n", help="h", source="s", outputs=(), run=_run)
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.name = "other"


def test_scraperspec_keeps_custom_add_arguments():
    """A supplied ``add_arguments`` callable is stored and invoked on a parser."""

    def add(parser):
        """Add a ``--x`` flag."""
        parser.add_argument("--x", default="1")

    spec = ScraperSpec(name="n", help="h", source="s", outputs=(), run=_run, add_arguments=add)
    parser = argparse.ArgumentParser()
    spec.add_arguments(parser)
    assert parser.parse_args(["--x", "2"]).x == "2"
