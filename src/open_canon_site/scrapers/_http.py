"""HTTP fetching with an on-disk response cache, politeness delay and retries."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

import httpx

DEFAULT_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/91.0.4472.124 Safari/537.36"
)
"""Browser-like User-Agent string; some source sites reject the default httpx one."""
DEFAULT_HEADERS: Final[dict[str, str]] = {"User-Agent": DEFAULT_USER_AGENT}
"""Headers sent with every request unless overridden per fetcher."""
DEFAULT_TIMEOUT: Final[float] = 30.0
"""Default per-request timeout in seconds."""


class CachedHttpFetcher:
    """Synchronous text fetcher that caches responses on disk and retries transient errors.

    Cached pages are served without touching the network or sleeping. Live requests
    are throttled by ``delay`` and retried on HTTP 429 (exponential backoff) and
    transport errors (fixed ``delay`` pause).
    """

    def __init__(
        self,
        *,
        cache_dir: str | Path | None = None,
        delay: float = 1.0,
        timeout: float = DEFAULT_TIMEOUT,
        headers: dict[str, str] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Create a fetcher and its underlying ``httpx.Client``.

        Args:
            cache_dir: Root directory for cached responses, created if missing. ``None``
                (or an empty value) disables caching.
            delay: Seconds to sleep before and after each live request, and the base
                for backoff when retrying.
            timeout: Per-request timeout in seconds.
            headers: Extra headers merged over ``DEFAULT_HEADERS`` (they win on conflict).
            logger: Logger for progress and retry messages; defaults to this module's.
        """
        self.cache_dir = Path(cache_dir) if cache_dir else None
        """Root of the on-disk response cache, or ``None`` when caching is disabled."""
        self.delay = delay
        """Politeness delay in seconds, also the base for retry backoff."""
        self.timeout = timeout
        """Per-request timeout in seconds."""
        self.logger = logger or logging.getLogger(__name__)
        """Logger used for debug and retry messages."""
        self.headers = dict(DEFAULT_HEADERS)
        """Request headers: the defaults updated with any caller-supplied headers."""
        if headers:
            self.headers.update(headers)

        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._client = self._build_client()
        """Shared ``httpx.Client`` used for every live request."""

    def close(self) -> None:
        """Close the underlying HTTP client and release its connections."""
        self._client.close()

    def fetch_text(self, *, url: str, retry_count: int = 3) -> str:
        """Return the body of ``url`` as text, from the cache when possible.

        A cache hit returns immediately with no delay. Otherwise the fetcher sleeps
        ``delay``, then makes up to ``retry_count`` attempts. A successful response is
        written to the cache and followed by another ``delay`` sleep. HTTP 429 waits
        ``delay * 2**attempt`` before retrying; transport errors (timeouts, connection
        failures) wait ``delay``. Other HTTP error statuses are raised immediately. With
        caching enabled, a URL without a host raises ``ValueError`` (see ``_cache_path``).

        Args:
            url: Absolute http(s) URL to fetch.
            retry_count: Maximum number of live attempts.

        Returns:
            The decoded response body (or the UTF-8 cached copy).

        Raises:
            RuntimeError: If every attempt failed with a retryable error; chained from
                the last error.
            httpx.HTTPStatusError: For any non-429 error status (raised without retry).
        """
        cache_path = self._cache_path(url)
        if cache_path and cache_path.exists():
            self.logger.debug("Loading %s from cache", cache_path)
            return cache_path.read_text(encoding="utf-8")
        time.sleep(self.delay)

        last_exc: Exception | None = None
        for attempt in range(retry_count):
            try:
                self.logger.debug("Fetching %s (attempt %d/%d)", url, attempt + 1, retry_count)
                response = self._client.get(url)
                response.raise_for_status()
                text = response.text

                if cache_path:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(text, encoding="utf-8")

                time.sleep(self.delay)
                return text
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code != 429:
                    raise

                wait = self.delay * (2**attempt)
                self.logger.warning("Rate limited on %s; waiting %.1fs", url, wait)
                time.sleep(wait)
            except httpx.TransportError as exc:
                last_exc = exc
                self.logger.warning("Error fetching %s: %s. Retrying…", url, exc)
                time.sleep(self.delay)

        raise RuntimeError(f"Failed to fetch {url} after {retry_count} attempts") from last_exc

    def cache_path_for(self, url: str) -> Path | None:
        """Return where ``url`` is (or would be) cached; public wrapper over ``_cache_path``.

        Args:
            url: Absolute URL.

        Returns:
            The cache file path, or ``None`` if caching is disabled.
        """
        return self._cache_path(url)

    def _build_client(self) -> httpx.Client:
        """Create the ``httpx.Client`` with this fetcher's headers and timeout.

        Returns:
            A client that follows redirects. Overridable hook for tests.
        """
        return httpx.Client(
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=True,
        )

    def _cache_path(self, url: str) -> Path | None:
        """Map a URL to its cache file: ``<cache_dir>/<host>/<path>``.

        The query string and fragment are ignored. An empty path or one ending in
        ``/`` becomes ``index.htm``, and a ``.html`` suffix is rewritten to ``.htm``.

        Args:
            url: Absolute URL.

        Returns:
            The cache path, or ``None`` if caching is disabled.

        Raises:
            ValueError: If caching is enabled and ``url`` has no host.
        """
        if not self.cache_dir:
            return None

        split = urlsplit(url)
        if not split.netloc:
            raise ValueError(f"Cannot derive cache path from URL without host: {url}")

        relative_path = split.path.lstrip("/")
        if not relative_path:
            relative_path = "index.htm"
        elif relative_path.endswith("/"):
            relative_path = f"{relative_path}index.htm"

        if relative_path.endswith(".html"):
            relative_path = f"{relative_path[:-5]}.htm"

        return self.cache_dir / split.netloc / relative_path
