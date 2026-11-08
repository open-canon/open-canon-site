"""Scraper contract: the ``ScraperSpec`` record every scraper module exports as ``SPEC``."""

from __future__ import annotations

import argparse
import dataclasses
from pathlib import Path
from typing import Callable


def _no_arguments(parser: argparse.ArgumentParser) -> None:
    """Register no scraper-specific options (default ``ScraperSpec.add_arguments``).

    Args:
        parser: Subcommand parser for the scraper; left untouched.
    """


@dataclasses.dataclass(frozen=True)
class ScraperSpec:
    """Describes one scraper and how it plugs into ``open-canon-scrape``.

    Each scraper module defines a module-level ``SPEC`` of this type and the registry
    collects them. Instances are frozen so a registered spec cannot be mutated at runtime.
    """

    name: str
    """CLI subcommand name for the scraper, in kebab-case (e.g. ``"kjv-apocrypha"``)."""
    help: str
    """One-line description shown in ``--help`` output for the subcommand."""
    source: str
    """Human-readable source URL or site name, shown by ``open-canon-scrape list``."""
    outputs: tuple[str, ...]
    """Default output filenames the scraper writes, relative to ``--output-dir``."""
    run: Callable[[argparse.Namespace], list[Path]]
    """Runs the scraper with the parsed arguments and returns the paths it wrote.

    The namespace carries the normalised common options (``output_dir``, ``cache_dir``,
    ``delay``) plus the scraper's own. It must not call ``logging.basicConfig``.
    """
    add_arguments: Callable[[argparse.ArgumentParser], None] = _no_arguments
    """Adds scraper-specific options to the subcommand parser (default: adds none)."""
