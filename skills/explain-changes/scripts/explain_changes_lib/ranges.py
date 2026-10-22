"""Diff ranges and subtraction of changes that are not the user's own."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import detect
from .gitcmd import git_text, run_git
from .model import BlockedError, Hunk

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
DIFF_FLAGS = ["--no-ext-diff", "--no-textconv", "--no-color",
              "--src-prefix=a/", "--dst-prefix=b/"]

ForeignLines = Dict[str, "Counter[Tuple[str, str]]"]


@dataclass
class RangeSpec:
    from_ref: Optional[str] = None
    commit: Optional[str] = None
    include_uncommitted: bool = False
    exclude_merges: List[str] = field(default_factory=list)
    include_merges: List[str] = field(default_factory=list)
    exclude_authors: List[str] = field(default_factory=list)

    def to_json(self) -> Dict:
        return {"from": self.from_ref, "commit": self.commit,
                "include_uncommitted": self.include_uncommitted,
                "exclude_merges": list(self.exclude_merges),
                "include_merges": list(self.include_merges),
                "exclude_authors": list(self.exclude_authors)}


def _rev(repo: Path, ref: str) -> Optional[str]:
    res = run_git(repo, ["rev-parse", "-q", "--verify", ref + "^{commit}"], check=False)
    out = res.out.decode("utf-8", errors="replace").strip()
    return out if res.code == 0 and out else None


def _need(repo: Path, ref: str) -> str:
    sha = _rev(repo, ref)
    if sha is None:
        raise BlockedError("bad_input", "Unknown revision: %s" % ref)
    return sha


def _base_sha(repo: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        name, _source = detect.find_base(repo)
    except BlockedError:
        return None, None
    return name, _rev(repo, name)


def normalize_spec(repo: Path, spec: RangeSpec) -> RangeSpec:
    """Resolve user-given merge SHAs to full SHAs; unknown ones are bad_input."""
    repo = Path(repo)
    return RangeSpec(
        from_ref=spec.from_ref, commit=spec.commit,
        include_uncommitted=spec.include_uncommitted,
        exclude_merges=list(dict.fromkeys(_need(repo, r) for r in spec.exclude_merges)),
        include_merges=list(dict.fromkeys(_need(repo, r) for r in spec.include_merges)),
        exclude_authors=list(spec.exclude_authors))


def resolve_range(repo: Path, spec: RangeSpec) -> Tuple[str, Optional[str]]:
    """Return ``(old, new)``; ``new`` is ``None`` for the working tree."""
    repo = Path(repo)
    if spec.commit:
        sha = _need(repo, spec.commit)
        return (_rev(repo, sha + "^1") or EMPTY_TREE), sha
    if not spec.from_ref:
        raise BlockedError("bad_input", "Either --from or --commit is required.")
    from_sha = _need(repo, spec.from_ref)
    head = _rev(repo, "HEAD")
    old = from_sha
    base, base_sha = _base_sha(repo)
    if base is not None and (spec.from_ref == base or from_sha == base_sha):
        shallow = git_text(repo, ["rev-parse", "--is-shallow-repository"]).strip() == "true"
        old = detect.find_merge_base(repo, base, shallow) or from_sha
    return old, None if spec.include_uncommitted else head


# --- foreign lines ---------------------------------------------------------

def _text(raw: bytes) -> str:
    return raw.decode("utf-8", "replace")


def _diff_path(line: bytes) -> Optional[str]:
    rest = line[4:].split(b"\t")[0]
    if rest == b"/dev/null" or rest.startswith(b'"'):
        return None
    return _text(rest[2:])


def _patch_lines(patch: bytes) -> ForeignLines:
    """Count the ``-``/``+`` lines of a plain patch, per file."""
    found: ForeignLines = {}
    old_path = new_path = None
    in_hunk = False
    for raw in patch.split(b"\n"):
        if raw.startswith(b"diff --git "):
            in_hunk, old_path, new_path = False, None, None
        elif raw.startswith(b"@@"):
            in_hunk = True
        elif not in_hunk and raw.startswith(b"--- "):
            old_path = _diff_path(raw)
        elif not in_hunk and raw.startswith(b"+++ "):
            new_path = _diff_path(raw)
        elif in_hunk and raw[:1] in (b"+", b"-"):
            path = new_path or old_path
            if path is not None:
                found.setdefault(path, Counter())[(_text(raw[:1]), _text(raw[1:]))] += 1
    return found


def _combined_lines(patch: bytes, mark: str) -> Dict[str, List[str]]:
    """Lines of a ``--cc`` patch that differ from every parent (all columns ``mark``)."""
    found: Dict[str, List[str]] = {}
    path, cols = None, 0
    for raw in patch.split(b"\n"):
        if raw.startswith(b"diff --cc ") or raw.startswith(b"diff --combined "):
            path, cols = _text(raw.split(b" ", 2)[2]), 0
        elif raw.startswith(b"@@@"):
            cols = len(raw.split(b" ", 1)[0]) - 1
        elif cols and path is not None and len(raw) >= cols and raw[:cols] == mark.encode() * cols:
            found.setdefault(path, []).append(_text(raw[cols:]))
    return found


def _merge_parents(repo: Path, sha: str) -> List[str]:
    return git_text(repo, ["log", "-1", "--format=%P", sha]).split()


def _range_end(spec: RangeSpec, new: Optional[str]) -> str:
    return new or "HEAD"


def _auto_foreign_merges(repo: Path, spec: RangeSpec, old: str, end: str) -> List[str]:
    """Merges in range that only bring in the base branch (never the user's work)."""
    base, _sha = _base_sha(repo)
    res = run_git(repo, ["log", "--merges", "--first-parent", "--format=%H", "%s..%s" % (old, end)], check=False)
    merges = res.out.decode("utf-8", errors="replace").split() if res.code == 0 else []
    chosen = []
    for sha in merges:
        if sha in spec.include_merges or sha == spec.commit:
            continue
        later = _merge_parents(repo, sha)[1:]
        if base is not None and later and all(
                run_git(repo, ["merge-base", "--is-ancestor", p, base], check=False).code == 0
                for p in later):
            chosen.append(sha)
    return chosen


def excluded_merges(repo: Path, spec: RangeSpec, old: str, new: Optional[str]) -> List[str]:
    end = _range_end(spec, new)
    chosen = list(spec.exclude_merges)
    for sha in _auto_foreign_merges(Path(repo), spec, old, end):
        if sha not in chosen:
            chosen.append(sha)
    return [s for s in chosen if s not in spec.include_merges]


def _author_commits(repo: Path, spec: RangeSpec, old: str, end: str) -> List[Tuple[str, str]]:
    if not spec.exclude_authors:
        return []
    wanted = {a.lower() for a in spec.exclude_authors}
    res = run_git(repo, ["log", "--no-merges", "--format=%H%x1f%ae", "%s..%s" % (old, end)],
                  check=False)
    rows = [l.split("\x1f") for l in res.out.decode("utf-8", errors="replace").split("\n") if l]
    return [(sha, email) for sha, email in rows if email.lower() in wanted]


def foreign_lines(repo: Path, spec: RangeSpec, old: str,
                  new: Optional[str] = None) -> ForeignLines:
    repo = Path(repo)
    end = _range_end(spec, new)
    foreign: ForeignLines = {}

    def add(lines: ForeignLines) -> None:
        for path, counter in lines.items():
            foreign.setdefault(path, Counter()).update(counter)

    for sha in excluded_merges(repo, spec, old, new):
        if len(_merge_parents(repo, sha)) < 2:
            continue
        brought = _patch_lines(run_git(
            repo, ["diff", "-p", "-U0", *DIFF_FLAGS, sha + "^1", sha]).out)
        cc = run_git(repo, ["diff-tree", "--cc", "-p", *DIFF_FLAGS, sha], check=False).out
        for mark in ("+", "-"):
            for path, texts in _combined_lines(cc, mark).items():
                for text in texts:
                    key = (mark, text)
                    if brought.get(path) and brought[path][key] > 0:
                        brought[path][key] -= 1
        add(brought)
    for sha, _email in _author_commits(repo, spec, old, end):
        add(_patch_lines(run_git(
            repo, ["show", "--format=", "-p", "-U0", *DIFF_FLAGS, sha]).out))
    return foreign


_TRIVIAL = re.compile(r"^[\W_]*$")


def _is_trivial(line: str) -> bool:
    return bool(_TRIVIAL.match(line.strip()))


def subtract(hunks: List[Hunk], foreign: ForeignLines) -> Tuple[List[Hunk], List[str]]:
    """Drop hunks made only of foreign lines; keep anything doubtful whole."""
    pool = {path: Counter(c) for path, c in foreign.items()}
    kept: List[Hunk] = []
    dropped: List[str] = []
    for hunk in hunks:
        lines = Counter([("-", l) for l in hunk.removed] + [("+", l) for l in hunk.added])
        have = pool.get(hunk.file)
        meaningful = any(not _is_trivial(t) for _s, t in lines)
        if lines and have and meaningful and all(have[k] >= n for k, n in lines.items()):
            have.subtract(lines)
            dropped.append(hunk.id)
        else:
            kept.append(hunk)
    return kept, dropped


def mark_resolved_in_merge(repo: Path, hunks: List[Hunk], merges: List[str]) -> None:
    """Annotate added lines that a merge's manual resolution produced (new line numbers)."""
    wanted: Dict[str, Counter] = {}
    for sha in merges:
        if len(_merge_parents(Path(repo), sha)) < 2:
            continue
        cc = run_git(repo, ["diff-tree", "--cc", "-p", *DIFF_FLAGS, sha], check=False).out
        for path, texts in _combined_lines(cc, "+").items():
            wanted.setdefault(path, Counter()).update(texts)
    for hunk in hunks:
        texts = wanted.get(hunk.file)
        if not texts:
            continue
        for offset, line in enumerate(hunk.added):
            lineno = hunk.new_start + offset
            if line in texts and lineno not in hunk.resolved_in_merge:
                hunk.resolved_in_merge.append(lineno)


def merges_in_range(repo: Path, spec: RangeSpec, old: str, new: Optional[str]) -> List[str]:
    res = run_git(repo, ["log", "--merges", "--first-parent", "--format=%H",
                         "%s..%s" % (old, _range_end(spec, new))], check=False)
    return res.out.decode("utf-8", errors="replace").split() if res.code == 0 else []
