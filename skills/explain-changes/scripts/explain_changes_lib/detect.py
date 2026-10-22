"""detect: repo state, blocking conditions and base branch."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .gitcmd import git_text, run_git
from .model import BlockedError

FALLBACK_BASES = ("main", "master", "develop")
FETCH_TIMEOUT = 20


def _ok(repo: Path, args: List[str]) -> bool:
    return run_git(repo, args, check=False).code == 0


def _text_or_none(repo: Path, args: List[str]) -> Optional[str]:
    res = run_git(repo, args, check=False)
    if res.code != 0:
        return None
    return res.out.decode("utf-8", errors="replace").strip() or None


def check_blocks(repo: Path) -> None:
    """Raise BlockedError when the repo is mid-rebase, mid-merge or conflicted."""
    git_dir = Path(git_text(repo, ["rev-parse", "--absolute-git-dir"]).strip())
    if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
        raise BlockedError("rebase_in_progress",
                           "A rebase is in progress. Finish or abort it, then run again.")
    if (git_dir / "MERGE_HEAD").exists():
        raise BlockedError("merge_in_progress",
                           "A merge is in progress. Finish or abort it, then run again.")
    if run_git(repo, ["ls-files", "-u"]).out.strip():
        raise BlockedError("unresolved_conflicts",
                           "There are unresolved conflicts. Resolve them, then run again.")


def current_branch(repo: Path) -> Optional[str]:
    return _text_or_none(repo, ["symbolic-ref", "-q", "--short", "HEAD"])


def _ref_exists(repo: Path, ref: str) -> bool:
    return _ok(repo, ["rev-parse", "--verify", "-q", ref + "^{commit}"])


def find_base(repo: Path) -> Tuple[str, str]:
    """Return (base ref name, base_source) or raise no_base_branch."""
    head = _text_or_none(repo, ["symbolic-ref", "-q", "refs/remotes/origin/HEAD"])
    prefix = "refs/remotes/"
    if head and head.startswith(prefix):
        name = head[len(prefix):]
        if _ref_exists(repo, name):
            return name, "origin/HEAD"
    for name in FALLBACK_BASES:
        if _ref_exists(repo, "refs/heads/" + name):
            return name, "local"
    for name in FALLBACK_BASES:
        if _ref_exists(repo, "refs/remotes/origin/" + name):
            return "origin/" + name, "local"
    raise BlockedError("no_base_branch",
                       "No base branch found (origin/HEAD, main, master or develop).")


def fetch_base(repo: Path, base: str) -> Tuple[str, List[Dict]]:
    """Fetch the base branch from origin. Returns (status, notices)."""
    if not _ok(repo, ["remote", "get-url", "origin"]):
        return "skipped", []
    branch = base[len("origin/"):] if base.startswith("origin/") else base
    res = run_git(repo, ["fetch", "--quiet", "origin", branch],
                  check=False, timeout=FETCH_TIMEOUT)
    if res.code == 0:
        return "ok", []
    return "failed", [{"code": "fetch_failed",
                       "params": {"base": branch, "reason": res.err.strip()[:300]}}]


def find_merge_base(repo: Path, base: str, shallow: bool) -> Optional[str]:
    mb = _text_or_none(repo, ["merge-base", "HEAD", base])
    if mb is None and shallow:
        raise BlockedError(
            "shallow_no_merge_base",
            "The repository is shallow and has no merge base with %s. "
            "Run 'git fetch --unshallow' yourself if you agree; "
            "this tool never runs --unshallow without permission." % base)
    return mb


def detect(repo: Path, fetch: bool = True) -> dict:
    check_blocks(repo)
    branch = current_branch(repo)
    head = _text_or_none(repo, ["rev-parse", "-q", "--verify", "HEAD"])
    shallow = git_text(repo, ["rev-parse", "--is-shallow-repository"]).strip() == "true"
    base, base_source = find_base(repo)
    notices: List[Dict] = []
    fetch_status = "skipped"
    if fetch:
        fetch_status, fetch_notices = fetch_base(repo, base)
        notices.extend(fetch_notices)
        if fetch_status == "ok":
            # The fetch may have created or moved the remote-tracking ref.
            base, base_source = find_base(repo)
    merge_base = find_merge_base(repo, base, shallow)
    if merge_base is None:
        notices.append({"code": "no_merge_base", "params": {"base": base}})
    return {
        "ok": True,
        "branch": branch,
        "detached": branch is None,
        "head": head,
        "shallow": shallow,
        "base": base,
        "base_source": base_source,
        "fetch": fetch_status,
        "merge_base": merge_base,
        "notices": notices,
    }
