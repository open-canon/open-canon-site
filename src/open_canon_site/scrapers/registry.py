from __future__ import annotations

from open_canon_site.scrapers.base import ScraperSpec

# Each port layer adds one import line per scraper and appends its SPEC below, e.g.:
#   from open_canon_site.scrapers.ebible.kjv_apocrypha import SPEC as KJV_APOCRYPHA
# Order matters: `open-canon-scrape all` runs scrapers in this order.

SCRAPERS: tuple[ScraperSpec, ...] = ()


def get_scraper(name: str) -> ScraperSpec:
    """Return the registered scraper called ``name`` or raise ``KeyError``."""
    for spec in SCRAPERS:
        if spec.name == name:
            return spec
    known = ", ".join(spec.name for spec in SCRAPERS) or "(none registered)"
    raise KeyError(f"Unknown scraper {name!r}. Available scrapers: {known}")
