"""Render reporte.md from facts and verified, save the branch state, prune stale states."""
from __future__ import annotations

import json
import subprocess  # noqa: F401  (kept out: all Git goes through gitcmd)
from pathlib import Path
from typing import Dict, List, Optional

from . import state
from .detect import current_branch, find_base
from .gitcmd import run_git
from .labels import LABELS
from .model import BlockedError
from .workspace import WORKDIR, remove_workfile, safe_write

REPORT_REL = "reporte.md"
UNGROUPED_ID = "ungrouped"
KIND_ORDER = ["lockfile", "generated", "whitespace", "move", "repeated_replacement"]

__all__ = ["LABELS", "render", "write_report", "resolve_labels"]


def resolve_labels(lang: str, override: Optional[Dict] = None) -> Dict[str, str]:
    labels = dict(LABELS["en"])
    labels.update(LABELS.get(lang, {}))
    labels.update(override or {})
    return labels


def _read(repo: Path, rel: str) -> Dict:
    try:
        data = json.loads((Path(repo) / WORKDIR / rel).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        raise BlockedError("bad_input", "No usable %s/%s; run the earlier steps first."
                           % (WORKDIR, rel))
    return data


def _cite_loc(loc: Dict) -> str:
    if "file" not in loc:
        return str(loc.get("raw", "?"))
    end = loc.get("end")
    span = "%s" % loc.get("start") if end in (None, loc.get("start")) \
        else "%s-%s" % (loc.get("start"), end)
    side = "" if loc.get("side", "new") == "new" else " (old)"
    return "%s:%s%s" % (loc["file"], span, side)


def _cite_line(ch: Dict) -> str:
    side = "" if ch.get("side", "new") == "new" else " (old)"
    return "%s:%s%s" % (ch.get("file"), ch.get("line"), side)


def _rule_ref(rule: Dict) -> str:
    return "%s:%s" % (rule.get("file"), rule.get("line"))


def _mark(ok: bool, text: str, labels: Dict) -> str:
    return text if ok else "%s ⚠ %s" % (text, labels["unverified_citation"])


def _summary(facts: Dict, labels: Dict) -> List[str]:
    t = facts.get("totals", {})
    touched = set()
    for item in list(facts.get("hunks", [])) + list(facts.get("files", [])):
        touched.update(item.get("rules") or [])
    return [
        "- %d %s (+%d / -%d)" % (t.get("files", 0), labels["files"],
                                 t.get("additions", 0), t.get("deletions", 0)),
        "- %d %s, %d %s" % (t.get("logic_lines", 0), labels["logic_lines"],
                            t.get("mechanical_lines", 0), labels["mechanical_lines"]),
        "- %d %s" % (len(touched), labels["rules_touched"]),
    ]


def _rules(verified: Dict, labels: Dict) -> List[str]:
    items = verified.get("rules") or []
    if not items:
        return [labels["no_rules"]]
    out: List[str] = []
    for status in ("complies", "seems_not", "not_applicable"):
        chosen = [i for i in items if i.get("status") == status]
        if not chosen:
            continue
        out += ["### " + labels[status], ""]
        for item in chosen:
            rule = item.get("rule") or {}
            line = "- " + _mark(bool(rule.get("verified")), _rule_ref(rule), labels)
            changes = item.get("changes") or []
            if changes:
                refs = ", ".join(_mark(bool(c.get("verified")), _cite_line(c), labels)
                                 for c in changes)
                line += " → " + refs
            if item.get("note"):
                line += ": " + str(item["note"])
            out.append(line)
        out.append("")
    return out


def _group_files(group: Dict, facts: Dict, hunks: Dict[str, Dict]) -> List[str]:
    per: Dict[str, List[int]] = {}
    for hid in group.get("hunk_ids") or []:
        h = hunks.get(hid)
        if h:
            cell = per.setdefault(h["file"], [0, 0])
            cell[0] += len(h.get("added") or [])
            cell[1] += len(h.get("removed") or [])
    by_path = {f["path"]: f for f in facts.get("files", [])}
    for path in group.get("files") or []:
        f = by_path.get(path, {})
        per.setdefault(path, [f.get("additions", 0), f.get("deletions", 0)])
    return ["- `%s` (+%d / -%d)" % (p, a, d) for p, (a, d) in sorted(per.items())]


def _groups(facts: Dict, verified: Dict, labels: Dict) -> List[str]:
    hunks = {h["id"]: h for h in facts.get("hunks", [])}
    groups = sorted(verified.get("groups") or [], key=lambda g: (g.get("order", 0), g.get("id", "")))
    out: List[str] = []
    for g in groups:
        name = labels["ungrouped"] if g.get("id") == UNGROUPED_ID or not g.get("name") \
            else g["name"]
        out += ["### " + name, ""]
        if g.get("what"):
            out += [str(g["what"]), ""]
        out += _group_files(g, facts, hunks)
        rules = sorted({r for hid in g.get("hunk_ids") or []
                        for r in (hunks.get(hid) or {}).get("rules", [])})
        if rules:
            out.append("- %s: %s" % (labels["rules_label"], ", ".join(rules)))
        if any((hunks.get(hid) or {}).get("changed_since_review")
               for hid in g.get("hunk_ids") or []):
            out.append("- **%s**" % labels["changed_since_review"])
        out.append("")
    return out


def _mechanical(facts: Dict, labels: Dict) -> List[str]:
    kinds: Dict[str, set] = {}
    for h in facts.get("hunks", []):
        if h.get("class") == "mechanical":
            kinds.setdefault(h.get("mechanical_kind") or "whitespace", set()).add(h["file"])
    for f in facts.get("files", []):
        if f.get("class") == "mechanical" and not f.get("hunks"):
            kinds.setdefault(f.get("mechanical_kind") or "whitespace", set()).add(f["path"])
    reps = facts.get("replacements") or []
    if reps:
        kinds.setdefault("repeated_replacement", set())
    out: List[str] = []
    for kind in KIND_ORDER + sorted(k for k in kinds if k not in KIND_ORDER):
        if kind not in kinds:
            continue
        out += ["### " + labels.get("kind_" + kind, kind), ""]
        if kind == "repeated_replacement":
            for rep in reps:
                out.append("- `%s` → `%s` (%d %s)" % (
                    rep["old"], rep["new"], len(rep.get("files") or []), labels["in_files"]))
                for exc in rep.get("exceptions") or []:
                    out.append("  - %s: `%s`" % (labels["exceptions"], exc["file"]))
        else:
            out += ["- `%s`" % p for p in sorted(kinds[kind])]
        out.append("")
    return out


def _unverified(verified: Dict, labels: Dict) -> List[str]:
    out = []
    for item in verified.get("unverified") or []:
        c = item.get("citation") or {}
        if item.get("kind") == "rule":
            ref = _rule_ref(c)
        elif item.get("kind") == "change":
            ref = _cite_line(c)
        else:
            ref = _cite_loc(c)
        out.append("- ⚠ %s: %s (%s)" % (labels["unverified_citation"], ref, item.get("kind")))
    return out


def _provenance(facts: Dict, verified: Dict, labels: Dict) -> List[str]:
    rng = facts.get("range") or {}
    spec = rng.get("spec") or {}
    ex = facts.get("excluded") or {}
    out = ["- %s: %s" % (labels["from"], spec.get("from") or spec.get("commit") or rng.get("old")),
           "- %s: %s" % (labels["to"], rng.get("new") or labels["working_tree"]),
           "- merge-base: %s" % rng.get("old"),
           "- %s: %s" % (labels["excluded_merges"], ", ".join(s[:10] for s in ex.get("merges") or [])
                         or labels["none"]),
           "- %s: %s" % (labels["excluded_authors"], ", ".join(ex.get("authors") or [])
                         or labels["none"])]
    commits = facts.get("commits") or []
    if commits:
        out.append("- %s:" % labels["commits"])
        out += ["  - %s %s" % (c["sha"][:10], c.get("subject", "")) for c in commits]
        if facts.get("commits_truncated"):
            out.append("  - " + labels["commits_truncated"])
    if verified.get("interpreted_in") == "same_conversation":
        out.append("- " + labels["same_conversation"])
    return out


def render(facts: Dict, verified: Dict, labels: Dict) -> str:
    """Fixed order: summary, rules, logic groups, mechanical, unverified, provenance."""
    parts: List[str] = ["# " + labels["title"], ""]

    def section(head: str, body: List[str]) -> None:
        parts.extend(["## " + head, ""] + body + ([""] if body and body[-1] != "" else []))

    section(labels["h_summary"], _summary(facts, labels))
    section(labels["h_rules"], _rules(verified, labels))
    section(labels["h_groups"], _groups(facts, verified, labels))
    mech = _mechanical(facts, labels)
    if mech:
        section(labels["h_mechanical"], mech)
    unv = _unverified(verified, labels)
    if unv:
        section(labels["h_unverified"], unv)
    section(labels["h_provenance"], _provenance(facts, verified, labels))
    return "\n".join(parts).rstrip("\n") + "\n"


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
    text = render(facts, verified, resolve_labels(lang, labels))
    safe_write(repo, REPORT_REL, text)
    branch = current_branch(repo)
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
    return {"ok": True, "path": WORKDIR + "/" + REPORT_REL, "state_path": state_path,
            "notices": notices}
