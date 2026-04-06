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


def test_index_page_groups_documents_into_named_collection(output_dir, tmp_path):
    """Documents whose work_id matches a configured collection appear under that heading."""
    bom_path = tmp_path / "bom.osis.xml"
    bom_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<osis xmlns="http://www.bibletechnologies.net/2003/OSIS/namespace">
    <osisText osisIDWork="BOM" xml:lang="en">
        <header>
            <work osisWork="BOM">
                <title>Book of Mormon</title>
            </work>
        </header>
        <div type="book" osisID="1Ne">
            <div type="chapter" osisID="1Ne.1">
                <verse osisID="1Ne.1.1">I, Nephi.</verse>
            </div>
        </div>
    </osisText>
</osis>
""",
        encoding="utf-8",
    )

    generate_site([bom_path], output_dir)
    html = (output_dir / "index.html").read_text()

    assert "Standard Works" in html
    assert "Book of Mormon" in html
    assert "<details" in html
    assert "<summary" in html
    assert "bom/index.html" in html


def test_index_page_places_unmatched_documents_in_other(output_dir):
    """Documents whose work_id is not in any collection appear under 'Other'."""
    generate_site([SAMPLE_OSIS], output_dir)
    html = (output_dir / "index.html").read_text()
    assert "Other" in html
    assert "King James Version" in html
    assert "kjv/index.html" in html


def test_index_page_uses_custom_collections_file(output_dir, tmp_path):
    """Passing a custom collections JSON file overrides the default grouping."""
    custom_collections = tmp_path / "my_collections.json"
    custom_collections.write_text(
        '[{"name": "My Texts", "work_ids": ["KJV"]}]',
        encoding="utf-8",
    )

    generate_site([SAMPLE_OSIS], output_dir, collections_path=custom_collections)
    html = (output_dir / "index.html").read_text()

    assert "My Texts" in html
    assert "King James Version" in html
    # No "Other" group because KJV was explicitly matched
    assert "Other" not in html


def test_sidebar_shows_collections_on_chapter_page(output_dir, tmp_path):
    """Chapter page sidebar groups documents into nested collapsible collections."""
    bom_path = tmp_path / "bom.osis.xml"
    bom_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<osis xmlns="http://www.bibletechnologies.net/2003/OSIS/namespace">
    <osisText osisIDWork="BOM" xml:lang="en">
        <header>
            <work osisWork="BOM">
                <title>Book of Mormon</title>
            </work>
        </header>
        <div type="book" osisID="1Ne">
            <div type="chapter" osisID="1Ne.1">
                <verse osisID="1Ne.1.1">I, Nephi.</verse>
            </div>
        </div>
    </osisText>
</osis>
""",
        encoding="utf-8",
    )

    generate_site([bom_path], output_dir)
    html = (output_dir / "bom" / "1ne" / "1ne-1.html").read_text()

    # Outer Library section is collapsible
    assert '<details class="nav-section" open>' in html
    assert "Library" in html
    # Named collection appears as a nested details inside Library
    assert '<details class="nav-collection">' in html
    assert "Standard Works" in html
    assert "Book of Mormon" in html


def test_work_can_appear_in_multiple_collections(output_dir, tmp_path):
    """A document whose work_id is listed in two collections appears under both."""
    custom_collections = tmp_path / "multi.json"
    custom_collections.write_text(
        '[{"name": "Group A", "work_ids": ["KJV"]},  {"name": "Group B", "work_ids": ["KJV"]}]',
        encoding="utf-8",
    )

    generate_site([SAMPLE_OSIS], output_dir, collections_path=custom_collections)
    html = (output_dir / "index.html").read_text()

    assert "Group A" in html
    assert "Group B" in html
    # KJV appears in both groups, so the title should occur at least twice
    assert html.count("King James Version") >= 2
    # No "Other" since KJV is matched
    assert "Other" not in html


def test_footer_has_github_link(output_dir):
    generate_site([SAMPLE_OSIS], output_dir)
    html = (output_dir / "index.html").read_text()
    assert 'href="https://github.com/open-canon/open-canon-site"' in html
    assert 'aria-label="GitHub repository"' in html
    assert 'footer-github-icon' in html


def test_collection_uses_work_id_order_from_json(output_dir, tmp_path):
    """Documents inside a collection follow the JSON work_ids order, not input file order."""
    bom_path = tmp_path / "bom.osis.xml"
    bom_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<osis xmlns="http://www.bibletechnologies.net/2003/OSIS/namespace">
    <osisText osisIDWork="BOM" xml:lang="en">
        <header>
            <work osisWork="BOM">
                <title>Book of Mormon</title>
            </work>
        </header>
        <div type="book" osisID="1Ne">
            <div type="chapter" osisID="1Ne.1">
                <verse osisID="1Ne.1.1">I, Nephi.</verse>
            </div>
        </div>
    </osisText>
</osis>
""",
        encoding="utf-8",
    )
    custom_collections = tmp_path / "ordered.json"
    custom_collections.write_text(
        '[{"name": "Scriptures", "work_ids": ["BOM", "KJV"]}]',
        encoding="utf-8",
    )

    generate_site([SAMPLE_OSIS, bom_path], output_dir, collections_path=custom_collections)
    html = (output_dir / "index.html").read_text()

    assert html.index("Book of Mormon") < html.index("King James Version")


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


def test_generate_site_renders_nested_book_chapters(output_dir, tmp_path):
    osis_path = tmp_path / "nested_books.osis.xml"
    osis_path.write_text(
        """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<osis xmlns=\"http://www.bibletechnologies.net/2003/OSIS/namespace\">
    <osisText osisIDWork=\"TEST\" xml:lang=\"en\">
        <header>
            <work osisWork=\"TEST\">
                <title>Nested Book Test</title>
            </work>
        </header>
        <div type=\"book\" osisID=\"Collection\">
            <title>Collection</title>
            <div type=\"introduction\">
                <title>Introduction</title>
                <p>Collection preface.</p>
            </div>
            <div type=\"book\" osisID=\"Collection.Child\">
                <title>The Child Book</title>
                <div type=\"chapter\" osisID=\"Collection.Child.1\">
                    <verse osisID=\"Collection.Child.1.1\">Verse one.</verse>
                </div>
            </div>
        </div>
    </osisText>
</osis>
""",
        encoding="utf-8",
    )

    generate_site([osis_path], output_dir)

    intro_html = (output_dir / "test" / "collection" / "front-1-introduction.html").read_text()
    chapter_html = (
        output_dir / "test" / "collection-child" / "collection-child-1.html"
    ).read_text()

    assert "Collection preface." in intro_html
    assert 'data-verse="Collection.Child.1.1"' in chapter_html
    assert "Verse one." in chapter_html


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


def test_generate_site_renders_chapter_summary(output_dir, tmp_path):
    osis_path = tmp_path / "summary.osis.xml"
    osis_path.write_text(
        """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<osis xmlns=\"http://www.bibletechnologies.net/2003/OSIS/namespace\">
    <osisText osisIDWork=\"TEST\" xml:lang=\"en\">
        <header>
            <work osisWork=\"TEST\">
                <title>Summary Test</title>
            </work>
        </header>
        <div type=\"book\" osisID=\"Book\">
            <chapter osisID=\"Book.1\">
                <div type=\"summary\">
                    <p>The summary of this chapter.</p>
                </div>
                <verse sID=\"Book.1.1\" osisID=\"Book.1.1\"/>Verse one.<verse eID=\"Book.1.1\"/>
            </chapter>
        </div>
    </osisText>
</osis>
""",
        encoding="utf-8",
    )

    generate_site([osis_path], output_dir)

    html = (output_dir / "test" / "book" / "book-1.html").read_text()
    assert "The summary of this chapter." in html
    assert 'class="chapter-summary"' in html


def test_generate_site_sidebar_shows_conventional_name(output_dir, tmp_path):
    """Books with a ``short`` title attribute show the conventional name in the sidebar."""
    osis_path = tmp_path / "short_title.osis.xml"
    osis_path.write_text(
        """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<osis xmlns=\"http://www.bibletechnologies.net/2003/OSIS/namespace\">
    <osisText osisIDWork=\"TEST\" xml:lang=\"en\">
        <header>
            <work osisWork=\"TEST\">
                <title>Short Title Test</title>
            </work>
        </header>
        <div type=\"book\" osisID=\"1Ne\">
            <title short=\"1 Nephi\">The First Book of Nephi</title>
            <div type=\"chapter\" osisID=\"1Ne.1\">
                <verse osisID=\"1Ne.1.1\">I, Nephi.</verse>
            </div>
        </div>
        <div type=\"book\" osisID=\"Enoch\">
            <title short=\"1 Enoch\">The Book of Enoch</title>
            <div type=\"chapter\" osisID=\"Enoch.1\">
                <verse osisID=\"Enoch.1.1\">Words of Enoch.</verse>
            </div>
        </div>
        <div type=\"book\" osisID=\"Gen\">
            <title>Genesis</title>
            <div type=\"chapter\" osisID=\"Gen.1\">
                <verse osisID=\"Gen.1.1\">In the beginning.</verse>
            </div>
        </div>
    </osisText>
</osis>
""",
        encoding="utf-8",
    )

    generate_site([osis_path], output_dir)

    html = (output_dir / "test" / "1ne" / "1ne-1.html").read_text()
    # Books with a short attribute show only the conventional name
    assert "1 Nephi" in html
    assert "1 Enoch" in html
    # The formal long titles must NOT appear as standalone sidebar entries
    assert "The First Book of Nephi (1 Nephi)" not in html
    assert "The Book of Enoch (1 Enoch)" not in html
    # Books without a short attribute show only their title, unchanged
    assert "Genesis (" not in html
    assert "Genesis" in html
