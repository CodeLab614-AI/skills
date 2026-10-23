"""Parse Git diffs into FileChange/Hunk objects, with intraline changes."""
from __future__ import annotations

import difflib
import os
import re
import stat
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .diskpath import on_disk
from .gitcmd import run_git
from .model import FileChange, Hunk

MAX_CHANGED_LINES = 20000
MAX_BLOB_BYTES = 2 * 1024 * 1024
MAX_INTRALINE_CHARS = 2000
ZERO_SHA = "0" * 40
WORKSPACE_DIR = ".explain-changes"
DIFF_OPTS = ["--no-ext-diff", "--no-textconv", "--no-color", "-M50%",
             "--src-prefix=a/", "--dst-prefix=b/"]
_HUNK_RE = re.compile(rb"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_STATUS = {"A": "added", "D": "deleted", "M": "modified", "T": "modified",
           "R": "renamed", "U": "modified"}


def _path(raw: bytes) -> str:
    return raw.decode("utf-8", "surrogateescape")


def _line(raw: bytes) -> Tuple[str, bool]:
    """Decode one line as UTF-8; on failure use ``replace`` and flag it."""
    try:
        return raw.decode("utf-8"), False
    except UnicodeDecodeError:
        return raw.decode("utf-8", "replace"), True


def intraline(old: str, new: str) -> List[Tuple[int, int, str, str]]:
    """Character-level changes between two lines as (col_start, col_end, before, after).

    Columns are 1-based and inclusive and refer to the NEW line. A pure
    insertion covers the inserted text; a pure deletion is an empty range
    anchored at the character that follows it (col_end == col_start - 1,
    after == ""). Lines longer than 2000 characters are not compared.
    """
    if len(old) > MAX_INTRALINE_CHARS or len(new) > MAX_INTRALINE_CHARS:
        return []
    out = []
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        out.append((j1 + 1, j2, old[i1:i2], new[j1:j2]))
    return out


def _hunk_intraline(removed: List[str], added: List[str], new_start: int) -> List[Dict]:
    if not removed or len(removed) != len(added):
        return []
    res = []
    for k, (a, b) in enumerate(zip(removed, added)):
        for cs, ce, before, after in intraline(a, b):
            res.append({"line": new_start + k, "col_start": cs, "col_end": ce,
                        "before": before, "after": after})
    return res


def _parse(path: str, patch: bytes) -> Tuple[List[Hunk], bool]:
    hunks: List[Hunk] = []
    bad = False
    cur = None
    rem_old = rem_new = 0
    for raw in patch.split(b"\n"):
        if cur is not None and (rem_old > 0 or rem_new > 0):
            if raw.startswith(b"-") and rem_old > 0:
                text, b = _line(raw[1:])
                cur["removed"].append(text)
                rem_old -= 1
                bad = bad or b
                continue
            if raw.startswith(b"+") and rem_new > 0:
                text, b = _line(raw[1:])
                cur["added"].append(text)
                rem_new -= 1
                bad = bad or b
                continue
        if raw.startswith(b"\\"):
            continue  # "\ No newline at end of file" is never content
        m = _HUNK_RE.match(raw)
        if m:
            if cur is not None:
                hunks.append(_make(path, cur))
            os_, ol, ns, nl = m.groups()
            cur = {"old_start": int(os_), "old_lines": int(ol) if ol is not None else 1,
                   "new_start": int(ns), "new_lines": int(nl) if nl is not None else 1,
                   "removed": [], "added": []}
            rem_old, rem_new = cur["old_lines"], cur["new_lines"]
    if cur is not None:
        hunks.append(_make(path, cur))
    _unique_ids(hunks)
    return hunks, bad


def _unique_ids(hunks: List[Hunk]) -> None:
    """Fingerprints are content-only, so repeated changes in one file share
    one; later occurrences get an ``-2``, ``-3`` suffix on the id."""
    seen: Dict[str, int] = {}
    for h in hunks:
        n = seen.get(h.fingerprint, 0) + 1
        seen[h.fingerprint] = n
        if n > 1:
            h.id_override = "h-%s-%d" % (h.fingerprint[:12], n)


def _make(path: str, c: Dict) -> Hunk:
    return Hunk(file=path, old_start=c["old_start"], old_lines=c["old_lines"],
                new_start=c["new_start"], new_lines=c["new_lines"],
                removed=c["removed"], added=c["added"],
                intraline=_hunk_intraline(c["removed"], c["added"], c["new_start"]))


def parse_hunks(path: str, patch: bytes) -> List[Hunk]:
    return _parse(path, patch)[0]


# --- git plumbing -----------------------------------------------------------

def _raw_entries(repo: Path, refs: List[str]) -> List[Dict]:
    out = run_git(repo, ["diff", "--raw", "-z", "--no-abbrev", *DIFF_OPTS, *refs]).out
    toks = out.split(b"\0")
    entries, i = [], 0
    while i < len(toks) and toks[i].startswith(b":"):
        meta = toks[i][1:].decode("ascii", "replace").split(" ")
        status = meta[4]
        e = {"old_mode": meta[0], "new_mode": meta[1], "old_sha": meta[2],
             "new_sha": meta[3], "letter": status[0],
             "score": int(status[1:]) if status[1:].isdigit() else None}
        if status[0] in "RC":
            e["old_path"], e["path"] = _path(toks[i + 1]), _path(toks[i + 2])
            i += 3
        else:
            e["old_path"], e["path"] = None, _path(toks[i + 1])
            i += 2
        entries.append(e)
    return entries


def _numstat(repo: Path, refs: List[str],
             extra: Optional[List[str]] = None) -> Dict[str, Tuple[Optional[int], Optional[int]]]:
    out = run_git(repo, ["diff", "--numstat", "-z", *(extra or []), *DIFF_OPTS, *refs]).out
    toks = out.split(b"\0")
    res, i = {}, 0
    while i < len(toks) and toks[i]:
        a, d, p = toks[i].split(b"\t", 2)
        if p == b"":  # rename: the next two tokens are old and new paths
            path, i = _path(toks[i + 2]), i + 3
        else:
            path, i = _path(p), i + 1
        res[path] = (None if a == b"-" else int(a), None if d == b"-" else int(d))
    return res


def _blob_sizes(repo: Path, shas: List[str]) -> Dict[str, int]:
    shas = sorted({s for s in shas if s and s != ZERO_SHA})
    if not shas:
        return {}
    res = run_git(repo, ["cat-file", "--batch-check=%(objectname) %(objectsize)"],
                  stdin=("\n".join(shas) + "\n").encode(), check=False)
    sizes = {}
    for ln in res.out.decode("ascii", "replace").splitlines():
        parts = ln.split(" ")
        if len(parts) == 2 and parts[1].isdigit():
            sizes[parts[0]] = int(parts[1])
    return sizes


def _hash_worktree(repo: Path, path: str) -> Optional[str]:
    res = run_git(repo, ["hash-object", "--", path], check=False)
    sha = res.out.decode("ascii", "replace").strip()
    return sha if res.code == 0 and len(sha) == 40 else None


def _disk_size(repo: Path, path: str) -> int:
    try:
        return os.lstat(on_disk(repo, path)).st_size
    except OSError:
        return 0


def _file_patch(repo: Path, refs: List[str], paths: List[str]) -> bytes:
    return run_git(repo, ["--literal-pathspecs", "diff", "-p", "-U0", *DIFF_OPTS,
                          *refs, "--", *paths]).out


_SECTION_RE = re.compile(rb"(?m)^diff --git ")


def _range_patches(repo: Path, refs: List[str], count: int) -> Optional[List[bytes]]:
    """One ``git diff -p -U0`` for the whole range, split into one chunk per raw entry
    (Git emits the sections in the same order as ``--raw``). ``None`` when the number of
    sections differs from ``count`` (for example a type change), so the caller falls back
    to one diff per file."""
    patch = run_git(repo, ["diff", "-p", "-U0", *DIFF_OPTS, *refs, "--"], timeout=300).out
    sections = _SECTION_RE.split(patch)[1:]
    return sections if len(sections) == count else None


def diff_files(repo: Path, old: str, new: Optional[str]) -> List[FileChange]:
    """Changes between ``old`` and ``new`` (``None`` = the working tree)."""
    refs = [old] if new is None else [old, new]
    stats = _numstat(repo, refs)
    entries = _raw_entries(repo, refs)
    # A file with changes that all disappear under --ignore-cr-at-eol only changed line endings.
    stats_no_eol = _numstat(repo, refs, ["--ignore-cr-at-eol"])
    sizes = _blob_sizes(repo, [e["old_sha"] for e in entries if e["old_mode"] != "160000"]
                        + [e["new_sha"] for e in entries if e["new_mode"] != "160000"])
    changes = []
    pending: List[Tuple[int, FileChange]] = []  # entry index and file that need hunks
    for idx, e in enumerate(entries):
        mode = lambda m: None if m == "000000" else m
        sha = lambda s: None if s == ZERO_SHA else s
        is_sub = "160000" in (e["old_mode"], e["new_mode"])
        adds, dels = stats.get(e["path"], (0, 0))
        fc = FileChange(
            path=e["path"], status="submodule" if is_sub else _STATUS.get(e["letter"], "modified"),
            old_path=e["old_path"], similarity=e["score"] if e["letter"] == "R" else None,
            additions=adds or 0, deletions=dels or 0,
            old_mode=mode(e["old_mode"]), new_mode=mode(e["new_mode"]),
            binary=adds is None and dels is None and not is_sub,
            old_blob=None if is_sub else sha(e["old_sha"]),
            new_blob=None if is_sub else sha(e["new_sha"]))
        if is_sub:
            fc.submodule = {"old": sha(e["old_sha"]) if e["old_mode"] == "160000" else None,
                            "new": sha(e["new_sha"]) if e["new_mode"] == "160000" else None}
            changes.append(fc)
            continue
        worktree_new = new is None and e["new_mode"] != "000000"
        if worktree_new and fc.new_blob is None and (fc.binary or e["letter"] != "D"):
            fc.new_blob = _hash_worktree(repo, fc.path)
        old_size = sizes.get(e["old_sha"], 0)
        new_size = _disk_size(repo, fc.path) if worktree_new else sizes.get(e["new_sha"], 0)
        if (fc.additions + fc.deletions > MAX_CHANGED_LINES
                or max(old_size, new_size) > MAX_BLOB_BYTES):
            fc.too_large = True
        if not fc.binary and not fc.too_large and (fc.additions or fc.deletions):
            pending.append((idx, fc))
            fc.eol_only = fc.path not in stats_no_eol
        changes.append(fc)
    _fill_hunks(repo, refs, entries, changes, pending)
    return changes


def _fill_hunks(repo: Path, refs: List[str], entries: List[Dict],
                changes: List[FileChange], pending: List[Tuple[int, FileChange]]) -> None:
    """Parse the hunks of ``pending`` files: from one range-wide diff when no file is
    huge (a too_large file is never parsed, so it must not be loaded), else per file."""
    if not pending:
        return
    patches = None
    if not any(fc.too_large for fc in changes):
        patches = _range_patches(repo, refs, len(entries))
    for idx, fc in pending:
        if patches is not None:
            patch = patches[idx]
        else:
            patch = _file_patch(repo, refs, [p for p in (fc.old_path, fc.path) if p])
        fc.hunks, fc.encoding_issue = _parse(fc.path, patch)


def _split_lines(data: bytes) -> List[bytes]:
    if not data:
        return []
    lines = data.split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    return lines


def _skipped(notices: Optional[List[Dict]], path: str, reason: str) -> None:
    if notices is not None:
        notices.append({"code": "untracked_skipped",
                        "params": {"path": path, "reason": reason}})


def untracked_files(repo: Path, notices: Optional[List[Dict]] = None) -> List[FileChange]:
    """Untracked files as added hunks. Entries that cannot be read as a regular file
    or symlink (nested repos, FIFOs, unreadable files) are skipped with a notice."""
    out = run_git(repo, ["ls-files", "--others", "--exclude-standard", "-z"]).out
    changes = []
    for raw in out.split(b"\0"):
        if not raw:
            continue
        path = _path(raw)
        if path == WORKSPACE_DIR or path.startswith(WORKSPACE_DIR + "/"):
            continue
        if path.endswith("/"):
            _skipped(notices, path, "nested_repo")
            continue
        full = on_disk(repo, path)
        is_link = os.path.islink(full)
        try:
            st = os.lstat(full)
            if not is_link and not stat.S_ISREG(st.st_mode):
                _skipped(notices, path, "not_regular_file")
                continue
            if is_link:
                data = os.fsencode(os.readlink(full))
            elif st.st_size > MAX_BLOB_BYTES:
                data = None  # too large: never read it into memory
            else:
                with open(full, "rb") as fh:
                    data = fh.read()
        except OSError:
            _skipped(notices, path, "unreadable")
            continue
        mode = "120000" if is_link else ("100755" if st.st_mode & 0o111 else "100644")
        fc = FileChange(path=path, status="untracked", new_mode=mode)
        if data is None:
            fc.too_large = True
            try:
                with open(full, "rb") as fh:
                    fc.binary = b"\0" in fh.read(8000)
            except OSError:
                pass
        elif b"\0" in data[:8000]:
            fc.binary = True
        else:
            lines = _split_lines(data)
            fc.additions = len(lines)
            if fc.additions > MAX_CHANGED_LINES or len(data) > MAX_BLOB_BYTES:
                fc.too_large = True
            else:
                added, bad = [], False
                for ln in lines:
                    text, b = _line(ln)
                    added.append(text)
                    bad = bad or b
                fc.encoding_issue = bad
                if added:
                    fc.hunks = [Hunk(file=path, old_start=0, old_lines=0, new_start=1,
                                     new_lines=len(added), removed=[], added=added)]
        changes.append(fc)
    return changes
