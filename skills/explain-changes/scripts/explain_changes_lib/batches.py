"""Batches: groups of changed files whose logic lines fit the threshold."""
from __future__ import annotations

from typing import Dict, List

from .model import FileChange, Hunk

THRESHOLD = 1500


def _key(path: str, depth: int) -> str:
    parts = path.split("/")
    if len(parts) <= depth:
        return path
    return "/".join(parts[:depth])


def make_batches(files: List[FileChange], hunks: List[Hunk],
                 threshold: int = THRESHOLD) -> List[Dict]:
    sizes: Dict[str, int] = {}
    for fc in files:
        lines = sum(len(h.removed) + len(h.added) for h in fc.hunks if h.klass == "logic")
        if lines or any(h.klass == "logic" for h in fc.hunks):
            sizes[fc.path] = lines
    if not sizes:
        return []

    groups: Dict[str, List[str]] = {}
    for path in sorted(sizes):
        groups.setdefault(_key(path, 1), []).append(path)
    units: List[List[str]] = []
    for key in sorted(groups):
        paths = groups[key]
        if sum(sizes[p] for p in paths) <= threshold:
            units.append(paths)
            continue
        sub: Dict[str, List[str]] = {}
        for p in paths:
            sub.setdefault(_key(p, 2), []).append(p)
        units.extend(sub[k] for k in sorted(sub))

    if sum(sizes.values()) <= threshold:
        bins = [list(units)]
    else:
        bins = []
        loads: List[int] = []
        for unit in units:
            size = sum(sizes[p] for p in unit)
            for i, load in enumerate(loads):
                if load + size <= threshold:
                    bins[i].append(unit)
                    loads[i] += size
                    break
            else:
                bins.append([unit])
                loads.append(size)

    batches: List[Dict] = []
    by_path = {fc.path: fc for fc in files}
    for n, members in enumerate(bins, start=1):
        paths = sorted(p for unit in members for p in unit)
        for p in paths:
            for h in by_path[p].hunks:
                if h.klass == "logic":
                    h.batch = n
        batches.append({"id": n, "paths": paths,
                        "logic_lines": sum(sizes[p] for p in paths)})
    return batches
