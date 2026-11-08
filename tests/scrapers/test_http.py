"""Tests for ``open_canon_site.scrapers._http`` using ``httpx.MockTransport`` (no network)."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest
from open_canon_site.scrapers import _http
from open_canon_site.scrapers._http import CachedHttpFetcher


@pytest.fixture
def sleeps(monkeypatch):
    """Replace ``time.sleep`` in the module under test and return the list of durations."""
    recorded = []
    monkeypatch.setattr(_http.time, "sleep", recorded.append)
    return recorded


def _fetcher(tmp_path, handler=None, **kwargs):
    """Build a fetcher whose client is backed by ``handler`` through a ``MockTransport``."""
    kwargs.setdefault("delay", 0.5)
    fetcher = CachedHttpFetcher(cache_dir=tmp_path / "cache", **kwargs)
    if handler is not None:
        fetcher._client.close()
        fetcher._client = httpx.Client(transport=httpx.MockTransport(handler))
    return fetcher


def _sequence(*outcomes):
    """Return a handler that replays ``outcomes`` (responses or exceptions) and a request log."""
    log = []
    iterator = iter(outcomes)

    def handler(request):
        """Record the request then return or raise the next scripted outcome."""
        log.append(request)
        outcome = next(iterator)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return handler, log


# --- __init__ / close / _build_client --------------------------------------------------


def test_init_defaults_without_cache_dir():
    """With no cache directory caching is off and defaults are applied."""
    fetcher = CachedHttpFetcher()
    assert fetcher.cache_dir is None
    assert fetcher.delay == 1.0 and fetcher.timeout == _http.DEFAULT_TIMEOUT
    assert fetcher.headers == _http.DEFAULT_HEADERS
    assert fetcher.logger is logging.getLogger(_http.__name__)
    fetcher.close()


def test_init_creates_cache_dir_and_accepts_str(tmp_path):
    """A string cache directory becomes a ``Path`` and is created with parents."""
    target = tmp_path / "x" / "y"
    fetcher = CachedHttpFetcher(cache_dir=str(target))
    assert fetcher.cache_dir == target and target.is_dir()
    fetcher.close()


def test_init_merges_custom_headers_without_mutating_defaults():
    """Custom headers override defaults for the instance only."""
    fetcher = CachedHttpFetcher(headers={"User-Agent": "mine", "X-Extra": "1"})
    assert fetcher.headers == {"User-Agent": "mine", "X-Extra": "1"}
    assert _http.DEFAULT_HEADERS["User-Agent"] == _http.DEFAULT_USER_AGENT
    fetcher.close()


def test_init_uses_supplied_logger():
    """A caller-supplied logger replaces the module logger."""
    logger = logging.getLogger("custom")
    fetcher = CachedHttpFetcher(logger=logger)
    assert fetcher.logger is logger
    fetcher.close()


def test_build_client_applies_headers_timeout_and_redirects():
    """The client carries the fetcher's headers and timeout and follows redirects."""
    fetcher = CachedHttpFetcher(timeout=7, headers={"X-A": "b"})
    client = fetcher._build_client()
    assert (
        client.headers["x-a"] == "b"
        and client.headers["user-agent"] == fetcher.headers["User-Agent"]
    )
    assert client.timeout.read == 7
    assert client.follow_redirects is True
    client.close()
    fetcher.close()


def test_close_closes_client():
    """After ``close`` the underlying client refuses further requests."""
    fetcher = CachedHttpFetcher()
    fetcher.close()
    assert fetcher._client.is_closed


# --- cache_path_for / _cache_path ------------------------------------------------------


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://sacred-texts.com/bib/boe/boe001.htm", "sacred-texts.com/bib/boe/boe001.htm"),
        ("https://example.org/a/b.html", "example.org/a/b.htm"),
        ("https://example.org/a/", "example.org/a/index.htm"),
        ("https://example.org", "example.org/index.htm"),
        ("https://example.org/", "example.org/index.htm"),
        ("https://example.org/x.xml?q=1", "example.org/x.xml"),
        ("https://example.org/p.html#frag", "example.org/p.htm"),
        ("https://example.org/a.html.html", "example.org/a.html.htm"),
        ("https://example.org/noext", "example.org/noext"),
        ("http://example.org:8080/a.htm", "example.org:8080/a.htm"),
        ("https://Example.ORG/a", "Example.ORG/a"),
    ],
)
def test_cache_path_for_layout(tmp_path, url, expected):
    """URLs map to ``<cache>/<host>/<path>`` with index/htm normalisation edge cases."""
    fetcher = _fetcher(tmp_path)
    assert fetcher.cache_path_for(url) == tmp_path / "cache" / expected
    fetcher.close()


def test_cache_path_for_none_without_cache_dir():
    """With caching disabled there is no cache path."""
    fetcher = CachedHttpFetcher(cache_dir=None)
    assert fetcher.cache_path_for("https://example.org/a") is None
    fetcher.close()


@pytest.mark.parametrize("url", ["/no/host.htm", "example.org/a", ""])
def test_cache_path_for_requires_host(tmp_path, url):
    """A URL with no network location raises ``ValueError``."""
    fetcher = _fetcher(tmp_path)
    with pytest.raises(ValueError, match="without host"):
        fetcher.cache_path_for(url)
    fetcher.close()


def test_cache_path_matches_public_wrapper(tmp_path):
    """``cache_path_for`` returns exactly what ``_cache_path`` computes."""
    fetcher = _fetcher(tmp_path)
    url = "https://example.org/a/b.html"
    assert fetcher.cache_path_for(url) == fetcher._cache_path(url)
    fetcher.close()


def test_cache_path_does_not_hit_network_or_create_files(tmp_path):
    """Computing a path never creates the file."""
    fetcher = _fetcher(tmp_path)
    assert not fetcher._cache_path("https://example.org/a.htm").exists()
    fetcher.close()


# --- fetch_text ------------------------------------------------------------------------


def test_fetch_text_reads_cache_without_network_or_sleep(tmp_path, sleeps):
    """A cached page is returned without any request or delay."""
    handler, log = _sequence()
    fetcher = _fetcher(tmp_path, handler)
    cached = Path(tmp_path / "cache" / "example.org" / "page.htm")
    cached.parent.mkdir(parents=True)
    cached.write_text("héllo", encoding="utf-8")
    assert fetcher.fetch_text(url="https://example.org/page.html") == "héllo"
    assert log == [] and sleeps == []
    fetcher.close()


def test_fetch_text_writes_cache_and_sleeps_before_and_after(tmp_path, sleeps):
    """A live fetch returns the body, stores it in the cache and sleeps ``delay`` twice."""
    handler, log = _sequence(httpx.Response(200, text="body ✓"))
    fetcher = _fetcher(tmp_path, handler)
    assert fetcher.fetch_text(url="https://example.org/a/b.html") == "body ✓"
    cached = tmp_path / "cache" / "example.org" / "a" / "b.htm"
    assert cached.read_text(encoding="utf-8") == "body ✓"
    assert sleeps == [0.5, 0.5] and len(log) == 1
    fetcher.close()


def test_fetch_text_second_call_is_served_from_cache(tmp_path, sleeps):
    """Fetching the same URL twice makes only one request."""
    handler, log = _sequence(httpx.Response(200, text="once"))
    fetcher = _fetcher(tmp_path, handler)
    url = "https://example.org/x"
    assert fetcher.fetch_text(url=url) == fetcher.fetch_text(url=url) == "once"
    assert len(log) == 1
    fetcher.close()


def test_fetch_text_without_cache_dir_does_not_write(tmp_path, sleeps):
    """With caching disabled nothing is written to disk."""
    fetcher = CachedHttpFetcher(delay=0)
    fetcher._client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="t"))
    )
    assert fetcher.fetch_text(url="https://example.org/x") == "t"
    assert list(tmp_path.iterdir()) == []
    fetcher.close()


def test_fetch_text_sends_configured_headers(tmp_path, sleeps):
    """Requests carry the fetcher's headers."""
    handler, log = _sequence(httpx.Response(200, text="ok"))
    fetcher = _fetcher(tmp_path, None, headers={"X-Test": "1"})
    fetcher._client = httpx.Client(headers=fetcher.headers, transport=httpx.MockTransport(handler))
    fetcher.fetch_text(url="https://example.org/h")
    assert log[0].headers["x-test"] == "1"
    fetcher.close()


def test_fetch_text_retries_429_with_exponential_backoff(tmp_path, sleeps):
    """HTTP 429 waits ``delay * 2**attempt`` and then succeeds on the next attempt."""
    handler, log = _sequence(
        httpx.Response(429), httpx.Response(429), httpx.Response(200, text="finally")
    )
    fetcher = _fetcher(tmp_path, handler, delay=1.0)
    assert fetcher.fetch_text(url="https://example.org/r") == "finally"
    assert len(log) == 3
    assert sleeps == [1.0, 1.0, 2.0, 1.0]  # initial, backoff 1*2**0, 1*2**1, post-success
    fetcher.close()


def test_fetch_text_retries_transport_errors_with_fixed_delay(tmp_path, sleeps):
    """Transport errors wait ``delay`` and retry."""
    handler, log = _sequence(
        httpx.ConnectError("down"), httpx.ReadTimeout("slow"), httpx.Response(200, text="up")
    )
    fetcher = _fetcher(tmp_path, handler, delay=0.25)
    assert fetcher.fetch_text(url="https://example.org/t") == "up"
    assert len(log) == 3
    assert sleeps == [0.25, 0.25, 0.25, 0.25]
    fetcher.close()


def test_fetch_text_non_429_http_error_is_raised_immediately(tmp_path, sleeps):
    """A 404 raises ``HTTPStatusError`` after a single attempt and caches nothing."""
    handler, log = _sequence(httpx.Response(404))
    fetcher = _fetcher(tmp_path, handler)
    with pytest.raises(httpx.HTTPStatusError) as exc:
        fetcher.fetch_text(url="https://example.org/missing.htm")
    assert exc.value.response.status_code == 404 and len(log) == 1
    assert not (tmp_path / "cache" / "example.org" / "missing.htm").exists()
    fetcher.close()


def test_fetch_text_fails_after_exhausting_429_retries(tmp_path, sleeps):
    """Persistent 429 raises ``RuntimeError`` chained from the last HTTP error."""
    handler, log = _sequence(*[httpx.Response(429)] * 2)
    fetcher = _fetcher(tmp_path, handler, delay=1.0)
    with pytest.raises(RuntimeError, match="after 2 attempts") as exc:
        fetcher.fetch_text(url="https://example.org/r", retry_count=2)
    assert isinstance(exc.value.__cause__, httpx.HTTPStatusError)
    assert len(log) == 2
    assert sleeps == [1.0, 1.0, 2.0]
    fetcher.close()


def test_fetch_text_fails_after_exhausting_transport_retries(tmp_path, sleeps):
    """Persistent transport errors raise ``RuntimeError`` chained from the last error."""
    handler, log = _sequence(httpx.ConnectError("a"), httpx.ConnectError("b"))
    fetcher = _fetcher(tmp_path, handler)
    with pytest.raises(RuntimeError, match="Failed to fetch") as exc:
        fetcher.fetch_text(url="https://example.org/t", retry_count=2)
    assert str(exc.value.__cause__) == "b"
    fetcher.close()


def test_fetch_text_zero_retries_raises_runtime_error_without_request(tmp_path, sleeps):
    """``retry_count=0`` never attempts a request and raises with no chained cause."""
    handler, log = _sequence()
    fetcher = _fetcher(tmp_path, handler)
    with pytest.raises(RuntimeError, match="after 0 attempts") as exc:
        fetcher.fetch_text(url="https://example.org/z", retry_count=0)
    assert log == [] and exc.value.__cause__ is None
    fetcher.close()


def test_fetch_text_follows_redirects(tmp_path, sleeps):
    """A redirect is followed and the final body returned."""

    def handler(request):
        """Redirect ``/old`` to ``/new``; serve the body at ``/new``."""
        if request.url.path == "/old":
            return httpx.Response(302, headers={"location": "https://example.org/new"})
        return httpx.Response(200, text="new body")

    fetcher = _fetcher(tmp_path, None)
    fetcher._client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    assert fetcher.fetch_text(url="https://example.org/old") == "new body"
    fetcher.close()


def test_fetch_text_url_without_host_raises_value_error_when_caching(tmp_path, sleeps):
    """With caching enabled a hostless URL fails before any request."""
    fetcher = _fetcher(tmp_path)
    with pytest.raises(ValueError):
        fetcher.fetch_text(url="/relative")
    fetcher.close()
