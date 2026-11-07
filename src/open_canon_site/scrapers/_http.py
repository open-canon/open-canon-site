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
DEFAULT_HEADERS: Final[dict[str, str]] = {"User-Agent": DEFAULT_USER_AGENT}
DEFAULT_TIMEOUT: Final[float] = 30.0


class CachedHttpFetcher:
    def __init__(
        self,
        *,
        cache_dir: str | Path | None = None,
        delay: float = 1.0,
        timeout: float = DEFAULT_TIMEOUT,
        headers: dict[str, str] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.delay = delay
        self.timeout = timeout
        self.logger = logger or logging.getLogger(__name__)
        self.headers = dict(DEFAULT_HEADERS)
        if headers:
            self.headers.update(headers)

        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._client = self._build_client()

    def close(self) -> None:
        self._client.close()

    def fetch_text(self, *, url: str, retry_count: int = 3) -> str:
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
        return self._cache_path(url)

    def _build_client(self) -> httpx.Client:
        return httpx.Client(
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=True,
        )

    def _cache_path(self, url: str) -> Path | None:
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
