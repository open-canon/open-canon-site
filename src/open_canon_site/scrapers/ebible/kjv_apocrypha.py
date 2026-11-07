import datetime
import io
import pathlib
import xml.etree.ElementTree as ET
import zipfile

import httpx
import pyosis

DOWNLOAD_URL = "https://ebible.org/Scriptures/eng-kjv_vpl.zip"
XML_FILENAME = "eng-kjv_vpl.xml"

OUTPUT_DIR = pathlib.Path("osis-documents")

# Mapping: VPL book code -> (display name, OSIS ID), in canonical KJV order
APOCRYPHA_BOOKS: dict[str, tuple[str, str]] = {
    "1ES": ("1 Esdras", "1Esd"),
    "2ES": ("2 Esdras", "2Esd"),
    "TOB": ("Tobit", "Tob"),
    "JDT": ("Judith", "Jdt"),
    "ESG": ("Additions to Esther", "AddEsth"),
    "WIS": ("Wisdom of Solomon", "Wis"),
    "SIR": ("Ecclesiasticus (Wisdom of Sirach)", "Sir"),
    "BAR": ("Baruch", "Bar"),
    "S3Y": ("Prayer of Azariah", "PrAzar"),
    "SUS": ("Susanna", "Sus"),
    "BEL": ("Bel and the Dragon", "Bel"),
    "MAN": ("Prayer of Manasseh", "PrMan"),
    "1MA": ("1 Maccabees", "1Macc"),
    "2MA": ("2 Maccabees", "2Macc"),
}


def download_xml() -> bytes:
    print(f"Downloading {DOWNLOAD_URL} ...")
    response = httpx.get(DOWNLOAD_URL, follow_redirects=True)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        return zf.read(XML_FILENAME)


def parse_books(xml_bytes: bytes) -> dict[str, pyosis.DivCt]:
    root = ET.fromstring(xml_bytes)

    # Collect verses grouped by book code -> chapter number -> list of (verse num, text)
    raw: dict[str, dict[int, list[tuple[int, str]]]] = {}
    for elem in root.iter("v"):
        book_code = elem.get("b")
        if book_code not in APOCRYPHA_BOOKS:
            continue
        chapter_num = int(elem.get("c"))
        verse_num = int(elem.get("v"))
        text = (elem.text or "").strip()
        raw.setdefault(book_code, {}).setdefault(chapter_num, []).append((verse_num, text))

    books: dict[str, pyosis.DivCt] = {}
    for book_code, (book_name, osis_id) in APOCRYPHA_BOOKS.items():
        if book_code not in raw:
            print(f"Warning: no verses found for {book_name} ({book_code})")
            continue

        chapters = []
        for chapter_num in sorted(raw[book_code]):
            verses = [
                pyosis.VerseCt(
                    osis_id=[f"{osis_id}.{chapter_num}.{verse_num}"],
                    content=[text],
                )
                for verse_num, text in sorted(raw[book_code][chapter_num])
            ]
            chapters.append(
                pyosis.ChapterCt(
                    osis_id=[f"{osis_id}.{chapter_num}"],
                    content=verses,
                )
            )

        books[book_code] = pyosis.DivCt(
            osis_id=[osis_id],
            type_value=pyosis.OsisDivs.BOOK,
            content=[
                pyosis.HeadCt(content=[book_name]),
                *chapters,
            ],
        )

    return books


def books_to_osis_xml(books: list[pyosis.DivCt]) -> pyosis.OsisXML:
    return pyosis.OsisXML(
        osis=pyosis.Osis(
            osis_text=pyosis.OsisTextCt(
                header=pyosis.HeaderCt(
                    work=[
                        pyosis.WorkCt(
                            osis_work="King James Version Apocrypha",
                            title=[pyosis.TitleCt(content=["King James Version--Apocrypha"])],
                            type_value=[
                                pyosis.TypeCt(type_value=pyosis.OsisType.OSIS, value="Bible")
                            ],
                        )
                    ],
                    revision_desc=[
                        pyosis.RevisionDescCt(
                            date=pyosis.DateCt(
                                event=pyosis.OsisEvents.EVERSION,
                                content=[datetime.datetime.now().strftime("%Y.%m.%dT%H:%M:%S")],
                                lang="en",
                            ),
                            p=[
                                pyosis.PCt(
                                    content=[
                                        "Downloaded from ebible.org (eng-kjv_vpl.zip),"
                                        " and converted to OSIS by the"
                                        " osis-kjv-apocrypha Python package."
                                    ]
                                )
                            ],
                        )
                    ],
                ),
                lang="en",
                div=books,
                osis_idwork="kjv-apocrypha",
            )
        )
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    xml_bytes = download_xml()
    books = parse_books(xml_bytes)

    all_book_divs = []
    for book_code, (book_name, _) in APOCRYPHA_BOOKS.items():
        if book_code not in books:
            continue
        book_div = books[book_code]
        all_book_divs.append(book_div)

        file_name = "_".join(book_name.split()) + ".xml"
        (OUTPUT_DIR / file_name).write_text(books_to_osis_xml([book_div]).to_xml())
        print(f"Saved {file_name}")

    (OUTPUT_DIR / "kjv_apocrypha.xml").write_text(books_to_osis_xml(all_book_divs).to_xml())
    print("Saved kjv_apocrypha.xml")


if __name__ == "__main__":
    main()
