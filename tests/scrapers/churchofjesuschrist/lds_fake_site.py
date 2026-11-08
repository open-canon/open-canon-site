"""A tiny offline mock of the churchofjesuschrist.org Study API for the lds-standard-works tests."""

from __future__ import annotations

import re
from typing import Any, Union

import httpx

FRONT_MATTER_SLUGS = {
    "title-page",
    "bofm-title",
    "introduction",
    "three",
    "eight",
    "js",
    "explanation",
    "illustrations",
    "pronunciation",
    "chron-order",
    "dedication",
}
"""Single-page front/back matter slugs served by `FakeSite` as a page with title and body block."""

PageSpec = Union[str, dict[str, Any]]  # noqa: UP007
"""A page override: an HTML body string, or a full JSON payload dictionary."""


def study_payload(
    uri: str,
    body: str,
    footnotes: dict[str, Any] | None = None,
    canonical: str | None = None,
) -> dict[str, Any]:
    """Build a minimal Study API JSON payload for one page.

    Args:
        uri: Requested URI, e.g. ``/scriptures/bofm/1-ne/1``.
        body: HTML body of the page.
        footnotes: Footnote objects keyed by id; empty when omitted.
        canonical: Value for ``meta.canonicalUrl``; defaults to ``uri``.

    Returns:
        A dictionary shaped like the real ``language-pages/type/content`` response.
    """
    return {
        "meta": {
            "archived": False,
            "title": "Test page",
            "canonicalUrl": canonical if canonical is not None else uri,
            "contentType": "text/html",
            "pageAttributes": {"data-uri": uri, "lang": "eng"},
            "scopedClassName": "classic-scripture",
        },
        "content": {"head": None, "body": body, "footnotes": footnotes or {}},
        "pids": [],
        "tableOfContentsUri": "/scriptures",
        "uri": uri,
        "verified": True,
    }


def chapter_body(label: str) -> str:
    """Build a one-verse chapter body with a book title.

    Args:
        label: Text embedded in the title and verse, usually the URI.

    Returns:
        HTML in the shape of a Study API chapter body.
    """
    return (
        f'<p id="title1"><span class="dominant">Title {label}</span></p>'
        '<div class="body-block"><p class="verse"><span class="verse-number">1</span>'
        f"Verse {label}</p></div>"
    )


def front_body(label: str) -> str:
    """Build a front matter page body with a title, copyright info and a body block.

    Args:
        label: Text embedded in the title and paragraph.

    Returns:
        HTML in the shape of a front matter page.
    """
    return (
        f'<h1 id="title1">Front {label}</h1>'
        '<div class="publish-info">Published by Test Press</div>'
        '<div class="copyright-info">&copy; Test. Source: 2013/10</div>'
        f'<div class="body-block"><p>Body {label}</p></div>'
    )


class FakeSite:
    """In-memory stand-in for the Study API, usable as an ``httpx.MockTransport`` handler."""

    def __init__(self, pages: dict[str, PageSpec] | None = None) -> None:
        """Create a site, optionally with explicit pages.

        Args:
            pages: Mapping of requested URI to an HTML body or full payload; takes precedence over
                the generated defaults.
        """
        self.pages: dict[str, PageSpec] = dict(pages or {})
        """Explicit page overrides keyed by URI."""
        self.requests: list[httpx.Request] = []
        """Every request received, in order."""

    def default_page(self, uri: str) -> PageSpec:
        """Generate the default response for a URI that has no explicit override.

        Book tables of contents answer with a redirect to the work's own table of contents (as the
        real site does for single-chapter books), front matter slugs get a front matter page, and
        everything else is treated as a chapter.

        Args:
            uri: Requested URI.

        Returns:
            An HTML body string, or a payload dictionary for redirects.
        """
        match = re.fullmatch(r"/scriptures/([^/]+)/([^/]+)", uri)
        if match:
            slug = match.group(2)
            if slug in FRONT_MATTER_SLUGS:
                return front_body(uri)
            return study_payload(uri, "", canonical=f"/scriptures/{match.group(1)}")
        if re.search(r"/fac-\d$", uri):
            return front_body(uri)
        return chapter_body(uri)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """Answer a request like the Study API.

        Args:
            request: Incoming request; its ``uri`` query parameter selects the page.

        Returns:
            A 200 JSON response with the page payload.
        """
        self.requests.append(request)
        uri = request.url.params["uri"]
        spec = self.pages.get(uri)
        if spec is None:
            spec = self.default_page(uri)
        payload = study_payload(uri, spec) if isinstance(spec, str) else spec
        return httpx.Response(200, json=payload)

    def uris(self) -> list[str]:
        """List the URIs requested so far.

        Returns:
            The ``uri`` parameter of every request, in order.
        """
        return [r.url.params["uri"] for r in self.requests]
