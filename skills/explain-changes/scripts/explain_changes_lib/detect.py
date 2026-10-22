"""detect: repo state, blocking conditions and base branch."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import rules, state
from .gitcmd import git_text, run_git
from .model import BlockedError

FALLBACK_BASES = ("main", "master", "develop")
FETCH_TIMEOUT = 20
MAX_PICK = 30
SQUASH_SCAN = 300
MAX_UNTRACKED_READ = 2 * 1024 * 1024


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


def _lines(repo: Path, args: List[str]) -> List[str]:
    res = run_git(repo, args, check=False)
    if res.code != 0:
        return []
    return [l for l in res.out.decode("utf-8", errors="replace").split("\n") if l]


def _commit_rows(repo: Path, args: List[str]) -> List[List[str]]:
    return [l.split("\x1f") for l in _lines(repo, ["log", "--format=%H%x1f%s%x1f%ae", *args])]


def own_commits(repo: Path, mb: Optional[str]) -> List[Dict]:
    if mb is None:
        return []
    return [{"sha": r[0], "subject": r[1], "email": r[2]}
            for r in _commit_rows(repo, ["--no-merges", mb + "..HEAD"])]


def foreign_merges(repo: Path, mb: Optional[str], base: str) -> List[Dict]:
    """Merges in mb..HEAD whose later parents are not reachable from the base."""
    if mb is None:
        return []
    found = []
    for line in _lines(repo, ["log", "--merges", "--format=%H%x1f%P%x1f%s", mb + "..HEAD"]):
        sha, parents, subject = line.split("\x1f")
        plist = parents.split()
        foreign = [p for p in plist[1:]
                   if not _ok(repo, ["merge-base", "--is-ancestor", p, base])]
        if not foreign:
            continue
        hint = _text_or_none(repo, ["name-rev", "--name-only", "--no-undefined", foreign[0]])
        files = len(_lines(repo, ["diff", "--name-only", sha + "^1", sha]))
        found.append({"sha": sha, "branch_hint": _clean_hint(hint, subject), "files": files})
    return found


def _clean_hint(hint: Optional[str], subject: str) -> str:
    if hint:
        return hint.split("~")[0].split("^")[0]
    return subject


def other_authors(commits: List[Dict], user_email: Optional[str]) -> List[Dict]:
    if not user_email:
        return []
    me = user_email.lower()
    return [{"sha": c["sha"], "email": c["email"]} for c in commits
            if c["email"].lower() != me]


def read_status(repo: Path) -> Tuple[Dict[str, int], List[str], List[str]]:
    """Count staged, unstaged and untracked paths (ignored files never show)."""
    res = run_git(repo, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    entries = res.out.decode("utf-8", errors="replace").split("\0")
    counts = {"staged": 0, "unstaged": 0, "untracked": 0}
    paths: List[str] = []
    untracked: List[str] = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        x, y, path = entry[0], entry[1], entry[3:]
        if x in "RC":
            i += 1  # skip the original path of a rename or copy
        if x == "?":
            counts["untracked"] += 1
            untracked.append(path)
        else:
            if x not in " ?!":
                counts["staged"] += 1
            if y not in " ?!":
                counts["unstaged"] += 1
        paths.append(path)
    return counts, paths, untracked


def _patch_ids(repo: Path, patch: bytes) -> List[Tuple[str, str]]:
    res = run_git(repo, ["patch-id", "--stable"], check=False, stdin=patch)
    pairs = []
    for line in res.out.decode("utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) == 2:
            pairs.append((parts[0], parts[1]))
    return pairs


def find_merged(repo: Path, mb: Optional[str], base: str,
                notices: Optional[List[Dict]] = None) -> Optional[Dict]:
    """Detect whether HEAD's work already landed in the base: merge, squash or tree."""
    if mb is None:
        return None
    if _ok(repo, ["merge-base", "--is-ancestor", "HEAD", base]):
        rows = _lines(repo, ["rev-list", "--merges", "--ancestry-path", "--reverse",
                             "HEAD.." + base])
        head = _text_or_none(repo, ["rev-parse", "HEAD"])
        for sha in rows:
            parents = _lines(repo, ["rev-list", "--parents", "-n", "1", sha])
            if head and parents and head in parents[0].split()[1:]:
                return {"how": "merge", "commit": sha}
        tip = _text_or_none(repo, ["rev-parse", base + "^{commit}"])
        if head and head != tip:  # HEAD == base tip means a branch with no own commits
            return {"how": "fast_forward", "commit": head}
        return None
    flags = ["--no-ext-diff", "--no-textconv"]
    diff = run_git(repo, ["diff", *flags, mb, "HEAD"], check=False).out
    if not diff.strip():
        return None
    mine = _patch_ids(repo, diff)
    if mine:
        log = run_git(repo, ["log", "-p", "--no-merges", *flags, "-n", str(SQUASH_SCAN),
                             mb + ".." + base], check=False).out
        theirs = {pid: sha for pid, sha in _patch_ids(repo, log)}
        if mine[0][0] in theirs:
            return {"how": "squash", "commit": theirs[mine[0][0]]}
    files = _lines(repo, ["diff", "--name-only", mb, "HEAD"])
    try:
        if files and _ok(repo, ["diff", "--quiet", "HEAD", base, "--", *files]):
            last = _text_or_none(repo, ["log", "-1", "--format=%H", base, "--", *files])
            if last:
                return {"how": "tree", "commit": last}
    except OSError:  # E2BIG: too many changed paths for one command line
        if notices is not None:
            notices.append({"code": "heuristic_skipped", "params": {"heuristic": "tree"}})
    return None


def count_unpushed(repo: Path) -> int:
    if _ok(repo, ["rev-parse", "--verify", "-q", "@{upstream}"]):
        out = _text_or_none(repo, ["rev-list", "--count", "@{upstream}..HEAD"])
    elif _lines(repo, ["remote"]):
        out = _text_or_none(repo, ["rev-list", "--count", "HEAD", "--not", "--remotes"])
    else:
        return 0
    return int(out) if out and out.isdigit() else 0


def _count_lines(path: Path) -> int:
    """Line count of a text file; unreadable, binary or oversized files count 0."""
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_UNTRACKED_READ:
            return 0
        data = path.read_bytes()
    except OSError:
        return 0
    if b"\0" in data:
        return 0
    return data.count(b"\n") + (0 if not data or data.endswith(b"\n") else 1)


def diff_size(repo: Path, mb: Optional[str], extra_paths: List[str],
              untracked: List[str]) -> Tuple[Dict, List[str]]:
    """Files and lines changed against mb (tracked + untracked); renames count by new path."""
    paths = set(extra_paths)
    lines = 0
    res = run_git(repo, ["diff", "--numstat", "-z", "--no-ext-diff", "--no-textconv",
                         mb or "HEAD"], check=False)
    fields = res.out.decode("utf-8", errors="replace").split("\0")
    i = 0
    while i < len(fields):
        head = fields[i]
        i += 1
        parts = head.split("\t", 2)
        if len(parts) < 3:
            continue
        add, dele, name = parts
        if name == "":  # rename or copy: the next two fields are old and new path
            name = fields[i + 1] if i + 1 < len(fields) else ""
            i += 2
        if name:
            paths.add(name)
        lines += (int(add) if add.isdigit() else 0) + (int(dele) if dele.isdigit() else 0)
    for name in untracked:
        lines += _count_lines(repo / name)
    return {"files": len(paths), "lines": lines}, sorted(paths)


def _opt(oid: str, recommended: bool, facts_args: List[str], params: Optional[Dict] = None) -> Dict:
    return {"id": oid, "recommended": recommended, "facts_args": facts_args,
            "params": params or {}}


def scope_options(repo: Path, info: Dict) -> List[Dict]:
    """Options for the scope question.

    from_commit and other_commit are pickers: their facts_args are only a prefix
    (["--from-commit"] / ["--commit"]) and the caller appends the chosen sha.
    from_commit is inclusive: the picked commit's own change is part of the range."""
    mb, pending = info["merge_base"], sum(info["uncommitted"].values()) > 0
    extra = ["--include-uncommitted"] if pending else []
    commits = [{"sha": c["sha"], "subject": c["subject"]}
               for c in info["own_commits"][:MAX_PICK]]
    if not commits:
        commits = [{"sha": r[0], "subject": r[1]}
                   for r in _commit_rows(repo, ["-n", str(MAX_PICK), "HEAD"])]
    review = info["last_review"]
    fresh = review is not None and (review.get("head") != info["head"] or pending)
    has_own = mb is not None and mb != info["head"]
    options: List[Dict] = []
    how = info["merged"]["how"] if info["merged"] else None
    if how in ("merge", "squash"):  # a fast-forward has no commit that stands for the branch
        options.append(_opt("merge_commit", False, ["--commit", info["merged"]["commit"]]))
    if fresh and mb:
        options.append(_opt("only_new", False, ["--from", mb, "--only-new", *extra]))
    if has_own:
        options.append(_opt("whole_branch", False, ["--from", mb, *extra]))
    if info["merged"]:
        options.append(_opt("other_commit", False, ["--commit"], {"commits": commits}))
    else:
        options.append(_opt("from_commit", False, ["--from-commit"], {"commits": commits}))
    if pending or (not info["on_base"] and has_own):
        options.append(_opt("uncommitted_only", False, ["--from", "HEAD", "--include-uncommitted"]))
    ids = [o["id"] for o in options]
    if not has_own and pending:
        rec = "uncommitted_only"  # nothing of the branch's own: the pending work is the point
    elif how in ("merge", "squash"):
        rec = "merge_commit"
    elif how in ("tree", "fast_forward") and has_own:
        rec = "whole_branch"  # the merge commit would under-cover the branch's work
    elif fresh and mb:
        rec = "only_new"
    else:
        rec = ids[0]
    for o in options:
        o["recommended"] = o["id"] == rec
    return options


def build_questions(repo: Path, info: Dict) -> Tuple[List[Dict], List[Dict], str]:
    """Return (questions, auto_answered notices, chosen scope option id)."""
    questions: List[Dict] = []
    notices: List[Dict] = []
    scope = scope_options(repo, info)
    chosen = next(o["id"] for o in scope if o["recommended"])
    candidates = [{"id": "scope", "options": scope}]
    merges = info["foreign_merges"]
    if merges:
        candidates.append({"id": "foreign_merges", "options": [
            _opt("exclude", True, [a for m in merges for a in ("--exclude-merge", m["sha"])]),
            _opt("include", False, [a for m in merges for a in ("--include-merge", m["sha"])]),
        ]})
    emails = sorted({c["email"] for c in info["other_author_commits"]}, key=str.lower)
    if emails:
        candidates.append({"id": "other_authors", "options": [
            _opt("exclude", True, [a for e in emails for a in ("--exclude-author", e)],
                 {"emails": emails}),
            _opt("include", False, []),
        ]})
    for q in candidates:
        if len(q["options"]) == 1:
            notices.append({"code": "auto_answered",
                            "params": {"question": q["id"], "option": q["options"][0]["id"],
                                       "facts_args": q["options"][0]["facts_args"],
                                       "params": q["options"][0]["params"]}})
        else:
            questions.append(q)
    return questions, notices, chosen


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
    result = {
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
    result.update(_describe_changes(repo, result))
    return result


def last_review(repo: Path, review: Optional[Dict], head: Optional[str],
                commits: List[Dict], status_paths: List[str], size: Dict) -> Optional[Dict]:
    """What changed since the saved review. A rewritten history (saved head no longer
    an ancestor of HEAD) cannot be measured by commits, so it falls back to the totals."""
    if review is None:
        return None
    saved = review.get("head")
    reachable = bool(saved and head and _ok(repo, ["merge-base", "--is-ancestor", saved, head]))
    if reachable:
        count = _text_or_none(repo, ["rev-list", "--count", saved + "..HEAD"])
        new_commits = int(count) if count and count.isdigit() else 0
        new_files = len(set(_lines(repo, ["diff", "--name-only", saved, "HEAD"]))
                        | set(status_paths))
    else:
        new_commits, new_files = len(commits), size["files"]
    return {"head": saved, "reviewed_at": review.get("reviewed_at"),
            "head_reachable": reachable, "new_commits": new_commits, "new_files": new_files}


def _describe_changes(repo: Path, info: Dict) -> Dict:
    mb, base, branch = info["merge_base"], info["base"], info["branch"]
    notices = info["notices"]
    commits = own_commits(repo, mb)
    user_email = _text_or_none(repo, ["config", "user.email"])
    if not user_email:
        notices.append({"code": "author_check_skipped", "params": {}})
    counts, status_paths, untracked = read_status(repo)
    base_short = base[len("origin/"):] if base.startswith("origin/") else base
    review = state.load_state(repo, branch) if branch else None
    size, changed = diff_size(repo, mb, status_paths, untracked)
    out = {
        "own_commits": commits,
        "foreign_merges": foreign_merges(repo, mb, base),
        "other_author_commits": other_authors(commits, user_email),
        "uncommitted": counts,
        "merged": None,
        "on_base": branch == base_short,
        "unpushed": count_unpushed(repo),
        "last_review": last_review(repo, review, info["head"], commits, status_paths, size),
        "rule_files": rules.find_rule_files(repo, changed),
        "diff_size": size,
    }
    if not out["on_base"]:
        out["merged"] = find_merged(repo, mb, base, notices)
        if out["merged"] is None and mb is not None and mb == info["head"]:
            notices.append({"code": "no_own_commits", "params": {"base": base}})
    merged_view = dict(info, **out)
    questions, auto, chosen = build_questions(repo, merged_view)
    notices.extend(auto)
    if out["last_review"] and not out["last_review"]["head_reachable"]:
        notices.append({"code": "history_rewritten",
                        "params": {"head": out["last_review"]["head"]}})
    out["questions"] = questions
    out["summary"] = {"scope_option": chosen, "base": base,
                      "rule_count": len(out["rule_files"])}
    return out
