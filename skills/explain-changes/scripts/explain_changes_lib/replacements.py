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
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
# Literals and keywords: swapping them changes behavior, never a mere rename.
_LITERALS = frozenset(["true", "false", "True", "False", "TRUE", "FALSE", "null",
                       "None", "nil", "undefined", "NaN"])

Pair = Tuple[str, str]


def _is_tok(text: str, i: int) -> bool:
    return 0 <= i < len(text) and bool(_TOKEN_CHAR.match(text[i]))


def _widen(text: str, i1: int, i2: int) -> Tuple[int, int]:
    while _is_tok(text, i1 - 1):
        i1 -= 1
    while _is_tok(text, i2):
        i2 += 1
    return i1, i2


def _line_pairs(old: str, new: str) -> Optional[Set[Pair]]:
    """Token pairs that explain one line pair, or None if they cannot be formed."""
    segments = intraline(old, new)
    if not segments:
        return None
    spans: List[List[int]] = []  # [old_start, old_end, new_start, new_end], widened
    shift = 0
    for col_start, col_end, before, after in segments:
        j1, j2 = col_start - 1, col_end
        i1 = j1 - shift
        i2 = i1 + len(before)
        shift += len(after) - len(before)
        oi1, oi2 = _widen(old, i1, i2)
        nj1, nj2 = _widen(new, j1, j2)
        if spans and (oi1 <= spans[-1][1] or nj1 <= spans[-1][3]):
            spans[-1][1] = max(spans[-1][1], oi2)
            spans[-1][3] = max(spans[-1][3], nj2)
        else:
            spans.append([oi1, oi2, nj1, nj2])
    pairs: Set[Pair] = set()
    for oi1, oi2, nj1, nj2 in spans:
        o, n = old[oi1:oi2], new[nj1:nj2]
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
    if not (_IDENT.fullmatch(o) and _IDENT.fullmatch(n)):
        return None
    if o in _LITERALS or n in _LITERALS:
        return None
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
    qualifying = [(pair, pure[pair]) for pair in sorted(pure)
                  if len({h.file for h in pure[pair]}) >= min_files]
    for _, group in qualifying:
        for h in group:
            h.klass, h.mechanical_kind = "mechanical", KIND
    remaining = [h for h in logic if h.klass == "logic"]
    result: List[Dict] = []
    for (o, n), group in qualifying:
        exceptions: Dict[str, List[str]] = {}
        for h in remaining:
            if any(o in line for line in h.removed) and any(n in line for line in h.added):
                exceptions.setdefault(h.file, []).append(h.id)
        result.append({
            "old": o, "new": n,
            "hunk_ids": sorted(h.id for h in group),
            "files": sorted({h.file for h in group}),
            "exceptions": [{"file": f, "hunk_ids": sorted(ids)}
                           for f, ids in sorted(exceptions.items())],
        })
    return result
