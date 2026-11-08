"""Unit tests for ``lecturesonfaith.lectures_on_faith`` against a trimmed copy of the site's JavaScript bundle."""

from __future__ import annotations

import argparse

import pytest
from open_canon_site.parser import parse_osis_text
from open_canon_site.scrapers import registry
from open_canon_site.scrapers.lecturesonfaith import lectures_on_faith as lof

INDEX_HTML = (
    "<!doctype html><html><head><title>Lectures on Faith</title>"
    '<script type="module" crossorigin src="/assets/index-Cpfpq6uF.js"></script>'
    '<link rel="stylesheet" crossorigin href="/assets/index-IlToXtk1.css">'
    '<script defer src="/~flock.js"></script></head><body><div id="root"></div></body></html>'
)


def _lecture(number: int, factory: str = "T", qa: str = "_", extra: str = "") -> str:
    """Build one minified lecture entry with two paragraphs and, for lectures 1-5, one question."""
    ordinal = ["", "First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh"][number]
    questions = f'{qa}("Question {number}?","Answer {number}. (1:1)")' if number <= 5 else ""
    return (
        f'{{number:{number},title:`Title\nof {number}`,subtitle:"Lecture {ordinal}",'
        f'paragraphs:[{factory}(1,"Lecture {number} opens."),{factory}(2,"It closes\\u2014so.")],'
        f"qa:[{questions}]{extra}}}"
    )


def make_bundle(rse: bool = True) -> str:
    """Build a bundle holding the 1835 array (preface + 7 lectures) and, optionally, an RSE array after it."""
    preface = (
        '{number:0,title:"Preface",subtitle:"",paragraphs:[T(1,"DEAR BRETHREN:"),'
        'T(2,`JOSEPH SMITH jr.\nOLIVER COWDERY.`),T(3,"Kirtland, Ohio, February 17, 1835.")],qa:[]}'
    )
    lectures = [
        _lecture(n, extra=',note:"Commit the whole to memory."' if n == 6 else "")
        for n in range(1, 8)
    ]
    bundle = (
        "var x=1;function T(e,t){return{number:e,text:t}}function _(e,t){return{question:e,answer:t}}"
        f"const at=[{preface},{','.join(lectures)}];function PT(){{return at}}"
    )
    if rse:
        # The modernised edition reuses the factory names with different keys; it must not affect the 1835 array.
        bundle += f"function T(e,t){{return{{n:e,body:t}}}}const Ky=[{_lecture(1, factory='T')}];"
    return bundle


def test_find_bundle_url_resolves_the_module_script():
    """The main module script on the home page is resolved against the site URL."""
    assert lof.find_bundle_url(INDEX_HTML) == "https://lecturesonfaith.com/assets/index-Cpfpq6uF.js"


def test_find_bundle_url_without_bundle_raises():
    """A home page without the bundle script is an error."""
    with pytest.raises(ValueError, match="names no"):
        lof.find_bundle_url("<html></html>")


def test_extract_lectures_reads_the_1835_array():
    """The preface and seven lectures are read with their paragraphs, catechisms and note."""
    lectures = lof.extract_lectures(make_bundle())
    assert [lecture.number for lecture in lectures] == list(range(8))
    preface, first = lectures[0], lectures[1]
    assert preface.paragraphs[1] == lof.Paragraph(2, "JOSEPH SMITH jr.\nOLIVER COWDERY.")
    assert first.subtitle == "Lecture First"
    assert first.paragraphs == (
        lof.Paragraph(1, "Lecture 1 opens."),
        lof.Paragraph(2, "It closes—so."),
    )
    assert first.qa == (lof.QuestionAnswer("Question 1?", "Answer 1. (1:1)"),)
    assert lectures[6].qa == ()
    assert lectures[6].note == "Commit the whole to memory."


def test_extract_lectures_without_preface_array_raises():
    """A bundle with only the revised edition (no preface) is rejected."""
    with pytest.raises(ValueError, match="No 1835"):
        lof.extract_lectures(
            "function g(e,t){return{number:e,text:t}}const Ky=[" + _lecture(1, "g") + "]"
        )


def test_extract_lectures_rejects_missing_lecture():
    """The array must hold the preface and exactly seven lectures."""
    bundle = make_bundle(rse=False).replace("," + _lecture(7), "")
    with pytest.raises(ValueError, match="lectures 1-7"):
        lof.extract_lectures(bundle)


def test_extract_lectures_rejects_paragraph_gap():
    """Paragraph numbers must run 1, 2, 3, ... with no gap."""
    bundle = make_bundle(rse=False).replace('T(2,"It closes', 'T(3,"It closes', 1)
    with pytest.raises(ValueError, match="numbered \\[1, 3\\]"):
        lof.extract_lectures(bundle)


def test_parser_rejects_unsupported_javascript():
    """An identifier that is not a known factory fails loudly instead of being guessed at."""
    with pytest.raises(ValueError, match="Unsupported JavaScript"):
        lof.JsLiteralParser("[foo]", {}).parse(0)


def test_parser_rejects_template_substitution():
    """Template literals with substitutions are not text and are rejected."""
    with pytest.raises(ValueError, match="Template substitution"):
        lof.JsLiteralParser("[`a${b}`]", {}).parse(0)


def test_parser_decodes_escapes_and_literals():
    """Escapes, quoted keys, numbers and minified booleans are decoded."""
    source = r"""{'a':"x\"y\n\x41é\u{1F600}",b:[1,2.5,!0,!1]} rest"""
    value, end = lof.JsLiteralParser(source, {}).parse(0)
    assert value == {"a": 'x"y\nAé\U0001f600', "b": [1, 2.5, True, False]}
    assert source[end:] == " rest"


def test_generate_osis_structure_renders_as_expected():
    """The OSIS parses into a preface page and seven chapters, with Q&A after each lecture's verses."""
    osis = lof.generate_osis(lof.extract_lectures(make_bundle()))
    document = parse_osis_text(osis.osis.osis_text)
    (book,) = document.divisions
    assert book.div_id == "LoF"
    assert [chapter.chapter_id for chapter in book.chapters] == [
        "LoF.Preface",
        *(f"LoF.{n}" for n in range(1, 8)),
    ]
    preface = book.chapters[0]
    preface_text = [item.content[0] for item in preface.body]
    assert preface_text == [
        "DEAR BRETHREN:",
        "JOSEPH SMITH jr.",
        "OLIVER COWDERY.",
        "Kirtland, Ohio, February 17, 1835.",
    ]

    first = book.chapters[1]
    assert first.title == "Lecture First"
    assert [verse.verse_id for verse in first.verses] == ["LoF.1.1", "LoF.1.2"]
    assert [section.title for section in first.sections] == [lof.QA_HEADING]
    assert first.trailing_body_count == 1

    sixth = book.chapters[6]
    assert sixth.sections == []
    assert [item.content for item in sixth.body] == [["Commit the whole to memory."]]


def test_generate_osis_xml_contains_question_and_answer():
    """Questions are bold and answers keep their paragraph references verbatim."""
    xml = lof.generate_osis(lof.extract_lectures(make_bundle())).to_xml()
    assert '<hi type="bold"' in xml and "Question 1?</hi>" in xml
    assert "Answer 1. (1:1)" in xml
    assert 'osisID="LoF.7.2"' in xml


class FakeFetcher:
    """Serves the home page and bundle from memory."""

    def __init__(self, pages: dict[str, str]) -> None:
        """Store the pages to serve."""
        self.pages = pages
        """URL to body."""
        self.closed = False
        """Whether ``close`` was called."""

    def fetch_text(self, *, url: str) -> str:
        """Return the stored body for ``url``."""
        return self.pages[url]

    def close(self) -> None:
        """Record that the fetcher was closed."""
        self.closed = True


def test_run_writes_output_file(tmp_path, monkeypatch):
    """``run`` fetches the home page and bundle and writes ``lectures_on_faith.xml``."""
    fetcher = FakeFetcher({
        lof.SOURCE_URL: INDEX_HTML,
        "https://lecturesonfaith.com/assets/index-Cpfpq6uF.js": make_bundle(),
    })
    monkeypatch.setattr(lof, "CachedHttpFetcher", lambda **kwargs: fetcher)
    args = argparse.Namespace(output_dir=tmp_path, cache_dir=None, delay=0)
    (path,) = lof.run(args)
    assert path == tmp_path / "lectures_on_faith.xml"
    text = path.read_text("utf-8")
    assert "index-Cpfpq6uF.js" in text and 'osisID="LoF.1.1"' in text
    assert fetcher.closed


def test_spec_is_registered():
    """The scraper is available as ``open-canon-scrape lectures-on-faith``."""
    spec = registry.get_scraper("lectures-on-faith")
    assert spec is lof.SPEC
    assert spec.outputs == ("lectures_on_faith.xml",)
