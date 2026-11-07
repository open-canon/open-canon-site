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
PACKAGE_VITA_MODULE = "1_enoch_osis.scrape_vita_adae_et_evae"
SOURCE_CACHE_DIR = REPO_ROOT / ".cache" / "html"
SNAPSHOT_FILE = "vita-adae-et-evae.xml"
EVERSION_DATE_PATTERN = re.compile(
    r'(<date event="eversion" type="ISO" xml:lang="en" TEIform="date">)'
    r"[^<]+"
    r"(</date>)"
)


def normalize_osis_snapshot(xml: str) -> str:
    normalized = xml.replace("\r\n", "\n")
    return EVERSION_DATE_PATTERN.sub(r"\1SCRAPE_TIMESTAMP\2", normalized)


@lru_cache(maxsize=1)
def load_scrape_vita_main() -> Any:
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))

    module = importlib.import_module(PACKAGE_VITA_MODULE)
    return module.main


@pytest.fixture(scope="session")
def generated_vita_output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    source_cache_path = (
        SOURCE_CACHE_DIR / "www.sacred-texts.com" / "chr" / "apo" / "adamnev.htm"
    )
    if not source_cache_path.exists():
        pytest.skip(f"Missing local Vita HTML cache at {source_cache_path}")

    output_dir = tmp_path_factory.mktemp("scrape-vita-output")
    output_path = output_dir / SNAPSHOT_FILE
    scrape_vita_main = load_scrape_vita_main()

    scrape_vita_main(
        output=str(output_path),
        delay=0,
        cache_dir=str(SOURCE_CACHE_DIR),
        log_level="WARNING",
    )
    return output_path


def test_scrape_vita_matches_snapshot(generated_vita_output: Path) -> None:
    expected_path = DOCUMENTS_DIR / SNAPSHOT_FILE

    assert generated_vita_output.exists(), "Missing generated Vita snapshot"
    assert expected_path.exists(), f"Missing committed snapshot: {SNAPSHOT_FILE}"

    actual_xml = normalize_osis_snapshot(
        generated_vita_output.read_text(encoding="utf-8")
    )
    expected_xml = normalize_osis_snapshot(expected_path.read_text(encoding="utf-8"))

    assert actual_xml == expected_xml


def test_scrape_vita_generates_expected_file(generated_vita_output: Path) -> None:
    assert generated_vita_output.name == SNAPSHOT_FILE
