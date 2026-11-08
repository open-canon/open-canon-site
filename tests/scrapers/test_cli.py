"""Tests for ``open_canon_site.scrapers.cli`` (parsers, helpers and ``main``)."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pytest
from open_canon_site.scrapers import cli, registry
from open_canon_site.scrapers.base import ScraperSpec

CALLS = []


def _make_spec(name: str) -> ScraperSpec:
    """Build a fake scraper that writes ``<name>.xml`` and records its namespace in ``CALLS``."""

    def add_arguments(parser):
        """Add a ``--flavor`` option."""
        parser.add_argument("--flavor", default="plain")

    def run(args):
        """Write a tiny XML file embedding the flavor and return its path."""
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
    """Replace the registry with two fake scrapers and reset the recorded calls."""
    CALLS.clear()
    monkeypatch.setattr(registry, "SCRAPERS", (_make_spec("fake-one"), _make_spec("fake-two")))


def _common_namespace(**overrides):
    """Return a namespace shaped like parsed common options, with ``overrides`` applied."""
    values = {
        "output_dir": "out",
        "cache_dir": ".cache/html",
        "no_cache": False,
        "delay": 1.5,
        "log_level": "INFO",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


# --- _common_parser -------------------------------------------------------------------


def test_common_parser_defaults():
    """With no arguments the common parser yields the documented defaults."""
    args = cli._common_parser().parse_args([])
    assert args.output_dir == Path("open-canon-osis-documents")
    assert args.cache_dir == Path(".cache/html")
    assert args.no_cache is False
    assert args.delay == 1.5
    assert args.log_level == "INFO"


def test_common_parser_parses_all_options():
    """Short and long forms convert to ``Path``/``float`` and set the flags."""
    args = cli._common_parser().parse_args([
        "-o",
        "o",
        "--cache-dir",
        "c",
        "--no-cache",
        "--delay",
        "0.25",
        "--log-level",
        "DEBUG",
    ])
    assert (args.output_dir, args.cache_dir) == (Path("o"), Path("c"))
    assert args.no_cache is True and args.delay == 0.25 and args.log_level == "DEBUG"


def test_common_parser_rejects_invalid_log_level(capsys):
    """A log level outside ``LOG_LEVELS`` is an argparse error."""
    with pytest.raises(SystemExit):
        cli._common_parser().parse_args(["--log-level", "LOUD"])
    assert "invalid choice" in capsys.readouterr().err


def test_common_parser_has_no_help_flag():
    """The parent parser disables ``-h`` so children can add their own without a clash."""
    with pytest.raises(SystemExit):
        cli._common_parser().parse_args(["-h"])  # unknown option, not help


# --- build_parser ---------------------------------------------------------------------


def test_build_parser_requires_a_command(capsys):
    """Calling the program with no subcommand is an argparse error."""
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args([])
    assert exc.value.code == 2


def test_build_parser_registers_list_all_and_each_scraper():
    """Every registered scraper name, plus ``list`` and ``all``, parses as a subcommand."""
    parser = cli.build_parser()
    assert parser.parse_args(["list"]).command == "list"
    assert parser.parse_args(["all"]).command == "all"
    assert parser.parse_args(["fake-two"]).command == "fake-two"


def test_build_parser_sets_spec_default_and_own_options():
    """Scraper subcommands carry their spec and own options; ``list`` has no common options."""
    parser = cli.build_parser()
    args = parser.parse_args(["fake-one", "--flavor", "x", "--delay", "2"])
    assert args.spec.name == "fake-one" and args.flavor == "x" and args.delay == 2.0
    assert not hasattr(parser.parse_args(["list"]), "output_dir")
    assert not hasattr(parser.parse_args(["all"]), "spec")


def test_build_parser_with_empty_registry_only_has_list_and_all(monkeypatch):
    """With no scrapers registered only ``list`` and ``all`` are valid commands."""
    monkeypatch.setattr(registry, "SCRAPERS", ())
    parser = cli.build_parser()
    assert parser.parse_args(["all"]).command == "all"
    with pytest.raises(SystemExit):
        parser.parse_args(["fake-one"])


# --- _format_listing ------------------------------------------------------------------


def test_format_listing_empty_says_no_scrapers():
    """An empty tuple renders the placeholder sentence."""
    assert cli._format_listing(()) == "No scrapers registered."


def test_format_listing_aligns_columns_and_joins_outputs():
    """Name and source columns are padded to the widest cell and outputs are comma-joined."""
    short = ScraperSpec("a", "h", "src", ("x.xml", "y.xml"), run=lambda args: [])
    long = ScraperSpec("longer-name", "h", "a-much-longer-source", ("z.xml",), run=lambda a: [])
    lines = cli._format_listing((short, long)).splitlines()
    assert lines[0].split() == ["NAME", "SOURCE", "OUTPUTS"]
    assert lines[1] == "a            src                   x.xml, y.xml"
    assert lines[2] == "longer-name  a-much-longer-source  z.xml"
    assert lines[0].index("SOURCE") == lines[2].index("a-much-longer-source")


def test_format_listing_strips_trailing_whitespace_for_empty_outputs():
    """A spec with no outputs leaves no trailing spaces on its row."""
    spec = ScraperSpec("a", "h", "src", (), run=lambda args: [])
    assert not cli._format_listing((spec,)).splitlines()[1].endswith(" ")


# --- _normalise -----------------------------------------------------------------------


def test_normalise_converts_paths_and_creates_output_dir(tmp_path):
    """String paths become ``Path`` and the output directory is created with parents."""
    args = _common_namespace(output_dir=str(tmp_path / "a" / "b"), cache_dir="c")
    cli._normalise(args)
    assert args.output_dir == tmp_path / "a" / "b" and args.output_dir.is_dir()
    assert args.cache_dir == Path("c")


def test_normalise_no_cache_sets_cache_dir_none(tmp_path):
    """``no_cache`` overrides any cache directory with ``None``."""
    args = _common_namespace(output_dir=str(tmp_path), no_cache=True)
    cli._normalise(args)
    assert args.cache_dir is None


def test_normalise_existing_output_dir_is_fine(tmp_path):
    """An already-existing output directory does not raise."""
    args = _common_namespace(output_dir=str(tmp_path))
    cli._normalise(args)
    cli._normalise(args)
    assert tmp_path.is_dir()


# --- _run_spec ------------------------------------------------------------------------


def test_run_spec_prints_each_path_and_returns_them(tmp_path, capsys):
    """Every path returned by the scraper is printed on its own line and returned."""
    paths = [tmp_path / "a.xml", tmp_path / "b.xml"]
    spec = ScraperSpec("n", "h", "s", (), run=lambda args: paths)
    assert cli._run_spec(spec, argparse.Namespace()) == paths
    assert capsys.readouterr().out.splitlines() == [str(p) for p in paths]


def test_run_spec_with_no_paths_prints_nothing(capsys):
    """A scraper that wrote nothing produces no output."""
    spec = ScraperSpec("n", "h", "s", (), run=lambda args: [])
    assert cli._run_spec(spec, argparse.Namespace()) == []
    assert capsys.readouterr().out == ""


def test_run_spec_propagates_scraper_exceptions():
    """Exceptions from ``spec.run`` are not swallowed by ``_run_spec``."""

    def boom(args):
        """Always fail."""
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        cli._run_spec(ScraperSpec("n", "h", "s", (), run=boom), argparse.Namespace())


# --- _default_args_for ----------------------------------------------------------------


def test_default_args_for_merges_defaults_common_options_and_spec():
    """The result has the scraper's own defaults, the common options and ``spec``."""
    spec = registry.SCRAPERS[0]
    common = _common_namespace(delay=0.0)
    args = cli._default_args_for(spec, common)
    assert args.flavor == "plain" and args.delay == 0.0 and args.spec is spec
    assert args.output_dir == "out"
    assert not hasattr(common, "flavor") and not hasattr(common, "spec")


def test_default_args_for_common_values_override_scraper_defaults():
    """A common option with the same name as a scraper option wins."""

    def add(parser):
        """Define a clashing ``--delay`` option."""
        parser.add_argument("--delay", default="scraper")

    spec = ScraperSpec("n", "h", "s", (), run=lambda a: [], add_arguments=add)
    assert cli._default_args_for(spec, _common_namespace(delay=9)).delay == 9


def test_default_args_for_spec_without_options():
    """A spec using the default ``add_arguments`` still produces a valid namespace."""
    spec = ScraperSpec("n", "h", "s", (), run=lambda a: [])
    args = cli._default_args_for(spec, _common_namespace())
    assert args.spec is spec and args.log_level == "INFO"


# --- main -----------------------------------------------------------------------------


def test_main_list_prints_table_and_skips_logging(monkeypatch, capsys):
    """``list`` prints names, sources and outputs, returns 0 and never configures logging."""
    monkeypatch.setattr(logging, "basicConfig", lambda **kw: pytest.fail("configured logging"))
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "fake-one" in out and "https://example.test/fake-two" in out
    assert "fake-two.xml" in out


def test_main_list_with_empty_registry(monkeypatch, capsys):
    """``list`` with no scrapers prints the placeholder and returns 0."""
    monkeypatch.setattr(registry, "SCRAPERS", ())
    assert cli.main(["list"]) == 0
    assert "No scrapers" in capsys.readouterr().out


def test_main_help_mentions_scrapers(capsys):
    """Top-level ``--help`` lists the built-in and registered subcommands."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for word in ("list", "all", "fake-one", "fake-two"):
        assert word in out


def test_main_scraper_help_shows_common_and_own_options(capsys):
    """A scraper's ``--help`` shows both the common options and its own."""
    with pytest.raises(SystemExit):
        cli.main(["fake-one", "--help"])
    out = capsys.readouterr().out
    for flag in ("--output-dir", "--cache-dir", "--no-cache", "--delay", "--log-level", "--flavor"):
        assert flag in out


def test_main_run_writes_to_output_dir(tmp_path, capsys):
    """Running a scraper creates the output dir, prints the path and passes defaults."""
    out_dir = tmp_path / "nested" / "out"
    assert cli.main(["fake-one", "-o", str(out_dir), "--flavor", "spicy"]) == 0
    written = out_dir / "fake-one.xml"
    assert written.read_text(encoding="utf-8") == "<osis flavor='spicy'/>"
    assert str(written) in capsys.readouterr().out
    args = CALLS[0]
    assert args.output_dir == out_dir
    assert args.cache_dir == Path(".cache/html")
    assert args.delay == 1.5


def test_main_no_cache_sets_cache_dir_none(tmp_path):
    """``--no-cache`` reaches the scraper as ``cache_dir is None``."""
    assert cli.main(["fake-one", "-o", str(tmp_path), "--no-cache"]) == 0
    assert CALLS[0].cache_dir is None


def test_main_custom_cache_dir_and_delay(tmp_path):
    """``--cache-dir`` and ``--delay`` are forwarded as ``Path`` and ``float``."""
    cache = tmp_path / "c"
    argv = ["fake-one", "-o", str(tmp_path), "--cache-dir", str(cache), "--delay", "0"]
    assert cli.main(argv) == 0
    assert CALLS[0].cache_dir == cache
    assert CALLS[0].delay == 0.0


def test_main_unknown_scraper_errors(capsys):
    """An unknown subcommand exits through argparse with ``invalid choice``."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["nope"])
    assert exc.value.code != 0
    assert "invalid choice" in capsys.readouterr().err


def test_main_all_runs_every_spec_with_defaults_in_order(tmp_path):
    """``all`` runs each registered scraper in registry order with its own defaults."""
    assert cli.main(["all", "-o", str(tmp_path), "--no-cache"]) == 0
    assert (tmp_path / "fake-one.xml").exists()
    assert (tmp_path / "fake-two.xml").exists()
    assert [c.spec.name for c in CALLS] == ["fake-one", "fake-two"]
    assert all(c.cache_dir is None and c.flavor == "plain" for c in CALLS)


def test_main_all_with_empty_registry_succeeds(tmp_path, monkeypatch):
    """``all`` with nothing registered does nothing and returns 0."""
    monkeypatch.setattr(registry, "SCRAPERS", ())
    assert cli.main(["all", "-o", str(tmp_path)]) == 0


def test_main_failure_returns_nonzero_and_reports_on_stderr(tmp_path, monkeypatch, capsys):
    """A scraper exception becomes ``error: <message>`` on stderr and exit code 1."""

    def boom(args):
        """Always fail."""
        raise RuntimeError("kaboom")

    spec = ScraperSpec(name="bad", help="h", source="s", outputs=("x",), run=boom)
    monkeypatch.setattr(registry, "SCRAPERS", (spec,))
    assert cli.main(["bad", "-o", str(tmp_path)]) == 1
    assert "error: kaboom" in capsys.readouterr().err


def test_main_all_stops_at_first_failure(tmp_path, monkeypatch, capsys):
    """When one scraper in ``all`` fails, later scrapers do not run and the exit code is 1."""

    def boom(args):
        """Always fail."""
        raise ValueError("bad")

    bad = ScraperSpec(name="bad", help="h", source="s", outputs=(), run=boom)
    monkeypatch.setattr(registry, "SCRAPERS", (bad, _make_spec("after")))
    assert cli.main(["all", "-o", str(tmp_path)]) == 1
    assert CALLS == []


def test_main_configures_logging_with_requested_level(tmp_path, monkeypatch):
    """``--log-level`` is translated to the numeric level passed to ``basicConfig``."""
    seen = {}
    monkeypatch.setattr(logging, "basicConfig", lambda **kw: seen.update(kw))
    assert cli.main(["fake-one", "-o", str(tmp_path), "--log-level", "ERROR"]) == 0
    assert seen["level"] == logging.ERROR
    assert "%(message)s" in seen["format"]
