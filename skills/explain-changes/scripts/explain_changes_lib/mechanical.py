"""Deterministic mechanical classification. When in doubt, a change is logic."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Set

from .gitcmd import run_git
from .model import FileChange, Hunk

LOCKFILES = frozenset([
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml",
    "bun.lock", "bun.lockb", "Cargo.lock", "poetry.lock", "Pipfile.lock",
    "uv.lock", "composer.lock", "Gemfile.lock", "go.sum", "packages.lock.json",
    "pubspec.lock", "mix.lock", "flake.lock", "Podfile.lock", "gradle.lockfile",
])
GENERATED_DIRS = frozenset([
    "dist", "build", "out", ".next", "coverage", "__generated__", "generated",
])
GENERATED_SUFFIXES = (
    ".min.js", ".min.css", ".pb.go", "_pb2.py", ".g.dart", ".freezed.dart",
)
HEAD_LINES = 5
HEAD_BYTES = 8192


def is_lockfile(path: str) -> bool:
    return PurePosixPath(path).name in LOCKFILES


def is_whitespace_only(hunk: Hunk) -> bool:
    """True when the - and + lines are equal once all whitespace is removed."""
    if not hunk.removed and not hunk.added:
        return False

    def squash(lines: Iterable[str]) -> str:
        return "".join("".join(line.split()) for line in lines)

    return squash(hunk.removed) == squash(hunk.added)


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
            if fc.status == "renamed" and fc.similarity == 100:
                _set(fc, "move")
            continue
        kinds = []
        for h in fc.hunks:
            if is_whitespace_only(h):
                h.klass, h.mechanical_kind = "mechanical", "whitespace"
            kinds.append(h.mechanical_kind)
        if all(kinds):
            fc.klass = "mechanical"
            fc.mechanical_kind = kinds[0] if len(set(kinds)) == 1 else "whitespace"
