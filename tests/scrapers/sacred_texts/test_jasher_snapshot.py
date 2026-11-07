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
PACKAGE_JASHER_MODULE = "1_enoch_osis.scrape_jasher"
SOURCE_CACHE_DIR = REPO_ROOT / ".cache" / "html"
INDEX_CACHE_FILE = (
    SOURCE_CACHE_DIR / "sacred-texts.com" / "chr" / "apo" / "jasher" / "index.htm"
)
SNAPSHOT_FILE = "jasher.xml"
EVERSION_DATE_PATTERN = re.compile(
    r'(<date event="eversion" type="ISO" xml:lang="en" TEIform="date">)'
    r"[^<]+"
    r"(</date>)"
)


def normalize_osis_snapshot(xml: str) -> str:
    normalized = xml.replace("\r\n", "\n")
    return EVERSION_DATE_PATTERN.sub(r"\1SCRAPE_TIMESTAMP\2", normalized)


@lru_cache(maxsize=1)
def load_scrape_jasher_main() -> Any:
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))

    module = importlib.import_module(PACKAGE_JASHER_MODULE)
    return module.main


@pytest.fixture(scope="session")
def generated_jasher_output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    module = importlib.import_module(PACKAGE_JASHER_MODULE)

    if not INDEX_CACHE_FILE.exists():
        pytest.skip(f"Missing Jasher index cache: {INDEX_CACHE_FILE}")

    index_source = INDEX_CACHE_FILE.read_text(encoding="utf-8")
    if not module.JasherParser.is_valid_index(index_source):
        pytest.skip(
            f"Missing valid original-site Jasher index cache: {INDEX_CACHE_FILE}"
        )

    missing_cache_files = []
    invalid_cache_files = []
    for chapter_number in module.EXPECTED_CHAPTERS:
        cache_file = (
            SOURCE_CACHE_DIR
            / "sacred-texts.com"
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
            "Missing complete local Jasher cache; first missing file: "
            f"{missing_cache_files[0]}"
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
        output=str(output_path),
        delay=0,
        cache_dir=str(SOURCE_CACHE_DIR),
        log_level="WARNING",
    )
    return output_path


def test_scrape_jasher_matches_snapshot(generated_jasher_output: Path) -> None:
    expected_path = DOCUMENTS_DIR / SNAPSHOT_FILE

    assert generated_jasher_output.exists(), "Missing generated Jasher snapshot"
    assert expected_path.exists(), f"Missing committed snapshot: {SNAPSHOT_FILE}"

    actual_xml = normalize_osis_snapshot(
        generated_jasher_output.read_text(encoding="utf-8")
    )
    expected_xml = normalize_osis_snapshot(expected_path.read_text(encoding="utf-8"))

    assert actual_xml == expected_xml


def test_scrape_jasher_generates_expected_file(generated_jasher_output: Path) -> None:
    assert generated_jasher_output.name == SNAPSHOT_FILE


def test_scrape_jasher_omits_footer_boilerplate(generated_jasher_output: Path) -> None:
    xml = generated_jasher_output.read_text(encoding="utf-8")

    assert "Next: Chapter" not in xml
    assert "Sacred Texts | Christianity" not in xml
    assert "THE END" not in xml
