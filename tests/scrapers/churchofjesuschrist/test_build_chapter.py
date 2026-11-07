"""Unit tests for build_chapter title handling."""

import pyosis.generated

from open_canon_site.scrapers.churchofjesuschrist.build_osis import build_chapter
from open_canon_site.scrapers.churchofjesuschrist.models import Content, Meta, ScriptureStudyContent


def _make_scripture_content(body: str) -> ScriptureStudyContent:
    """Create a minimal ScriptureStudyContent for testing."""
    content = Content(head=None, body=body, footnotes={})
    meta = Meta(
        archived=False,
        title="Test",
        canonicalUrl="/",
        contentType="text/html",
        pageAttributes={},
        scopedClassName="classic-scripture",
    )
    return ScriptureStudyContent(
        meta=meta, content=content, pids=[], tableOfContentsUri="/", uri="/", verified=True
    )


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
    sc = _make_scripture_content(_BODY_WITH_TITLE)
    _chapter, front_matter = build_chapter(
        sc, book_osis_id="1 Nephi", chapter_number=1, book_short_name="1 Nephi"
    )

    assert front_matter is not None
    titles = [item for item in front_matter if isinstance(item, pyosis.generated.TitleCt)]
    main_titles = [t for t in titles if t.type_value == pyosis.generated.OsisTitles.MAIN]
    assert len(main_titles) == 1
    assert main_titles[0].short == "1 Nephi"
    assert main_titles[0].content == ["The First Book of Nephi"]


def test_build_chapter_title_without_short_name() -> None:
    """build_chapter emits TitleCt(type=main, short=None) when book_short_name is not given."""
    sc = _make_scripture_content(_BODY_WITH_TITLE)
    _chapter, front_matter = build_chapter(sc, book_osis_id="1 Nephi", chapter_number=1)

    assert front_matter is not None
    titles = [item for item in front_matter if isinstance(item, pyosis.generated.TitleCt)]
    main_titles = [t for t in titles if t.type_value == pyosis.generated.OsisTitles.MAIN]
    assert len(main_titles) == 1
    assert main_titles[0].short is None


def test_build_chapter_no_title_tag() -> None:
    """build_chapter produces no front matter when there is no title tag in the HTML."""
    sc = _make_scripture_content(_BODY_WITHOUT_TITLE)
    _chapter, front_matter = build_chapter(
        sc, book_osis_id="Gen", chapter_number=2, book_short_name="Genesis"
    )

    assert front_matter is None
