"""Snapshot test comparing a full 1 Enoch scrape of the cached HTML with the committed OSIS file."""

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
PACKAGE_MODULE = "open_canon_site.scrapers.sacred_texts.enoch"
SOURCE_CACHE_DIR = REPO_ROOT / ".cache" / "html"
SOURCE_CACHE_TREE = SOURCE_CACHE_DIR / "sacred-texts.com" / "bib" / "boe"
SNAPSHOT_FILE = "1-enoch.xml"
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
    """Make a snapshot comparable: unify newlines and provenance text, mask the eversion date.

    Args:
        xml: OSIS XML text.

    Returns:
        The XML with CRLF newlines made LF, old provenance wording replaced and the
        scrape timestamp replaced by ``SCRAPE_TIMESTAMP``.
    """
    normalized = xml.replace("\r\n", "\n").replace(OLD_PROVENANCE, NEW_PROVENANCE)
    return EVERSION_DATE_PATTERN.sub(r"\1SCRAPE_TIMESTAMP\2", normalized)


@lru_cache(maxsize=1)
def load_scrape_sacred_texts_main() -> Any:
    """Import the enoch module lazily and return its ``run`` function (cached)."""
    return importlib.import_module(PACKAGE_MODULE).run


@pytest.fixture(scope="session")
def generated_1_enoch_output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Run the scraper once per session against the local HTML cache and return the output path.

    Skips when the cache or the committed snapshot is absent.
    """
    if not SOURCE_CACHE_TREE.exists():
        pytest.skip(f"Missing local 1 Enoch HTML cache at {SOURCE_CACHE_TREE}")
    if not (DOCUMENTS_DIR / SNAPSHOT_FILE).exists():
        pytest.skip(f"Missing committed snapshot: {SNAPSHOT_FILE}")

    output_dir = tmp_path_factory.mktemp("scrape-sacred-texts-output")
    output_path = output_dir / SNAPSHOT_FILE
    scrape_sacred_texts_main = load_scrape_sacred_texts_main()

    scrape_sacred_texts_main(
        argparse.Namespace(
            output_dir=output_dir,
            cache_dir=SOURCE_CACHE_DIR,
            delay=0,
            start_page=0,
            end_page=112,
        )
    )
    return output_path


def test_scrape_sacred_texts_matches_snapshot(generated_1_enoch_output: Path) -> None:
    """The generated OSIS equals the committed snapshot after normalisation."""
    expected_path = DOCUMENTS_DIR / SNAPSHOT_FILE

    assert generated_1_enoch_output.exists(), "Missing generated 1 Enoch snapshot"
    assert expected_path.exists(), f"Missing committed snapshot: {SNAPSHOT_FILE}"

    actual_xml = normalize_osis_snapshot(generated_1_enoch_output.read_text(encoding="utf-8"))
    expected_xml = normalize_osis_snapshot(expected_path.read_text(encoding="utf-8"))

    assert actual_xml == expected_xml


def test_scrape_sacred_texts_generates_expected_file(
    generated_1_enoch_output: Path,
) -> None:
    """The scraper writes its output under the documented filename."""
    assert generated_1_enoch_output.name == SNAPSHOT_FILE
