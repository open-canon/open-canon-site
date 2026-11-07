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
PACKAGE_MODULE = "open_canon_site.scrapers.sacred_texts.forgotten_books_of_eden"
SOURCE_CACHE_DIR = REPO_ROOT / ".cache" / "html"
SOURCE_CACHE_TREE = SOURCE_CACHE_DIR / "sacred-texts.com" / "bib" / "fbe"
SNAPSHOT_FILES = (
    "adam-and-eve.xml",
    "2-enoch.xml",
    "psalms-of-solomon.xml",
    "odes-of-solomon.xml",
    "letter-of-aristeas.xml",
    "4-maccabees.xml",
    "story-of-ahikar.xml",
    "testaments-twelve-patriarchs.xml",
)
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
    normalized = xml.replace("\r\n", "\n").replace(OLD_PROVENANCE, NEW_PROVENANCE)
    return EVERSION_DATE_PATTERN.sub(r"\1SCRAPE_TIMESTAMP\2", normalized)


@lru_cache(maxsize=1)
def load_scrape_fbe_main() -> Any:
    return importlib.import_module(PACKAGE_MODULE).run


@pytest.fixture(scope="session")
def generated_fbe_output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not SOURCE_CACHE_TREE.exists():
        pytest.skip(f"Missing local FBE HTML cache tree at {SOURCE_CACHE_TREE}")
    missing = [n for n in SNAPSHOT_FILES if not (DOCUMENTS_DIR / n).exists()]
    if missing:
        pytest.skip(f"Missing committed snapshots: {missing}")

    output_dir = tmp_path_factory.mktemp("scrape-fbe-output")
    scrape_fbe_main = load_scrape_fbe_main()

    scrape_fbe_main(
        argparse.Namespace(
            output_dir=output_dir,
            cache_dir=SOURCE_CACHE_DIR,
            delay=0,
            start_page=0,
            end_page=295,
        )
    )
    return output_dir


@pytest.mark.parametrize("snapshot_name", SNAPSHOT_FILES)
def test_scrape_fbe_matches_snapshots(
    generated_fbe_output: Path,
    snapshot_name: str,
) -> None:
    actual_path = generated_fbe_output / snapshot_name
    expected_path = DOCUMENTS_DIR / snapshot_name

    assert actual_path.exists(), f"Missing generated snapshot: {snapshot_name}"
    assert expected_path.exists(), f"Missing committed snapshot: {snapshot_name}"

    actual_xml = normalize_osis_snapshot(actual_path.read_text(encoding="utf-8"))
    expected_xml = normalize_osis_snapshot(expected_path.read_text(encoding="utf-8"))

    assert actual_xml == expected_xml


def test_scrape_fbe_generates_expected_files(generated_fbe_output: Path) -> None:
    assert sorted(path.name for path in generated_fbe_output.glob("*.xml")) == sorted(
        SNAPSHOT_FILES
    )
