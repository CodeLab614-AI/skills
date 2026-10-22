"""The .explain-changes/ workspace: exclusion, safe writes, manifest, cleanup."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List

from .gitcmd import git_text, run_git
from .model import BlockedError

WORKDIR = ".explain-changes"
MANIFEST = ".manifest.json"
EXCLUDE_LINE = "/.explain-changes/"
KEEP_PREFIX = "estado/"


def _is_ignored(repo: Path) -> bool:
    return run_git(repo, ["check-ignore", "-q", WORKDIR + "/x"], check=False).code == 0


def ensure_excluded(repo: Path) -> None:
    repo = Path(repo)
    if not _is_ignored(repo):
        raw = git_text(repo, ["rev-parse", "--git-path", "info/exclude"]).strip()
        exclude = Path(raw)
        if not exclude.is_absolute():
            exclude = repo / exclude
        exclude.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if EXCLUDE_LINE not in existing.splitlines():
            sep = "" if not existing or existing.endswith("\n") else "\n"
            with open(exclude, "a", encoding="utf-8") as fh:
                fh.write(sep + EXCLUDE_LINE + "\n")
    if not _is_ignored(repo):
        raise BlockedError(
            "not_excluded",
            f"{WORKDIR}/ is not excluded from Git; refusing to write inside the repository.",
        )


def _workdir(repo: Path) -> Path:
    return Path(repo) / WORKDIR


def _read_manifest(repo: Path) -> List[str]:
    path = _workdir(repo) / MANIFEST
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [p for p in data.get("files", []) if isinstance(p, str)]
    except (OSError, ValueError, AttributeError):
        return []


def _write_manifest(repo: Path, files: List[str]) -> None:
    path = _workdir(repo) / MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"files": sorted(set(files))}, indent=2), encoding="utf-8")


def _checked_target(repo: Path, rel: str) -> Path:
    if not rel or os.path.isabs(rel) or Path(rel).is_absolute():
        raise ValueError(f"absolute path not allowed: {rel!r}")
    parts = Path(rel).parts
    if ".." in parts:
        raise ValueError(f"path escapes {WORKDIR}/: {rel!r}")
    base = _workdir(repo)
    base.mkdir(parents=True, exist_ok=True)
    base_real = base.resolve()
    if base_real.parent != Path(repo).resolve():
        raise ValueError(f"{WORKDIR}/ must be a real directory inside the repository")
    target = base / rel
    target_real = target.resolve()
    if target_real != base_real and base_real not in target_real.parents:
        raise ValueError(f"path escapes {WORKDIR}/: {rel!r}")
    return target


def safe_write(repo: Path, rel: str, text: str) -> Path:
    repo = Path(repo)
    ensure_excluded(repo)
    target = _checked_target(repo, rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    norm = Path(rel).as_posix()
    files = _read_manifest(repo)
    if norm not in files:
        files.append(norm)
    _write_manifest(repo, files)
    return target


def cleanup_previous(repo: Path) -> List[str]:
    repo = Path(repo)
    removed: List[str] = []
    keep: List[str] = []
    for rel in _read_manifest(repo):
        if rel.startswith(KEEP_PREFIX):
            keep.append(rel)
            continue
        try:
            target = _checked_target(repo, rel)
        except ValueError:
            continue
        if target.is_file() or target.is_symlink():
            target.unlink()
            removed.append(rel)
    if (_workdir(repo)).exists():
        _write_manifest(repo, keep)
    return removed
