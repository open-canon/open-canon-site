"""Tests for the OSIS content renderer."""

from __future__ import annotations

from open_canon_site.renderer import _int_to_alpha, render_content, render_note_content

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def test_int_to_alpha_single():
    assert _int_to_alpha(1) == "a"
    assert _int_to_alpha(26) == "z"


def test_int_to_alpha_double():
    assert _int_to_alpha(27) == "aa"
    assert _int_to_alpha(52) == "az"


# ---------------------------------------------------------------------------
# Rendering plain strings
# ---------------------------------------------------------------------------


def test_render_plain_string():
    assert render_content(["Hello world"]) == "Hello world"


def test_render_html_escaped():
    assert render_content(["<b>bold</b>"]) == "&lt;b&gt;bold&lt;/b&gt;"


def test_render_none_item():
    assert render_content([None]) == ""


def test_render_empty_list():
    assert render_content([]) == ""


# ---------------------------------------------------------------------------
# Note markers
# ---------------------------------------------------------------------------


def test_render_note_marker_tuple():
    nc = [0]
    result = render_content([("note_marker", "doc-n1")], nc)
    assert '<sup class="note-marker"' in result
    assert 'data-note="doc-n1"' in result
    assert ">a<" in result  # first marker is "a"


def test_render_note_marker_increments():
    nc = [0]
    content = [
        ("note_marker", "doc-n1"),
        ("note_marker", "doc-n2"),
    ]
    result = render_content(content, nc)
    assert ">a<" in result
    assert ">b<" in result


def test_render_note_marker_links_to_note():
    nc = [0]
    result = render_content([("note_marker", "doc-n1")], nc)
    assert 'href="#note-doc-n1"' in result


# ---------------------------------------------------------------------------
# Pyosis element rendering
# ---------------------------------------------------------------------------


def _make_hi(type_value_str: str, inner: str):
    """Create a HiCt instance with the given type."""
    from pyosis.generated.osis_core_2_1_1 import HiCt, OsisHi

    return HiCt.model_construct(type_value=OsisHi(type_value_str), content=[inner])


def test_render_hi_italic():
    hi = _make_hi("italic", "word")
    assert render_content([hi]) == "<em>word</em>"


def test_render_hi_bold():
    hi = _make_hi("bold", "word")
    assert render_content([hi]) == "<strong>word</strong>"


def test_render_hi_small_caps():
    hi = _make_hi("small-caps", "Lord")
    assert 'class="small-caps"' in render_content([hi])


def _make_divine_name(text: str):
    from pyosis.generated.osis_core_2_1_1 import DivineNameCt

    return DivineNameCt.model_construct(content=[text])


def test_render_divine_name():
    dn = _make_divine_name("LORD")
    result = render_content([dn])
    assert '<span class="divine-name">LORD</span>' == result


def test_render_line_group_from_structured_children():
    from pyosis.generated.osis_core_2_1_1 import LCt, LgCt

    lg = LgCt.model_construct(
        l=[
            LCt.model_construct(content=["Line one"]),
            LCt.model_construct(content=["Line two"]),
        ]
    )

    assert (
        render_content([lg])
        == '<div class="lg"><div class="l">Line one</div><div class="l">Line two</div></div>'
    )


def _make_note_ct(inner: str):
    from pyosis.generated.osis_core_2_1_1 import NoteCt

    return NoteCt.model_construct(content=[inner])


def test_render_inline_note_is_suppressed():
    """NoteCt instances that were not pre-processed by parser should be hidden."""
    note = _make_note_ct("Note text")
    assert render_content([note]) == ""


def test_render_note_content():
    result = render_note_content(["See <b>John</b> 1:1"])
    assert "See &lt;b&gt;John&lt;/b&gt; 1:1" in result


# ---------------------------------------------------------------------------
# Mixed content
# ---------------------------------------------------------------------------


def test_render_mixed_string_and_elements():
    hi = _make_hi("italic", "own")
    result = render_content(["In his ", hi, " image"])
    assert result == "In his <em>own</em> image"
