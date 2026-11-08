"""Tests for ``open_canon_site.scrapers.registry``."""

from __future__ import annotations

import pytest
from open_canon_site.scrapers import registry
from open_canon_site.scrapers.base import ScraperSpec


def _spec(name):
    """Build a minimal spec called ``name``."""
    return ScraperSpec(name=name, help="h", source="s", outputs=(), run=lambda args: [])


def test_scrapers_is_a_tuple_of_specs():
    """The registry exposes an ordered tuple containing only ``ScraperSpec`` objects."""
    assert isinstance(registry.SCRAPERS, tuple)
    assert all(isinstance(spec, ScraperSpec) for spec in registry.SCRAPERS)


def test_get_scraper_returns_matching_spec(monkeypatch):
    """``get_scraper`` returns the spec whose name matches exactly."""
    a, b = _spec("a"), _spec("b")
    monkeypatch.setattr(registry, "SCRAPERS", (a, b))
    assert registry.get_scraper("b") is b


def test_get_scraper_unknown_lists_available_names(monkeypatch):
    """An unknown name raises ``KeyError`` listing the registered names."""
    monkeypatch.setattr(registry, "SCRAPERS", (_spec("a"), _spec("b")))
    with pytest.raises(KeyError, match="Unknown scraper 'zzz'.*a, b"):
        registry.get_scraper("zzz")


def test_get_scraper_empty_registry_says_none_registered(monkeypatch):
    """With nothing registered the error message says so."""
    monkeypatch.setattr(registry, "SCRAPERS", ())
    with pytest.raises(KeyError, match=r"\(none registered\)"):
        registry.get_scraper("a")


def test_get_scraper_is_case_sensitive(monkeypatch):
    """Names are matched exactly, so a different case is not found."""
    monkeypatch.setattr(registry, "SCRAPERS", (_spec("a"),))
    with pytest.raises(KeyError):
        registry.get_scraper("A")
