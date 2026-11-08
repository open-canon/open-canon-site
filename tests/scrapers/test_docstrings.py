"""AST-based docstring audit for the scrapers package.

Ruff's ``D``/``DOC`` rules (see ``src/open_canon_site/scrapers/ruff.toml``) skip private
names and know nothing about attribute docstrings, so this test walks the source of every
module under ``open_canon_site.scrapers`` and checks:

* every module, class, function and method (private, nested, dunder or property) has a
  docstring;
* every class-body attribute (plain, annotated, dataclass/pydantic field, enum member,
  constant) is immediately followed by a string-literal statement;
* the first ``self.x = ...`` assignment in ``__init__`` / ``__post_init__`` is immediately
  followed by a string-literal statement.

Modules are discovered by walking the package directory, so scrapers added by later layers
are covered automatically.
"""

from __future__ import annotations

import ast
import importlib.util
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

_INIT_METHODS = ("__init__", "__post_init__")
"""Method names whose first ``self.x`` assignments are treated as instance attributes."""


def _package_root() -> Path:
    """Locate the scrapers package directory without importing its submodules.

    Returns:
        Absolute path of the ``open_canon_site/scrapers`` directory.
    """
    spec = importlib.util.find_spec("open_canon_site.scrapers")
    assert spec is not None and spec.submodule_search_locations
    return Path(list(spec.submodule_search_locations)[0])


def discover_module_paths() -> list[Path]:
    """Find every Python source file in the scrapers package, including subpackages.

    Returns:
        Sorted paths of all ``*.py`` files under the package directory.
    """
    return sorted(_package_root().rglob("*.py"))


def _is_docstring(node: ast.stmt | None) -> bool:
    """Report whether a statement is a bare string literal (an attribute docstring).

    Args:
        node: The statement following an assignment, or ``None`` at the end of a body.

    Returns:
        True for an expression statement whose value is a ``str`` constant.
    """
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _target_names(node: ast.stmt) -> list[str]:
    """Name the class-body attributes bound by an assignment statement.

    Args:
        node: Any statement from a class body.

    Returns:
        The simple names assigned by ``Assign``/``AnnAssign`` (tuple targets are
        flattened); empty for every other kind of statement.
    """
    if isinstance(node, ast.AnnAssign):
        targets: Sequence[ast.expr] = [node.target]
    elif isinstance(node, ast.Assign):
        targets = node.targets
    else:
        return []
    names: list[str] = []
    stack = list(targets)
    while stack:
        target = stack.pop(0)
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            stack.extend(target.elts)
    return names


def _self_attribute_names(node: ast.stmt) -> list[str]:
    """Name the ``self.<attr>`` attributes bound by an assignment statement.

    Args:
        node: Any statement from a method body.

    Returns:
        Attribute names for ``self.x = ...`` / ``self.x: T = ...`` targets (tuple targets
        flattened); empty for other statements.
    """
    if isinstance(node, ast.AnnAssign):
        targets: list[ast.expr] = [node.target]
    elif isinstance(node, ast.Assign):
        targets = list(node.targets)
    else:
        return []
    names: list[str] = []
    while targets:
        target = targets.pop(0)
        if isinstance(target, (ast.Tuple, ast.List)):
            targets.extend(target.elts)
        elif (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        ):
            names.append(target.attr)
    return names


def _statement_lists(node: ast.AST) -> Iterator[list[ast.stmt]]:
    """Yield the statement lists nested directly inside a statement, in source order.

    Covers ``body``/``orelse``/``finalbody`` and ``except`` handlers, so assignments inside
    ``if``/``with``/``try`` blocks are seen. Nested function and class definitions are not
    descended into.

    Args:
        node: A compound statement.

    Yields:
        Each child statement list.
    """
    for field in ("body", "orelse", "finalbody"):
        block = getattr(node, field, None)
        if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
            yield block
    for handler in getattr(node, "handlers", []):
        yield handler.body


def _check_instance_attributes(
    body: list[ast.stmt], seen: set, filename: str, out: list[str]
) -> None:
    """Check that first ``self.x`` assignments in a method body carry attribute docstrings.

    Recurses into ``if``/``with``/``try`` blocks but not into nested functions or classes.

    Args:
        body: Statement list to scan.
        seen: Attribute names already assigned earlier (only the first assignment needs a
            docstring); updated in place.
        filename: Display name used in failure messages.
        out: List that violation messages are appended to.
    """
    for index, node in enumerate(body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for name in _self_attribute_names(node):
            if name in seen:
                continue
            seen.add(name)
            following = body[index + 1] if index + 1 < len(body) else None
            if not _is_docstring(following):
                out.append(f"{filename}:{node.lineno} self.{name} (missing attribute docstring)")
        for block in _statement_lists(node):
            _check_instance_attributes(block, seen, filename, out)


def find_violations(source: str, filename: str = "<string>") -> list[str]:
    """Audit Python source for missing docstrings.

    Args:
        source: Full text of a Python module.
        filename: Name shown in messages as the ``file`` part of ``file:line symbol``.

    Returns:
        One message per violation, formatted ``"<filename>:<line> <symbol> (<problem>)"``,
        in source order. Empty when the module is fully documented.
    """
    tree = ast.parse(source, filename=filename)
    out: list[str] = []
    if ast.get_docstring(tree) is None:
        out.append(f"{filename}:1 <module> (missing module docstring)")

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if ast.get_docstring(node) is None:
                out.append(f"{filename}:{node.lineno} {node.name} (missing function docstring)")
            if node.name in _INIT_METHODS:
                _check_instance_attributes(node.body, set(), filename, out)
        elif isinstance(node, ast.ClassDef):
            if ast.get_docstring(node) is None:
                out.append(f"{filename}:{node.lineno} {node.name} (missing class docstring)")
            for index, stmt in enumerate(node.body):
                following = node.body[index + 1] if index + 1 < len(node.body) else None
                for name in _target_names(stmt):
                    if not _is_docstring(following):
                        out.append(
                            f"{filename}:{stmt.lineno} {node.name}.{name} "
                            "(missing attribute docstring)"
                        )
    return sorted(out, key=lambda message: int(message.split(":")[1].split(" ")[0]))


def test_discover_module_paths_finds_core_modules():
    """Discovery returns the framework modules (and would return any added later)."""
    names = {path.name for path in discover_module_paths()}
    assert {"__init__.py", "base.py", "cli.py", "_http.py", "_osis.py", "registry.py"} <= names


@pytest.mark.parametrize("path", discover_module_paths(), ids=lambda p: p.name)
def test_scrapers_module_is_fully_documented(path):
    """Every module, class, function and attribute in ``path`` has a docstring."""
    violations = find_violations(path.read_text(encoding="utf-8"), str(path))
    assert not violations, "Missing docstrings:\n" + "\n".join(violations)


def test_find_violations_accepts_documented_source():
    """Fully documented module, class, method, attribute and nested function pass."""
    source = '''"""Mod."""
class A:
    """Doc."""

    x: int = 1
    """The x."""

    def __init__(self):
        """Init."""
        self.y = 2
        """The y."""

        def inner():
            """Nested."""
'''
    assert find_violations(source) == []


def test_find_violations_reports_missing_function_class_and_module():
    """Missing module, class, private, nested and dunder docstrings are all named."""
    source = """class A:
    def _private(self):
        def inner():
            pass
    def __repr__(self):
        pass
"""
    messages = find_violations(source, "m.py")
    assert messages == [
        "m.py:1 <module> (missing module docstring)",
        "m.py:1 A (missing class docstring)",
        "m.py:2 _private (missing function docstring)",
        "m.py:3 inner (missing function docstring)",
        "m.py:5 __repr__ (missing function docstring)",
    ]


def test_find_violations_reports_class_attribute_without_docstring():
    """Plain, annotated and bare-annotation class attributes need a following string."""
    source = '''"""Mod."""
class A:
    """Doc."""

    a = 1
    b: int = 2
    """Documented."""
    c: str
'''
    assert find_violations(source, "m.py") == [
        "m.py:5 A.a (missing attribute docstring)",
        "m.py:8 A.c (missing attribute docstring)",
    ]


def test_find_violations_reports_undocumented_init_attribute_once():
    """Only the first ``self.x`` assignment is checked, including inside an ``if``."""
    source = '''"""Mod."""
class A:
    """Doc."""

    def __post_init__(self):
        """Init."""
        self.a = 1
        self.a = 2
        if self.a:
            self.b = 3
'''
    assert find_violations(source, "m.py") == [
        "m.py:7 self.a (missing attribute docstring)",
        "m.py:10 self.b (missing attribute docstring)",
    ]


def test_find_violations_ignores_self_assignments_outside_init():
    """Assignments in ordinary methods are not instance-attribute declarations."""
    source = '''"""Mod."""
class A:
    """Doc."""

    def run(self):
        """Run."""
        self.z = 1
'''
    assert find_violations(source) == []
