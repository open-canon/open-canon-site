from __future__ import annotations

from pathlib import Path

import pytest

from open_canon_site.scrapers._http import CachedHttpFetcher


def _fetcher(tmp_path):
    return CachedHttpFetcher(cache_dir=tmp_path, delay=0)


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://sacred-texts.com/bib/boe/boe001.htm", "sacred-texts.com/bib/boe/boe001.htm"),
        ("https://example.org/a/b.html", "example.org/a/b.htm"),
        ("https://example.org/a/", "example.org/a/index.htm"),
        ("https://example.org", "example.org/index.htm"),
        ("https://example.org/x.xml?q=1", "example.org/x.xml"),
    ],
)
def test_cache_path_layout(tmp_path, url, expected):
    fetcher = _fetcher(tmp_path)
    assert fetcher.cache_path_for(url) == tmp_path / expected
    fetcher.close()


def test_cache_path_none_without_cache_dir():
    fetcher = CachedHttpFetcher(cache_dir=None)
    assert fetcher.cache_path_for("https://example.org/a") is None
    fetcher.close()


def test_cache_path_requires_host(tmp_path):
    fetcher = _fetcher(tmp_path)
    with pytest.raises(ValueError):
        fetcher.cache_path_for("/no/host.htm")
    fetcher.close()


def test_fetch_text_reads_cache_without_network(tmp_path):
    fetcher = _fetcher(tmp_path)
    cached = Path(tmp_path / "example.org" / "page.htm")
    cached.parent.mkdir(parents=True)
    cached.write_text("hello", encoding="utf-8")
    assert fetcher.fetch_text(url="https://example.org/page.html") == "hello"
    fetcher.close()
