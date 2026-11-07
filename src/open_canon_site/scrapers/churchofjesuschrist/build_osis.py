"""Build OSIS XML files."""

from __future__ import annotations

import asyncio
import copy
import warnings
from typing import cast

import bs4
import bs4._typing
import bs4.element
import httpx
import pyosis.generated

from open_canon_site.scrapers.churchofjesuschrist import models as church_website_models

OneElement = bs4._typing._OneElement  # pyright: ignore[reportPrivateUsage]


def clean_up_html(html: bs4.BeautifulSoup) -> bs4.BeautifulSoup:
    """Remove any Church website formatting oddities from the html (such as page break markers).

    Args:
        html: BeautifulSoup parsing the webpage.

    Returns:
        The same BeautifulSoup object (changes are made in place).
    """
    for span_page_break in html.find_all("span", class_="page-break"):
        span_page_break.extract()
    return html


def extract_footnote(
    tag: bs4.element.Tag, footnotes_dict: dict[str, church_website_models.Footnote]
) -> list[
    pyosis.generated.NoteCt
    | pyosis.generated.ReferenceCt
    | pyosis.generated.ForeignCt
    | str
    | object
]:
    """Extract a footnote from a BeautifulSoup Tag.

    Args:
        tag: Footnote tag from Church Website HTML.
        footnotes_dict: Dictionary of footnotes extract from Church Website JSON.

    Returns:
        List of OSIS Notes/References/Foreign tags.
    """
    note_content = extract_markup(tag, footnotes_dict, no_container=True)
    # If the mark href is an id, we should look it up in the dictionary, otherwise, we won't find it, and it's probably
    # a real link to somewhere else. Just copy it for now, since we don't know how to deal with it.
    href: str = cast(str, tag["href"])
    mark_href: str = href.lstrip("#")
    footnote_obj = footnotes_dict.get(mark_href, None)
    if footnote_obj is None:
        warnings.warn(f"Footnote {tag} did not have corresponding footnote content.")
        footnote_obj_text = mark_href
    else:
        footnote_obj_text = footnote_obj.text
    footnote_text = bs4.BeautifulSoup(footnote_obj_text, "html.parser").get_text()

    return [pyosis.generated.NoteCt(canonical=False, content=[footnote_text]), *note_content]


def extract_markup(
    tag: OneElement,
    footnotes_dict: dict[str, church_website_models.Footnote],
    no_container: bool = False,
) -> list[object]:
    """Extract markup from an BeautifulSoup Tag (i.e. html) and convert it to the equivalent OSIS structures.

    Args:
        tag: BeautifulSoup Tag.
        footnotes_dict: Dictionary whose keys are strings contained within the footnote html tags and values are parsed
            Footnote JSON objects.
        no_container: Whether to include the root element of the tag as a container for the contents when converting.

    Returns:
        List of PyOSIS objects or strings, which can be assembled into an OSIS XML document.

    Raises:
        NotImplementedError: If the function encounters a tag or structure that is not yet supported (e.g., <table>
            outside <figure>, <thead>, <tfoot>, <th>).
        ValueError: If the function encounters a tag it does not know how to parse.
    """

    def extract_children(tag: OneElement, no_strings: bool = False) -> list[object]:
        """Extracts and processes the children of a given tag element, optionally filtering out string elements.

        Args:
            tag: The tag element whose children are to be extracted and processed.
            no_strings: If True, string elements are excluded from the returned list. Defaults to False.

        Returns:
            A list of processed child elements, which may include strings and other objects,
            unless no_strings is True, in which case only non-string objects are included.
        """
        if isinstance(tag, bs4.element.NavigableString):
            return [extract_markup(tag, footnotes_dict=footnotes_dict)]
        assert isinstance(tag, bs4.element.Tag)
        contents: list[object] = []
        for content in tag.contents:
            extracted = extract_markup(content, footnotes_dict=footnotes_dict)
            for item in extracted:
                if isinstance(item, str) and contents and isinstance(contents[-1], str):
                    contents[-1] += item
                else:
                    contents.append(item)

        if no_strings:
            contents = [item for item in contents if not isinstance(item, str)]
        return contents

    if isinstance(tag, bs4.element.NavigableString):
        return [tag.text]

    assert isinstance(tag, bs4.element.Tag)

    # 2 Nephi 22 has (what I think is) a bug in the Church website, where the deity name class is outside the footnote,
    # when it should be on the text inside the footnote
    # <span class="deity-name"><span class="small-caps">
    # <a class="study-note-ref" href="/study/scriptures/bofm/2-ne/22?lang=eng#note2b" data-scroll-id="note2b">
    # <sup class="marker" data-value="b"></sup>Jehovah</a></span></span>
    # but we want
    # <a class="study-note-ref" href="/study/scriptures/bofm/2-ne/22?lang=eng#note2b" data-scroll-id="note2b">
    # <sup class="marker" data-value="b"></sup><span class="deity-name">
    # <span class="small-caps">Jehovah</span></span></a>
    # We want to extract the embedded `a`, wrap its contents in the `.deity-name` and `.small-caps` tags exactly as
    # present, and then put those into the `a`, and then process the `a`.
    if tag.name == "span" and "deity-name" in tag.attrs["class"]:
        deity_name_span = tag
        small_caps_span = deity_name_span.find("span", class_="small-caps")
        if isinstance(small_caps_span, bs4.element.Tag):
            a_tag = small_caps_span.find("a", class_="study-note-ref")
            if isinstance(a_tag, bs4.element.Tag):
                a_tag = a_tag.extract()
                a_tag_contents = copy.deepcopy(a_tag.contents)
                a_tag.clear()
                small_caps_span.extend(a_tag_contents)
                a_tag.insert(0, deity_name_span)
                tag = a_tag

    if no_container:
        return extract_children(tag)

    # These we should ignore and just return the contents
    if tag.name == "span" and "dominant" in tag.attrs["class"]:
        return extract_children(tag)

    if tag.name == "p":
        return [pyosis.generated.PCt(content=extract_children(tag))]

    if tag.name == "a" and "scripture-ref" in tag.attrs["class"]:
        # TODO: use Osis refs
        # There's an issue where the website refers to specific pages in the
        # captions for the illustrations (presumably pointing at the currently
        # published version of the Book of Mormon). Obviously, these pages
        # aren't going to be applicable in the OSIS version.

        tag_text = tag.get_text().strip()
        tag_text, *_ = tag_text.split(", page", maxsplit=1)
        if ",” page" in tag_text:
            tag_text, *_ = tag_text.split(",” page", maxsplit=1)
            tag_text += "”"

        return [pyosis.generated.ReferenceCt(canonical=False, content=[tag_text])]

    if (
        tag.name == "span"
        and ("small-caps" in tag.attrs["class"] or "uppercase" in tag.attrs["class"])
    ) or tag.name == "small":
        # TODO: Figure out a way to determine when small should be small caps or just smaller text.
        # TODO: Figure out a better way to represent <span class="uppercase">Translated by Joseph Smith</span>
        return [
            pyosis.generated.HiCt(
                type_value=pyosis.generated.OsisHi.SMALL_CAPS, content=extract_children(tag)
            )
        ]
    if tag.name == "sup":
        if tag.get_text().strip() == "":
            # This is a footnote marker, so we should return an empty string
            return []
        return [
            pyosis.generated.HiCt(
                type_value=pyosis.generated.OsisHi.SUPER, content=extract_children(tag)
            )
        ]
    if tag.name == "sub":
        return [
            pyosis.generated.HiCt(
                type_value=pyosis.generated.OsisHi.SUB, content=extract_children(tag)
            )
        ]
    if tag.name == "b":
        return [
            pyosis.generated.HiCt(
                type_value=pyosis.generated.OsisHi.BOLD, content=extract_children(tag)
            )
        ]
    if tag.name == "em":
        return [
            pyosis.generated.HiCt(
                type_value=pyosis.generated.OsisHi.EMPHASIS, content=extract_children(tag)
            )
        ]
    if tag.name == "i":
        return [
            pyosis.generated.HiCt(
                type_value=pyosis.generated.OsisHi.ITALIC, content=extract_children(tag)
            )
        ]

    if tag.name == "span" and "deity-name" in tag.attrs["class"]:
        return [pyosis.generated.DivineNameCt(content=extract_children(tag))]

    if tag.name == "span" and "language" in tag.attrs["class"]:
        # TODO: Parse language code
        return [
            pyosis.generated.ForeignCt(lang=str(tag.attrs["lang"]), content=extract_children(tag))
        ]

    if tag.name == "span" and "question" in tag.attrs.get("class", []):
        return [pyosis.generated.DivCt(type_value="x-question", content=extract_children(tag))]

    if tag.name == "span" and "answer" in tag.attrs.get("class", []):
        return [pyosis.generated.DivCt(type_value="x-answer", content=extract_children(tag))]

    if tag.name == "span" and "line" in tag.attrs.get("class", []):
        return [pyosis.generated.LCt(content=extract_children(tag))]

    if tag.name == "span" and "translit" in tag.attrs.get("class", []):
        return [
            pyosis.generated.ForeignCt(
                lang=str(tag.attrs.get("lang", "")), content=extract_children(tag)
            )
        ]
    if tag.name == "span" and "clarity-word" in tag.attrs.get("class", []):
        return [pyosis.generated.TransChangeCt(type_value="added", content=extract_children(tag))]

    if tag.name == "span":
        # Unknown span class — pass through contents with a warning
        warnings.warn(
            f"Unknown span class(es) {tag.attrs.get('class')} parsed, contents passed through. "
            "Please report this to the open-canon-site project.\n"
            f"Element in question:\n{str(tag)[:120]}..."
        )
        return extract_children(tag)

    if tag.name == "a" and (
        "study-note-ref" in tag.attrs["class"] or "note-ref" in tag.attrs["class"]
    ):
        return extract_footnote(tag, footnotes_dict)

    if tag.name in ("ol", "ul"):
        return [pyosis.generated.ListCt(content=extract_children(tag))]

    if tag.name == "li":
        return [pyosis.generated.ItemCt(content=extract_children(tag))]

    if tag.name == "img":
        # TODO: Get artist name from the image metadata
        return [
            pyosis.generated.FigureCt(
                alt=str(tag.attrs["data-public-description"]),
                src=str(tag.attrs["src"]),
                caption=[pyosis.generated.CaptionCt(content=[str(tag.attrs["alt"])])],
            )
        ]
    if tag.name == "figure":
        if "image" in tag.attrs["class"]:
            # HTML figures aren't exactly the same as OSIS figures, but as a temporary workaround, we can put the
            # HTML figure as an OSIS div and the contained images as OSIS figures
            return [
                pyosis.generated.DivCt(
                    type_value="x-figure",
                    content=extract_children(tag),
                )
            ]
        if "table" in tag.attrs["class"]:
            # TODO: parse caption tags?
            header_tag = tag.find("header")
            if header_tag:
                head_osis = pyosis.generated.HeadCt(
                    content=extract_markup(
                        header_tag, footnotes_dict=footnotes_dict, no_container=True
                    ),
                )
            else:
                head_osis = None

            table_tag = tag.find("table")
            if table_tag is None:
                raise ValueError(f"Could not find table in tag {tag}")

            rows = [
                row
                for row in extract_markup(
                    table_tag, footnotes_dict=footnotes_dict, no_container=True
                )
                if isinstance(row, pyosis.generated.RowCt)
            ]
            return [
                pyosis.generated.TableCt(
                    head=head_osis,
                    row=rows,
                )
            ]

    if tag.name == "table":
        raise NotImplementedError("Table tag should be inside a figure tag")

    if tag.name == "thead":
        return extract_children(tag)

    if tag.name == "tbody":
        # TODO: support alignment and other attrs
        return extract_children(tag)

    if tag.name == "tfoot":
        raise NotImplementedError("Tfoot tag not yet implemented")

    if tag.name == "th":
        return [
            pyosis.generated.CellCt(
                role=pyosis.generated.TableRole.LABEL,
                content=extract_children(tag),
            )
        ]

    if tag.name == "header":
        return extract_children(tag)

    if tag.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        return [pyosis.generated.HeadCt(content=extract_children(tag))]

    if tag.name == "tr":
        # TODO: Figure out role
        cells = [
            cell
            for cell in extract_children(tag, no_strings=True)
            if isinstance(cell, pyosis.generated.CellCt)
        ]
        return [pyosis.generated.RowCt(cell=cells)]

    if tag.name == "td":
        # TODO: Figure out role, colspan, rowspan, alignment, etc.
        return [
            pyosis.generated.CellCt(
                content=extract_children(tag),
            )
        ]
    if tag.name == "figcaption":
        # HTML figcaptions do not have a direct OSIS equivalent.
        # As a workaround, wrap the figcaption content in an OSIS div with a custom type.
        return [
            pyosis.generated.DivCt(
                type_value="x-figcaption",
                content=extract_children(tag),
            )
        ]

    if tag.name == "div":
        if "credit" in tag.attrs["class"]:
            return [
                pyosis.generated.DivCt(
                    type_value=pyosis.generated.OsisDivs.ACKNOWLEDGEMENT,
                    content=extract_children(tag),
                )
            ]
        if "publish-info" in tag.attrs["class"]:
            return [
                pyosis.generated.DivCt(
                    type_value="x-publish-info",
                    content=extract_children(tag),
                )
            ]
        if "copyright-info" in tag.attrs["class"]:
            return [
                pyosis.generated.DivCt(
                    type_value="x-copyright-info",
                    content=extract_children(tag),
                )
            ]
        if "card-label" in tag.attrs["class"]:
            # Mobile duplicate of the column header — skip
            return []
        warnings.warn(
            f"Unknown Div tag {tag} parsed, but probably incorrectly. "
            "Please report this to the open-canon-site project."
        )
        return [
            pyosis.generated.DivCt(
                type_value="x-unknown",
                content=extract_children(tag),
            )
        ]

    if tag.name == "br":
        return [pyosis.generated.LbCt()]

    if tag.name == "section":
        return [
            pyosis.generated.DivCt(
                type_value="x-section",
                content=extract_children(tag),
            )
        ]

    if tag.name == "blockquote":
        return [
            pyosis.generated.DivCt(
                type_value="x-blockquote",
                content=extract_children(tag),
            )
        ]

    raise ValueError(f"Not sure how to parse markup {tag}")


def build_chapter(
    scripture_content: church_website_models.ScriptureStudyContent,
    book_osis_id: str,
    chapter_number: int,
    book_short_name: str | None = None,
) -> tuple[pyosis.generated.ChapterCt, list[object] | None]:
    """Builds an OSIS (Open Scripture Information Standard) chapter object and its associated front matter from parsed
    HTML scripture content.

    The function parses the HTML content for the chapter, extracts and cleans up titles, subtitles, introductions, and
    verses, and constructs the corresponding OSIS objects. It also handles study introductions and summaries if present.

    Args:
        scripture_content: The scripture content object containing HTML body and footnotes.
        book_osis_id: The OSIS identifier for the book (e.g., "Gen" for Genesis).
        chapter_number: The chapter number to process.
        book_short_name: The conventional/short name of the book (e.g., "1 Nephi", "Genesis") used as the ``short``
            attribute on the main title element. When provided, the book's main title is emitted as a
            ``<title type="main" short="…">`` element instead of a plain heading.

    Returns:
        tuple:
            - pyosis.generated.ChapterCt: The constructed OSIS chapter object containing verses and optional summary.
            - list[objectl] | None: A list of front matter elements (such as titles, subtitles, and introductions) or
            None if no front matter is present.
    """
    chapter_osis_id = f"{book_osis_id}.{chapter_number}"

    chapter_html: bs4.BeautifulSoup = bs4.BeautifulSoup(
        scripture_content.content.body, "html.parser"
    )
    chapter_html = clean_up_html(chapter_html)

    front_matter: list[object] = []
    titles_tag = chapter_html.find("p", id="title1") or chapter_html.find("h1", id="title1")
    if titles_tag:
        title = chapter_html.find("span", class_="dominant")
        if title:
            front_matter.append(
                pyosis.generated.TitleCt(
                    canonical=True,
                    type_value=pyosis.generated.OsisTitles.MAIN,
                    short=book_short_name,
                    content=extract_markup(title, scripture_content.content.footnotes),
                )
            )
            title.extract()  # We have to remove the title tag from the soup so it doesn't get duplicated in the header
        other_titles = extract_markup(
            titles_tag, scripture_content.content.footnotes, no_container=True
        )
        for other_title in other_titles:
            if isinstance(other_title, str):
                if stripped := other_title.strip():
                    front_matter.append(
                        pyosis.generated.TitleCt(
                            canonical=True,
                            type_value=pyosis.generated.OsisTitles.SUB,
                            content=[stripped],
                        )
                    )
            elif isinstance(other_title, pyosis.generated.LbCt):
                # We don't need to worry about line breaks in the title, because we're adding them as
                # front matter/metadata not divs.
                continue
            else:
                front_matter.append(pyosis.generated.PCt(canonical=True, content=[other_title]))

    subtitle = chapter_html.find("p", class_="subtitle")
    if subtitle:
        front_matter.append(
            pyosis.generated.TitleCt(
                canonical=True,
                type_value=pyosis.generated.OsisTitles.SUB,
                content=extract_markup(subtitle, scripture_content.content.footnotes),
            )
        )
    intro = chapter_html.find("p", class_="intro")
    if intro:
        front_matter.append(
            pyosis.generated.DivCt(
                canonical=True,
                type_value=pyosis.generated.OsisDivs.INTRODUCTION,
                content=extract_markup(intro, scripture_content.content.footnotes),
            )
        )
    study_intro = chapter_html.find("p", class_="study-intro")
    if study_intro:
        front_matter.append(
            pyosis.generated.DivCt(
                canonical=False,
                type_value=pyosis.generated.OsisDivs.INTRODUCTION,
                content=extract_markup(study_intro, scripture_content.content.footnotes),
            )
        )

    body = chapter_html.find("div", class_="body-block")
    assert isinstance(body, bs4.element.Tag)
    osis_verses: list[object] = []
    for verse_p in body.find_all("p", class_="verse"):
        assert isinstance(verse_p, bs4.element.Tag)
        verse_number_span = verse_p.find("span", class_="verse-number")
        if verse_number_span is None:
            raise ValueError(f"Cannot find verse number in verse tag {verse_p}")
        verse_number = verse_number_span.text.strip()
        verse_osis_id = f"{chapter_osis_id}.{verse_number}"
        verse_number_span.extract()

        verse_contents: list[object] = extract_markup(
            verse_p, scripture_content.content.footnotes, no_container=True
        )
        verse_classes = verse_p.get_attribute_list("class")

        if "contains-line" in verse_classes:
            verse_contents = [
                pyosis.generated.LgCt(
                    l=[c for c in verse_contents if isinstance(c, pyosis.generated.LCt)]
                )
            ]

        osis_verse = pyosis.generated.VerseCt(
            s_id=verse_osis_id, e_id=verse_osis_id, osis_id=[verse_osis_id], content=verse_contents
        )

        osis_verses.append(osis_verse)

    chapter_contents: list[object] = []
    study_summary_p = chapter_html.find("p", class_="study-summary")
    if study_summary_p:
        chapter_contents.append(
            pyosis.generated.DivCt(
                canonical=False,
                type_value=pyosis.generated.OsisDivs.SUMMARY,
                content=extract_markup(study_summary_p, scripture_content.content.footnotes),
            )
        )
    chapter_contents.extend(osis_verses)

    return (
        pyosis.generated.ChapterCt(
            canonical=False, osis_id=[chapter_osis_id], content=chapter_contents
        ),
        front_matter or None,
    )


async def build_book(
    lang: str, parent_book: str, book: str, client: httpx.AsyncClient
) -> pyosis.generated.DivCt:
    """Asynchronously builds an OSIS book division from scripture content.

    Fetches the list of chapter numbers for the specified book and language, retrieves the content for each chapter
    concurrently, and constructs OSIS chapter elements. Handles front matter if present in chapters and assembles the
    complete OSIS book division.

    Args:
        lang: The language code for the scripture content.
        parent_book: The parent book identifier (e.g., for grouped books).
        book: The book identifier to build.
        client: An asynchronous HTTP client for making requests.

    Returns:
        pyosis.generated.DivCt: An OSIS division element representing the complete book, including all chapters and
        any front matter.


    """
    chapter_nums = await church_website_models.get_chapters_list(
        lang=lang, parent_book=parent_book, book=book, client=client
    )
    chapter_contents = await asyncio.gather(
        *[
            church_website_models.get_scripture_content(
                lang, parent_book, book, chapter_num, client
            )
            for chapter_num in chapter_nums
        ]
    )

    osis_chapters: list[object] = []
    for chapter_num, chapter_content in zip(chapter_nums, chapter_contents):
        osis_chapter, front_matter = build_chapter(
            chapter_content, book_osis_id=book, chapter_number=chapter_num, book_short_name=book
        )
        if front_matter:
            osis_chapters.extend(front_matter)
        osis_chapters.append(osis_chapter)

    return pyosis.generated.DivCt(
        canonical=True,
        type_value=pyosis.generated.OsisDivs.BOOK,
        osis_id=[book],
        content=osis_chapters,
    )
