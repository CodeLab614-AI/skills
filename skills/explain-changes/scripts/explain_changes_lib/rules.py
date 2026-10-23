"""Rule-file discovery: agent/editor instruction files inside the repo."""
from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional

from .diskpath import from_disk, on_disk

MAX_IMPORT_DEPTH = 5
IMPORT_RE = re.compile(r"(?<![\w`])@([~./\w-][\w./-]*)")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


def _inside(repo_real: str, real: str) -> bool:
    return real == repo_real or real.startswith(repo_real + os.sep)


def _resolve(repo: Path, rel: str) -> Optional[Path]:
    """Return the real file for a repo-relative path, or None if not a safe file."""
    repo_real = os.path.realpath(repo)
    real = os.path.realpath(on_disk(repo_real, rel))
    if not _inside(repo_real, real) or not os.path.isfile(real):
        return None
    return Path(real)


def read_rule_text(repo: Path, path: str) -> List[str]:
    real = _resolve(repo, path)
    if real is None:
        return []
    try:
        data = real.read_bytes()
    except OSError:
        return []
    return data.decode("utf-8", errors="replace").splitlines()


def _is_text_file(real: Path) -> bool:
    if real.name == ".DS_Store":
        return False
    try:
        with open(real, "rb") as fh:
            return b"\0" not in fh.read(8192)
    except OSError:
        return False


def _tree_files(repo: Path, top: str) -> List[str]:
    root = os.path.join(str(repo), top)
    found: List[str] = []
    if not os.path.isdir(root) or os.path.islink(root):
        return found
    for dirpath, _dirs, files in os.walk(root, followlinks=False):
        for name in files:
            rel = os.path.relpath(os.path.join(dirpath, name), str(repo))
            found.append(PurePosixPath(*from_disk(rel).split(os.sep)).as_posix())
    return sorted(found)


def _import_targets(lines: List[str]) -> List[str]:
    targets: List[str] = []
    in_fence = False
    for line in lines:
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in IMPORT_RE.finditer(line):
            targets.append(m.group(1))
    return targets


def _resolve_import(repo: Path, importer: str, target: str) -> Optional[str]:
    if target.startswith("~"):
        return None
    base = PurePosixPath(importer).parent
    rel = os.path.normpath(str(base / target)).replace(os.sep, "/")
    if rel.startswith("../") or rel == "..":
        return None
    real = _resolve(repo, rel)
    if real is None:
        return None
    out = from_disk(os.path.relpath(str(real), os.path.realpath(repo))).replace(os.sep, "/")
    parts = out.split("/")
    if ".git" in parts or parts[-1].startswith(".env"):
        return None
    return out


def find_rule_files(repo: Path, changed_paths: List[str]) -> List[Dict]:
    repo = Path(repo)
    result: List[Dict] = []
    seen = set()

    def add(path: str, kind: str, imported_from: Optional[str] = None) -> bool:
        real = _resolve(repo, path)
        if path in seen or real is None or not _is_text_file(real):
            return False
        seen.add(path)
        result.append({"path": path, "kind": kind,
                       "line_count": len(read_rule_text(repo, path)),
                       "imported_from": imported_from})
        return True

    def add_imports(path: str, depth: int) -> None:
        if depth >= MAX_IMPORT_DEPTH:
            return
        for target in _import_targets(read_rule_text(repo, path)):
            rel = _resolve_import(repo, path, target)
            if rel is None and target.rstrip(".,;:)") != target:
                rel = _resolve_import(repo, path, target.rstrip(".,;:)"))
            if rel is not None and add(rel, "import", path):
                add_imports(rel, depth + 1)

    for p in _tree_files(repo, ".agents/rules"):
        add(p, "agents_rules")
    add("AGENTS.md", "agents_md")
    if add("CLAUDE.md", "claude_md"):
        add_imports("CLAUDE.md", 0)
    for p in _tree_files(repo, ".cursor/rules"):
        add(p, "cursor_rules")
    add(".cursorrules", "cursorrules")
    add(".github/copilot-instructions.md", "copilot_instructions")
    add(".windsurfrules", "windsurfrules")
    add("CONTRIBUTING.md", "contributing")
    for changed in changed_paths:
        parent = PurePosixPath(changed).parent
        parts = parent.parts
        for i in range(1, len(parts) + 1):
            add(PurePosixPath(*parts[:i], "AGENTS.md").as_posix(), "nested_agents_md")
    return result
