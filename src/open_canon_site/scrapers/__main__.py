"""Module entry point so ``python -m open_canon_site.scrapers`` runs the CLI."""

from __future__ import annotations

import sys

from open_canon_site.scrapers.cli import main

if __name__ == "__main__":
    sys.exit(main())
