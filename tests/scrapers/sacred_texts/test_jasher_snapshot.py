"""Snapshot tests comparing the Jasher scraper's output with the committed OSIS document.

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
PACKAGE_MODULE = "open_canon_site.scrapers.sacred_texts.jasher"
SOURCE_CACHE_DIR = REPO_ROOT / ".cache" / "html"
INDEX_CACHE_FILE = (
    SOURCE_CACHE_DIR / "archive.sacred-texts.com" / "chr" / "apo" / "jasher" / "index.htm"
)
SNAPSHOT_FILE = "jasher.xml"
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
def load_scrape_jasher_main() -> Any:
    """Import the scraper module lazily and return its ``run`` entry point.

    Returns:
        The ``run`` function of the Jasher scraper module.
    """
    return importlib.import_module(PACKAGE_MODULE).run


@pytest.fixture(scope="session")
def generated_jasher_output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Run the Jasher scraper once per session against the local cache and return the output path.

    Skips when the committed snapshot or any required cached source page is missing or invalid.

    Returns:
        Path of the freshly generated OSIS file.
    """
    if not (DOCUMENTS_DIR / SNAPSHOT_FILE).exists():
        pytest.skip(f"Missing committed snapshot: {SNAPSHOT_FILE}")
    module = importlib.import_module(PACKAGE_MODULE)

    if not INDEX_CACHE_FILE.exists():
        pytest.skip(f"Missing Jasher index cache: {INDEX_CACHE_FILE}")

    index_source = INDEX_CACHE_FILE.read_text(encoding="utf-8")
    if not module.JasherParser.is_valid_index(index_source):
        pytest.skip(f"Missing valid original-site Jasher index cache: {INDEX_CACHE_FILE}")

    missing_cache_files = []
    invalid_cache_files = []
    for chapter_number in module.EXPECTED_CHAPTERS:
        cache_file = (
            SOURCE_CACHE_DIR
            / "archive.sacred-texts.com"
            / "chr"
            / "apo"
            / "jasher"
            / f"{chapter_number}.htm"
        )
        if not cache_file.exists():
            missing_cache_files.append(cache_file)
            continue

        cached_source = cache_file.read_text(encoding="utf-8")
        if not module.JasherParser.is_valid_chapter_page(cached_source, chapter_number):
            invalid_cache_files.append(cache_file)

    if missing_cache_files:
        pytest.skip(
            f"Missing complete local Jasher cache; first missing file: {missing_cache_files[0]}"
        )

    if invalid_cache_files:
        pytest.skip(
            "Missing valid original-site Jasher cache; first invalid file: "
            f"{invalid_cache_files[0]}"
        )

    output_dir = tmp_path_factory.mktemp("scrape-jasher-output")
    output_path = output_dir / SNAPSHOT_FILE
    scrape_jasher_main = load_scrape_jasher_main()

    scrape_jasher_main(
        argparse.Namespace(output_dir=output_dir, cache_dir=SOURCE_CACHE_DIR, delay=0)
    )
    return output_path


def test_scrape_jasher_matches_snapshot(generated_jasher_output: Path) -> None:
    """The generated Jasher OSIS equals the committed snapshot after normalisation."""
    expected_path = DOCUMENTS_DIR / SNAPSHOT_FILE

    assert generated_jasher_output.exists(), "Missing generated Jasher snapshot"
    assert expected_path.exists(), f"Missing committed snapshot: {SNAPSHOT_FILE}"

    actual_xml = normalize_osis_snapshot(generated_jasher_output.read_text(encoding="utf-8"))
    expected_xml = normalize_osis_snapshot(expected_path.read_text(encoding="utf-8"))

    assert actual_xml == expected_xml


def test_scrape_jasher_generates_expected_file(generated_jasher_output: Path) -> None:
    """The scraper writes a file named ``jasher.xml``."""
    assert generated_jasher_output.name == SNAPSHOT_FILE


def test_scrape_jasher_omits_footer_boilerplate(generated_jasher_output: Path) -> None:
    """Footer navigation text and the ``THE END`` marker do not leak into the OSIS output."""
    xml = generated_jasher_output.read_text(encoding="utf-8")

    assert "Next: Chapter" not in xml
    assert "Sacred Texts | Christianity" not in xml
    assert "THE END" not in xml
