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
PACKAGE_MODULE = "open_canon_site.scrapers.sacred_texts.vita_adae_et_evae"
SOURCE_CACHE_DIR = REPO_ROOT / ".cache" / "html"
SNAPSHOT_FILE = "vita-adae-et-evae.xml"
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
def load_scrape_vita_main() -> Any:
    return importlib.import_module(PACKAGE_MODULE).run


@pytest.fixture(scope="session")
def generated_vita_output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not (DOCUMENTS_DIR / SNAPSHOT_FILE).exists():
        pytest.skip(f"Missing committed snapshot: {SNAPSHOT_FILE}")
    source_cache_path = SOURCE_CACHE_DIR / "sacred-texts.com" / "chr" / "apo" / "adamnev.htm"
    if not source_cache_path.exists():
        pytest.skip(f"Missing local Vita HTML cache at {source_cache_path}")

    output_dir = tmp_path_factory.mktemp("scrape-vita-output")
    output_path = output_dir / SNAPSHOT_FILE
    scrape_vita_main = load_scrape_vita_main()

    scrape_vita_main(argparse.Namespace(output_dir=output_dir, cache_dir=SOURCE_CACHE_DIR, delay=0))
    return output_path


def test_scrape_vita_matches_snapshot(generated_vita_output: Path) -> None:
    expected_path = DOCUMENTS_DIR / SNAPSHOT_FILE

    assert generated_vita_output.exists(), "Missing generated Vita snapshot"
    assert expected_path.exists(), f"Missing committed snapshot: {SNAPSHOT_FILE}"

    actual_xml = normalize_osis_snapshot(generated_vita_output.read_text(encoding="utf-8"))
    expected_xml = normalize_osis_snapshot(expected_path.read_text(encoding="utf-8"))

    assert actual_xml == expected_xml


def test_scrape_vita_generates_expected_file(generated_vita_output: Path) -> None:
    assert generated_vita_output.name == SNAPSHOT_FILE
