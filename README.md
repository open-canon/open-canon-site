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
  --clean             Remove the output directory before generating
  -h / --help         Show this message and exit
```

### Multiple documents

Pass several files to build a combined library:

```bash
uv run open-canon-site kjv.osis.xml bom.osis.xml -o output --clean
```

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
