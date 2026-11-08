"""Unit tests for ``churchofjesuschrist.build_osis``: HTML to OSIS conversion and chapter/book assembly."""

from __future__ import annotations

import warnings
from typing import Any

import bs4
import bs4.element
import pyosis.generated as osis
import pytest
from hypothesis import given
from hypothesis import strategies as st
from lds_fake_site import FakeSite, study_payload
from open_canon_site.scrapers.churchofjesuschrist import build_osis
from open_canon_site.scrapers.churchofjesuschrist import models as lds_models
from open_canon_site.scrapers.churchofjesuschrist.build_osis import (
    build_book,
    build_chapter,
    clean_up_html,
    extract_footnote,
    extract_markup,
)


def _tag(html: str, name: str | None = None) -> bs4.element.Tag:
    """Parse ``html`` and return its first element (or the first ``name`` element)."""
    soup = bs4.BeautifulSoup(html, "html.parser")
    found = soup.find(name) if name else soup.find(True)
    assert isinstance(found, bs4.element.Tag)
    return found


def _convert(html: str, footnotes: dict[str, Any] | None = None, **kwargs: Any) -> list[object]:
    """Run extract_markup on the first element of ``html`` with warnings turned into errors."""
    notes = {k: lds_models.Footnote(**v) for k, v in (footnotes or {}).items()}
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        return extract_markup(_tag(html), notes, **kwargs)


def _chapter(
    body: str, footnotes: dict[str, Any] | None = None
) -> lds_models.ScriptureStudyContent:
    """Create a ScriptureStudyContent whose body is ``body``."""
    return lds_models.ScriptureStudyContent(**study_payload("/", body, footnotes=footnotes))


def _titles(items: list[object] | None, kind: Any) -> list[osis.TitleCt]:
    """Pick the TitleCt entries of the given OSIS title type from front matter."""
    assert items is not None
    return [i for i in items if isinstance(i, osis.TitleCt) and i.type_value == kind]


# --- clean_up_html -----------------------------------------------------------------------------


def test_clean_up_html_removes_page_breaks() -> None:
    """clean_up_html deletes ``span.page-break`` elements and returns the same soup object."""
    soup = bs4.BeautifulSoup(
        '<p>a<span class="page-break" data-page="3"></span>b<span class="other">c</span></p>',
        "html.parser",
    )
    result = clean_up_html(soup)
    assert result is soup
    assert soup.find("span", class_="page-break") is None
    assert soup.get_text() == "abc"


# --- extract_footnote --------------------------------------------------------------------------

_NOTE_LINK = (
    '<a class="study-note-ref" href="#note1a"><sup class="marker" data-value="a"></sup>reign</a>'
)


def test_extract_footnote_known_note() -> None:
    """extract_footnote emits a non-canonical note with the footnote's plain text, then the link contents."""
    notes = {"note1a": lds_models.Footnote(id="note1a", text="<p>TG <i>Kings</i></p>")}
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = extract_footnote(_tag(_NOTE_LINK), notes)
    note, *rest = result
    assert isinstance(note, osis.NoteCt)
    assert note.canonical is False
    assert note.content == ["TG Kings"]
    assert rest == ["reign"]


def test_extract_footnote_unknown_note_warns_and_uses_id() -> None:
    """A link whose id is missing from the footnotes warns and uses the id as the note text."""
    with pytest.warns(UserWarning, match="did not have corresponding footnote content"):
        result = extract_footnote(_tag(_NOTE_LINK), {})
    assert isinstance(result[0], osis.NoteCt)
    assert result[0].content == ["note1a"]


# --- extract_markup: plain nodes and containers ------------------------------------------------


def test_extract_markup_navigable_string_returns_text() -> None:
    """A NavigableString is returned as its text in a one-element list."""
    assert extract_markup(bs4.element.NavigableString("hello"), {}) == ["hello"]


def test_extract_markup_paragraph_merges_adjacent_text() -> None:
    """A ``p`` becomes PCt and adjacent text pieces (including dropped nodes) are concatenated."""
    (p,) = _convert("<p>one <sup></sup>two</p>")
    assert isinstance(p, osis.PCt)
    assert p.content == ["one two"]


def test_extract_markup_no_container_returns_children_only() -> None:
    """no_container=True returns the tag's converted children rather than a wrapper element."""
    assert _convert("<p>a<b>b</b></p>", no_container=True) == [
        "a",
        osis.HiCt(type_value=osis.OsisHi.BOLD, content=["b"]),
    ]


def test_extract_markup_dominant_span_passes_children_through() -> None:
    """``span.dominant`` is dropped and only its contents are returned."""
    assert _convert('<span class="dominant">The Book</span>') == ["The Book"]


def test_extract_markup_scripture_ref_becomes_reference() -> None:
    """``a.scripture-ref`` becomes a non-canonical ReferenceCt with its text."""
    (ref,) = _convert('<a class="scripture-ref" href="/x"> Alma 1:1 </a>')
    assert isinstance(ref, osis.ReferenceCt)
    assert ref.canonical is False
    assert ref.content == ["Alma 1:1"]


def test_extract_markup_scripture_ref_drops_page_number() -> None:
    """A trailing ``, page N`` is stripped from a scripture reference."""
    (ref,) = _convert('<a class="scripture-ref">Mosiah 3:5, page 12</a>')
    assert isinstance(ref, osis.ReferenceCt)
    assert ref.content == ["Mosiah 3:5"]


def test_extract_markup_scripture_ref_page_after_closing_quote() -> None:
    """For ``,” page N`` the page number is dropped but the closing quote is kept."""
    (ref,) = _convert('<a class="scripture-ref">“Title,” page 4</a>')
    assert isinstance(ref, osis.ReferenceCt)
    assert ref.content == ["“Title”"]


@pytest.mark.parametrize(
    "html",
    [
        '<span class="small-caps">Lord</span>',
        '<span class="uppercase">Lord</span>',
        "<small>Lord</small>",
    ],
)
def test_extract_markup_small_caps_variants(html: str) -> None:
    """``span.small-caps``, ``span.uppercase`` and ``small`` map to hi type smallCaps."""
    (hi,) = _convert(html)
    assert isinstance(hi, osis.HiCt)
    assert hi.type_value == osis.OsisHi.SMALL_CAPS
    assert hi.content == ["Lord"]


@pytest.mark.parametrize(
    ("html", "kind"),
    [
        ("<sup>2</sup>", osis.OsisHi.SUPER),
        ("<sub>2</sub>", osis.OsisHi.SUB),
        ("<b>x</b>", osis.OsisHi.BOLD),
        ("<em>x</em>", osis.OsisHi.EMPHASIS),
        ("<i>x</i>", osis.OsisHi.ITALIC),
    ],
)
def test_extract_markup_highlight_elements(html: str, kind: Any) -> None:
    """sup/sub/b/em/i map to the matching OSIS hi type."""
    (hi,) = _convert(html)
    assert isinstance(hi, osis.HiCt)
    assert hi.type_value == kind


def test_extract_markup_empty_sup_is_footnote_marker_and_dropped() -> None:
    """An empty ``sup`` (footnote marker) produces no output."""
    assert _convert('<sup class="marker" data-value="a"></sup>') == []


def test_extract_markup_deity_name_span() -> None:
    """``span.deity-name`` becomes DivineNameCt."""
    (name,) = _convert('<span class="deity-name">Lord</span>')
    assert isinstance(name, osis.DivineNameCt)
    assert name.content == ["Lord"]


def test_extract_markup_deity_name_wrapping_footnote_is_hoisted_inside_link() -> None:
    """A deity-name span wrapping a footnote link (2 Nephi 22) is rewritten so the link contains the name."""
    html = (
        '<span class="deity-name"><span class="small-caps">'
        '<a class="study-note-ref" href="#note2b">'
        '<sup class="marker" data-value="b"></sup>Jehovah</a></span></span>'
    )
    result = _convert(html, {"note2b": {"id": "note2b", "text": "<p>HEB the Lord</p>"}})
    note, name = result
    assert isinstance(note, osis.NoteCt)
    assert note.content == ["HEB the Lord"]
    assert isinstance(name, osis.DivineNameCt)
    (small_caps,) = name.content
    assert isinstance(small_caps, osis.HiCt)
    assert small_caps.content == ["Jehovah"]


def test_extract_markup_language_span_becomes_foreign() -> None:
    """``span.language`` becomes ForeignCt carrying its lang attribute."""
    (foreign,) = _convert('<span class="language" lang="heb">Selah</span>')
    assert isinstance(foreign, osis.ForeignCt)
    assert foreign.lang == "heb"
    assert foreign.content == ["Selah"]


def test_extract_markup_question_answer_and_line_spans() -> None:
    """``span.question``/``answer`` become x- divs and ``span.line`` becomes an ``l`` element."""
    (question,) = _convert('<span class="question">Q</span>')
    (answer,) = _convert('<span class="answer">A</span>')
    (line,) = _convert('<span class="line">L</span>')
    assert isinstance(question, osis.DivCt) and question.type_value == "x-question"
    assert isinstance(answer, osis.DivCt) and answer.type_value == "x-answer"
    assert isinstance(line, osis.LCt) and line.content == ["L"]


def test_extract_markup_translit_span_with_lang() -> None:
    """extract_markup maps <span class="translit" lang="hbo"> to ForeignCt with the given lang."""
    (foreign,) = _convert('<span class="translit" lang="hbo">Elohim</span>')
    assert isinstance(foreign, osis.ForeignCt)
    assert foreign.lang == "hbo"
    assert foreign.content == ["Elohim"]


def test_extract_markup_translit_span_without_lang() -> None:
    """extract_markup maps <span class="translit"> (no lang) to ForeignCt with an empty lang."""
    (foreign,) = _convert('<span class="translit">YHWH</span>')
    assert isinstance(foreign, osis.ForeignCt)
    assert foreign.lang == ""
    assert foreign.content == ["YHWH"]


def test_extract_markup_clarity_word_span_maps_to_trans_change_added() -> None:
    """``span.clarity-word`` maps to TransChangeCt(type_value="added")."""
    (node,) = _convert('<span class="clarity-word">the</span>')
    assert isinstance(node, osis.TransChangeCt)
    assert node.type_value == "added"
    assert node.content == ["the"]


def test_extract_markup_unknown_span_class_warns_and_passes_through() -> None:
    """A span with an unrecognised class warns and returns its contents unwrapped."""
    with pytest.warns(UserWarning, match="Unknown span class"):
        result = extract_markup(_tag('<span class="mystery">text</span>'), {})
    assert result == ["text"]


def test_extract_markup_study_note_ref_link_becomes_note() -> None:
    """``a.study-note-ref`` is delegated to extract_footnote."""
    result = _convert(_NOTE_LINK, {"note1a": {"id": "note1a", "text": "N"}})
    assert isinstance(result[0], osis.NoteCt)
    assert result[0].content == ["N"]
    assert result[1:] == ["reign"]


def test_extract_markup_note_ref_class_also_becomes_note() -> None:
    """``a.note-ref`` (older markup) is also converted as a footnote."""
    html = '<a class="note-ref" href="#n1">word</a>'
    result = _convert(html, {"n1": {"id": "n1", "text": "T"}})
    assert isinstance(result[0], osis.NoteCt)


def test_extract_markup_lists() -> None:
    """``ul``/``ol`` become ListCt and ``li`` becomes ItemCt."""
    (lst,) = _convert("<ul><li>a</li><li>b</li></ul>")
    assert isinstance(lst, osis.ListCt)
    assert [type(i) for i in lst.content] == [osis.ItemCt, osis.ItemCt]
    (ordered,) = _convert("<ol><li>x</li></ol>")
    assert isinstance(ordered, osis.ListCt)


def test_extract_markup_img_becomes_figure_with_caption() -> None:
    """``img`` becomes FigureCt using data-public-description as alt, src and alt as caption."""
    html = '<img src="/img/a.jpg" alt="Caption" data-public-description="Describes it">'
    (fig,) = _convert(html)
    assert isinstance(fig, osis.FigureCt)
    assert fig.src == "/img/a.jpg"
    assert fig.alt == "Describes it"
    assert fig.caption[0].content == ["Caption"]


def test_extract_markup_image_figure_and_figcaption() -> None:
    """``figure.image`` becomes an x-figure div and ``figcaption`` an x-figcaption div."""
    html = (
        '<figure class="image"><img src="s" alt="a" data-public-description="d">'
        "<figcaption>Cap</figcaption></figure>"
    )
    (div,) = _convert(html)
    assert isinstance(div, osis.DivCt) and div.type_value == "x-figure"
    assert isinstance(div.content[0], osis.FigureCt)
    cap = div.content[1]
    assert isinstance(cap, osis.DivCt) and cap.type_value == "x-figcaption"


_TABLE = (
    '<figure class="table"><header><h2>Heading</h2></header><table><thead><tr><th>H1</th><th>H2</th></tr></thead>'
    "<tbody><tr><td>a</td><td>b</td></tr></tbody></table></figure>"
)


def test_extract_markup_table_figure_with_header() -> None:
    """``figure.table`` becomes TableCt with a head, label cells in the header row and ordinary cells."""
    (table,) = _convert(_TABLE)
    assert isinstance(table, osis.TableCt)
    assert table.head is not None
    assert isinstance(table.head.content[0], osis.HeadCt)
    header_row, body_row = table.row
    assert [c.role for c in header_row.cell] == [osis.TableRole.LABEL] * 2
    assert [c.content for c in body_row.cell] == [["a"], ["b"]]


def test_extract_markup_table_figure_without_header_has_no_head() -> None:
    """A table figure with no ``header`` has ``head=None``."""
    (table,) = _convert(
        '<figure class="table"><table><tbody><tr><td>x</td></tr></tbody></table></figure>'
    )
    assert isinstance(table, osis.TableCt)
    assert table.head is None
    assert len(table.row) == 1


def test_extract_markup_table_figure_without_table_raises() -> None:
    """A table figure that contains no ``table`` raises ValueError."""
    with pytest.raises(ValueError, match="Could not find table"):
        _convert('<figure class="table"></figure>')


def test_extract_markup_bare_table_raises() -> None:
    """A ``table`` outside a figure is not supported."""
    with pytest.raises(NotImplementedError, match="inside a figure"):
        extract_markup(_tag("<table></table>"), {})


def test_extract_markup_tfoot_raises() -> None:
    """``tfoot`` is not yet implemented."""
    with pytest.raises(NotImplementedError, match="Tfoot"):
        extract_markup(_tag("<tfoot></tfoot>"), {})


def test_extract_markup_thead_tbody_header_pass_children_through() -> None:
    """thead, tbody and header are transparent containers."""
    for html in ("<thead>x</thead>", "<tbody>x</tbody>", "<header>x</header>"):
        assert _convert(html) == ["x"]


@pytest.mark.parametrize("name", ["h1", "h2", "h3", "h4", "h5", "h6"])
def test_extract_markup_headings_become_head(name: str) -> None:
    """Every ``h1``-``h6`` becomes HeadCt."""
    (head,) = _convert(f"<{name}>Title</{name}>")
    assert isinstance(head, osis.HeadCt)
    assert head.content == ["Title"]


def test_extract_markup_row_ignores_whitespace_between_cells() -> None:
    """``tr`` keeps only its cells, dropping whitespace strings between them."""
    (row,) = _convert("<tr>\n <td>a</td>\n <th>b</th>\n</tr>")
    assert isinstance(row, osis.RowCt)
    assert len(row.cell) == 2


@pytest.mark.parametrize(
    ("css", "expected"),
    [
        ("credit", osis.OsisDivs.ACKNOWLEDGEMENT),
        ("publish-info", "x-publish-info"),
        ("copyright-info", "x-copyright-info"),
    ],
)
def test_extract_markup_known_div_classes(css: str, expected: Any) -> None:
    """``div.credit``, ``div.publish-info`` and ``div.copyright-info`` map to their OSIS div types."""
    (div,) = _convert(f'<div class="{css}">text</div>')
    assert isinstance(div, osis.DivCt)
    assert div.type_value == expected
    assert div.content == ["text"]


def test_extract_markup_card_label_div_is_skipped() -> None:
    """``div.card-label`` (mobile duplicate of a column header) produces nothing."""
    assert _convert('<div class="card-label">Label</div>') == []


def test_extract_markup_unknown_div_warns() -> None:
    """An unrecognised div becomes an x-unknown div with a warning."""
    with pytest.warns(UserWarning, match="Unknown Div tag"):
        (div,) = extract_markup(_tag('<div class="weird">x</div>'), {})
    assert isinstance(div, osis.DivCt) and div.type_value == "x-unknown"


def test_extract_markup_br_section_blockquote() -> None:
    """``br`` becomes a line break; ``section`` and ``blockquote`` become x- divs."""
    assert isinstance(_convert("<br/>")[0], osis.LbCt)
    (section,) = _convert("<section>s</section>")
    (quote,) = _convert("<blockquote>q</blockquote>")
    assert isinstance(section, osis.DivCt) and section.type_value == "x-section"
    assert isinstance(quote, osis.DivCt) and quote.type_value == "x-blockquote"


def test_extract_markup_unsupported_tag_raises() -> None:
    """An element the converter has no rule for raises ValueError."""
    with pytest.raises(ValueError, match="Not sure how to parse markup"):
        extract_markup(_tag("<marquee>x</marquee>"), {})


def test_extract_markup_figure_without_known_class_raises() -> None:
    """A figure that is neither ``image`` nor ``table`` falls through to ValueError."""
    with pytest.raises(ValueError, match="Not sure how to parse markup"):
        extract_markup(_tag('<figure class="video"></figure>'), {})


def test_extract_markup_span_without_class_attribute() -> None:
    """A classless ``span`` is treated as an unknown span (warn, pass through) rather than crash."""
    with pytest.warns(UserWarning, match="Unknown span class"):
        assert extract_markup(_tag("<span>x</span>"), {}) == ["x"]


def test_extract_markup_div_without_class_attribute() -> None:
    """A classless ``div`` is treated as an unknown div (warn, ``x-unknown`` wrapper)."""
    with pytest.warns(UserWarning, match="Unknown Div tag"):
        (result,) = extract_markup(_tag("<div>x</div>"), {})
    assert isinstance(result, osis.DivCt)
    assert result.type_value == "x-unknown" and result.content == ["x"]


def test_extract_markup_anchor_without_class_attribute_is_unparseable() -> None:
    """A classless ``a`` matches no known anchor class and reaches the generic ValueError."""
    with pytest.raises(ValueError, match="Not sure how to parse markup"):
        extract_markup(_tag('<a href="#x">x</a>'), {})


def test_extract_markup_figure_without_class_attribute_is_unparseable() -> None:
    """A classless ``figure`` is neither image nor table, so it reaches the generic ValueError."""
    with pytest.raises(ValueError, match="Not sure how to parse markup"):
        extract_markup(_tag("<figure>x</figure>"), {})


def test_extract_markup_classless_span_inside_paragraph_keeps_text() -> None:
    """A classless span nested in a paragraph passes its text through to the paragraph."""
    with pytest.warns(UserWarning, match="Unknown span class"):
        (result,) = extract_markup(_tag("<p>a <span>b</span> c</p>"), {})
    assert isinstance(result, osis.PCt) and result.content == ["a b c"]


@pytest.mark.parametrize(
    ("html", "expected_type"),
    [
        ('<span class="dominant">x</span>', None),
        ('<div class="credit">x</div>', osis.OsisDivs.ACKNOWLEDGEMENT),
        ('<div class="publish-info">x</div>', "x-publish-info"),
    ],
)
def test_extract_markup_classed_tags_unchanged(html: str, expected_type: object) -> None:
    """Tags that do have a recognised class still convert exactly as before."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = extract_markup(_tag(html), {})
    if expected_type is None:
        assert result == ["x"]
    else:
        (div,) = result
        assert isinstance(div, osis.DivCt) and div.type_value == expected_type


@given(st.sampled_from(["span", "div"]), st.text(alphabet="abc xyz", min_size=1, max_size=20))
def test_extract_markup_classless_span_or_div_never_raises(name: str, text: str) -> None:
    """Classless span/div elements always convert (with a warning) whatever their text."""
    tag = bs4.BeautifulSoup(f"<{name}></{name}>", "html.parser").find(name)
    assert isinstance(tag, bs4.element.Tag)
    tag.append(bs4.element.NavigableString(text))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert extract_markup(tag, {})


@given(st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc")), max_size=40))
def test_extract_markup_plain_text_in_paragraph_is_preserved(text: str) -> None:
    """Text without markup inside a ``p`` is returned verbatim as the paragraph's only child."""
    p = bs4.BeautifulSoup("<p></p>", "html.parser").p
    assert p is not None
    p.append(bs4.element.NavigableString(text))
    (result,) = extract_markup(p, {})
    assert isinstance(result, osis.PCt)
    assert result.content == [text]


# --- build_chapter -----------------------------------------------------------------------------

_BODY_WITH_TITLE = """
<p id="title1"><span class="dominant">The First Book of Nephi</span></p>
<div class="body-block">
  <p class="verse"><span class="verse-number">1</span>I, Nephi...</p>
</div>
"""

_BODY_WITHOUT_TITLE = """
<div class="body-block">
  <p class="verse"><span class="verse-number">1</span>In the beginning...</p>
</div>
"""


def test_build_chapter_title_with_short_name() -> None:
    """build_chapter emits TitleCt(type=main, short=book_short_name) when book_short_name is given."""
    sc = _chapter(_BODY_WITH_TITLE)
    _chapter_ct, front_matter = build_chapter(
        sc, book_osis_id="1 Nephi", chapter_number=1, book_short_name="1 Nephi"
    )
    main_titles = _titles(front_matter, osis.OsisTitles.MAIN)
    assert len(main_titles) == 1
    assert main_titles[0].short == "1 Nephi"
    assert main_titles[0].content == ["The First Book of Nephi"]


def test_build_chapter_title_without_short_name() -> None:
    """build_chapter emits TitleCt(type=main, short=None) when book_short_name is not given."""
    _chapter_ct, front_matter = build_chapter(
        _chapter(_BODY_WITH_TITLE), book_osis_id="1 Nephi", chapter_number=1
    )
    main_titles = _titles(front_matter, osis.OsisTitles.MAIN)
    assert len(main_titles) == 1
    assert main_titles[0].short is None


def test_build_chapter_no_title_tag() -> None:
    """build_chapter produces no front matter when there is no title tag in the HTML."""
    _chapter_ct, front_matter = build_chapter(
        _chapter(_BODY_WITHOUT_TITLE),
        book_osis_id="Gen",
        chapter_number=2,
        book_short_name="Genesis",
    )
    assert front_matter is None


def test_build_chapter_verses_ids_and_text() -> None:
    """Each ``p.verse`` becomes a VerseCt with id ``<book>.<chapter>.<n>``; the verse number is not in the text."""
    body = (
        '<div class="body-block">'
        '<p class="verse"><span class="verse-number">1 </span>First.</p>'
        '<p class="verse"><span class="verse-number">2</span>Second <b>bold</b>.</p></div>'
    )
    chapter, _ = build_chapter(_chapter(body), book_osis_id="Gen", chapter_number=3)
    assert chapter.osis_id == ["Gen.3"]
    assert chapter.canonical is False
    first, second = chapter.content
    assert isinstance(first, osis.VerseCt)
    assert first.osis_id == ["Gen.3.1"] and first.s_id == first.e_id == "Gen.3.1"
    assert first.content == ["First."]
    assert isinstance(second, osis.VerseCt)
    assert second.osis_id == ["Gen.3.2"]
    assert second.content[0] == "Second "


def test_build_chapter_page_breaks_are_removed() -> None:
    """Page break markers inside verses never reach the output."""
    body = (
        '<div class="body-block"><p class="verse"><span class="verse-number">1</span>a'
        '<span class="page-break"></span>b</p></div>'
    )
    chapter, _ = build_chapter(_chapter(body), book_osis_id="Gen", chapter_number=1)
    assert chapter.content[0].content == ["ab"]  # type: ignore[attr-defined]


def test_build_chapter_h1_title_is_accepted() -> None:
    """A title in ``h1#title1`` is handled like one in ``p#title1``."""
    body = (
        '<h1 id="title1"><span class="dominant">Genesis</span></h1><div class="body-block"></div>'
    )
    _chapter_ct, front = build_chapter(_chapter(body), book_osis_id="Gen", chapter_number=1)
    assert _titles(front, osis.OsisTitles.MAIN)[0].content == ["Genesis"]


def test_build_chapter_title_extras_become_subtitles_and_paragraphs() -> None:
    """Text after the dominant span becomes a sub title, markup becomes a p, and ``br`` is dropped."""
    body = (
        '<p id="title1"><span class="dominant">Book</span><br/>Sub title text <br/>'
        '<span class="small-caps">Smcp</span></p><div class="body-block"></div>'
    )
    _chapter_ct, front = build_chapter(_chapter(body), book_osis_id="X", chapter_number=1)
    subs = _titles(front, osis.OsisTitles.SUB)
    assert [t.content for t in subs] == [["Sub title text"]]
    paragraphs = [i for i in front or [] if isinstance(i, osis.PCt)]
    assert len(paragraphs) == 1 and isinstance(paragraphs[0].content[0], osis.HiCt)
    assert not any(isinstance(i, osis.LbCt) for i in front or [])


def test_build_chapter_subtitle_intro_and_study_intro() -> None:
    """``p.subtitle``, ``p.intro`` and ``p.study-intro`` become a sub title and two introduction divs."""
    body = (
        '<p class="subtitle">Sub</p><p class="intro">Intro</p><p class="study-intro">Study</p>'
        '<div class="body-block"></div>'
    )
    _chapter_ct, front = build_chapter(_chapter(body), book_osis_id="X", chapter_number=1)
    assert front is not None
    sub, intro, study = front
    assert isinstance(sub, osis.TitleCt) and sub.type_value == osis.OsisTitles.SUB
    assert isinstance(intro, osis.DivCt) and intro.canonical is True
    assert intro.type_value == osis.OsisDivs.INTRODUCTION
    assert isinstance(study, osis.DivCt) and study.canonical is False


def test_build_chapter_study_summary_precedes_verses() -> None:
    """``p.study-summary`` becomes a non-canonical summary div placed before the verses."""
    body = (
        '<p class="study-summary">Summary</p><div class="body-block">'
        '<p class="verse"><span class="verse-number">1</span>v</p></div>'
    )
    chapter, _ = build_chapter(_chapter(body), book_osis_id="X", chapter_number=1)
    summary, verse = chapter.content
    assert isinstance(summary, osis.DivCt)
    assert summary.type_value == osis.OsisDivs.SUMMARY and summary.canonical is False
    assert isinstance(verse, osis.VerseCt)


def test_build_chapter_contains_line_verse_wrapped_in_line_group() -> None:
    """A ``p.verse.contains-line`` has its ``span.line`` elements wrapped in a single LgCt."""
    body = (
        '<div class="body-block"><p class="verse contains-line"><span class="verse-number">1</span>'
        '<span class="line">one</span> <span class="line">two</span></p></div>'
    )
    chapter, _ = build_chapter(_chapter(body), book_osis_id="Ps", chapter_number=1)
    verse = chapter.content[0]
    assert isinstance(verse, osis.VerseCt)
    (group,) = verse.content
    assert isinstance(group, osis.LgCt)
    assert [line.content for line in group.l] == [["one"], ["two"]]


def test_build_chapter_missing_verse_number_raises() -> None:
    """A verse paragraph without ``span.verse-number`` raises ValueError."""
    body = '<div class="body-block"><p class="verse">No number</p></div>'
    with pytest.raises(ValueError, match="Cannot find verse number"):
        build_chapter(_chapter(body), book_osis_id="X", chapter_number=1)


def test_build_chapter_footnotes_become_notes() -> None:
    """Footnote links inside verses are converted using the chapter's footnotes dictionary."""
    body = (
        '<div class="body-block"><p class="verse"><span class="verse-number">1</span>'
        '<a class="study-note-ref" href="#note1a"><sup class="marker"></sup>word</a></p></div>'
    )
    chapter, _ = build_chapter(
        _chapter(body, {"note1a": {"id": "note1a", "text": "<p>Note</p>"}}),
        book_osis_id="X",
        chapter_number=1,
    )
    verse = chapter.content[0]
    assert isinstance(verse, osis.VerseCt)
    assert isinstance(verse.content[0], osis.NoteCt) and verse.content[0].content == ["Note"]


@given(st.lists(st.integers(1, 176), min_size=1, max_size=15, unique=True))
def test_build_chapter_verse_ids_follow_verse_numbers(numbers: list[int]) -> None:
    """For arbitrary verse numbers, the OSIS verse ids are ``<book>.<chapter>.<number>`` in document order."""
    verses = "".join(
        f'<p class="verse"><span class="verse-number">{n}</span>t</p>' for n in numbers
    )
    body = f'<div class="body-block">{verses}</div>'
    chapter, _ = build_chapter(_chapter(body), book_osis_id="Ps", chapter_number=7)
    assert [v.osis_id[0] for v in chapter.content] == [f"Ps.7.{n}" for n in numbers]  # type: ignore[attr-defined]


# --- build_book --------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_book_multi_chapter(site: FakeSite, make_client) -> None:
    """build_book fetches the table of contents and every chapter, in order, with front matter."""
    site.pages["/scriptures/bofm/jacob"] = (
        '<ul><li><p class="title">Chapter 1</p></li><li><p class="title">Chapter 2</p></li></ul>'
    )
    async with make_client(site) as client:
        book = await build_book("eng", "BookOfMormon", "Jacob", client)
    assert isinstance(book, osis.DivCt)
    assert book.osis_id == ["Jacob"]
    assert book.canonical is True and book.type_value == osis.OsisDivs.BOOK
    kinds = [type(c) for c in book.content]
    assert kinds == [osis.TitleCt, osis.ChapterCt, osis.TitleCt, osis.ChapterCt]
    assert [c.osis_id for c in book.content if isinstance(c, osis.ChapterCt)] == [
        ["Jacob.1"],
        ["Jacob.2"],
    ]
    assert book.content[0].short == "Jacob"  # type: ignore[attr-defined]
    assert sorted(site.uris()) == [
        "/scriptures/bofm/jacob",
        "/scriptures/bofm/jacob/1",
        "/scriptures/bofm/jacob/2",
    ]


@pytest.mark.asyncio
async def test_build_book_single_chapter_via_redirect(site: FakeSite, make_client) -> None:
    """A book whose table of contents redirects is built as a single chapter."""
    async with make_client(site) as client:
        book = await build_book("eng", "BookOfMormon", "Enos", client)
    chapters = [c for c in book.content if isinstance(c, osis.ChapterCt)]
    assert [c.osis_id for c in chapters] == [["Enos.1"]]


def test_one_element_alias_is_bs4_node_type() -> None:
    """OneElement is BeautifulSoup's private node type alias, accepting both Tag and NavigableString."""
    assert build_osis.OneElement is not None
