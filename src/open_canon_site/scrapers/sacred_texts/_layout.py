"""Isolate the main content of a sacred-texts.com page, old layout or new.

sacred-texts.com was rebuilt as a SvelteKit "reader" app. A text page now wraps the old
page body in a large shell: an archive banner, a site sidebar, a "Chapters" sidebar,
reader toolbars, advertising, "Saved" and "Comments and social" panels and a footer. The
text itself sits in ``<article data-slot="reader-content">``, which also repeats the
page title as a screen-reader ``<h1>`` and holds the footnotes in their own section.
The content markup is also sanitised: ``name`` attributes and ``<font>`` tags are
dropped, a second ``<h1>`` becomes ``<div data-legacy-h1>``, and footnotes are linked
by ``id``/``data-footnote-ref`` instead of ``fr_N``/``fn_N`` anchors.

Book index pages became "book overview" pages: a title, an "About this book" blurb and
a paginated table of contents.

The parsers were written for the old pages, which are still valid input (for example
from an HTML cache or archive.sacred-texts.com). Rather than branch on the URL, they
call :func:`legacy_html` first: an old-layout page is returned unchanged, and a
reader-layout page is rebuilt as a minimal old-layout document so that the existing
logic runs on it unmodified.
"""

from __future__ import annotations

import re
from typing import Final

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

READER_CONTENT_RE: Final[re.Pattern[str]] = re.compile(r"""data-slot\s*=\s*["']?reader-content\b""")
"""Matches the ``data-slot="reader-content"`` attribute that marks a reader-layout page."""

BOOK_OVERVIEW_RE: Final[re.Pattern[str]] = re.compile(
    r"""data-module-id\s*=\s*["']?book-overview-about\b"""
)
"""Matches the ``data-module-id="book-overview-about"`` block of a book overview page."""

PAGE_MARKER_RE: Final[re.Pattern[str]] = re.compile(r"^p\.\s*(?P<page>[0-9ivxlcdm]+)$", re.I)
"""Matches the text of a printed page marker such as ``p. 40`` or ``p. xvii``."""

CHAPTER_COUNT_RE: Final[re.Pattern[str]] = re.compile(r"^\s*(?P<count>\d+)\s+chapters?\s*$")
"""Matches a table-of-contents count line such as ``91 chapters``."""

INLINE_TAGS: Final[frozenset[str]] = frozenset({
    "a",
    "b",
    "br",
    "cite",
    "em",
    "font",
    "i",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "u",
})
"""Inline elements that may be gathered, with loose text, into a rebuilt paragraph."""

BLOCK_TAGS: Final[frozenset[str]] = frozenset({
    "blockquote",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "ol",
    "p",
    "table",
    "ul",
})
"""Block elements; an inline element containing one is never wrapped in a paragraph."""

PAGE_NOTE_LABEL_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9ivxlcdm]+:\d+$", re.I)
"""Matches a ``page:note`` footnote label such as ``39:6`` or ``viii:1``."""

LEADING_LABEL_RE: Final[re.Pattern[str]] = re.compile(r"^\s*(?P<label>[0-9ivxlcdm]+:\d+)\s+", re.I)
"""Matches a ``page:note`` label at the start of footnote text, with its trailing space."""

BLOCK_END_RE: Final[re.Pattern[str]] = re.compile(r"(</(?:p|h[1-6])>)(?=<)")
"""Matches a paragraph or heading end tag that is directly followed by another tag.

Old pages always had a newline after such a tag; the reader layout drops it, and parsers
that join consecutive paragraphs with the whitespace between them then glue words together.
"""

KEPT_ATTRIBUTES: Final[frozenset[str]] = frozenset({"name", "href", "color", "size"})
"""Attributes kept on rebuilt content; the reader app's classes and data attributes go."""
UNTERMINATED_CHARREF_RE: Final[re.Pattern[str]] = re.compile(r"&#(\d+)(?![\d;])")
"""Matches a decimal character reference that lacks its closing ``;`` (digits in group 1)."""


def is_reader_layout(raw_html: str) -> bool:
    """Report whether a page uses the redesigned reader layout.

    Args:
        raw_html: Raw page HTML.

    Returns:
        True if the page has a ``data-slot="reader-content"`` element.
    """
    return bool(READER_CONTENT_RE.search(raw_html))


def is_book_overview_layout(raw_html: str) -> bool:
    """Report whether a page is a redesigned book overview (index) page.

    Args:
        raw_html: Raw page HTML.

    Returns:
        True if the page has a ``book-overview-about`` module.
    """
    return bool(BOOK_OVERVIEW_RE.search(raw_html))


def page_title(soup: BeautifulSoup) -> str:
    """Return the whitespace-normalised text of a page's ``<title>``.

    Args:
        soup: Parsed page.

    Returns:
        The title text, or ``""`` if the page has none.
    """
    if soup.title is None:
        return ""
    return " ".join(soup.title.get_text(" ", strip=True).split())


def _remove_comments(root: Tag) -> None:
    """Delete every HTML comment (the reader app's hydration markers) under ``root``.

    Args:
        root: Element to clean in place.
    """
    for comment in root.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()


def _is_empty_anchor(node: object) -> bool:
    """Report whether a node is an ``<a>`` with no attributes and no text.

    The reader layout leaves these where an old ``<a name="...">`` anchor was.

    Args:
        node: Any parse-tree node.

    Returns:
        True for an attribute-less, text-less ``<a>`` tag.
    """
    return (
        isinstance(node, Tag)
        and node.name == "a"
        and not node.attrs
        and not node.get_text(strip=True)
    )


def _restore_legacy_headings(root: Tag) -> None:
    """Turn ``<div data-legacy-hN role="heading">`` back into ``<hN>`` elements.

    The reader layout keeps only one ``<h1>`` per page; later ones are demoted to a
    ``div`` carrying ``data-legacy-h1`` (and ``aria-level``).

    Args:
        root: Element to fix in place.
    """
    for element in root.find_all(True):
        for attribute in list(element.attrs):
            match = re.fullmatch(r"data-legacy-(h[1-6])", attribute)
            if match:
                element.name = match.group(1)
                break


def _restore_page_markers(root: Tag, soup: BeautifulSoup) -> None:
    """Rebuild old page markers from the reader layout's bare ``<a>p. N</a>`` links.

    The old markup was ``<a name="page_N"><font size="1" color="green">p. N</font></a>``;
    the scrapers rely on the ``page_`` name and on the green font.

    Args:
        root: Element to fix in place.
        soup: Document that owns ``root`` (used to create tags).
    """
    for anchor in root.find_all("a"):
        if anchor.attrs:
            continue
        text = anchor.get_text(strip=True)
        match = PAGE_MARKER_RE.match(text)
        if not match:
            continue
        anchor["name"] = f"page_{match.group('page')}"
        font = soup.new_tag("font", attrs={"size": "1", "color": "green"})
        font.string = text
        anchor.clear()
        anchor.append(font)


def _footnote_body(item: Tag) -> Tag | None:
    """Return the body element of a reader-layout footnote list item.

    Args:
        item: A ``<li data-slot="reader-footnote">`` element.

    Returns:
        The ``reader-footnote-body`` element, or ``None`` if there is none.
    """
    body = item.find(attrs={"data-slot": "reader-footnote-body"})
    return body if isinstance(body, Tag) else None


def _clean_footnote_body(body: Tag) -> None:
    """Strip reader-layout residue from a footnote body in place.

    Removes empty anchors and empty paragraphs and unwraps the remaining paragraphs
    (with a space between them), since an old footnote was a single ``<p>``.

    Args:
        body: A footnote body element.
    """
    for anchor in body.find_all("a"):
        if _is_empty_anchor(anchor):
            anchor.decompose()
    for paragraph in body.find_all("p"):
        if not paragraph.get_text(strip=True):
            paragraph.decompose()
        else:
            if paragraph.previous_sibling is not None:
                paragraph.insert_before(" ")
            paragraph.unwrap()


def _restore_reference_space(anchor: Tag) -> None:
    """Put back the no-break space the old pages had before every footnote reference.

    Old pages always wrote ``text&nbsp;<a name="fr_N">``; the reader layout turns the
    no-break space into a plain one. A trailing plain space on the preceding text node is
    replaced by U+00A0, and one is inserted if the preceding text does not end with it.

    Args:
        anchor: The ``fr_N`` anchor in front of a reference.
    """
    previous = anchor.previous_sibling
    if isinstance(previous, NavigableString) and not isinstance(previous, Comment):
        text = str(previous)
        if text.endswith("\xa0"):
            return
        if text.endswith(" "):
            text = text[:-1]
        previous.replace_with(NavigableString(text + "\xa0"))
        return
    anchor.insert_before(NavigableString("\xa0"))


def _label_from_body(body: Tag, label: str, label_link: Tag) -> str:
    """Move a ``page:note`` label that the reader layout put in the note text back to the label.

    Some books (the Book of Enoch front matter) number notes ``1`` in the label and start the
    note text with the old label, for example ``viii:1``. When the note starts with such a
    token and the label is not already one, the token becomes the label and leaves the body.

    Args:
        body: Cleaned footnote body; its leading text is edited in place.
        label: The label shown by the reader layout.
        label_link: The ``<a href="#fr_N">`` label element to update.

    Returns:
        The label now in use.
    """
    if PAGE_NOTE_LABEL_RE.match(label):
        return label
    first = next((node for node in body.descendants if isinstance(node, NavigableString)), None)
    if first is None:
        return label
    match = LEADING_LABEL_RE.match(str(first))
    if not match:
        return label
    first.replace_with(NavigableString(str(first)[match.end() :]))
    label_link.string = match.group("label")
    return match.group("label")


def _rebuild_footnotes(article: Tag, prose: Tag, soup: BeautifulSoup) -> list[Tag]:
    """Convert reader-layout footnotes to old ``fr_N``/``fn_N`` anchors.

    Each reference ``<a data-footnote-ref href="#ID">`` becomes
    ``<a name="fr_N"></a><a href="#fn_N">label</a>`` (reusing the empty ``<a>`` the
    reader layout leaves in front of it, and restoring the no-break space before it), and each footnote becomes
    ``<p><a name="fn_N"></a><a href="#fr_N">label</a> body</p>``. Footnotes are numbered
    from 1 in list order; a reference to an unlisted footnote gets the next free number.

    Args:
        article: The ``reader-content`` article holding the footnotes section.
        prose: The isolated prose, whose references are rewritten in place.
        soup: Document that owns both (used to create tags).

    Returns:
        The rebuilt footnote paragraphs, in order; empty if the page has none.
    """
    numbers: dict[str, int] = {}
    items = article.find_all(attrs={"data-slot": "reader-footnote"})
    for item in items:
        item_id = item.get("id")
        if item_id and item_id not in numbers:
            numbers[item_id] = len(numbers) + 1

    for reference in prose.find_all("a", attrs={"data-footnote-ref": True}):
        target = reference.get("href", "").lstrip("#")
        if target not in numbers:
            numbers[target] = len(numbers) + 1
        number = numbers[target]
        label = reference.get_text(strip=True)
        reference.attrs = {"href": f"#fn_{number}"}
        reference.clear()
        reference.append(label)

        previous = reference.previous_sibling
        if _is_empty_anchor(previous):
            previous["name"] = f"fr_{number}"
            anchor = previous
        else:
            anchor = soup.new_tag("a", attrs={"name": f"fr_{number}"})
            reference.insert_before(anchor)
        _restore_reference_space(anchor)

    paragraphs: list[Tag] = []
    for item in items:
        item_id = item.get("id")
        if not item_id:
            continue
        number = numbers[item_id]
        label_tag = item.find(attrs={"data-slot": "reader-footnote-label"})
        label = label_tag.get_text(strip=True) if label_tag is not None else ""

        paragraph = soup.new_tag("p")
        paragraph.append(soup.new_tag("a", attrs={"name": f"fn_{number}"}))
        label_link = soup.new_tag("a", attrs={"href": f"#fr_{number}"})
        label_link.string = label
        paragraph.append(label_link)
        paragraph.append(" ")

        body = _footnote_body(item)
        if body is not None:
            _clean_footnote_body(body)
            label = _label_from_body(body, label, label_link)
            for child in list(body.contents):
                paragraph.append(child.extract())
        paragraphs.append(paragraph)

    return paragraphs


def _is_inline_run_node(node: object) -> bool:
    """Report whether a top-level node can belong to a run of loose paragraph content.

    Args:
        node: A child of the content container.

    Returns:
        True for a text node, or an inline element with no block element inside.
    """
    if isinstance(node, NavigableString):
        return True
    return (
        isinstance(node, Tag) and node.name in INLINE_TAGS and node.find(list(BLOCK_TAGS)) is None
    )


def _follows_wrapped_block(node: object) -> bool:
    """Report whether a node directly follows an inline element that wraps a block.

    The old pages wrote summaries as ``<i><p>text</i>. [<i>note</i>.]</p>``, which parses
    to the italic block followed by loose text. The parsers have always ignored that
    loose text, so it must not be promoted to a paragraph.

    Args:
        node: First node of a run of loose content.

    Returns:
        True if the previous non-blank sibling is an inline element containing a block.
    """
    previous = getattr(node, "previous_sibling", None)
    while isinstance(previous, NavigableString) and not previous.strip():
        previous = previous.previous_sibling
    return (
        isinstance(previous, Tag)
        and previous.name in INLINE_TAGS
        and previous.find(list(BLOCK_TAGS)) is not None
    )


def _is_italic_only(run: list[object]) -> bool:
    """Tell whether a run of loose nodes is nothing but italic elements and whitespace.

    Args:
        run: Consecutive loose nodes under the content container.

    Returns:
        ``True`` if the run holds at least one ``<i>``/``<em>`` and no other element or text.
    """
    italics = 0
    for node in run:
        if isinstance(node, NavigableString):
            if str(node).strip():
                return False
        elif node.name in {"i", "em"}:
            italics += 1
        else:
            return False
    return italics > 0


def _wrap_loose_text(root: Tag, soup: BeautifulSoup) -> None:
    """Wrap runs of loose top-level text in ``<p>`` elements.

    An old paragraph interrupted by a margin-note table (``<p>text<tr><td>...``) is
    flattened by the reader layout into bare text between paragraphs, which the
    paragraph-based parsers would skip. A run of consecutive text nodes and inline
    elements directly under ``root`` is wrapped in a new ``<p>`` when it contains at
    least one letter or digit (leading whitespace is trimmed), so stray punctuation left between blocks (for example
    the ``.`` after ``<i><p>...</p></i>``) stays loose as it was in the old markup. A run
    that is only italic elements (a chapter summary such as ``<h3>I</h3><em>...</em>``) is
    left as it is: the parsers recognise a summary by its italic element, not by a paragraph.

    Args:
        root: The content container, modified in place.
        soup: Document that owns ``root`` (used to create tags).
    """
    runs: list[list[object]] = []
    current: list[object] = []
    for child in list(root.children):
        if _is_inline_run_node(child):
            current.append(child)
            continue
        if current:
            runs.append(current)
        current = []
    if current:
        runs.append(current)

    for run in runs:
        if _follows_wrapped_block(run[0]) or _is_italic_only(run):
            continue
        text = "".join(
            str(node) if isinstance(node, NavigableString) else node.get_text() for node in run
        )
        if not re.search(r"\w", text):
            continue
        paragraph = soup.new_tag("p")
        run[0].insert_before(paragraph)
        for node in run:
            paragraph.append(node.extract())
        first = paragraph.contents[0]
        if isinstance(first, NavigableString):
            first.replace_with(NavigableString(str(first).lstrip()))


def _strip_attributes(root: Tag) -> None:
    """Drop every attribute not in ``KEPT_ATTRIBUTES`` from ``root``'s descendants.

    Args:
        root: Element to clean in place.
    """
    for element in root.find_all(True):
        element.attrs = {
            key: value for key, value in element.attrs.items() if key in KEPT_ATTRIBUTES
        }


def _legacy_document(title: str, parts: list[str]) -> str:
    """Wrap body fragments in a minimal old-layout HTML document.

    Args:
        title: Text for the ``<title>`` element (escaped here).
        parts: Serialised body fragments, in order.

    Returns:
        ``<html><head><title>...</title></head><body>...</body></html>``.
    """
    escaped = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    body = "\n".join(parts)
    return f"<html>\n<head><title>{escaped}</title></head>\n<body>\n{body}\n</body>\n</html>\n"


def reader_page_to_legacy(raw_html: str) -> str:
    """Rebuild a reader-layout text page as a minimal old-layout document.

    Keeps only the prose inside ``reader-content`` (dropping the screen-reader ``<h1>``
    copy of the title and all site chrome), restores demoted headings, page markers,
    paragraphs around loose text, newlines between blocks and footnote anchors, appends the footnotes after an ``<hr>`` and a ``Footnotes``
    heading, and closes the content with an ``<hr>`` as the old pages did.

    Args:
        raw_html: Raw reader-layout page HTML.

    Returns:
        The rebuilt document.

    Raises:
        ValueError: If the page has no ``reader-content`` element.
    """
    soup = BeautifulSoup(raw_html, "html.parser")
    article = soup.find(attrs={"data-slot": "reader-content"})
    if not isinstance(article, Tag):
        raise ValueError("Page has no reader-content element")

    _remove_comments(article)
    prose = article.find(attrs={"data-slot": "reader-prose"})
    if not isinstance(prose, Tag):
        prose = article
    container = prose.find(attrs={"data-slot": "ad-content"})
    if isinstance(container, Tag):
        prose = container

    _restore_legacy_headings(prose)
    _restore_page_markers(prose, soup)
    _wrap_loose_text(prose, soup)
    footnotes = _rebuild_footnotes(article, prose, soup)
    _strip_attributes(prose)

    parts = [BLOCK_END_RE.sub(r"\1\n", prose.decode_contents()), "<hr/>"]
    if footnotes:
        parts.append("<h3>Footnotes</h3>")
        for paragraph in footnotes:
            _strip_attributes(paragraph)
            parts.append(str(paragraph))
        parts.append("<hr/>")
    return _legacy_document(page_title(soup), parts)


def book_overview_parts(raw_html: str) -> tuple[str, list[str], int | None]:
    """Extract the useful parts of a reader-layout book overview (index) page.

    The page renders its modules twice (mobile and desktop variants); the first
    occurrence of each is used.

    Args:
        raw_html: Raw book overview page HTML.

    Returns:
        ``(title, about_html, chapter_count)``: the book title from the
        ``book-overview-title`` module (falling back to ``<title>``), the serialised
        ``<p>`` elements of the "About this book" blurb with reader attributes removed,
        and the chapter count from the table of contents (``None`` if absent).
    """
    soup = BeautifulSoup(raw_html, "html.parser")
    _remove_comments(soup)

    title = ""
    title_module = soup.find(attrs={"data-module-id": "book-overview-title"})
    if isinstance(title_module, Tag):
        heading = title_module.find(attrs={"role": "heading"}) or title_module.find(["h1", "h2"])
        if heading is not None:
            title = " ".join(heading.get_text(" ", strip=True).split())
    if not title:
        title = page_title(soup)

    about_html: list[str] = []
    about = soup.find(attrs={"data-module-id": "book-overview-about"})
    if isinstance(about, Tag):
        for paragraph in about.find_all("p"):
            if not paragraph.get_text(strip=True):
                continue
            _strip_attributes(paragraph)
            paragraph.attrs = {}
            about_html.append(str(paragraph))

    chapter_count: int | None = None
    toc = soup.find(attrs={"data-module-id": "book-overview-table-of-contents"})
    if isinstance(toc, Tag):
        for element in toc.find_all(["p", "span", "div"]):
            if element.find(True) is not None:
                continue
            match = CHAPTER_COUNT_RE.match(element.get_text(" ", strip=True))
            if match:
                chapter_count = int(match.group("count"))
                break

    return title, about_html, chapter_count


def close_character_references(raw_html: str) -> str:
    """Add the missing semicolon to decimal character references.

    The old pages contain references such as ``&#7730araite`` (no ``;``). With character
    references converted, ``html.parser`` then buffers everything from there to the end of
    the page as one text node, losing the rest of the markup (and, on Jubilees' introduction,
    most of the text and every footnote).

    Args:
        raw_html: Raw page HTML.

    Returns:
        The HTML with every ``&#<digits>`` not followed by a digit or ``;`` closed.
    """
    return UNTERMINATED_CHARREF_RE.sub(r"&#\1;", raw_html)


def legacy_html(raw_html: str) -> str:
    """Return a page in old-layout form, whichever layout it was fetched in.

    Old-layout pages (and anything that is not a reader-layout text page, such as
    mirror Markdown or a book overview page) are returned as they are, apart from
    :func:`close_character_references`.

    Args:
        raw_html: Raw page HTML.

    Returns:
        The page with its character references closed, or the rebuilt document from
        :func:`reader_page_to_legacy`.
    """
    raw_html = close_character_references(raw_html)
    if not is_reader_layout(raw_html):
        return raw_html
    return reader_page_to_legacy(raw_html)
