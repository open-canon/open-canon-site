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


def test_library_section_is_collapsible(output_dir):
    generate_site([SAMPLE_OSIS], output_dir)
    html = (output_dir / "kjv" / "gen" / "gen-1.html").read_text()
    # Library section must use a <details> element so it is collapsible
    assert "<details" in html
    assert "<summary" in html
    # The summary should contain the "Library" label
    assert "Library" in html
    # The details element should be open by default (open attribute on <details>)
    assert '<details class="nav-section" open>' in html


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


def test_generate_site_renders_front_matter_page(output_dir, tmp_path):
    osis_path = tmp_path / "front.osis.xml"
    osis_path.write_text(
        """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<osis xmlns=\"http://www.bibletechnologies.net/2003/OSIS/namespace\">
    <osisText osisIDWork=\"TEST\" xml:lang=\"en\">
        <header>
            <work osisWork=\"TEST\">
                <title>Front Test</title>
            </work>
        </header>
        <div type=\"book\" osisID=\"Book\">
            <div type=\"front\">
                <head>Preface</head>
                <p>Introductory material.</p>
            </div>
            <div type=\"chapter\" osisID=\"Book.1\">
                <verse osisID=\"Book.1.1\">Verse one.</verse>
            </div>
        </div>
    </osisText>
</osis>
""",
        encoding="utf-8",
    )

    generate_site([osis_path], output_dir)

    html = (output_dir / "test" / "book" / "front-1-preface.html").read_text()
    assert "Introductory material." in html
    assert "Preface" in html


def test_generate_site_renders_prose_only_chapter(output_dir, tmp_path):
    osis_path = tmp_path / "prose.osis.xml"
    osis_path.write_text(
        """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<osis xmlns=\"http://www.bibletechnologies.net/2003/OSIS/namespace\">
    <osisText osisIDWork=\"TEST\" xml:lang=\"en\">
        <header>
            <work osisWork=\"TEST\">
                <title>Prose Test</title>
            </work>
        </header>
        <div type=\"book\" osisID=\"Book\">
            <div type=\"chapter\" osisID=\"Book.1\">
                <title type=\"chapter\">Chapter 1</title>
                <p>Opening prose.</p>
            </div>
        </div>
    </osisText>
</osis>
""",
        encoding="utf-8",
    )

    generate_site([osis_path], output_dir)

    html = (output_dir / "test" / "book" / "book-1.html").read_text()
    assert "Opening prose." in html
    assert "No content in this chapter." not in html


def test_generate_site_sidebar_links_to_body_sections(output_dir, tmp_path):
    osis_path = tmp_path / "sections.osis.xml"
    osis_path.write_text(
        """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<osis xmlns=\"http://www.bibletechnologies.net/2003/OSIS/namespace\">
    <osisText osisIDWork=\"TEST\" xml:lang=\"en\">
        <header>
            <work osisWork=\"TEST\">
                <title>Section Test</title>
            </work>
        </header>
        <div type=\"book\" osisID=\"Book\">
            <div type=\"front\">
                <head>Introduction</head>
                <div type=\"section\">
                    <head>Overview</head>
                    <p>Overview text.</p>
                </div>
                <div type=\"section\">
                    <head>Historical Setting</head>
                    <p>Historical setting text.</p>
                </div>
            </div>
        </div>
    </osisText>
</osis>
""",
        encoding="utf-8",
    )

    generate_site([osis_path], output_dir)

    html = (output_dir / "test" / "book" / "front-1-introduction.html").read_text()
    css = (output_dir / "static" / "style.css").read_text()
    assert 'href="#overview"' in html
    assert 'href="#historical-setting"' in html
    assert 'id="overview"' in html
    assert 'id="historical-setting"' in html
    assert ">Overview<" in html
    assert ">Historical Setting<" in html
    assert ".chapter-section" in css
    assert "scroll-margin-top" in css
    assert "overview.html" not in html


def test_generate_site_uses_arabic_numerals_for_roman_chapter_titles(output_dir, tmp_path):
    osis_path = tmp_path / "roman.osis.xml"
    osis_path.write_text(
        """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<osis xmlns=\"http://www.bibletechnologies.net/2003/OSIS/namespace\">
    <osisText osisIDWork=\"TEST\" xml:lang=\"en\">
        <header>
            <work osisWork=\"TEST\">
                <title>Roman Test</title>
            </work>
        </header>
        <div type=\"book\" osisID=\"Book\">
            <title>Book Title</title>
            <div type=\"chapter\" osisID=\"Book.18\">
                <title type=\"chapter\">CHAPTER XVIII.</title>
                <verse osisID=\"Book.18.1\">Verse one.</verse>
            </div>
        </div>
    </osisText>
</osis>
""",
        encoding="utf-8",
    )

    generate_site([osis_path], output_dir)

    html = (output_dir / "test" / "book" / "book-18.html").read_text()
    assert "Chapter 18" in html
    assert "Book Title — Chapter 18" in html
    assert "CHAPTER XVIII" not in html
