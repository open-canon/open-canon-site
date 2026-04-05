"""Parse OSIS documents into structured data for site generation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyosis
from pyosis.generated.osis_core_2_1_1 import (
    ChapterCt,
    DivCt,
    HeadCt,
    NoteCt,
    OsisDivs,
    OsisTextCt,
    TitleCt,
    VerseCt,
)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class NoteData:
    """A single extracted note."""

    note_id: str
    verse_id: str  # OSIS ID of the parent verse/context (e.g. "Gen.1.1")
    content: list[Any]  # raw pyosis content items


@dataclass
class VerseData:
    """A single verse or paragraph with its associated notes."""

    verse_id: str  # OSIS ID (e.g. "Gen.1.1")
    number: str  # display number (e.g. "1")
    content: list[Any]  # raw pyosis content items (strings + inline elements)
    notes: list[NoteData] = field(default_factory=list)


@dataclass
class ChapterData:
    """A chapter (or chapter-level division)."""

    chapter_id: str  # OSIS ID (e.g. "Gen.1")
    number: str  # display number (e.g. "1")
    slug: str  # URL-safe identifier
    title: str  # display title
    body: list[Any] = field(default_factory=list)
    sections: list[SectionData] = field(default_factory=list)
    notes: list[NoteData] = field(default_factory=list)
    verses: list[VerseData] = field(default_factory=list)


@dataclass
class SectionData:
    """A same-page section within a chapter or front-matter page."""

    title: str
    anchor: str
    item_index: int


@dataclass
class DivisionData:
    """A top-level division (e.g. a book) within a document."""

    div_id: str  # OSIS ID (e.g. "Gen")
    slug: str  # URL-safe identifier
    title: str  # display title
    chapters: list[ChapterData] = field(default_factory=list)


@dataclass
class DocumentData:
    """A full OSIS document (work)."""

    work_id: str  # osisIDWork value
    slug: str  # URL-safe identifier
    title: str  # display title
    divisions: list[DivisionData] = field(default_factory=list)
    source_path: Path | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """Convert an OSIS ID or title to a URL-safe slug."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _text_of(content: list[Any]) -> str:
    """Extract plain text from a pyosis content list, skipping notes."""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, NoteCt):
            continue
        elif hasattr(item, "content"):
            parts.append(_text_of(item.content))
        else:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                parts.append(text)
            children = getattr(item, "children", None)
            if isinstance(children, list):
                parts.append(_text_of(children))
    return "".join(parts).strip()


def _extract_title(items: list[Any]) -> str:
    """Return the first TitleCt or HeadCt text found in *items*."""
    for item in items:
        if _is_heading_item(item):
            return _text_of([item])
    return ""


def _normalize_chapter_title(title: str, chapter_number: str) -> str:
    """Convert standalone Roman-numeral chapter titles to Arabic numerals."""
    normalized = re.match(r"^chapter\s+[ivxlcdm]+[\s.]*$", title.strip(), re.IGNORECASE)
    if normalized:
        return f"Chapter {chapter_number}"
    return title


def _is_heading_item(item: Any) -> bool:
    qname = getattr(item, "qname", "")
    return isinstance(item, (TitleCt, HeadCt)) or str(qname).endswith("}head")


def _copy_item_with_updates(item: Any, updates: dict[str, Any]) -> Any:
    if hasattr(item, "model_copy"):
        return item.model_copy(update=updates)
    return item


def _section_title_of(item: Any) -> str:
    if _is_heading_item(item):
        return _text_of([item])

    content = getattr(item, "content", None)
    if isinstance(content, list):
        return _extract_title(content)

    children = getattr(item, "children", None)
    if isinstance(children, list):
        return _extract_title(children)

    return ""


def _extract_sections_from_body(body: list[Any]) -> list[SectionData]:
    sections: list[SectionData] = []
    used_anchors: dict[str, int] = {}

    for item_index, item in enumerate(body):
        title = _section_title_of(item)
        if not title:
            continue

        base_anchor = _slugify(title) or "section"
        count = used_anchors.get(base_anchor, 0) + 1
        used_anchors[base_anchor] = count
        anchor = base_anchor if count == 1 else f"{base_anchor}-{count}"

        sections.append(SectionData(title=title, anchor=anchor, item_index=item_index))

    return sections


# ---------------------------------------------------------------------------
# Content collection helpers (milestone vs. contained)
# ---------------------------------------------------------------------------


def _collect_milestone_groups(content: list[Any]) -> list[dict]:
    """Group flat mixed content around verse/chapter milestones.

    Returns a list of dicts with keys:
        - "type": "verse" | "chapter_title" | "other"
        - "verse_id": str (for type=="verse")
        - "chapter_id": str (for type=="chapter_title")
        - "items": list of content items
    """
    groups: list[dict] = []
    current_verse_id: str | None = None
    current_items: list[Any] = []

    def flush(vid: str | None) -> None:
        nonlocal current_items
        if vid is not None and any(
            (isinstance(i, str) and i.strip()) or isinstance(i, NoteCt) for i in current_items
        ):
            groups.append({"type": "verse", "verse_id": vid, "items": list(current_items)})
        elif current_items:
            # Non-verse content (titles, etc.)
            for item in current_items:
                if isinstance(item, TitleCt):
                    groups.append({"type": "title", "items": [item]})
        current_items = []

    for item in content:
        if isinstance(item, VerseCt):
            if item.s_id:
                # Start of a new verse milestone
                flush(current_verse_id)
                current_verse_id = item.s_id
            elif item.e_id:
                # End of a verse milestone
                flush(current_verse_id)
                current_verse_id = None
        elif isinstance(item, ChapterCt):
            flush(current_verse_id)
            current_verse_id = None
        elif isinstance(item, TitleCt):
            flush(current_verse_id)
            groups.append({"type": "title", "items": [item]})
            current_items = []
        else:
            current_items.append(item)

    flush(current_verse_id)
    return groups


def _is_chapter_level(div: DivCt) -> bool:
    """Return True when the div represents a chapter."""
    return div.type_value in (OsisDivs.CHAPTER, "chapter") or (
        isinstance(div.type_value, str) and div.type_value.lower() == "chapter"
    )


def _is_book_level(div: DivCt) -> bool:
    """Return True when the div is a book or higher section."""
    book_types = {
        OsisDivs.BOOK,
        OsisDivs.BOOK_GROUP,
        OsisDivs.SECTION,
        OsisDivs.INTRODUCTION,
        OsisDivs.PREFACE,
        OsisDivs.GLOSSARY,
        OsisDivs.INDEX,
        OsisDivs.MAP,
        OsisDivs.APPENDIX,
    }
    return div.type_value in book_types or (
        isinstance(div.type_value, str)
        and div.type_value.lower() in {"book", "bookgroup", "major", "testament"}
    )


# ---------------------------------------------------------------------------
# Verse extraction
# ---------------------------------------------------------------------------

_NOTE_COUNTER: int = 0


def _next_note_id(doc_slug: str, verse_id: str) -> str:
    global _NOTE_COUNTER
    _NOTE_COUNTER += 1
    return f"{doc_slug}-n{_NOTE_COUNTER}"


def _extract_notes_from_content(
    content: list[Any], verse_id: str, doc_slug: str
) -> tuple[list[Any], list[NoteData]]:
    """Walk *content*, pull out NoteCt instances into NoteData, return (cleaned_content, notes)."""
    cleaned: list[Any] = []
    notes: list[NoteData] = []
    for item in content:
        cleaned_item, item_notes = _extract_notes_from_item(item, verse_id, doc_slug)
        notes.extend(item_notes)
        if cleaned_item is not None:
            cleaned.append(cleaned_item)
    return cleaned, notes


def _extract_notes_from_item(
    item: Any, context_id: str, doc_slug: str
) -> tuple[Any, list[NoteData]]:
    if isinstance(item, NoteCt):
        note_id = _next_note_id(doc_slug, context_id)
        return ("note_marker", note_id), [
            NoteData(note_id=note_id, verse_id=context_id, content=item.content)
        ]

    notes: list[NoteData] = []

    content = getattr(item, "content", None)
    if isinstance(content, list):
        cleaned_children, child_notes = _extract_notes_from_content(content, context_id, doc_slug)
        notes.extend(child_notes)
        return _copy_item_with_updates(item, {"content": cleaned_children}), notes

    updates: dict[str, Any] = {}
    for attr in ("l", "lg", "q"):
        value = getattr(item, attr, None)
        if not isinstance(value, list):
            continue
        cleaned_children, child_notes = _extract_notes_from_content(value, context_id, doc_slug)
        updates[attr] = cleaned_children
        notes.extend(child_notes)

    if updates:
        return _copy_item_with_updates(item, updates), notes

    return item, notes


def _parse_body_content(
    content: list[Any], context_id: str, doc_slug: str
) -> tuple[list[Any], list[NoteData]]:
    contained = any(
        isinstance(item, VerseCt) and item.osis_id and item.content and item.content != [None]
        for item in content
    )
    has_milestones = any(isinstance(item, VerseCt) and (item.s_id or item.e_id) for item in content)

    if has_milestones and not contained:
        return [], []

    body_items = [
        item
        for item in content
        if not _is_heading_item(item) and not isinstance(item, (VerseCt, ChapterCt))
    ]
    return _extract_notes_from_content(body_items, context_id, doc_slug)


def _parse_verses_from_content(
    content: list[Any], chapter_id: str, doc_slug: str
) -> list[VerseData]:
    """Extract VerseData from a chapter div's content list.

    Handles both contained and milestone encoding styles.
    """
    global _NOTE_COUNTER
    verses: list[VerseData] = []

    # Detect contained style: if any VerseCt has its own osis_id AND content
    contained = any(
        isinstance(item, VerseCt) and item.osis_id and item.content and item.content != [None]
        for item in content
    )

    if contained:
        for item in content:
            if isinstance(item, VerseCt) and item.osis_id:
                vid = " ".join(item.osis_id)
                num = vid.rsplit(".", 1)[-1]
                cleaned, notes = _extract_notes_from_content(item.content, vid, doc_slug)
                verses.append(VerseData(verse_id=vid, number=num, content=cleaned, notes=notes))
    else:
        # Milestone style – group content between sID/eID markers
        groups = _collect_milestone_groups(content)
        for group in groups:
            if group["type"] != "verse":
                continue
            vid = group["verse_id"]
            num = vid.rsplit(".", 1)[-1]
            cleaned, notes = _extract_notes_from_content(group["items"], vid, doc_slug)
            verses.append(VerseData(verse_id=vid, number=num, content=cleaned, notes=notes))

    return verses


# ---------------------------------------------------------------------------
# Chapter extraction
# ---------------------------------------------------------------------------


def _parse_chapter_div(div: DivCt, doc_slug: str, parent_id: str) -> ChapterData:
    """Parse a chapter-level DivCt into ChapterData."""
    cid = " ".join(div.osis_id) if div.osis_id else parent_id
    num = cid.rsplit(".", 1)[-1]
    title_text = _normalize_chapter_title(_extract_title(div.content), num) or f"Chapter {num}"
    body, notes = _parse_body_content(div.content, cid, doc_slug)
    sections = _extract_sections_from_body(body)
    return ChapterData(
        chapter_id=cid,
        number=num,
        slug=_slugify(cid),
        title=title_text,
        body=body,
        sections=sections,
        notes=notes,
        verses=_parse_verses_from_content(div.content, cid, doc_slug),
    )


def _parse_chapter_ct(chapter: ChapterCt, doc_slug: str, parent_id: str) -> ChapterData:
    """Parse a contained ChapterCt element (osisID but no s_id/e_id) into ChapterData."""
    cid = " ".join(chapter.osis_id) if chapter.osis_id else parent_id
    num = cid.rsplit(".", 1)[-1]
    content = chapter.content or []
    title_text = _normalize_chapter_title(_extract_title(content), num) or f"Chapter {num}"
    body, notes = _parse_body_content(content, cid, doc_slug)
    sections = _extract_sections_from_body(body)
    return ChapterData(
        chapter_id=cid,
        number=num,
        slug=_slugify(cid),
        title=title_text,
        body=body,
        sections=sections,
        notes=notes,
        verses=_parse_verses_from_content(content, cid, doc_slug),
    )


def _parse_non_chapter_div(
    div: DivCt, doc_slug: str, parent_id: str, page_number: int
) -> ChapterData:
    """Parse front matter or other non-chapter divisions into a renderable page."""
    div_id = " ".join(div.osis_id) if div.osis_id else f"{parent_id}.front.{page_number}"
    title_text = _extract_title(div.content) or f"Front Matter {page_number}"
    body, notes = _parse_body_content(div.content, div_id, doc_slug)
    sections = _extract_sections_from_body(body)
    return ChapterData(
        chapter_id=div_id,
        number="",
        slug=_slugify(div_id if div.osis_id else f"front-{page_number}-{title_text}"),
        title=title_text,
        body=body,
        sections=sections,
        notes=notes,
    )


def _find_chapters_milestone(content: list[Any], book_id: str, doc_slug: str) -> list[ChapterData]:
    """Extract chapters from milestone-encoded content (chapter milestones)."""
    chapters: list[ChapterData] = []
    current_chapter_id: str | None = None
    current_content: list[Any] = []

    def flush(cid: str | None) -> None:
        if cid is None:
            return
        num = cid.rsplit(".", 1)[-1]
        title = _normalize_chapter_title(_extract_title(current_content), num) or f"Chapter {num}"
        verses = _parse_verses_from_content(current_content, cid, doc_slug)
        body, notes = _parse_body_content(current_content, cid, doc_slug)
        sections = _extract_sections_from_body(body)
        chapters.append(
            ChapterData(
                chapter_id=cid,
                number=num,
                slug=_slugify(cid),
                title=title,
                body=body,
                sections=sections,
                notes=notes,
                verses=verses,
            )
        )

    for item in content:
        if isinstance(item, ChapterCt):
            if item.s_id:
                flush(current_chapter_id)
                current_chapter_id = item.s_id
                current_content = []
            elif item.e_id:
                flush(current_chapter_id)
                current_chapter_id = None
                current_content = []
            elif item.osis_id and not item.s_id and not item.e_id:
                # Contained chapter element (osisID, no milestone markers)
                flush(current_chapter_id)
                current_chapter_id = None
                chapters.append(_parse_chapter_ct(item, doc_slug, book_id))
                current_content = []
        elif isinstance(item, DivCt) and _is_chapter_level(item):
            chapters.append(_parse_chapter_div(item, doc_slug, book_id))
        else:
            if current_chapter_id is not None:
                current_content.append(item)

    flush(current_chapter_id)
    return chapters


# ---------------------------------------------------------------------------
# Division (book) extraction
# ---------------------------------------------------------------------------


def _parse_book_div(div: DivCt, doc_slug: str) -> DivisionData:
    """Parse a book-level DivCt into DivisionData."""
    did = " ".join(div.osis_id) if div.osis_id else "unknown"
    title = _extract_title(div.content) or did

    # Collect chapters
    chapters: list[ChapterData] = []
    has_chapter_divs = any(isinstance(c, DivCt) and _is_chapter_level(c) for c in div.content)
    has_chapter_milestones = any(isinstance(c, ChapterCt) and c.s_id for c in div.content)
    has_contained_chapters = any(
        isinstance(c, ChapterCt) and c.osis_id and not c.s_id and not c.e_id for c in div.content
    )

    page_number = 0
    if has_chapter_divs:
        for item in div.content:
            if not isinstance(item, DivCt):
                continue
            if _is_chapter_level(item):
                chapters.append(_parse_chapter_div(item, doc_slug, did))
                continue

            page_number += 1
            page = _parse_non_chapter_div(item, doc_slug, did, page_number)
            if page.body or page.notes:
                chapters.append(page)

    elif has_chapter_milestones:
        chapters = _find_chapters_milestone(div.content, did, doc_slug)

    elif has_contained_chapters:
        for item in div.content:
            if isinstance(item, ChapterCt) and item.osis_id and not item.s_id and not item.e_id:
                chapters.append(_parse_chapter_ct(item, doc_slug, did))

    else:
        child_divs = [item for item in div.content if isinstance(item, DivCt)]
        if child_divs:
            for item in div.content:
                if not isinstance(item, DivCt):
                    continue
                page_number += 1
                page = _parse_non_chapter_div(item, doc_slug, did, page_number)
                if page.body or page.notes:
                    chapters.append(page)
            return DivisionData(div_id=did, slug=_slugify(did), title=title, chapters=chapters)

        # Treat the whole book as a single pseudo-chapter
        verses = _parse_verses_from_content(div.content, did, doc_slug)
        body, notes = _parse_body_content(div.content, did, doc_slug)
        if verses or body:
            sections = _extract_sections_from_body(body)
            chapters = [
                ChapterData(
                    chapter_id=did,
                    number="1",
                    slug=_slugify(did),
                    title=title,
                    body=body,
                    sections=sections,
                    notes=notes,
                    verses=verses,
                )
            ]

    return DivisionData(div_id=did, slug=_slugify(did), title=title, chapters=chapters)


def _collect_book_divs(divs: list[DivCt], doc_slug: str) -> list[DivisionData]:
    """Recursively collect book-level divisions from a list of DivCts."""
    divisions: list[DivisionData] = []
    for div in divs:
        if _is_book_level(div):
            if div.type_value in (OsisDivs.BOOK_GROUP,) or (
                isinstance(div.type_value, str)
                and div.type_value.lower() in {"bookgroup", "testament"}
            ):
                # Recurse into bookGroups
                sub_divs = [c for c in div.content if isinstance(c, DivCt)]
                divisions.extend(_collect_book_divs(sub_divs, doc_slug))
            else:
                divisions.append(_parse_book_div(div, doc_slug))
        elif div.type_value is None or (isinstance(div.type_value, str) and div.type_value == ""):
            # Generic div – recurse
            sub_divs = [c for c in div.content if isinstance(c, DivCt)]
            if sub_divs:
                divisions.extend(_collect_book_divs(sub_divs, doc_slug))
            else:
                divisions.append(_parse_book_div(div, doc_slug))
    return divisions


# ---------------------------------------------------------------------------
# Document parsing
# ---------------------------------------------------------------------------


def _reset_note_counter() -> None:
    global _NOTE_COUNTER
    _NOTE_COUNTER = 0


def parse_osis_text(osis_text: OsisTextCt, source_path: Path | None = None) -> DocumentData:
    """Parse an OsisTextCt into a DocumentData."""
    _reset_note_counter()

    work_id = osis_text.osis_idwork or "unknown"
    slug = _slugify(work_id)

    # Get title from header
    title = work_id
    if osis_text.header and osis_text.header.work:
        for work in osis_text.header.work:
            if work.title:
                title = _text_of(work.title[0].content)
                break

    divisions = _collect_book_divs(osis_text.div, slug)

    return DocumentData(
        work_id=work_id,
        slug=slug,
        title=title,
        divisions=divisions,
        source_path=source_path,
    )


def parse_osis_file(path: Path) -> DocumentData:
    """Parse an OSIS XML file and return a DocumentData."""
    _reset_note_counter()
    xml_text = path.read_text(encoding="utf-8")
    osis_xml = pyosis.OsisXML.from_xml(xml_text)

    # Handle corpus (multiple osisText elements)
    if osis_xml.osis.osis_corpus:
        corpus = osis_xml.osis.osis_corpus
        # Return first text for now (corpus support can be extended)
        if corpus.osis_text:
            return parse_osis_text(corpus.osis_text[0], source_path=path)

    if osis_xml.osis.osis_text:
        return parse_osis_text(osis_xml.osis.osis_text, source_path=path)

    raise ValueError(f"No osisText found in {path}")
