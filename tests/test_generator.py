"""Integration test: run the full generator pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from open_canon_site.generator import generate_site


SAMPLE_OSIS = Path(__file__).parent.parent / "sample_data" / "sample.osis.xml"


@pytest.fixture()
def output_dir(tmp_path):
    return tmp_path / "site"


def test_generate_site_creates_index(output_dir):
    generate_site([SAMPLE_OSIS], output_dir)
    assert (output_dir / "index.html").exists()


def test_generate_site_creates_chapter_pages(output_dir):
    generate_site([SAMPLE_OSIS], output_dir)
    assert (output_dir / "kjv" / "gen" / "gen-1.html").exists()
    assert (output_dir / "kjv" / "gen" / "gen-2.html").exists()
    assert (output_dir / "kjv" / "gen" / "gen-3.html").exists()


def test_generate_site_copies_static_assets(output_dir):
    generate_site([SAMPLE_OSIS], output_dir)
    assert (output_dir / "static" / "style.css").exists()
    assert (output_dir / "static" / "notes-sync.js").exists()


def test_chapter_page_has_three_columns(output_dir):
    generate_site([SAMPLE_OSIS], output_dir)
    html = (output_dir / "kjv" / "gen" / "gen-1.html").read_text()
    assert "sidebar-nav" in html
    assert "content-main" in html
    assert "notes-tray" in html


def test_chapter_page_has_verses(output_dir):
    generate_site([SAMPLE_OSIS], output_dir)
    html = (output_dir / "kjv" / "gen" / "gen-1.html").read_text()
    assert 'data-verse="Gen.1.1"' in html
    assert "In the beginning" in html


def test_chapter_page_has_notes(output_dir):
    generate_site([SAMPLE_OSIS], output_dir)
    html = (output_dir / "kjv" / "gen" / "gen-1.html").read_text()
    assert "notes-tray" in html
    assert "note-item" in html
    assert "Gen.1.1" in html


def test_chapter_page_has_nav_links(output_dir):
    generate_site([SAMPLE_OSIS], output_dir)
    html = (output_dir / "kjv" / "gen" / "gen-1.html").read_text()
    # Left nav should show all three chapters
    assert "gen-1.html" in html
    assert "gen-2.html" in html
    assert "gen-3.html" in html


def test_next_prev_navigation(output_dir):
    generate_site([SAMPLE_OSIS], output_dir)
    # Chapter 1 should have a "next chapter" link but no "prev"
    html1 = (output_dir / "kjv" / "gen" / "gen-1.html").read_text()
    assert "Next chapter" in html1
    assert "Previous chapter" not in html1

    # Chapter 2 should have both
    html2 = (output_dir / "kjv" / "gen" / "gen-2.html").read_text()
    assert "Previous chapter" in html2
    assert "Next chapter" in html2


def test_clean_flag_removes_old_output(output_dir):
    # First generation
    generate_site([SAMPLE_OSIS], output_dir)
    stale_file = output_dir / "stale.html"
    stale_file.write_text("stale")

    # Second generation with --clean
    generate_site([SAMPLE_OSIS], output_dir, clean=True)
    assert not stale_file.exists()


def test_index_page_lists_document(output_dir):
    generate_site([SAMPLE_OSIS], output_dir)
    html = (output_dir / "index.html").read_text()
    assert "King James Version" in html
    assert "kjv/index.html" in html
