"""Repeated replacements: the same token swapped for another across many files.

Conservative by construction: a hunk is pure only if every one of its line
pairs is explained exactly by one (old, new) token pair, verified with
``str.replace``. Anything else stays logic.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from .diffparse import intraline
from .model import Hunk

MIN_FILES = 3
KIND = "repeated_replacement"
_TOKEN_CHAR = re.compile(r"[\w$]")
_TOKEN = re.compile(r"[\w$]+")

Pair = Tuple[str, str]


def _is_tok(text: str, i: int) -> bool:
    return 0 <= i < len(text) and bool(_TOKEN_CHAR.match(text[i]))


def _line_pairs(old: str, new: str) -> Optional[Set[Pair]]:
    """Token pairs that explain one line pair, or None if they cannot be formed."""
    segments = intraline(old, new)
    if not segments:
        return None
    pairs: Set[Pair] = set()
    shift = 0
    for col_start, col_end, before, after in segments:
        j1, j2 = col_start - 1, col_end
        i1, i2 = j1 - shift, j1 - shift + len(before)
        shift += len(after) - len(before)
        while _is_tok(old, i1 - 1) and _is_tok(new, j1 - 1):
            i1, j1 = i1 - 1, j1 - 1
        while _is_tok(old, i2) and _is_tok(new, j2):
            i2, j2 = i2 + 1, j2 + 1
        o, n = old[i1:i2], new[j1:j2]
        if not (_TOKEN.fullmatch(o) and _TOKEN.fullmatch(n)) or o == n:
            return None
        pairs.add((o, n))
    return pairs


def _pure_pair(hunk: Hunk) -> Optional[Pair]:
    """The single (old, new) token pair that exactly explains the hunk, or None."""
    if not hunk.removed or len(hunk.removed) != len(hunk.added):
        return None
    pairs: Set[Pair] = set()
    for old, new in zip(hunk.removed, hunk.added):
        found = _line_pairs(old, new)
        if found is None:
            return None
        pairs |= found
    if len(pairs) != 1:
        return None
    o, n = next(iter(pairs))
    if all(old.replace(o, n) == new for old, new in zip(hunk.removed, hunk.added)):
        return (o, n)
    return None


def find_repeated_replacements(hunks: List[Hunk], min_files: int = MIN_FILES) -> List[Dict]:
    """Find token replacements repeated in ``min_files``+ files; mark pure hunks mechanical."""
    logic = [h for h in hunks if h.klass == "logic"]
    pure: Dict[Pair, List[Hunk]] = {}
    for h in logic:
        pair = _pure_pair(h)
        if pair is not None:
            pure.setdefault(pair, []).append(h)
    result: List[Dict] = []
    for (o, n) in sorted(pure):
        group = pure[(o, n)]
        files = sorted({h.file for h in group})
        if len(files) < min_files:
            continue
        in_group = {id(h) for h in group}
        exceptions: Dict[str, List[str]] = {}
        for h in logic:
            if id(h) in in_group:
                continue
            if any(o in line for line in h.removed) and any(n in line for line in h.added):
                exceptions.setdefault(h.file, []).append(h.id)
        for h in group:
            h.klass, h.mechanical_kind = "mechanical", KIND
        result.append({
            "old": o, "new": n,
            "hunk_ids": sorted(h.id for h in group),
            "files": files,
            "exceptions": [{"file": f, "hunk_ids": sorted(ids)}
                           for f, ids in sorted(exceptions.items())],
        })
    return result
