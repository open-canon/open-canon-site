"""This module provides functionality to build OSIS XML files for the Standard Works of the Church of Jesus Christ of
Latter-day Saints.

Features:
    - Asynchronous gathering and processing of scripture texts.
    - Extensible enumeration for available Standard Works.
    - Command-line interface for building OSIS files using the `fire` library.
    - Integration with HTTPX for asynchronous web requests and pyosis for OSIS XML generation.
    - Progress reporting via tqdm.

Usage:
    Run this module as a script to generate OSIS XML files for the supported Standard Works.
"""

import asyncio
import enum
import itertools
import pathlib
from collections.abc import Awaitable
from typing import Callable, Literal, TypeVar

import fire  # type: ignore
import httpx
import pyosis
import tqdm.auto

import churchstudy_to_osis.standard_works.book_of_mormon
import churchstudy_to_osis.standard_works.doctrine_and_covenants
import churchstudy_to_osis.standard_works.new_testament
import churchstudy_to_osis.standard_works.old_testament
import churchstudy_to_osis.standard_works.pearl_of_great_price

K = TypeVar("K")
V = TypeVar("V")


async def gather_dict(tasks: dict[K, Awaitable[V]]) -> dict[K, V]:
    """Gather a dictionary's awaitable values into a new dictionary.

    Args:
        tasks: Dictionary whose values are awaitable.

    Returns:
        Dictionary with awaited values.
    """

    async def mark(key: K, coro: Awaitable[V]) -> tuple[K, V]:
        return key, await coro

    return {key: result for key, result in await asyncio.gather(*itertools.starmap(mark, tasks.items()))}


class AvailableStandardWorks(enum.IntFlag):
    """Enumeration of available Standard Works.

    Attributes:
        BOOK_OF_MORMON: Represents the Book of Mormon.
        DOCTRINE_AND_COVENANTS: Represents the Doctrine and Covenants.
        NEW_TESTAMENT: Represents the New Testament.
        OLD_TESTAMENT: Represents the Old Testament.
        PEARL_OF_GREAT_PRICE: Represents the Pearl of Great Price.
        ALL: All the available Standard Works.
    """

    BOOK_OF_MORMON = enum.auto()
    DOCTRINE_AND_COVENANTS = enum.auto()
    NEW_TESTAMENT = enum.auto()
    OLD_TESTAMENT = enum.auto()
    PEARL_OF_GREAT_PRICE = enum.auto()
    ALL = BOOK_OF_MORMON | DOCTRINE_AND_COVENANTS | NEW_TESTAMENT | OLD_TESTAMENT | PEARL_OF_GREAT_PRICE


async def build_standard_works(
    lang: Literal["eng"] | str = "eng",
    standard_works_to_build: AvailableStandardWorks = AvailableStandardWorks.ALL,
    root_dir: str | pathlib.Path = "churchstudy-to-osis/osis_files/standard_works",
    client: httpx.AsyncClient | None = None,
) -> None:
    """Build OSIS XML files for the Standard Works of the Church of Jesus Christ of Latter-day Saints.

    Args:
        lang: Language code to use when scaping the Church's website. Only "eng" is officially supported currently.
        standard_works_to_build: Flag of which Standard Works to build. Defaults to all available ones.
        root_dir: Directory in which to place the OSIS XML files once generated.
        client: HTTPX Async Client to use for asynchronous web requests. If None, one will be instantiated.
    """
    root_dir = pathlib.Path(root_dir)
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout=60.0, pool=None))

    standard_works_mapping: dict[
        AvailableStandardWorks, tuple[pathlib.Path, Callable[[str, httpx.AsyncClient], Awaitable[pyosis.OsisXML]]]
    ] = {
        AvailableStandardWorks.BOOK_OF_MORMON: (
            root_dir / "book_of_mormon.xml",
            churchstudy_to_osis.standard_works.book_of_mormon.build_book_of_mormon,
        ),
        AvailableStandardWorks.DOCTRINE_AND_COVENANTS: (
            root_dir / "doctrine_and_covenants.xml",
            churchstudy_to_osis.standard_works.doctrine_and_covenants.build_doctrine_and_covenants,
        ),
        AvailableStandardWorks.NEW_TESTAMENT: (
            root_dir / "new_testament.xml",
            churchstudy_to_osis.standard_works.new_testament.build_new_testament,
        ),
        AvailableStandardWorks.OLD_TESTAMENT: (
            root_dir / "old_testament.xml",
            churchstudy_to_osis.standard_works.old_testament.build_old_testament,
        ),
        AvailableStandardWorks.PEARL_OF_GREAT_PRICE: (
            root_dir / "pearl_of_great_price.xml",
            churchstudy_to_osis.standard_works.pearl_of_great_price.build_pearl_of_great_price,
        ),
    }

    standard_works_to_build = AvailableStandardWorks(standard_works_to_build)
    texts_tasks: dict[pathlib.Path, Awaitable[pyosis.OsisXML]] = {
        file_name: func(lang, client)
        for k, (file_name, func) in standard_works_mapping.items()
        if standard_works_to_build & k
    }

    osis_texts = await gather_dict(texts_tasks)

    for file_name, osis_text in tqdm.auto.tqdm(osis_texts.items()):
        file_path = pathlib.Path(file_name)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(osis_text.to_xml(), "utf-8")


if __name__ == "__main__":
    fire.Fire(build_standard_works)
