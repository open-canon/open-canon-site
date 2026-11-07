from __future__ import annotations

import pytest

from open_canon_site.scrapers import cli, registry

SACRED_TEXTS = {
    "1-enoch": ("1-enoch.xml",),
    "jasher": ("jasher.xml",),
    "jubilees": ("jubilees.xml",),
    "vita-adae-et-evae": ("vita-adae-et-evae.xml",),
}


def test_sacred_texts_registered_in_order() -> None:
    expected = [
        "1-enoch",
        "forgotten-books-of-eden",
        "jasher",
        "jubilees",
        "vita-adae-et-evae",
    ]
    names = [spec.name for spec in registry.SCRAPERS if spec.name in expected]
    assert names == expected


@pytest.mark.parametrize(("name", "outputs"), SACRED_TEXTS.items())
def test_single_file_scraper_outputs(name: str, outputs: tuple[str, ...]) -> None:
    assert registry.get_scraper(name).outputs == outputs


def test_fbe_outputs() -> None:
    outputs = registry.get_scraper("forgotten-books-of-eden").outputs
    assert len(outputs) == 8
    assert "adam-and-eve.xml" in outputs


def test_page_range_options_parse() -> None:
    args = cli.build_parser().parse_args(["1-enoch", "--start-page", "4", "--end-page", "10"])
    assert (args.start_page, args.end_page) == (4, 10)
    args = cli.build_parser().parse_args(["forgotten-books-of-eden"])
    assert (args.start_page, args.end_page) == (0, 295)
