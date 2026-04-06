"""Static site generator – orchestrates parsing and HTML output."""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass, field
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
# Collection configuration
# ---------------------------------------------------------------------------

#: Path to the default collections configuration shipped with the package.
_DEFAULT_COLLECTIONS_PATH = Path(__file__).parent / "collections.json"


@dataclass
class CollectionConfig:
    """A single collection definition loaded from JSON.

    Attributes:
        name:     Display name for the collection.
        work_ids: Work IDs matched case-insensitively against each
                  document's ``work_id`` (entire documents).
        osis_ids: OSIS division IDs matched case-insensitively against
                  each division's ``div_id`` (individual books/divisions).
    """

    name: str
    work_ids: tuple[str, ...] = field(default_factory=tuple)
    osis_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class CollectionEntry:
    """A single rendered entry within a collection group, used by templates.

    Attributes:
        title:    Display title for this entry.
        url:      Relative URL to link to (e.g. ``"kjv/index.html"`` for a
                  whole document, or ``"kjv/gen/gen-1.html"`` for a specific
                  division).
        doc_slug: Slug of the parent document; used by the chapter sidebar to
                  detect the currently-active document.
        work_id:  Source work identifier, shown as metadata.
        subtitle: Short descriptive line shown beneath the title (e.g.
                  ``"3 divisions"`` or ``"12 chapters"``).
    """

    title: str
    url: str
    doc_slug: str
    work_id: str
    subtitle: str


def _load_collections(path: Path | None = None) -> list[CollectionConfig]:
    """Load collection definitions from a JSON file.

    Each entry in the JSON array must have a ``"name"`` string and may
    include a ``"work_ids"`` array of strings and/or an ``"osis_ids"`` array
    of strings.  Work IDs are matched case-insensitively against each
    document's ``work_id`` (selecting the whole document).  OSIS IDs are
    matched case-insensitively against each division's ``div_id`` (selecting
    individual books or other top-level divisions).

    Args:
        path: Path to a JSON collections file.  If *None*, the default
              ``collections.json`` bundled with the package is used.

    Returns:
        An ordered list of :class:`CollectionConfig` objects.
    """
    resolved = path if path is not None else _DEFAULT_COLLECTIONS_PATH
    raw: list[dict] = json.loads(resolved.read_text(encoding="utf-8"))
    return [
        CollectionConfig(
            name=entry["name"],
            work_ids=tuple(entry.get("work_ids", [])),
            osis_ids=tuple(entry.get("osis_ids", [])),
        )
        for entry in raw
    ]


def _group_into_collections(
    documents: list[DocumentData],
    collections: list[CollectionConfig],
) -> list[dict[str, object]]:
    """Organize *documents* into named collections for the library index.

    An entry may appear in **more than one** collection if the admin
    configures overlapping ``work_ids`` or ``osis_ids`` lists.  Documents
    whose ``work_id`` does not match any collection, and whose divisions are
    not referenced by ``osis_ids`` in any collection, are placed under a
    final ``"Other"`` group.

    Args:
        documents:   All parsed documents to group.
        collections: Ordered collection definitions from :func:`_load_collections`.

    Returns:
        A list of dicts, each with ``"name"`` (str) and ``"documents"``
        (list[:class:`CollectionEntry`]), suitable for use in the index and
        chapter templates.
    """
    docs_by_work_id: dict[str, list[DocumentData]] = {}
    for doc in documents:
        docs_by_work_id.setdefault(doc.work_id.upper(), []).append(doc)

    # Build a flat index from OSIS division ID → [(DocumentData, DivisionData)]
    # so that ``osis_ids`` in a collection can resolve to specific books.
    divs_by_osis_id: dict[str, list[tuple[DocumentData, DivisionData]]] = {}
    for doc in documents:
        for div in doc.divisions:
            if div.div_id and div.div_id != "unknown":
                divs_by_osis_id.setdefault(div.div_id.upper(), []).append((doc, div))

    # Track which document slugs appear in at least one named collection so we
    # can compute the "Other" fallback.  Documents are NOT excluded from later
    # collections even after being added to an earlier one.
    seen_doc_slugs: set[str] = set()
    result: list[dict[str, object]] = []

    for config in collections:
        matches: list[CollectionEntry] = []
        seen_work_ids: set[str] = set()
        seen_osis_ids: set[str] = set()

        # --- work_ids: match entire documents ---
        for work_id in config.work_ids:
            normalized = work_id.upper()
            if normalized in seen_work_ids:
                continue
            seen_work_ids.add(normalized)
            for doc in docs_by_work_id.get(normalized, []):
                n_divs = len(doc.divisions)
                matches.append(
                    CollectionEntry(
                        title=doc.title,
                        url=f"{doc.slug}/index.html",
                        doc_slug=doc.slug,
                        work_id=doc.work_id,
                        subtitle=f"{n_divs} division{'s' if n_divs != 1 else ''}",
                    )
                )

        # --- osis_ids: match individual divisions (books) ---
        for osis_id in config.osis_ids:
            normalized = osis_id.upper()
            if normalized in seen_osis_ids:
                continue
            seen_osis_ids.add(normalized)
            for doc, div in divs_by_osis_id.get(normalized, []):
                if div.chapters:
                    url = f"{doc.slug}/{div.slug}/{div.chapters[0].slug}.html"
                else:
                    url = f"{doc.slug}/index.html"
                n_chapters = len(div.chapters)
                title = div.short_title if div.short_title else div.title
                matches.append(
                    CollectionEntry(
                        title=title,
                        url=url,
                        doc_slug=doc.slug,
                        work_id=doc.work_id,
                        subtitle=f"{n_chapters} chapter{'s' if n_chapters != 1 else ''}",
                    )
                )

        if matches:
            result.append({"name": config.name, "documents": matches})
            seen_doc_slugs.update(entry.doc_slug for entry in matches)

    # Build the "Other" group from documents not yet represented anywhere.
    other_entries: list[CollectionEntry] = []
    for doc in documents:
        if doc.slug not in seen_doc_slugs:
            n_divs = len(doc.divisions)
            other_entries.append(
                CollectionEntry(
                    title=doc.title,
                    url=f"{doc.slug}/index.html",
                    doc_slug=doc.slug,
                    work_id=doc.work_id,
                    subtitle=f"{n_divs} division{'s' if n_divs != 1 else ''}",
                )
            )
    if other_entries:
        result.append({"name": "Other", "documents": other_entries})

    return result


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


def _generate_index(
    env: Environment,
    documents: list[DocumentData],
    output_dir: Path,
    collections: list[CollectionConfig],
) -> None:
    """Render the top-level index.html listing all documents."""
    template = env.get_template("index.html")
    grouped = _group_into_collections(documents, collections)
    html = template.render(documents=documents, collections=grouped, version=__version__)
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
    collections: list[dict[str, object]],
) -> None:
    """Render a single chapter page."""
    template = env.get_template("chapter.html")

    rendered_body_blocks = _render_body_blocks(chapter)
    rendered_summary = render_content(chapter.summary) if chapter.summary else ""

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
        collections=collections,
        current_doc=doc,
        current_div=div,
        current_chapter=chapter,
        rendered_body_blocks=rendered_body_blocks,
        rendered_summary=rendered_summary,
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
    collections_path: Path | None = None,
) -> None:
    """Generate a static site from a list of OSIS XML files.

    Args:
        input_paths:       List of OSIS XML file paths to process.
        output_dir:        Directory where the HTML files will be written.
        clean:             If True, remove and recreate *output_dir* first.
        collections_path:  Optional path to a JSON file that defines which
                           documents belong to which library collection.  When
                           *None* the default ``collections.json`` bundled with
                           the package is used.
    """
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    env = _make_env()
    collections = _load_collections(collections_path)

    # Parse all documents
    documents: list[DocumentData] = []
    for path in input_paths:
        print(f"  Parsing {path.name} …")
        documents.append(parse_osis_file(path))

    # Group documents into collections once; reused by index and every chapter page.
    grouped = _group_into_collections(documents, collections)

    print("  Generating index …")
    _generate_index(env, documents, output_dir, collections)

    for doc in documents:
        print(f"  Generating '{doc.title}' ({len(doc.divisions)} division(s)) …")
        _generate_doc_index(env, doc, documents, output_dir)
        for div in doc.divisions:
            for chapter in div.chapters:
                _generate_chapter(env, doc, div, chapter, documents, output_dir, grouped)

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
        "--collections",
        type=Path,
        default=None,
        metavar="JSON_FILE",
        help=(
            "JSON file defining library collections and their work IDs "
            "(default: built-in collections.json)."
        ),
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

    generate_site(args.input, args.output, clean=args.clean, collections_path=args.collections)
