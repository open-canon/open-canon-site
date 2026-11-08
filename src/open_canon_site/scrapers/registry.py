"""Registry of every scraper available to ``open-canon-scrape``."""

from __future__ import annotations

from open_canon_site.scrapers.base import ScraperSpec

# Each port layer adds one import line per scraper and appends its SPEC below, e.g.:
#   from open_canon_site.scrapers.ebible.kjv_apocrypha import SPEC as KJV_APOCRYPHA
# Order matters: `open-canon-scrape all` runs scrapers in this order.

SCRAPERS: tuple[ScraperSpec, ...] = ()
"""All registered scrapers in the order ``open-canon-scrape all`` runs them."""


def get_scraper(name: str) -> ScraperSpec:
    """Look up a registered scraper by its CLI name.

    Args:
        name: Subcommand name to find, matched exactly against ``ScraperSpec.name``.

    Returns:
        The first spec in ``SCRAPERS`` whose name equals ``name``.

    Raises:
        KeyError: If no registered scraper has that name. The message lists the
            available names (or says none are registered).
    """
    for spec in SCRAPERS:
        if spec.name == name:
            return spec
    known = ", ".join(spec.name for spec in SCRAPERS) or "(none registered)"
    raise KeyError(f"Unknown scraper {name!r}. Available scrapers: {known}")
