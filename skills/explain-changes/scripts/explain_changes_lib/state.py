"""Per-branch review state: what was reviewed, so a later run can show only the new."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .workspace import WORKDIR, safe_write

STATE_DIR = "estado"


def state_key(branch: str) -> str:
    """File-safe, collision-free key: sanitized name plus a short hash of the original."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", branch.replace("/", "__"))
    digest = hashlib.sha1(branch.encode("utf-8")).hexdigest()[:8]
    return safe + "-" + digest


def _rel(branch: str) -> str:
    return "%s/%s.json" % (STATE_DIR, state_key(branch))


def load_state(repo: Path, branch: Optional[str]) -> Optional[Dict]:
    """The saved state of ``branch``, or None (no branch, no file or unreadable)."""
    if not branch:
        return None
    path = Path(repo) / WORKDIR / _rel(branch)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("hunks"), list):
        return None
    return data


def _get(hunk: Any, name: str) -> Any:
    return hunk[name] if isinstance(hunk, dict) else getattr(hunk, name)


def build_state(branch: str, head: Optional[str], hunks: Iterable[Any],
                files: Optional[Iterable[str]] = None) -> Dict:
    """State to save after a review. ``hunks`` may be Hunk objects or their JSON dicts.

    ``files`` lists the reviewed paths so hunkless changes (binary, rename, mode)
    can be recognized as seen later."""
    return {
        "branch": branch,
        "head": head,
        "reviewed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hunks": [{"fingerprint": _get(h, "fingerprint"), "file": _get(h, "file"),
                   "new_start": _get(h, "new_start"), "new_lines": _get(h, "new_lines")}
                  for h in hunks],
        "files": sorted(set(files or [])),
    }


def save_state(repo: Path, branch: str, state: Dict) -> str:
    """Write the state file and return its path relative to the repo."""
    if not branch:
        raise ValueError("no state is kept for a detached HEAD")
    rel = _rel(branch)
    safe_write(Path(repo), rel, json.dumps(state, ensure_ascii=False, indent=1))
    return WORKDIR + "/" + rel


def _span(start: int, lines: int) -> range:
    return range(start, start + max(lines, 1))


def _overlaps(hunk: Any, saved: List[Dict]) -> bool:
    mine = _span(hunk.new_start, hunk.new_lines)
    for s in saved:
        theirs = _span(s.get("new_start", 0), s.get("new_lines", 0))
        if mine.start < theirs.stop and theirs.start < mine.stop:
            return True
    return False


def mark_new(hunks: List[Any], state: Dict) -> None:
    """Set ``seen`` / ``changed_since_review``. Saved fingerprints form a multiset."""
    saved = [s for s in state.get("hunks", []) if isinstance(s, dict)]
    budget = Counter(s.get("fingerprint") for s in saved)
    by_file: Dict[str, List[Dict]] = {}
    for s in saved:
        by_file.setdefault(s.get("file"), []).append(s)
    for h in hunks:
        if budget[h.fingerprint] > 0:
            budget[h.fingerprint] -= 1
            h.seen, h.changed_since_review = True, False
        else:
            h.seen = False
            h.changed_since_review = _overlaps(h, by_file.get(h.file, []))
