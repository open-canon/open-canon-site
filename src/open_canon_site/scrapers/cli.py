"""Argparse command line for ``open-canon-scrape``: ``list``, ``all`` and one subcommand per scraper."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from open_canon_site.scrapers import registry
from open_canon_site.scrapers.base import ScraperSpec

DEFAULT_OUTPUT_DIR = "open-canon-osis-documents"
"""Default ``--output-dir``: the directory the site build reads OSIS XML from."""
DEFAULT_CACHE_DIR = ".cache/html"
"""Default ``--cache-dir``: where fetched HTML is cached between runs."""
DEFAULT_DELAY = 1.5
"""Default ``--delay`` in seconds between requests."""
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
"""Accepted values for ``--log-level``."""


def _common_parser() -> argparse.ArgumentParser:
    """Build the parent parser holding the options shared by every runnable subcommand.

    Returns:
        A parser with ``add_help=False`` defining ``-o/--output-dir``, ``--cache-dir``,
        ``--no-cache``, ``--delay`` and ``--log-level``, meant for ``parents=[...]``.
    """
    parent = argparse.ArgumentParser(add_help=False)
    group = parent.add_argument_group("common options")
    group.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path(DEFAULT_OUTPUT_DIR),
        help="directory to write OSIS XML files to (default: %(default)s)",
    )
    group.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(DEFAULT_CACHE_DIR),
        help="directory for cached HTTP responses (default: %(default)s)",
    )
    group.add_argument(
        "--no-cache",
        action="store_true",
        help="disable the HTTP response cache",
    )
    group.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help="politeness delay in seconds between requests (default: %(default)s)",
    )
    group.add_argument(
        "--log-level",
        choices=LOG_LEVELS,
        default="INFO",
        help="logging verbosity (default: %(default)s)",
    )
    return parent


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level ``open-canon-scrape`` parser.

    Adds ``list``, ``all`` and one subcommand per entry in ``registry.SCRAPERS``. Each
    scraper subcommand gets the common options, its own options via
    ``ScraperSpec.add_arguments``, and ``spec`` stored as a parser default.

    Returns:
        The configured parser; a subcommand is required.
    """
    parser = argparse.ArgumentParser(
        prog="open-canon-scrape",
        description="Scrape source texts into OSIS XML documents for open-canon-site.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True
    common = _common_parser()

    subparsers.add_parser("list", help="list available scrapers")
    subparsers.add_parser(
        "all",
        parents=[common],
        help="run every registered scraper with default options",
    )
    for spec in registry.SCRAPERS:
        sub = subparsers.add_parser(
            spec.name, parents=[common], help=spec.help, description=spec.help
        )
        spec.add_arguments(sub)
        sub.set_defaults(spec=spec)
    return parser


def _format_listing(specs: tuple[ScraperSpec, ...]) -> str:
    """Render the ``list`` subcommand output as an aligned text table.

    Args:
        specs: Scrapers to show, in display order.

    Returns:
        A ``NAME  SOURCE  OUTPUTS`` header plus one row per spec, with the name and
        source columns padded to align, or ``"No scrapers registered."`` when empty.
    """
    if not specs:
        return "No scrapers registered."
    rows = [("NAME", "SOURCE", "OUTPUTS")]
    rows += [(s.name, s.source, ", ".join(s.outputs)) for s in specs]
    widths = [max(len(row[i]) for row in rows) for i in range(2)]
    return "\n".join(
        f"{name.ljust(widths[0])}  {source.ljust(widths[1])}  {outputs}".rstrip()
        for name, source, outputs in rows
    )


def _normalise(args: argparse.Namespace) -> None:
    """Normalise the common options in place and create the output directory.

    Converts ``output_dir`` to a ``Path``, sets ``cache_dir`` to ``None`` when
    ``--no-cache`` was given (otherwise a ``Path``), and creates ``output_dir``
    (with parents) if it does not exist.

    Args:
        args: Parsed namespace containing ``output_dir``, ``cache_dir`` and ``no_cache``.
    """
    args.output_dir = Path(args.output_dir)
    args.cache_dir = None if args.no_cache else Path(args.cache_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)


def _run_spec(spec: ScraperSpec, args: argparse.Namespace) -> list[Path]:
    """Run one scraper and print each path it wrote to stdout.

    Args:
        spec: Scraper to run.
        args: Normalised namespace passed through to ``spec.run``.

    Returns:
        The paths returned by ``spec.run``.
    """
    paths = spec.run(args)
    for path in paths:
        print(path)
    return paths


def _default_args_for(spec: ScraperSpec, common: argparse.Namespace) -> argparse.Namespace:
    """Build a namespace with the common options plus ``spec``'s own defaults.

    Used by ``all`` so every scraper runs as if invoked with only its default options.

    Args:
        spec: Scraper whose ``add_arguments`` defines the own-option defaults.
        common: Already-normalised namespace of common options; each attribute is
            copied onto the result, overriding same-named scraper defaults.

    Returns:
        A new namespace holding the scraper defaults, the common options and ``spec``.
    """
    sub = argparse.ArgumentParser(add_help=False)
    spec.add_arguments(sub)
    args = sub.parse_args([])
    for key, value in vars(common).items():
        setattr(args, key, value)
    args.spec = spec
    return args


def main(argv: list[str] | None = None) -> int:
    """Run the ``open-canon-scrape`` command line.

    ``list`` prints the scraper table and returns without configuring logging. Other
    commands configure logging, normalise the common options, then run the chosen
    scraper (or every registered scraper for ``all``). Any exception from a scraper is
    reported on stderr as ``error: ...`` rather than propagated.

    Args:
        argv: Arguments excluding the program name; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code: 0 on success, 1 if a scraper raised. Argument errors exit
        through ``SystemExit`` raised by argparse.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "list":
        print(_format_listing(registry.SCRAPERS))
        return 0

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _normalise(args)

    try:
        if args.command == "all":
            for spec in registry.SCRAPERS:
                _run_spec(spec, _default_args_for(spec, args))
        else:
            _run_spec(args.spec, args)
    except Exception as exc:  # noqa: BLE001 - report any scraper failure as exit code 1
        logging.getLogger(__name__).debug("Scraper failed", exc_info=True)
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
