# open-canon-site

Website for viewing various Ancient Religious Texts

A static site generator that reads [OSIS XML](http://www.bibletechnologies.net/) scriptural documents and produces a clean, three-panel reading interface inspired by the study tools of [churchofjesuschrist.org](https://www.churchofjesuschrist.org).

## Features

- **Left navigation sidebar** – lists all loaded documents; for the current document shows its top-level divisions (books, sections, etc.); for the current division shows all chapters
- **Arabic chapter numbering** – normalizes chapter headings like `CHAPTER XVIII.` to `Chapter 18` in the sidebar and page titles while preserving the underlying OSIS chapter IDs
- **In-page section links** – exposes section headings from introductions and other prose pages in the sidebar and links directly to the right anchor on the current page
- **Center reading pane** – renders the full chapter text with verse numbers, inline formatting, and footnote/cross-reference markers
- **Structured poetry support** – handles OSIS line groups such as `<lg>` and `<l>` used in texts like 1 Enoch
- **Front matter support** – renders non-chapter material such as introductions, prefaces, and prose-only sections into navigable pages
- **Right notes tray** – displays all embedded notes for the chapter, automatically scrolling to stay aligned with whatever verse is currently visible in the center
- **UV-managed dependencies** – project uses [UV](https://docs.astral.sh/uv/) for fast, reproducible package management

## Quick start

```bash
# 1. Install UV (if you don't have it)
pip install uv

# 2. Install the project and its dependencies
uv sync

# 3. Generate a site from the bundled sample OSIS file
uv run open-canon-site sample_data/sample.osis.xml -o output

# 4. Browse the site (Python's built-in server)
python -m http.server --directory output 8080
# → open http://localhost:8080
```

## Usage

```text
open-canon-site [OPTIONS] OSIS_FILE [OSIS_FILE ...]

Positional arguments:
  OSIS_FILE   One or more OSIS XML files to render.

Options:
  -o / --output DIR   Output directory (default: ./output)
  --collections JSON_FILE
                      JSON file defining library collections and their work IDs
  --clean             Remove the output directory before generating
  -h / --help         Show this message and exit
```

### Multiple documents

Pass several files to build a combined library:

```bash
uv run open-canon-site kjv.osis.xml bom.osis.xml -o output --clean
```

If you provide a custom collections file with `--collections`, the collections
themselves follow the JSON array order, and the books within each collection
follow the `work_ids` list order.

## Scrapers

The repository also ships scrapers that fetch public-domain texts and write the OSIS XML
documents the site build reads. They are optional; the core site install does not need them.

```bash
uv sync --extra scrapers            # or: pip install open-canon-site[scrapers]

uv run open-canon-scrape list                       # show available scrapers
uv run open-canon-scrape <scraper> --help           # scraper-specific options
uv run open-canon-scrape <scraper> -o open-canon-osis-documents
uv run open-canon-scrape all --no-cache             # run every scraper with defaults
```

Common options (accepted by every scraper and by `all`):

| option | default | meaning |
|---|---|---|
| `-o`, `--output-dir DIR` | `open-canon-osis-documents` | where OSIS XML files are written |
| `--cache-dir DIR` | `.cache/html` | cache of downloaded pages |
| `--no-cache` | off | disable the cache |
| `--delay SECONDS` | `1.5` | politeness delay between requests |
| `--log-level LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |

| subcommand | source | outputs |
|---|---|---|
| `kjv-apocrypha` | [ebible.org](https://ebible.org/Scriptures/eng-kjv_vpl.zip) KJV Apocrypha | `kjv_apocrypha.xml` (`--per-book` also writes one file per book) |
| `1-enoch` (`--start-page`, `--end-page`) | sacred-texts.com, Book of Enoch | `1-enoch.xml` |
| `forgotten-books-of-eden` (`--start-page`, `--end-page`) | sacred-texts.com, Forgotten Books of Eden | `adam-and-eve.xml`, `2-enoch.xml`, `psalms-of-solomon.xml`, `odes-of-solomon.xml`, `letter-of-aristeas.xml`, `4-maccabees.xml`, `story-of-ahikar.xml`, `testaments-twelve-patriarchs.xml` |
| `jasher` | sacred-texts.com, Book of Jasher | `jasher.xml` |
| `jubilees` | sacred-texts.com, Book of Jubilees | `jubilees.xml` |
| `pseudo-philo` | sacred-texts.com, Biblical Antiquities of Philo (M. R. James) | `pseudo-philo.xml` |
| `vita-adae-et-evae` | sacred-texts.com, Vita Adae et Evae | `vita-adae-et-evae.xml` |
| `lds-standard-works` | [churchofjesuschrist.org](https://www.churchofjesuschrist.org/study/scriptures) | `book_of_mormon.xml`, `doctrine_and_covenants.xml`, `new_testament.xml`, `old_testament.xml`, `pearl_of_great_price.xml` (options: `--works book-of-mormon,new-testament,...` default all, `--lang eng`) |

Tests that hit the network are skipped unless `OPEN_CANON_NETWORK_TESTS=1` is set.

## Project layout

```text
open-canon-site/
├── pyproject.toml                  # UV/PEP-517 project metadata & dependencies
├── sample_data/
│   └── sample.osis.xml             # Demo OSIS excerpt (Genesis 1–3, KJV)
├── src/
│   └── open_canon_site/
│       ├── __main__.py             # CLI entry point
│       ├── generator.py            # Orchestrates parsing → HTML writing
│       ├── parser.py               # Extracts document structure from OSIS
│       ├── renderer.py             # Converts pyosis content nodes to HTML
│       ├── static/
│       │   ├── style.css           # Three-column layout & typography
│       │   └── notes-sync.js       # Scroll-sync between text and notes tray
│       └── templates/
│           ├── base.html           # Shared HTML shell
│           ├── index.html          # Library landing page
│           ├── doc_index.html      # Per-document redirect page
│           └── chapter.html        # Chapter reading page
└── tests/
    ├── test_generator.py           # Integration tests (full pipeline)
    ├── test_parser.py              # Unit tests for OSIS parsing
    └── test_renderer.py            # Unit tests for content rendering
```

## Running tests

```bash
uv sync --extra dev
uv run --extra dev pytest
```

## GitHub Pages deployment

Production and PR preview deployments both publish to the `gh-pages` branch.
Keep the repository Pages source set to `Deploy from a branch` with `gh-pages`
selected; the preview workflow relies on branch-based deployments.

The preview jobs intentionally avoid conditions based on
`github.event.pull_request.head.repo`. GitHub can omit that object when a
`pull_request` workflow is manually re-run, which would incorrectly skip
same-repository preview deployments.

The preview deployment job also uses an explicit `always()` guard with a
`needs.build.result == 'success'` check. Without that override, GitHub applies
the default `success()` condition to downstream jobs, and the PR preview job is
silently skipped because the release job is expected to be skipped on
`pull_request` events.

## Dependencies

| Package                                        | Purpose                                    |
| ---------------------------------------------- | ------------------------------------------ |
| [pyosis](https://pypi.org/project/pyosis/)     | Parses OSIS XML into typed Python models   |
| [Jinja2](https://jinja.palletsprojects.com/)   | HTML template rendering                    |

## Contributing

Commit messages must follow the **[Conventional Commits](https://www.conventionalcommits.org/)** format (Angular preset) — this drives automatic versioning via [python-semantic-release](https://python-semantic-release.readthedocs.io/).

```text
feat(parser): support Hebrew right-to-left text direction
fix(renderer): correct verse numbering for chapters > 99
docs: clarify OSIS file requirements in README
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.
