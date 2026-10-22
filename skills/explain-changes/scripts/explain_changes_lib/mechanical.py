"""Deterministic mechanical classification. When in doubt, a change is logic."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .gitcmd import run_git
from .model import FileChange, Hunk

LOCKFILES = frozenset([
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml",
    "bun.lock", "bun.lockb", "Cargo.lock", "poetry.lock", "Pipfile.lock",
    "uv.lock", "composer.lock", "Gemfile.lock", "go.sum", "packages.lock.json",
    "pubspec.lock", "mix.lock", "flake.lock", "Podfile.lock", "gradle.lockfile",
])
GENERATED_DIRS = frozenset(["dist", ".next", "coverage", "__generated__"])
GENERATED_SUFFIXES = (
    ".min.js", ".min.css", ".pb.go", "_pb2.py", ".g.dart", ".freezed.dart",
)
HEAD_LINES = 5
HEAD_BYTES = 8192


def is_lockfile(path: str) -> bool:
    return PurePosixPath(path).name in LOCKFILES


INDENT_SENSITIVE_SUFFIXES = (
    ".py", ".pyi", ".yml", ".yaml", ".mk", ".coffee", ".pug", ".haml", ".sass", ".styl",
)
INDENT_SENSITIVE_NAMES = frozenset(["Makefile", "GNUmakefile"])


def is_indent_sensitive(path: str) -> bool:
    name = PurePosixPath(path).name
    return name in INDENT_SENSITIVE_NAMES or name.endswith(INDENT_SENSITIVE_SUFFIXES)


def _squashed(lines: Iterable[str]) -> List[Tuple[str, str]]:
    """(leading indentation, text without whitespace) per line; blank lines dropped."""
    out = []
    for line in lines:
        text = "".join(line.split())
        if text:
            out.append((line[:len(line) - len(line.lstrip())], text))
    return out


def is_whitespace_only(hunk: Hunk) -> bool:
    """Per-line equal once whitespace is removed (like ``-w``); blank lines ignored.

    In indentation-significant files a changed leading indentation is logic.
    """
    if not hunk.removed and not hunk.added:
        return False
    old, new = _squashed(hunk.removed), _squashed(hunk.added)
    if [t for _, t in old] != [t for _, t in new]:
        return False
    if is_indent_sensitive(hunk.file) and any(o[0] != n[0] for o, n in zip(old, new)):
        return False
    return True


def generated_attr_paths(repo: Path, paths: List[str]) -> Set[str]:
    """Paths whose ``linguist-generated`` attribute is set/true (one Git call)."""
    if not paths:
        return set()
    res = run_git(repo, ["check-attr", "-z", "--stdin", "linguist-generated"],
                  check=False, stdin=b"".join(p.encode("utf-8", "surrogateescape") + b"\0"
                                              for p in paths))
    if res.code != 0:
        return set()
    parts = res.out.split(b"\0")
    found: Set[str] = set()
    for i in range(0, len(parts) - 2, 3):
        if parts[i + 2] in (b"set", b"true"):
            found.add(parts[i].decode("utf-8", "surrogateescape"))
    return found


def generated_reason(repo: Path, path: str, head_lines: List[str],
                     attr_paths: Optional[Set[str]] = None) -> Optional[str]:
    """Why the file counts as generated, or None. ``attr_paths`` is a batch cache."""
    if attr_paths is None:
        attr_paths = generated_attr_paths(repo, [path])
    if path in attr_paths:
        return "linguist-generated"
    if any("@generated" in line for line in head_lines[:HEAD_LINES]):
        return "@generated header"
    posix = PurePosixPath(path)
    if any(part in GENERATED_DIRS for part in posix.parts[:-1]):
        return "generated directory"
    if posix.name.endswith(GENERATED_SUFFIXES):
        return "generated suffix"
    return None


def _head_lines(repo: Path, fc: FileChange) -> List[str]:
    """First lines of the new content, bounded. Blob first, then the disk."""
    data = b""
    if fc.new_blob:
        res = run_git(repo, ["cat-file", "blob", fc.new_blob], check=False)
        if res.code == 0:
            data = res.out[:HEAD_BYTES]
    if not data:
        try:
            with open(repo / fc.path, "rb") as fh:
                data = fh.read(HEAD_BYTES)
        except OSError:
            return []
    text = data.decode("utf-8", errors="replace")
    return text.split("\n")[:HEAD_LINES]


def _set(fc: FileChange, kind: str) -> None:
    fc.klass, fc.mechanical_kind = "mechanical", kind
    for h in fc.hunks:
        h.klass, h.mechanical_kind = "mechanical", kind


def refresh_file_class(fc: FileChange) -> None:
    """A file is mechanical only if all its hunks are; mixed kinds read as whitespace."""
    kinds = [h.mechanical_kind for h in fc.hunks]
    if kinds and all(kinds):
        fc.klass = "mechanical"
        fc.mechanical_kind = kinds[0] if len(set(kinds)) == 1 else "whitespace"


def classify(repo: Path, files: List[FileChange], hunks: List[Hunk]) -> None:
    """Mark class / mechanical_kind on every hunk and file (in place)."""
    repo = Path(repo)
    for h in hunks:
        h.klass, h.mechanical_kind = "logic", None
    attr_paths = generated_attr_paths(repo, [f.path for f in files if f.status != "deleted"])
    for fc in files:
        fc.klass, fc.mechanical_kind = "logic", None
        if is_lockfile(fc.path):
            _set(fc, "lockfile")
            continue
        if fc.status != "deleted":
            head = []
            if not fc.binary and not fc.too_large:
                head = _head_lines(repo, fc)
            if generated_reason(repo, fc.path, head, attr_paths):
                _set(fc, "generated")
                continue
        if fc.binary or fc.too_large:
            continue
        if not fc.hunks:
            if (fc.status == "renamed" and fc.similarity == 100
                    and fc.old_mode == fc.new_mode):
                _set(fc, "move")
            continue
        for h in fc.hunks:
            if is_whitespace_only(h):
                h.klass, h.mechanical_kind = "mechanical", "whitespace"
        refresh_file_class(fc)
