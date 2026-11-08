"""Snapshot tests comparing the Jubilees scraper's output with the committed OSIS document.

Skipped unless the local HTML cache under ``.cache/html`` holds the original pages.
"""

from __future__ import annotations

import argparse
import importlib
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCUMENTS_DIR = REPO_ROOT / "open-canon-osis-documents"
PACKAGE_MODULE = "open_canon_site.scrapers.sacred_texts.jubilees"
SOURCE_CACHE_DIR = REPO_ROOT / ".cache" / "html"
JUBILEES_CACHE_FILE = SOURCE_CACHE_DIR / "archive.sacred-texts.com" / "bib" / "jub" / "jub00.htm"
SNAPSHOT_FILE = "jubilees.xml"
EVERSION_DATE_PATTERN = re.compile(
    r'(<date event="eversion" type="ISO" xml:lang="en" TEIform="date">)'
    r"[^<]+"
    r"(</date>)"
)


# The committed snapshots predate the move into open-canon-site and name the old
# repository in their provenance notes; the scrapers now name open-canon-site.
OLD_PROVENANCE = "converted to OSIS in this repository."
NEW_PROVENANCE = "converted to OSIS by the open-canon-site scrapers."


def normalize_osis_snapshot(xml: str) -> str:
    """Normalise an OSIS snapshot for comparison.

    Converts CRLF to LF, rewrites the old repository provenance note to the current one and
    replaces the volatile eversion timestamp with ``SCRAPE_TIMESTAMP``.

    Args:
        xml: OSIS XML text.

    Returns:
        The normalised XML.
    """
    normalized = xml.replace("\r\n", "\n").replace(OLD_PROVENANCE, NEW_PROVENANCE)
    return EVERSION_DATE_PATTERN.sub(r"\1SCRAPE_TIMESTAMP\2", normalized)


@lru_cache(maxsize=1)
def load_scrape_jubilees_main() -> Any:
    """Import the scraper module lazily and return its ``run`` entry point.

    Returns:
        The ``run`` function of the Jubilees scraper module.
    """
    return importlib.import_module(PACKAGE_MODULE).run


@pytest.fixture(scope="session")
def generated_jubilees_output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Run the Jubilees scraper once per session against the local cache and return the output path.

    Skips when the committed snapshot or any required cached source page is missing or invalid.

    Returns:
        Path of the freshly generated OSIS file.
    """
    if not (DOCUMENTS_DIR / SNAPSHOT_FILE).exists():
        pytest.skip(f"Missing committed snapshot: {SNAPSHOT_FILE}")
    module = importlib.import_module(PACKAGE_MODULE)
    missing_cache_files = []
    invalid_cache_files = []
    for page_number in range(module.PAGE_RANGE[0], module.PAGE_RANGE[1] + 1):
        cache_file = (
            SOURCE_CACHE_DIR
            / "archive.sacred-texts.com"
            / "bib"
            / "jub"
            / f"jub{page_number:02d}.htm"
        )
        if not cache_file.exists():
            missing_cache_files.append(cache_file)
            continue

        cached_source = cache_file.read_text(encoding="utf-8")
        if not module.JubileesParser.is_valid_page(cached_source):
            invalid_cache_files.append(cache_file)

    if missing_cache_files:
        pytest.skip(
            f"Missing complete local Jubilees cache; first missing file: {missing_cache_files[0]}"
        )

    if invalid_cache_files:
        pytest.skip(
            "Missing valid original-site Jubilees cache; first invalid file: "
            f"{invalid_cache_files[0]}"
        )

    output_dir = tmp_path_factory.mktemp("scrape-jubilees-output")
    output_path = output_dir / SNAPSHOT_FILE
    scrape_jubilees_main = load_scrape_jubilees_main()

    scrape_jubilees_main(
        argparse.Namespace(output_dir=output_dir, cache_dir=SOURCE_CACHE_DIR, delay=0)
    )
    return output_path


def test_scrape_jubilees_matches_snapshot(generated_jubilees_output: Path) -> None:
    """The generated Jubilees OSIS equals the committed snapshot after normalisation."""
    expected_path = DOCUMENTS_DIR / SNAPSHOT_FILE

    assert generated_jubilees_output.exists(), "Missing generated Jubilees snapshot"
    assert expected_path.exists(), f"Missing committed snapshot: {SNAPSHOT_FILE}"

    actual_xml = normalize_osis_snapshot(generated_jubilees_output.read_text(encoding="utf-8"))
    expected_xml = normalize_osis_snapshot(expected_path.read_text(encoding="utf-8"))

    assert actual_xml == expected_xml


def test_scrape_jubilees_generates_expected_file(
    generated_jubilees_output: Path,
) -> None:
    """The scraper writes a file named ``jubilees.xml``."""
    assert generated_jubilees_output.name == SNAPSHOT_FILE


def test_scrape_jubilees_preserves_inline_footnotes(
    generated_jubilees_output: Path,
) -> None:
    """Footnotes survive as inline ``<note>`` elements with their labels (for example ``35:5``)."""
    xml = generated_jubilees_output.read_text(encoding="utf-8")

    assert "<note" in xml
    assert 'n="35:5"' in xml


def test_scrape_jubilees_omits_sidebar_am_dates(
    generated_jubilees_output: Path,
) -> None:
    """Marginal A.M. date ranges from the source sidebar are not emitted as text."""
    xml = generated_jubilees_output.read_text(encoding="utf-8")

    assert "64-70 A.M." not in xml
    assert "71-77 A.M." not in xml
    assert "78-84 A.M." not in xml
    assert "309-315 A.M." not in xml
    assert "2450 A.M." not in xml
