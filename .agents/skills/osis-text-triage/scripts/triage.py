"""Render changed OSIS XML documents and surface text oddities for triage.

Renders each XML file (and its version at a base git ref) with the site generator,
flattens every rendered page to plain text, prints a per-page diff of the reading
text, and lists heuristic flags: things that *might* be scraping artifacts. A flag is
a prompt to look, not a verdict. See ../SKILL.md for how to triage them.

Usage (from the repository root):

    # every changed XML file vs the merge-base with main
    uv run python .agents/skills/osis-text-triage/scripts/triage.py
    # specific files, or another base
    uv run python .agents/skills/osis-text-triage/scripts/triage.py FILE.xml --base HEAD~1

Only the standard library is used beyond the project itself.
"""

from __future__ import annotations

import argparse
import difflib
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

DOCS_DIR = "open-canon-osis-documents"
OSIS_NS = "{http://www.bibletechnologies.net/2003/OSIS/namespace}"
BLOCK_TAGS = {
    "div",
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "br",
    "tr",
    "blockquote",
    "section",
}
CAPTURE_CLASSES = {"content-main", "notes-tray"}

# (label, regex) heuristics run on every line of rendered text. Each is a *hint*.
LINE_FLAGS: list[tuple[str, re.Pattern[str]]] = [
    ("leftover markup", re.compile(r"</?[a-zA-Z][a-zA-Z0-9]*(\s[^<>]*)?/?>")),
    ("escaped entity in text", re.compile(r"&(#\d+|#x[0-9a-fA-F]+|[a-zA-Z]{2,8});?")),
    ("replacement / mojibake", re.compile(r"�|â€|Ã[\x80-\xbf]|Â[\xa0-\xbf]")),
    ("control character", re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")),
    (
        "site chrome / navigation",
        re.compile(
            r"click to enlarge|\[paragraph continues\]|\(see page \d+\)|next:|previous:|"
            r"sacred-texts|javascript|cookie|copyright ©|all rights reserved|comments and social",
            re.IGNORECASE,
        ),
    ),
    ("verse number inside verse text", re.compile(r"^\d+[a-z]?\s+\d+[a-z]?[.\s]")),
    ("bare page marker", re.compile(r"(^|\s)p\.\s*[0-9ivxlc]+\s*$", re.IGNORECASE)),
    ("doubled word", re.compile(r"\b(\w{2,})\s+\1\b", re.IGNORECASE)),
    ("space before punctuation", re.compile(r"\w\s+[,;:.!?](\s|$)")),
    ("missing space after punctuation", re.compile(r"[a-z][.;:,!?][A-Z][a-z]")),
]


class _TextExtractor(HTMLParser):
    """Collect visible text inside the reading pane and notes tray, one block per line."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0  # >0 while inside a captured region
        self.stack: list[str] = []
        self.lines: list[str] = []
        self.current: list[str] = []
        self.skip = 0

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self.current)).strip()
        if text:
            self.lines.append(text)
        self.current = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = set((dict(attrs).get("class") or "").split())
        if tag in {"script", "style"}:
            self.skip += 1
        if self.depth:
            if tag != "br":
                self.depth += 1
            if tag in BLOCK_TAGS:
                self._flush()
        elif classes & CAPTURE_CLASSES and tag != "br":
            self.depth = 1
            self.lines.append(f"===== {', '.join(sorted(classes & CAPTURE_CLASSES))} =====")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.skip:
            self.skip -= 1
        if self.depth:
            if tag in BLOCK_TAGS:
                self._flush()
            self.depth -= 1
            if not self.depth:
                self._flush()

    def handle_data(self, data: str) -> None:
        if self.depth and not self.skip:
            self.current.append(data)


def page_text(path: Path) -> list[str]:
    parser = _TextExtractor()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    return parser.lines


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def default_base() -> str:
    for ref in ("origin/main", "main"):
        try:
            return git("merge-base", "HEAD", ref).strip()
        except subprocess.CalledProcessError:
            continue
    return "HEAD"


def repo_path(path: Path) -> str:
    """``path`` relative to the repository root, as git's ``REF:path`` syntax needs.

    Raises:
        ValueError: If ``path`` is outside the repository.
    """
    root = Path(git("rev-parse", "--show-toplevel").strip()).resolve()
    return path.resolve().relative_to(root).as_posix()


def changed_xml(base: str) -> list[Path]:
    names = set(git("diff", "--name-only", base, "--", f"{DOCS_DIR}/*.xml").split())
    names |= set(
        git("ls-files", "--others", "--exclude-standard", "--", f"{DOCS_DIR}/*.xml").split()
    )
    return sorted(Path(n) for n in names if Path(n).exists())


class RenderError(Exception):
    """The site generator failed; the message carries its captured output."""


def render(xml: Path, out: Path) -> dict[str, list[str]]:
    """Render one XML file into ``out`` and return {page path: text lines}.

    Raises:
        RenderError: If the generator exits nonzero, with its stderr/stdout tail.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "open_canon_site", str(xml), "-o", str(out), "--clean"],
        capture_output=True,
        text=True,
    )
    if proc.returncode:
        output = (proc.stderr or proc.stdout).strip().splitlines()
        raise RenderError("\n".join(output[-20:]) or f"exit status {proc.returncode}")
    return {
        str(p.relative_to(out)): page_text(p)
        for p in sorted(out.rglob("*.html"))
        if p.name != "index.html" or p.parent != out
    }


def dump_text(pages: dict[str, list[str]], dest_dir: Path) -> None:
    for rel, lines in pages.items():
        dest = dest_dir / (rel + ".txt")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _is_milestone(verse: ET.Element) -> bool:
    """True for a verse start or end milestone, which carries no text of its own.

    A contained verse may carry ``osisID``, ``sID`` and ``eID`` together (the LDS
    documents do), so ``eID`` alone does not make a verse an end milestone.
    """
    start_only = verse.get("sID") is not None and verse.get("eID") is None
    end_only = verse.get("eID") is not None and not verse.get("osisID") and not verse.get("sID")
    return start_only or end_only


def _reading_text(el: ET.Element) -> str:
    """Text of ``el`` without its notes (the site moves notes to the notes tray).

    A note's tail is kept: it is the verse text that follows the note.
    """
    parts = [el.text or ""]
    for child in el:
        if child.tag != f"{OSIS_NS}note":
            parts.append(_reading_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _chapter_verses(root: ET.Element) -> list[tuple[str, list[ET.Element]]]:
    """Group verses by chapter, in document order, as (chapter id, verses) pairs.

    Each chapter element is its own group, so two chapters that share an id stay
    apart (they are reported as a duplicate chapter id instead).

    Handles both chapter encodings the site parser accepts: containers
    (``<chapter>`` or ``<div type="chapter">`` holding the verses) and milestones
    (verses between ``<chapter sID="X"/>`` and ``<chapter eID="X"/>``).
    """
    chapter_tag, div_tag, verse_tag = f"{OSIS_NS}chapter", f"{OSIS_NS}div", f"{OSIS_NS}verse"
    parents = {child: parent for parent in root.iter() for child in parent}
    groups: dict[object, tuple[str, list[ET.Element]]] = {}
    milestone: tuple[ET.Element, str] | None = None
    for el in root.iter():
        is_chapter = el.tag == chapter_tag or (el.tag == div_tag and el.get("type") == "chapter")
        if is_chapter and len(el) == 0 and not (el.text or "").strip():
            if el.get("sID") is not None and el.get("eID") is None:
                milestone = (el, el.get("osisID") or el.get("sID") or "?")
            elif el.get("eID") is not None and el.get("sID") is None:
                milestone = None
            continue
        if el.tag != verse_tag:
            continue
        key = milestone
        ancestor = parents.get(el)
        while ancestor is not None:
            if ancestor.tag == chapter_tag or (
                ancestor.tag == div_tag and ancestor.get("type") == "chapter"
            ):
                key = (ancestor, ancestor.get("osisID") or ancestor.get("sID") or "?")
                break
            ancestor = parents.get(ancestor)
        if key is not None:
            groups.setdefault(key[0], (key[1], []))[1].append(el)
    return list(groups.values())


def structural_checks(xml: Path) -> list[str]:
    """Verse-level checks on the XML itself: duplicates, gaps, empty verses."""
    findings: list[str] = []
    try:
        root = ET.parse(xml).getroot()
    except ET.ParseError as exc:
        return [f"XML does not parse: {exc}"]
    ids = Counter()
    chapters = _chapter_verses(root)
    chapter_ids = Counter(cid for cid, _ in chapters)
    findings += [
        f"duplicate chapter osisID {cid} (x{n})" for cid, n in chapter_ids.items() if n > 1
    ]
    for cid, verses in chapters:
        prev = 0
        for verse in verses:
            vid = verse.get("osisID") or verse.get("sID")
            if vid is None:  # end milestone
                continue
            ids[vid] += 1
            if not _is_milestone(verse) and not _reading_text(verse).strip():
                findings.append(f"empty verse {vid}")
            m = re.match(r"(\d+)", vid.rsplit(".", 1)[-1])
            if m:
                num = int(m.group(1))
                if num > prev + 1:
                    findings.append(f"verse gap in {cid}: {prev} -> {num}")
                elif num < prev:
                    findings.append(f"verse order goes backwards in {cid}: {prev} -> {num}")
                prev = max(prev, num)
    findings += [f"duplicate osisID {vid} (x{n})" for vid, n in ids.items() if n > 1]
    return findings


def verse_count(xml_text: str) -> int:
    return len(re.findall(r"<verse\b(?![^>]*\beID=\"[^\"]*\"[^>]*/>)", xml_text))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("files", nargs="*", type=Path, help="XML files (default: changed vs --base)")
    ap.add_argument("--base", help="git ref to compare against (default: merge-base with main)")
    ap.add_argument(
        "--out", type=Path, help="keep rendered HTML and text dumps here (default: temp dir)"
    )
    ap.add_argument("--no-diff", action="store_true", help="skip the base render and text diff")
    ap.add_argument("--context", type=int, default=1, help="diff context lines (default 1)")
    ap.add_argument(
        "--diff-limit", type=int, default=400, help="max diff lines printed per file (0 = no limit)"
    )
    ap.add_argument(
        "--max-flags", type=int, default=40, help="max lines shown per flag type per file"
    )
    args = ap.parse_args()

    base = args.base or default_base()
    files = args.files or changed_xml(base)
    if not files:
        print(f"No changed XML under {DOCS_DIR}/ relative to {base}.")
        return 0

    work = args.out or Path(tempfile.mkdtemp(prefix="osis-triage-"))
    work.mkdir(parents=True, exist_ok=True)
    print(f"base: {base}\nwork dir: {work}\n")

    status = 0
    for xml in files:
        print("#" * 78)
        print(f"# {xml}")
        print("#" * 78)

        print("-- structural checks (XML) --")
        for finding in structural_checks(xml) or ["none"]:
            print(f"  {finding}")
        print()

        head_dir = work / "head" / xml.stem
        try:
            head_pages = render(xml, head_dir)
        except RenderError as exc:
            status = 1
            print(f"RENDER FAILED for {xml}; skipping diff and flags:\n{exc}\n")
            continue
        dump_dir = work / "text" / "head" / xml.stem
        dump_text(head_pages, dump_dir)
        print(f"rendered {len(head_pages)} pages; plain-text dumps in {dump_dir}")

        if not args.no_diff:
            try:
                base_xml_text = git("show", f"{base}:{repo_path(xml)}")
            except (subprocess.CalledProcessError, ValueError):
                base_xml_text = None
            if base_xml_text is None:
                print("(new file: no base version to diff)")
            else:
                base_xml = work / "base-src" / xml.name
                base_xml.parent.mkdir(parents=True, exist_ok=True)
                base_xml.write_text(base_xml_text, encoding="utf-8")
                try:
                    base_pages = render(base_xml, work / "base" / xml.stem)
                except RenderError as exc:
                    status = 1
                    print(f"base render failed; no diff for {xml}:\n{exc}")
                    base_pages = None
            if base_xml_text is not None and base_pages is not None:
                dump_text(base_pages, work / "text" / "base" / xml.stem)
                head_count = verse_count(xml.read_text(encoding="utf-8"))
                print(f"verses: {verse_count(base_xml_text)} -> {head_count}")
                added = sorted(set(head_pages) - set(base_pages))
                removed = sorted(set(base_pages) - set(head_pages))
                if added:
                    print("pages added:   " + ", ".join(added))
                if removed:
                    print("pages removed: " + ", ".join(removed))
                changed = 0
                printed = 0
                for rel in sorted(set(head_pages) | set(base_pages)):
                    diff = list(
                        difflib.unified_diff(
                            base_pages.get(rel, []),
                            head_pages.get(rel, []),
                            f"base/{rel}",
                            f"head/{rel}",
                            n=args.context,
                            lineterm="",
                        )
                    )
                    if diff:
                        changed += 1
                        if args.diff_limit and printed + len(diff) > args.diff_limit:
                            if printed < args.diff_limit:
                                print("\n".join(diff[: args.diff_limit - printed]))
                                print(f"... diff truncated; compare dumps under {work / 'text'}")
                            printed = args.diff_limit
                        else:
                            print("\n".join(diff))
                            printed += len(diff)
                print(f"pages with text changes: {changed}")

        print("\n-- heuristic flags (rendered text; hints, not verdicts) --")
        any_flag = False
        for label, pattern in LINE_FLAGS:
            hits = [
                (rel, i + 1, line)
                for rel, lines in head_pages.items()
                for i, line in enumerate(lines)
                if not line.startswith("=====") and pattern.search(line)
            ]
            if not hits:
                continue
            any_flag = True
            print(f"  [{label}] {len(hits)} line(s)")
            for rel, n, line in hits[: args.max_flags]:
                snippet = line if len(line) <= 160 else line[:157] + "..."
                print(f"    {rel}:{n}: {snippet}")
            if len(hits) > args.max_flags:
                print(f"    ... {len(hits) - args.max_flags} more")
        if not any_flag:
            print("  none")
        print()

    if args.out is None:
        print(f"(temp work dir kept for inspection: {work}; delete with: rm -rf {work})")
    return status


if __name__ == "__main__":
    if shutil.which("git") is None:
        sys.exit("git is required")
    sys.exit(main())
