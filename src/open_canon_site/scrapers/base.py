from __future__ import annotations

import argparse
import dataclasses
from pathlib import Path
from typing import Callable


def _no_arguments(parser: argparse.ArgumentParser) -> None:
    """Default ``add_arguments``: the scraper has no options of its own."""


@dataclasses.dataclass(frozen=True)
class ScraperSpec:
    """Describes one scraper and how it plugs into ``open-canon-scrape``."""

    name: str  # CLI subcommand, kebab-case
    help: str  # one line
    source: str  # human-readable source URL/site
    outputs: tuple[str, ...]  # default output filenames (relative to --output-dir)
    run: Callable[[argparse.Namespace], list[Path]]  # returns paths written
    add_arguments: Callable[[argparse.ArgumentParser], None] = _no_arguments
