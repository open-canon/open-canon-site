from __future__ import annotations

from pathlib import Path

import pytest

from open_canon_site.scrapers import cli, registry
from open_canon_site.scrapers.base import ScraperSpec

CALLS = []


def _make_spec(name: str) -> ScraperSpec:
    def add_arguments(parser):
        parser.add_argument("--flavor", default="plain")

    def run(args):
        CALLS.append(args)
        out = args.output_dir / f"{name}.xml"
        out.write_text(f"<osis flavor='{args.flavor}'/>", encoding="utf-8")
        return [out]

    return ScraperSpec(
        name=name,
        help=f"fake scraper {name}",
        source="https://example.test/" + name,
        outputs=(f"{name}.xml",),
        run=run,
        add_arguments=add_arguments,
    )


@pytest.fixture(autouse=True)
def fake_registry(monkeypatch):
    CALLS.clear()
    monkeypatch.setattr(registry, "SCRAPERS", (_make_spec("fake-one"), _make_spec("fake-two")))


def test_list(capsys):
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "fake-one" in out and "https://example.test/fake-two" in out
    assert "fake-two.xml" in out


def test_help_mentions_scrapers(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for word in ("list", "all", "fake-one", "fake-two"):
        assert word in out


def test_scraper_help_shows_common_and_own_options(capsys):
    with pytest.raises(SystemExit):
        cli.main(["fake-one", "--help"])
    out = capsys.readouterr().out
    for flag in ("--output-dir", "--cache-dir", "--no-cache", "--delay", "--log-level", "--flavor"):
        assert flag in out


def test_run_writes_to_output_dir(tmp_path, capsys):
    out_dir = tmp_path / "nested" / "out"
    assert cli.main(["fake-one", "-o", str(out_dir), "--flavor", "spicy"]) == 0
    written = out_dir / "fake-one.xml"
    assert written.read_text(encoding="utf-8") == "<osis flavor='spicy'/>"
    assert str(written) in capsys.readouterr().out
    args = CALLS[0]
    assert args.output_dir == out_dir
    assert args.cache_dir == Path(".cache/html")
    assert args.delay == 1.5


def test_no_cache_sets_cache_dir_none(tmp_path):
    assert cli.main(["fake-one", "-o", str(tmp_path), "--no-cache"]) == 0
    assert CALLS[0].cache_dir is None


def test_custom_cache_dir_and_delay(tmp_path):
    cache = tmp_path / "c"
    assert (
        cli.main(["fake-one", "-o", str(tmp_path), "--cache-dir", str(cache), "--delay", "0"]) == 0
    )
    assert CALLS[0].cache_dir == cache
    assert CALLS[0].delay == 0.0


def test_unknown_scraper_errors(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["nope"])
    assert exc.value.code != 0
    assert "invalid choice" in capsys.readouterr().err


def test_all_runs_every_spec(tmp_path):
    assert cli.main(["all", "-o", str(tmp_path), "--no-cache"]) == 0
    assert (tmp_path / "fake-one.xml").exists()
    assert (tmp_path / "fake-two.xml").exists()
    assert len(CALLS) == 2
    assert all(c.cache_dir is None and c.flavor == "plain" for c in CALLS)


def test_failure_returns_nonzero(tmp_path, monkeypatch, capsys):
    def boom(args):
        raise RuntimeError("kaboom")

    spec = ScraperSpec(name="bad", help="h", source="s", outputs=("x",), run=boom)
    monkeypatch.setattr(registry, "SCRAPERS", (spec,))
    assert cli.main(["bad", "-o", str(tmp_path)]) == 1
    assert "kaboom" in capsys.readouterr().err


def test_get_scraper():
    assert registry.get_scraper("fake-two").name == "fake-two"
    with pytest.raises(KeyError, match="Unknown scraper"):
        registry.get_scraper("missing")


def test_empty_registry_list(monkeypatch, capsys):
    monkeypatch.setattr(registry, "SCRAPERS", ())
    assert cli.main(["list"]) == 0
    assert "No scrapers" in capsys.readouterr().out
