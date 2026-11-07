from __future__ import annotations

import importlib
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
DOCUMENTS_DIR = REPO_ROOT / "documents"
PACKAGE_SCRAPE_FBE_MODULE = "1_enoch_osis.scrape_fbe"
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


def normalize_osis_snapshot(xml: str) -> str:
    normalized = xml.replace("\r\n", "\n")
    return EVERSION_DATE_PATTERN.sub(r"\1SCRAPE_TIMESTAMP\2", normalized)


@lru_cache(maxsize=1)
def load_scrape_fbe_main() -> Any:
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))

    module = importlib.import_module(PACKAGE_SCRAPE_FBE_MODULE)
    return module.main


@pytest.fixture(scope="session")
def generated_fbe_output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not SOURCE_CACHE_TREE.exists():
        pytest.fail(f"Missing local FBE HTML cache tree at {SOURCE_CACHE_TREE}")

    output_dir = tmp_path_factory.mktemp("scrape-fbe-output")
    scrape_fbe_main = load_scrape_fbe_main()

    scrape_fbe_main(
        output_dir=str(output_dir),
        cache_dir=str(SOURCE_CACHE_DIR),
        delay=0,
        log_level="WARNING",
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
