"""Render pyosis content nodes to HTML strings."""

from __future__ import annotations

import html
from typing import Any

from pyosis.generated.osis_core_2_1_1 import (
    ACt,
    DivineNameCt,
    ForeignCt,
    HeadCt,
    HiCt,
    LCt,
    LgCt,
    ListCt,
    NoteCt,
    PCt,
    QCt,
    RdgCt,
    SegCt,
    TitleCt,
    TransChangeCt,
    VerseCt,
    WCt,
)


def _container_children(item: Any) -> list[Any]:
    """Return child nodes for pyosis containers with inconsistent field layouts."""
    content = getattr(item, "content", None)
    if isinstance(content, list):
        return content

    children = getattr(item, "children", None)
    if isinstance(children, list):
        items: list[Any] = []
        text = getattr(item, "text", None)
        if isinstance(text, str) and text:
            items.append(text)
        items.extend(children)
        return items

    children = []
    for attr in ("l", "lg", "q"):
        value = getattr(item, attr, None)
        if isinstance(value, list):
            children.extend(value)
    return children


def render_content(items: list[Any], note_counter: list[int] | None = None) -> str:
    """Render a list of mixed pyosis content items to an HTML string.

    Note markers are replaced with ``<sup>`` elements whose ``data-note``
    attribute carries the pre-assigned note id from the parser.

    Args:
        items:          Mixed content list from a pyosis model.
        note_counter:   Mutable list with one integer used to number note
                        markers sequentially within a chapter.

    Returns:
        An HTML string ready for use in a Jinja2 template (mark with
        ``| safe``).
    """
    if note_counter is None:
        note_counter = [0]

    parts: list[str] = []
    for item in items:
        parts.append(_render_item(item, note_counter))
    return "".join(parts)


# ---------------------------------------------------------------------------
# Internal dispatch
# ---------------------------------------------------------------------------


def _render_item(item: Any, nc: list[int]) -> str:
    if item is None:
        return ""
    if isinstance(item, str):
        return html.escape(item)
    # Note marker tuple injected by the parser
    if isinstance(item, tuple) and len(item) == 2 and item[0] == "note_marker":
        nc[0] += 1
        label = _int_to_alpha(nc[0])
        note_id = item[1]
        return (
            f'<sup class="note-marker" data-note="{html.escape(note_id)}">'
            f'<a href="#note-{html.escape(note_id)}">{html.escape(label)}</a>'
            f"</sup>"
        )
    if isinstance(item, WCt):
        return render_content(item.content, nc)
    if isinstance(item, HiCt):
        return _render_hi(item, nc)
    if str(getattr(item, "qname", "")).endswith("}head"):
        return f"<h3>{html.escape(getattr(item, 'text', '') or '')}</h3>"
    if isinstance(item, TitleCt):
        return f"<h3>{render_content(item.content, nc)}</h3>"
    if isinstance(item, HeadCt):
        return f"<h3>{render_content(item.content, nc)}</h3>"
    if isinstance(item, PCt):
        return f"<p>{render_content(item.content, nc)}</p>"
    if isinstance(item, LgCt):
        return f'<div class="lg">{render_content(_container_children(item), nc)}</div>'
    if isinstance(item, LCt):
        return f'<div class="l">{render_content(item.content, nc)}</div>'
    if isinstance(item, QCt):
        level = getattr(item, "level", 1) or 1
        return f'<div class="q q-{level}">{render_content(item.content, nc)}</div>'
    if isinstance(item, ACt):
        href = item.href or "#"
        return f'<a href="{html.escape(href)}">{render_content(item.content, nc)}</a>'
    if isinstance(item, DivineNameCt):
        return f'<span class="divine-name">{render_content(item.content, nc)}</span>'
    if isinstance(item, TransChangeCt):
        return f'<em class="transchange">{render_content(item.content, nc)}</em>'
    if isinstance(item, ForeignCt):
        return f'<em class="foreign">{render_content(item.content, nc)}</em>'
    if isinstance(item, SegCt):
        return f'<span class="seg">{render_content(item.content, nc)}</span>'
    if isinstance(item, RdgCt):
        return render_content(item.content, nc)
    if isinstance(item, ListCt):
        items_html = "".join(
            f"<li>{render_content(getattr(li, 'content', []), nc)}</li>"
            for li in (item.content or [])
        )
        return f"<ul>{items_html}</ul>"
    if isinstance(item, NoteCt):
        # Inline note that was not pre-processed by the parser (e.g. nested)
        return ""
    if isinstance(item, VerseCt):
        # Nested verse inside another verse (unusual); skip milestone markers
        if item.s_id or item.e_id:
            return ""
        return render_content(item.content, nc)
    # Generic fallback for elements with a content list
    children = _container_children(item)
    if children:
        return render_content(children, nc)
    return ""


# ---------------------------------------------------------------------------
# hi (highlighting) element
# ---------------------------------------------------------------------------

_HI_TAG_MAP: dict[str, str] = {
    "bold": "strong",
    "italic": "em",
    "emphasis": "em",
    "sup": "sup",
    "sub": "sub",
    "underline": "u",
    "line-through": "s",
    "small-caps": "span",
}


def _render_hi(item: HiCt, nc: list[int]) -> str:
    raw = getattr(item, "type_value", None)
    # Enum value gives e.g. OsisHi.ITALIC; use .value to get 'italic'
    rend = (raw.value if hasattr(raw, "value") else str(raw or "")).lower().strip()
    tag = _HI_TAG_MAP.get(rend, "span")
    css_class = ""
    if rend == "small-caps":
        css_class = ' class="small-caps"'
    inner = render_content(item.content, nc)
    return f"<{tag}{css_class}>{inner}</{tag}>"


# ---------------------------------------------------------------------------
# Note content rendering
# ---------------------------------------------------------------------------


def render_note_content(items: list[Any]) -> str:
    """Render the content of a note to HTML (no further note-markers expected)."""
    return render_content(items, note_counter=[0])


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _int_to_alpha(n: int) -> str:
    """Convert 1 → a, 2 → b, …, 26 → z, 27 → aa, …"""
    result = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(ord("a") + rem) + result
    return result
