"""Build an OSIS file of "The Living Christ: The Testimony of the Apostles" (2000) from Gospel Library.

"The Living Christ" was issued on 1 January 2000 by the First Presidency and the Quorum of the Twelve Apostles of The
Church of Jesus Christ of Latter-day Saints. It is a testimony, not one of the official proclamations, so it gets its own
output file and ``open-canon-scrape lds-living-christ`` subcommand rather than a book in ``lds_proclamations.xml``.

The Study API page has the same layout as the proclamations, so it is converted with
`proclamations.build_proclamation`: one book ``LivingChrist`` with a single chapter whose paragraphs are verses, scripture
references kept as ``reference`` elements, the byline as an introduction and the signature block (the titles "The First
Presidency" and "The Quorum of the Twelve" and the date, without the signature images) as a colophon.
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib

import httpx
import pyosis.serialization

from open_canon_site.scrapers.base import ScraperSpec
from open_canon_site.scrapers.churchofjesuschrist import models as church_website_models
from open_canon_site.scrapers.churchofjesuschrist.proclamations import (
    Proclamation,
    add_arguments,
    build_proclamation,
    osis_document,
)

LIVING_CHRIST = Proclamation(
    "LivingChrist",
    "/manual/the-living-christ-the-testimony-of-the-apostles/the-living-christ-the-testimony-of-the-apostles",
    2000,
)
"""The Study API page of "The Living Christ"."""

OUTPUT_FILENAME = "the_living_christ.xml"
"""Name of the OSIS file written."""


async def build_living_christ(lang: str, client: httpx.AsyncClient) -> pyosis.serialization.OsisXML:
    """Fetch "The Living Christ" and convert it to an OSIS document.

    Args:
        lang: Language code of the content to fetch.
        client: HTTP client used for the request.

    Returns:
        The OSIS XML, holding the single book ``LivingChrist``.
    """
    page = await church_website_models.get_scripture_content_from_uri(
        lang, LIVING_CHRIST.uri, client
    )
    return osis_document(
        lang,
        osis_work="LivingChrist",
        title="The Living Christ: The Testimony of the Apostles",
        divs=[build_proclamation(LIVING_CHRIST, page)],
    )


async def write_living_christ(
    lang: str, root_dir: str | pathlib.Path, client: httpx.AsyncClient | None = None
) -> list[pathlib.Path]:
    """Build the OSIS file and write it to ``root_dir/the_living_christ.xml``.

    Args:
        lang: Language code of the content to fetch.
        root_dir: Directory to write into (created if missing).
        client: HTTP client to use; one is created and closed here when None.

    Returns:
        A one-element list holding the written path.
    """
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(timeout=60.0, pool=None))
    try:
        osis = await build_living_christ(lang, client)
    finally:
        if owns_client:
            await client.aclose()
    path = pathlib.Path(root_dir) / OUTPUT_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(osis.to_xml(), "utf-8")
    return [path]


def run(args: argparse.Namespace) -> list[pathlib.Path]:
    """Run the scraper for the parsed command-line arguments.

    Args:
        args: Parsed arguments; needs ``lang`` and ``output_dir`` attributes.

    Returns:
        The path of the OSIS file written.
    """
    return asyncio.run(write_living_christ(args.lang, args.output_dir))


SPEC = ScraperSpec(
    name="lds-living-christ",
    help='Scrape "The Living Christ: The Testimony of the Apostles" (2000) from churchofjesuschrist.org',
    source="https://www.churchofjesuschrist.org/study" + LIVING_CHRIST.uri,
    outputs=(OUTPUT_FILENAME,),
    run=run,
    add_arguments=add_arguments,
)
"""Registration entry for the ``lds-living-christ`` subcommand."""
