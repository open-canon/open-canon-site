"""Unit tests for extract_markup span class handling."""

import warnings

import bs4
import pyosis.generated

from open_canon_site.scrapers.churchofjesuschrist.build_osis import extract_markup


def test_translit_span_with_lang() -> None:
    """extract_markup maps <span class="translit" lang="hbo"> to ForeignCt with the given lang."""
    html = bs4.BeautifulSoup('<span class="translit" lang="hbo">Elohim</span>', "html.parser")
    tag = html.find("span")
    assert isinstance(tag, bs4.element.Tag)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = extract_markup(tag, {})

    assert len(result) == 1
    foreign = result[0]
    assert isinstance(foreign, pyosis.generated.ForeignCt)
    assert foreign.lang == "hbo"
    assert foreign.content == ["Elohim"]


def test_translit_span_without_lang() -> None:
    """extract_markup maps <span class="translit"> (no lang) to ForeignCt with an empty lang."""
    html = bs4.BeautifulSoup('<span class="translit">YHWH</span>', "html.parser")
    tag = html.find("span")
    assert isinstance(tag, bs4.element.Tag)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = extract_markup(tag, {})

    assert len(result) == 1
    foreign = result[0]
    assert isinstance(foreign, pyosis.generated.ForeignCt)
    assert foreign.lang == ""
    assert foreign.content == ["YHWH"]


def test_clarity_word_span_maps_to_trans_change_added() -> None:
    """<span class="clarity-word"> should map to TransChangeCt(type_value="added")."""
    html = bs4.BeautifulSoup('<span class="clarity-word">the</span>', "html.parser")
    tag = html.find("span")
    assert tag is not None

    result = extract_markup(tag, footnotes_dict={})

    assert len(result) == 1
    node = result[0]
    assert isinstance(node, pyosis.generated.TransChangeCt)
    assert node.type_value == "added"
    assert node.content == ["the"]
