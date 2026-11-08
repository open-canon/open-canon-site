"""Registry of every scraper available to ``open-canon-scrape``."""

from __future__ import annotations

from open_canon_site.scrapers.base import ScraperSpec
from open_canon_site.scrapers.churchofjesuschrist.proclamations import SPEC as LDS_PROCLAMATIONS
from open_canon_site.scrapers.churchofjesuschrist.standard_works import SPEC as LDS_STANDARD_WORKS
from open_canon_site.scrapers.ebible.kjv_apocrypha import SPEC as KJV_APOCRYPHA
from open_canon_site.scrapers.sacred_texts.cave_of_treasures import SPEC as CAVE_OF_TREASURES
from open_canon_site.scrapers.sacred_texts.enoch import SPEC as ENOCH
from open_canon_site.scrapers.sacred_texts.forgotten_books_of_eden import (
    SPEC as FORGOTTEN_BOOKS_OF_EDEN,
)
from open_canon_site.scrapers.sacred_texts.jasher import SPEC as JASHER
from open_canon_site.scrapers.sacred_texts.jubilees import SPEC as JUBILEES
from open_canon_site.scrapers.sacred_texts.kebra_nagast import SPEC as KEBRA_NAGAST
from open_canon_site.scrapers.sacred_texts.lost_books_of_the_bible import (
    SPEC as LOST_BOOKS_OF_THE_BIBLE,
)
from open_canon_site.scrapers.sacred_texts.vita_adae_et_evae import SPEC as VITA_ADAE_ET_EVAE

# Each port layer adds one import line per scraper and appends its SPEC below, e.g.:
#   from open_canon_site.scrapers.ebible.kjv_apocrypha import SPEC as KJV_APOCRYPHA
# Order matters: `open-canon-scrape all` runs scrapers in this order.

SCRAPERS: tuple[ScraperSpec, ...] = (
    KJV_APOCRYPHA,
    CAVE_OF_TREASURES,
    ENOCH,
    FORGOTTEN_BOOKS_OF_EDEN,
    JASHER,
    JUBILEES,
    KEBRA_NAGAST,
    LOST_BOOKS_OF_THE_BIBLE,
    VITA_ADAE_ET_EVAE,
    LDS_STANDARD_WORKS,
    LDS_PROCLAMATIONS,
)
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
