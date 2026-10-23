"""Render report.md and report.html from facts and verified; save the branch state."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from . import state
from .detect import current_branch, find_base
from .gitcmd import run_git
from .labels import LABELS, fill
from .model import BlockedError
from .report_html import MAX_LISTED, render_html
from .richtext import code_md, one, strip_bold, to_markdown
from .verify import UNEXPLAINED
from .workspace import WORKDIR, remove_workfile, safe_write

REPORT_REL = "report.md"
REPORT_HTML_REL = "report.html"

__all__ = ["LABELS", "render", "summary_model", "write_report", "resolve_labels"]


def resolve_labels(lang: str, override: Optional[Dict] = None) -> Dict[str, str]:
    labels = dict(LABELS["en"])
    labels.update(LABELS.get(lang, {}))
    labels.update(override or {})
    return {k: one(v) for k, v in labels.items()}


def _read(repo: Path, rel: str) -> Dict:
    try:
        data = json.loads((Path(repo) / WORKDIR / rel).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        raise BlockedError("bad_input", "No usable %s/%s; run the earlier steps first."
                           % (WORKDIR, rel))
    return data


def count_files(n: int, labels: Dict) -> str:
    return fill(labels["count_files_one" if n == 1 else "count_files_many"], n=n)


def summary_model(facts: Dict, verified: Dict, labels: Dict) -> Dict:
    """The conversation summary as data: the same text feeds report.md and report.html."""
    total = (facts.get("totals") or {}).get("files", 0)
    points = verified.get("points") or []
    rest_files = 0
    unexplained: List[str] = []
    for group in (verified.get("rest") or {}).get("groups") or []:
        paths = [f["path"] for f in group.get("files") or []]
        if group.get("kind") == UNEXPLAINED:
            unexplained = paths
        else:
            rest_files += len(paths)
    if not total:
        lead = labels["no_changes"]
    elif not points:
        lead = fill(labels["lead_none"], files=count_files(total, labels))
    else:
        key = "lead_one" if len(points) == 1 else "lead_many"
        lead = fill(labels[key], files=count_files(total, labels), n=len(points))
    rest = None
    if rest_files:
        line = one((verified.get("rest") or {}).get("line") or "")
        rest = {"head": fill(labels["rest_head"], files=count_files(rest_files, labels)),
                "line": line}
    warnings = []
    for w in verified.get("warnings") or []:
        rule = fill(labels["warn_rule"], name="**%s**" % strip_bold(w["name"]), says=w["says"])
        warnings.append({"text": "%s %s" % (one(w["change"]), one(rule)),
                         "verified": bool(w.get("verified"))})
    return {"lead": one(lead),
            "points": [{"title": strip_bold(p["title"]), "line": one(p.get("line") or "")}
                       for p in points],
            "rest": rest,
            "unexplained": ({"head": fill(labels["kind_unexplained"] + " ({files}):",
                                          files=count_files(len(unexplained), labels)),
                             "files": unexplained} if unexplained else None),
            "warnings": warnings}


def render(facts: Dict, verified: Dict, labels: Dict) -> str:
    """report.md: only the summary shown in the conversation."""
    model = summary_model(facts, verified, labels)
    out: List[str] = [model["lead"], ""]
    for n, p in enumerate(model["points"], start=1):
        out.append("%d. **%s** %s" % (n, to_markdown(p["title"]), to_markdown(p["line"])))
    if model["points"]:
        out.append("")
    if model["rest"]:
        out += ["**%s** %s" % (model["rest"]["head"], to_markdown(model["rest"]["line"])), ""]
    un = model["unexplained"]
    if un:
        listed = [code_md(p) for p in un["files"][:MAX_LISTED]]
        more = len(un["files"]) - MAX_LISTED
        if more > 0:
            listed.append(fill(labels["and_more"], n=more))
        out += ["**%s** %s" % (un["head"], ", ".join(listed)), ""]
    if model["warnings"]:
        out += ["**%s**" % labels["warn_head"], ""]
        for w in model["warnings"]:
            mark = "" if w["verified"] else " ⚠ %s" % labels["unverified_citation"]
            out.append("- %s%s" % (to_markdown(w["text"]), mark))
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def _head(repo: Path) -> Optional[str]:
    res = run_git(repo, ["rev-parse", "-q", "--verify", "HEAD"], check=False)
    return res.out.decode("utf-8", errors="replace").strip() or None if res.code == 0 else None


def _is_ancestor(repo: Path, commit: str, base: str) -> bool:
    return run_git(repo, ["merge-base", "--is-ancestor", commit, base], check=False).code == 0


def _branch_exists(repo: Path, branch: str) -> bool:
    return run_git(repo, ["rev-parse", "-q", "--verify", "refs/heads/" + branch + "^{commit}"],
                   check=False).code == 0


def cleanup_stale_states(repo: Path, current: Optional[str]) -> List[Dict]:
    """Delete states of deleted or base-merged branches. Failures become notices."""
    notices: List[Dict] = []
    folder = Path(repo) / WORKDIR / state.STATE_DIR
    if not folder.is_dir():
        return notices
    try:
        base: Optional[str] = find_base(repo)[0]
    except BlockedError:
        base = None
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            branch = data.get("branch") if isinstance(data, dict) else None
            if not isinstance(branch, str) or not state._valid(data, branch) \
                    or path.name != state.state_key(branch) + ".json" or branch == current:
                continue
            head = data.get("head")
            stale = not _branch_exists(repo, branch) or (
                base is not None and isinstance(head, str) and _is_ancestor(repo, head, base))
            if stale:
                remove_workfile(repo, "%s/%s" % (state.STATE_DIR, path.name))
        except Exception as exc:  # cleanup must never block the report
            notices.append({"code": "state_cleanup_failed",
                            "params": {"file": path.name, "reason": str(exc)[:200]}})
    return notices


def write_report(repo: Path, lang: str, labels: Optional[Dict] = None) -> Dict:
    repo = Path(repo)
    facts = _read(repo, "run/facts.json")
    verified = _read(repo, "run/verified.json")
    resolved = resolve_labels(lang, labels)
    branch = current_branch(repo)
    safe_write(repo, REPORT_REL, render(facts, verified, resolved))
    safe_write(repo, REPORT_HTML_REL, render_html(facts, verified, resolved, branch, lang))
    state_path = None
    if branch:
        hunks = list(facts.get("hunks", []))
        files = [f["path"] for f in facts.get("files", [])]
        prior = state.load_state(repo, branch) if facts.get("only_new") else None
        if prior:
            hunks = list(prior.get("hunks", [])) + hunks
            files = list(prior.get("files", [])) + files
        state_path = state.save_state(
            repo, branch, state.build_state(branch, _head(repo), hunks, files))
    notices = cleanup_stale_states(repo, branch)
    return {"ok": True, "path": WORKDIR + "/" + REPORT_REL,
            "html_path": WORKDIR + "/" + REPORT_HTML_REL, "state_path": state_path,
            "notices": notices}
