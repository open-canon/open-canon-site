"""Static site generator – orchestrates parsing and HTML output."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from open_canon_site import __version__
from open_canon_site.parser import (
    ChapterData,
    DivisionData,
    DocumentData,
    NoteData,
    VerseData,
    parse_osis_file,
)
from open_canon_site.renderer import render_content, render_note_content

# ---------------------------------------------------------------------------
# Jinja2 environment
# ---------------------------------------------------------------------------


def _make_env() -> Environment:
    env = Environment(
        loader=PackageLoader("open_canon_site", "templates"),
        autoescape=select_autoescape(["html"]),
    )
    return env


# ---------------------------------------------------------------------------
# Template context helpers
# ---------------------------------------------------------------------------


def _verse_html(verse: VerseData) -> str:
    """Render the inline text of a verse (note markers included)."""
    nc: list[int] = [0]
    return render_content(verse.content, nc)


def _all_notes_html(notes: list[NoteData]) -> list[dict]:
    """Return a list of dicts ready for the template notes tray."""
    result = []
    for note in notes:
        result.append(
            {
                "id": note.note_id,
                "verse_id": note.verse_id,
                "html": render_note_content(note.content),
            }
        )
    return result


def _chapter_notes(chapter: ChapterData) -> list[NoteData]:
    """Collect all notes across all verses in a chapter."""
    notes: list[NoteData] = list(chapter.notes)
    for verse in chapter.verses:
        notes.extend(verse.notes)
    return notes


# ---------------------------------------------------------------------------
# Page generation
# ---------------------------------------------------------------------------


def _generate_index(env: Environment, documents: list[DocumentData], output_dir: Path) -> None:
    """Render the top-level index.html listing all documents."""
    template = env.get_template("index.html")
    html = template.render(documents=documents, version=__version__)
    (output_dir / "index.html").write_text(html, encoding="utf-8")


def _chapter_url(doc: DocumentData, div: DivisionData, chapter: ChapterData) -> str:
    return f"{doc.slug}/{div.slug}/{chapter.slug}.html"


def _render_body_blocks(chapter: ChapterData) -> list[dict[str, str | None]]:
    """Render body items individually so top-level sections can receive anchors."""
    note_counter = [0]
    sections_by_index = {section.item_index: section for section in chapter.sections}
    blocks: list[dict[str, str | None]] = []

    for item_index, item in enumerate(chapter.body):
        section = sections_by_index.get(item_index)
        blocks.append(
            {
                "anchor": section.anchor if section else None,
                "html": render_content([item], note_counter),
            }
        )

    return blocks


def _generate_chapter(
    env: Environment,
    doc: DocumentData,
    div: DivisionData,
    chapter: ChapterData,
    documents: list[DocumentData],
    output_dir: Path,
) -> None:
    """Render a single chapter page."""
    template = env.get_template("chapter.html")

    rendered_body_blocks = _render_body_blocks(chapter)

    # Build per-verse rendered data
    rendered_verses = []
    for verse in chapter.verses:
        rendered_verses.append(
            {
                "id": verse.verse_id,
                "number": verse.number,
                "html": _verse_html(verse),
                "has_notes": bool(verse.notes),
                "note_ids": [n.note_id for n in verse.notes],
            }
        )

    notes = _all_notes_html(_chapter_notes(chapter))

    # Prev / next chapter navigation
    all_chapters = [(d, c) for d in doc.divisions for c in d.chapters]
    current_idx = next(
        (i for i, (d, c) in enumerate(all_chapters) if c.chapter_id == chapter.chapter_id), -1
    )
    prev_chapter_url = (
        _chapter_url(doc, all_chapters[current_idx - 1][0], all_chapters[current_idx - 1][1])
        if current_idx > 0
        else None
    )
    next_chapter_url = (
        _chapter_url(doc, all_chapters[current_idx + 1][0], all_chapters[current_idx + 1][1])
        if current_idx >= 0 and current_idx < len(all_chapters) - 1
        else None
    )

    html = template.render(
        documents=documents,
        current_doc=doc,
        current_div=div,
        current_chapter=chapter,
        rendered_body_blocks=rendered_body_blocks,
        rendered_verses=rendered_verses,
        notes=notes,
        prev_chapter_url=prev_chapter_url,
        next_chapter_url=next_chapter_url,
        chapter_url_fn=lambda d, di, c: _chapter_url(d, di, c),
        version=__version__,
    )

    dest = output_dir / doc.slug / div.slug / f"{chapter.slug}.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html, encoding="utf-8")


def _generate_doc_index(
    env: Environment,
    doc: DocumentData,
    documents: list[DocumentData],
    output_dir: Path,
) -> None:
    """Render a per-document index that redirects to the first chapter."""
    template = env.get_template("doc_index.html")
    first_url: str | None = None
    if doc.divisions and doc.divisions[0].chapters:
        first_div = doc.divisions[0]
        first_chap = first_div.chapters[0]
        first_url = f"{first_div.slug}/{first_chap.slug}.html"

    html = template.render(
        documents=documents,
        current_doc=doc,
        first_chapter_url=first_url,
        version=__version__,
    )
    dest = output_dir / doc.slug / "index.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# Static asset copying
# ---------------------------------------------------------------------------


def _copy_static(output_dir: Path) -> None:
    """Copy static CSS/JS assets to the output directory."""
    static_src = Path(__file__).parent / "static"
    if static_src.exists():
        static_dst = output_dir / "static"
        if static_dst.exists():
            shutil.rmtree(static_dst)
        shutil.copytree(static_src, static_dst)


# ---------------------------------------------------------------------------
# Main generation entry point
# ---------------------------------------------------------------------------


def generate_site(
    input_paths: list[Path],
    output_dir: Path,
    clean: bool = False,
) -> None:
    """Generate a static site from a list of OSIS XML files.

    Args:
        input_paths:    List of OSIS XML file paths to process.
        output_dir:     Directory where the HTML files will be written.
        clean:          If True, remove and recreate *output_dir* first.
    """
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    env = _make_env()

    # Parse all documents
    documents: list[DocumentData] = []
    for path in input_paths:
        print(f"  Parsing {path.name} …")
        documents.append(parse_osis_file(path))

    print("  Generating index …")
    _generate_index(env, documents, output_dir)

    for doc in documents:
        print(f"  Generating '{doc.title}' ({len(doc.divisions)} division(s)) …")
        _generate_doc_index(env, doc, documents, output_dir)
        for div in doc.divisions:
            for chapter in div.chapters:
                _generate_chapter(env, doc, div, chapter, documents, output_dir)

    _copy_static(output_dir)
    print(f"  Site written to {output_dir}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for the ``open-canon-site`` command."""
    parser = argparse.ArgumentParser(
        description="Generate a static study-site from OSIS XML documents."
    )
    parser.add_argument(
        "input",
        nargs="+",
        type=Path,
        metavar="OSIS_FILE",
        help="One or more OSIS XML files to render.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("output"),
        metavar="DIR",
        help="Output directory (default: ./output).",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove the output directory before generating.",
    )
    args = parser.parse_args()

    print("Open Canon Site Generator")
    print(f"  Input files : {[str(p) for p in args.input]}")
    print(f"  Output dir  : {args.output}")

    generate_site(args.input, args.output, clean=args.clean)
