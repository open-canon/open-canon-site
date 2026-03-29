# Contributing to Open Canon Site

Thank you for your interest in contributing!

## Commit message style

This project uses **[Conventional Commits](https://www.conventionalcommits.org/)** (Angular preset) to automate versioning with [python-semantic-release](https://python-semantic-release.readthedocs.io/).

Every commit message **must** follow this format:

```
<type>(<scope>): <short summary>

[optional body]

[optional footer(s)]
```

### Types

| Type       | When to use                                              | Version bump |
| ---------- | -------------------------------------------------------- | ------------ |
| `feat`     | A new feature visible to end users                       | minor        |
| `fix`      | A bug fix visible to end users                           | patch        |
| `docs`     | Documentation changes only                              | –            |
| `style`    | Formatting, whitespace – no logic change                 | –            |
| `refactor` | Code change that is neither a feature nor a bug fix      | –            |
| `perf`     | A code change that improves performance                  | patch        |
| `test`     | Adding or updating tests                                 | –            |
| `build`    | Changes to the build system or external dependencies     | –            |
| `ci`       | Changes to CI configuration files and scripts            | –            |
| `chore`    | Other changes that don't modify src or test files        | –            |
| `revert`   | Reverts a previous commit                                | –            |

### Breaking changes

Append `!` after the type/scope **or** add a `BREAKING CHANGE:` footer to trigger a major version bump:

```
feat!: redesign template rendering API

BREAKING CHANGE: The `generate_site` function signature has changed.
```

### Examples

```
feat(templates): add dark-mode toggle to site header
fix(parser): handle OSIS files with missing work ID
docs: update quick-start instructions in README
chore(release): v1.2.0 [skip ci]
```

## Development workflow

```bash
# Install all dependencies (including dev extras)
uv sync --all-extras

# Run the test suite
uv run pytest

# Lint the code
uv run ruff check .
uv run ruff format --check .
```
