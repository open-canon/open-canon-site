"""Build OSIS XML files for the Standard Works of the Church of Jesus Christ of Latter-day Saints.

Features:
    - Asynchronous gathering and processing of scripture texts.
    - Extensible enumeration for available Standard Works.
    - Registered with ``open-canon-scrape`` as the ``lds-standard-works`` subcommand.
    - Integration with HTTPX for asynchronous web requests and pyosis for OSIS XML generation.
    - Progress reporting via tqdm.

Usage:
    ``open-canon-scrape lds-standard-works --works book-of-mormon,new-testament``
"""

from __future__ import annotations

import argparse
import asyncio
import enum
import itertools
import pathlib
from collections.abc import Awaitable
from typing import Callable, Literal, TypeVar

import httpx
import pyosis
import tqdm.auto

import open_canon_site.scrapers.churchofjesuschrist.book_of_mormon
import open_canon_site.scrapers.churchofjesuschrist.doctrine_and_covenants
import open_canon_site.scrapers.churchofjesuschrist.new_testament
import open_canon_site.scrapers.churchofjesuschrist.old_testament
import open_canon_site.scrapers.churchofjesuschrist.pearl_of_great_price
from open_canon_site.scrapers.base import ScraperSpec

K = TypeVar("K")
"""Key type of `gather_dict`."""
V = TypeVar("V")
"""Awaited value type of `gather_dict`."""


async def gather_dict(tasks: dict[K, Awaitable[V]]) -> dict[K, V]:
    """Gather a dictionary's awaitable values into a new dictionary.

    Args:
        tasks: Dictionary whose values are awaitable.

    Returns:
        Dictionary with awaited values.
    """

    async def mark(key: K, coro: Awaitable[V]) -> tuple[K, V]:
        """Await one task and pair its result with its key.

        Args:
            key: Dictionary key the result belongs to.
            coro: Awaitable to run.

        Returns:
            The ``(key, result)`` pair.
        """
        return key, await coro

    return {
        key: result for key, result in await asyncio.gather(*itertools.starmap(mark, tasks.items()))
    }


class AvailableStandardWorks(enum.IntFlag):
    """Flag enumeration of the Standard Works that can be built; members combine with ``|``."""

    BOOK_OF_MORMON = enum.auto()
    """Represents the Book of Mormon."""
    DOCTRINE_AND_COVENANTS = enum.auto()
    """Represents the Doctrine and Covenants."""
    NEW_TESTAMENT = enum.auto()
    """Represents the New Testament."""
    OLD_TESTAMENT = enum.auto()
    """Represents the Old Testament."""
    PEARL_OF_GREAT_PRICE = enum.auto()
    """Represents the Pearl of Great Price."""
    ALL = (
        BOOK_OF_MORMON
        | DOCTRINE_AND_COVENANTS
        | NEW_TESTAMENT
        | OLD_TESTAMENT
        | PEARL_OF_GREAT_PRICE
    )
    """All the available Standard Works."""


async def build_standard_works(
    lang: Literal["eng"] | str = "eng",
    standard_works_to_build: AvailableStandardWorks = AvailableStandardWorks.ALL,
    root_dir: str | pathlib.Path = "open-canon-osis-documents",
    client: httpx.AsyncClient | None = None,
) -> list[pathlib.Path]:
    """Build OSIS XML files for the Standard Works of the Church of Jesus Christ of Latter-day Saints.

    Args:
        lang: Language code to use when scaping the Church's website. Only "eng" is officially supported currently.
        standard_works_to_build: Flag of which Standard Works to build. Defaults to all available ones.
        root_dir: Directory in which to place the OSIS XML files once generated.
        client: HTTPX Async Client to use for asynchronous web requests. If None, one will be instantiated and closed
            before returning; a client passed in is left open for the caller.

    Returns:
        Paths of the OSIS XML files written, in canonical work order (Book of Mormon, Doctrine and Covenants, New Testament, Old
        Testament, Pearl of Great Price), restricted to the works requested.
    """
    root_dir = pathlib.Path(root_dir)
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(timeout=60.0, pool=None))

    standard_works_mapping: dict[
        AvailableStandardWorks,
        tuple[pathlib.Path, Callable[[str, httpx.AsyncClient], Awaitable[pyosis.OsisXML]]],
    ] = {
        AvailableStandardWorks.BOOK_OF_MORMON: (
            root_dir / "book_of_mormon.xml",
            open_canon_site.scrapers.churchofjesuschrist.book_of_mormon.build_book_of_mormon,
        ),
        AvailableStandardWorks.DOCTRINE_AND_COVENANTS: (
            root_dir / "doctrine_and_covenants.xml",
            open_canon_site.scrapers.churchofjesuschrist.doctrine_and_covenants.build_doctrine_and_covenants,
        ),
        AvailableStandardWorks.NEW_TESTAMENT: (
            root_dir / "new_testament.xml",
            open_canon_site.scrapers.churchofjesuschrist.new_testament.build_new_testament,
        ),
        AvailableStandardWorks.OLD_TESTAMENT: (
            root_dir / "old_testament.xml",
            open_canon_site.scrapers.churchofjesuschrist.old_testament.build_old_testament,
        ),
        AvailableStandardWorks.PEARL_OF_GREAT_PRICE: (
            root_dir / "pearl_of_great_price.xml",
            open_canon_site.scrapers.churchofjesuschrist.pearl_of_great_price.build_pearl_of_great_price,
        ),
    }

    standard_works_to_build = AvailableStandardWorks(standard_works_to_build)
    try:
        texts_tasks: dict[pathlib.Path, Awaitable[pyosis.OsisXML]] = {
            file_name: func(lang, client)
            for k, (file_name, func) in standard_works_mapping.items()
            if standard_works_to_build & k
        }

        osis_texts = await gather_dict(texts_tasks)
    finally:
        if owns_client:
            await client.aclose()

    written: list[pathlib.Path] = []
    for file_name, osis_text in tqdm.auto.tqdm(osis_texts.items()):
        file_path = pathlib.Path(file_name)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(osis_text.to_xml(), "utf-8")
        written.append(file_path)
    return written


WORK_NAMES: dict[str, AvailableStandardWorks] = {
    "book-of-mormon": AvailableStandardWorks.BOOK_OF_MORMON,
    "doctrine-and-covenants": AvailableStandardWorks.DOCTRINE_AND_COVENANTS,
    "new-testament": AvailableStandardWorks.NEW_TESTAMENT,
    "old-testament": AvailableStandardWorks.OLD_TESTAMENT,
    "pearl-of-great-price": AvailableStandardWorks.PEARL_OF_GREAT_PRICE,
}
"""CLI work names (kebab-case) mapped to their flag. Keys follow the enum member names."""


def parse_works(value: str) -> AvailableStandardWorks:
    """Parse a comma-separated list of kebab-case work names into an ``AvailableStandardWorks`` flag.

    Used as the ``type=`` callable of the ``--works`` argument. Whitespace around names and empty
    items (e.g. a trailing comma) are ignored; duplicates are harmless.

    Args:
        value: Comma-separated names, each a key of `WORK_NAMES` (e.g. ``"book-of-mormon,new-testament"``).

    Returns:
        The union of the named works' flags.

    Raises:
        argparse.ArgumentTypeError: If no names are given, or a name is not in `WORK_NAMES`.
    """
    names = [part.strip() for part in value.split(",") if part.strip()]
    if not names:
        raise argparse.ArgumentTypeError(f"no works given; choose from: {', '.join(WORK_NAMES)}")
    works = AvailableStandardWorks(0)
    for name in names:
        try:
            works |= WORK_NAMES[name]
        except KeyError:
            raise argparse.ArgumentTypeError(
                f"unknown work {name!r}; choose from: {', '.join(WORK_NAMES)}"
            ) from None
    return works


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the ``lds-standard-works`` options to its subcommand parser.

    Adds ``--works`` (parsed with `parse_works`, defaulting to all works) and ``--lang`` (default ``eng``).

    Args:
        parser: Subcommand parser to add the arguments to.
    """
    parser.add_argument(
        "--works",
        type=parse_works,
        default=AvailableStandardWorks.ALL,
        metavar="NAMES",
        help="comma-separated works to build: " + ", ".join(WORK_NAMES) + " (default: all)",
    )
    parser.add_argument(
        "--lang",
        default="eng",
        help="language code used on churchofjesuschrist.org (default: %(default)s)",
    )


def run(args: argparse.Namespace) -> list[pathlib.Path]:
    """Run the scraper for the parsed command-line arguments.

    Args:
        args: Parsed arguments; needs ``lang``, ``works`` and ``output_dir`` attributes.

    Returns:
        Paths of the OSIS XML files written by `build_standard_works`.
    """
    # This scraper talks to the Scripture Content API directly and does not use the
    # shared HTTP cache or --delay.
    return asyncio.run(
        build_standard_works(
            lang=args.lang,
            standard_works_to_build=args.works,
            root_dir=args.output_dir,
        )
    )


SPEC = ScraperSpec(
    name="lds-standard-works",
    help="Scrape the LDS Standard Works from churchofjesuschrist.org",
    source="https://www.churchofjesuschrist.org/study/scriptures",
    outputs=(
        "book_of_mormon.xml",
        "doctrine_and_covenants.xml",
        "new_testament.xml",
        "old_testament.xml",
        "pearl_of_great_price.xml",
    ),
    run=run,
    add_arguments=add_arguments,
)
"""Registration entry for the ``lds-standard-works`` subcommand."""
