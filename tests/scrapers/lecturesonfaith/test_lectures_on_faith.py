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


def _lecture(
    number: int, factory: str = "T", qa: str = "_", paragraphs: int = 2, extra: str = ""
) -> str:
    """Build one minified lecture entry with ``paragraphs`` paragraphs and, for lectures 1-5, one question."""
    ordinal = ["", "First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh"][number]
    questions = f'{qa}("Question {number}?","Answer {number}. (1:1)")' if number <= 5 else ""
    body = [f'{factory}(1,"Lecture {number} opens.")'] + [
        f'{factory}({n},"It closes\\u2014so.")' for n in range(2, paragraphs + 1)
    ]
    return (
        f'{{number:{number},title:`Title\nof {number}`,subtitle:"Lecture {ordinal}",'
        f"paragraphs:[{','.join(body)}],qa:[{questions}]{extra}}}"
    )


PREFACE = (
    '{number:0,title:"Preface",subtitle:"",paragraphs:[T(1,"DEAR BRETHREN:"),'
    'T(2,`JOSEPH SMITH jr.\nOLIVER COWDERY.`),T(3,"Kirtland, Ohio, February 17, 1835.")],qa:[]}'
)


def array_1835(lectures: range = range(1, 8)) -> str:
    """Build the 1835 array (preface + lectures) with its factories ``T`` and ``_``."""
    entries = [
        _lecture(n, extra=',note:"Commit the whole to memory."' if n == 6 else "") for n in lectures
    ]
    return (
        "function T(e,t){return{number:e,text:t}}function _(e,t){return{question:e,answer:t}}"
        f"const at=[{PREFACE},{','.join(entries)}];function PT(){{return at}}"
    )


def array_rse(lectures: range = range(1, 8)) -> str:
    """Build the Revised Standard Edition array (lectures only, three paragraphs each) with factories ``g``/``C``."""
    entries = [_lecture(n, factory="g", qa="C", paragraphs=3) for n in lectures]
    return (
        "function g(e,t){return{number:e,text:t}}function C(e,t){return{question:e,answer:t}}"
        f"const Ky=[{','.join(entries)}];"
    )


def make_bundle(old: str | None = None, rse: str | None = None) -> str:
    """Build a bundle with both editions, preceded by an unrelated factory reusing the name ``g``.

    The decoy ``g`` builds different keys; the revised array must use the ``g`` defined just before it.
    """
    return (
        "var x=1;function g(e,t){return{n:e,body:t}}"
        + (array_1835() if old is None else old)
        + (array_rse() if rse is None else rse)
    )


def test_find_bundle_url_resolves_the_module_script():
    """The main module script on the home page is resolved against the site URL."""
    assert lof.find_bundle_url(INDEX_HTML) == "https://lecturesonfaith.com/assets/index-Cpfpq6uF.js"


def test_find_bundle_url_without_bundle_raises():
    """A home page without the bundle script is an error."""
    with pytest.raises(ValueError, match="names no"):
        lof.find_bundle_url("<html></html>")


def test_extract_editions_reads_the_1835_array():
    """The 1835 preface and seven lectures are read with their paragraphs, catechisms and note."""
    (edition, lectures), _ = lof.extract_editions(make_bundle())
    assert edition is lof.EDITION_1835
    assert [lecture.number for lecture in lectures] == list(range(8))
    preface, first = lectures[0], lectures[1]
    assert preface.paragraphs[1] == lof.Paragraph(2, "JOSEPH SMITH jr.\nOLIVER COWDERY.")
    assert first.subtitle == "Lecture First"
    assert first.paragraphs == (
        lof.Paragraph(1, "Lecture 1 opens."),
        lof.Paragraph(2, "It closes\u2014so."),
    )
    assert first.qa == (lof.QuestionAnswer("Question 1?", "Answer 1. (1:1)"),)
    assert lectures[6].qa == ()
    assert lectures[6].note == "Commit the whole to memory."


def test_extract_editions_reads_the_revised_array_with_its_own_factories():
    """The revised edition has no preface, its own paragraph numbering, and uses the nearest factory definitions."""
    _, (edition, lectures) = lof.extract_editions(make_bundle())
    assert edition is lof.EDITION_RSE
    assert [lecture.number for lecture in lectures] == list(range(1, 8))
    assert [p.number for p in lectures[0].paragraphs] == [1, 2, 3]
    assert lectures[0].qa == (lof.QuestionAnswer("Question 1?", "Answer 1. (1:1)"),)


def test_extract_editions_order_does_not_depend_on_bundle_order():
    """Editions are identified by content, not by where they appear in the bundle."""
    bundle = "var x=1;" + array_rse() + array_1835()
    assert [edition for edition, _ in lof.extract_editions(bundle)] == list(lof.EDITIONS)


@pytest.mark.parametrize(
    ("bundle", "match"),
    [
        (array_rse(), "No lecture array in the bundle for: Lectures on Faith \\(1835\\)"),
        (array_1835(), "Revised Standard Edition"),
        (array_1835() + array_1835(), "two lecture arrays"),
    ],
    ids=["no-1835", "no-rse", "duplicate"],
)
def test_extract_editions_requires_each_edition_once(bundle, match):
    """Both editions must be present, each exactly once."""
    with pytest.raises(ValueError, match=match):
        lof.extract_editions(bundle)


def test_extract_editions_rejects_missing_lecture():
    """Each edition must hold all seven lectures."""
    with pytest.raises(ValueError, match="Revised Standard Edition.*expected lectures"):
        lof.extract_editions(make_bundle(rse=array_rse(range(1, 7))))


def test_extract_editions_rejects_paragraph_gap():
    """Paragraph numbers must run 1, 2, 3, ... with no gap."""
    old = array_1835().replace('T(2,"It closes', 'T(3,"It closes', 1)
    with pytest.raises(
        ValueError, match="\\(1835\\): lecture 1 paragraphs are numbered \\[1, 3\\]"
    ):
        lof.extract_editions(make_bundle(old=old))


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
    """The book group parses into two books: 1835 (preface + lectures) and the revised edition (lectures only)."""
    osis = lof.generate_osis(lof.extract_editions(make_bundle()))
    document = parse_osis_text(osis.osis.osis_text)
    old, rse = document.divisions
    assert (old.div_id, old.short_title) == ("LoF1835", "1835 Edition")
    assert (rse.div_id, rse.short_title) == ("LoFRSE", "Revised Standard Edition")
    assert [chapter.chapter_id for chapter in old.chapters] == [
        "LoF1835.Preface",
        *(f"LoF1835.{n}" for n in range(1, 8)),
    ]
    assert [chapter.chapter_id for chapter in rse.chapters] == [f"LoFRSE.{n}" for n in range(1, 8)]

    preface_text = [item.content[0] for item in old.chapters[0].body]
    assert preface_text == [
        "DEAR BRETHREN:",
        "JOSEPH SMITH jr.",
        "OLIVER COWDERY.",
        "Kirtland, Ohio, February 17, 1835.",
    ]

    first = old.chapters[1]
    assert first.title == "Lecture First"
    assert [verse.verse_id for verse in first.verses] == ["LoF1835.1.1", "LoF1835.1.2"]
    assert [section.title for section in first.sections] == [lof.QA_HEADING]
    assert first.trailing_body_count == 1
    assert [verse.verse_id for verse in rse.chapters[0].verses] == [
        "LoFRSE.1.1",
        "LoFRSE.1.2",
        "LoFRSE.1.3",
    ]

    sixth = old.chapters[6]
    assert sixth.sections == []
    assert [item.content for item in sixth.body] == [["Commit the whole to memory."]]


def test_generate_osis_xml_contains_question_and_answer():
    """Questions are bold and answers keep their paragraph references verbatim, inside a book group."""
    xml = lof.generate_osis(lof.extract_editions(make_bundle())).to_xml()
    assert 'type="bookGroup" osisID="LoF"' in xml
    assert '<hi type="bold"' in xml and "Question 1?</hi>" in xml
    assert "Answer 1. (1:1)" in xml
    assert 'osisID="LoF1835.7.2"' in xml and 'osisID="LoFRSE.7.3"' in xml


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
    assert "index-Cpfpq6uF.js" in text and 'osisID="LoF1835.1.1"' in text
    assert fetcher.closed


def test_spec_is_registered():
    """The scraper is available as ``open-canon-scrape lectures-on-faith``."""
    spec = registry.get_scraper("lectures-on-faith")
    assert spec is lof.SPEC
    assert spec.outputs == ("lectures_on_faith.xml",)
