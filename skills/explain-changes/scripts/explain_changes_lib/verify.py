"""Verification of the interpreter's output: files, rule citations and code comments."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from . import rules as rules_mod
from .model import BlockedError
from .workspace import safe_write

VERIFIED_REL = "run/verified.json"
UNEXPLAINED = "unexplained"
REST_KINDS = ["tests", "stories", "docs", "exports", "cleanup", "other", "mechanical"]
POSITIONS = ("before", "after")
# Imports and re-exports never get an explanatory comment.
IMPORT_RE = re.compile(r"^\s*(import\b|export\b.*\bfrom\b|from\s+\S+\s+import\b)")


def load_facts(repo: Path) -> Dict:
    path = Path(repo) / ".explain-changes" / "run/facts.json"
    try:
        facts = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        facts = None
    if not isinstance(facts, dict):
        raise BlockedError(
            "bad_input", "No usable .explain-changes/run/facts.json; run the facts "
            "subcommand first.")
    return facts


def _bad(where: str, what: str):
    raise BlockedError("bad_input", "Invalid interpretation at %s: %s." % (where, what))


def _dict_list(value, where: str) -> List[Dict]:
    if not isinstance(value, list):
        _bad(where, "expected a list")
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            _bad("%s[%d]" % (where, i), "expected an object")
    return value


def _text(item: Dict, key: str, where: str, required: bool = True) -> str:
    value = item.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        _bad("%s.%s" % (where, key),
             "expected a non-empty string" if required else "expected a string")
    return value


def _str_list(value, where: str) -> List[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        _bad(where, "expected a list of strings")
    return value


def _table(value, where: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        _bad(where, "expected an object with head and rows")
    _str_list(value.get("head"), where + ".head")
    rows = value.get("rows")
    if not isinstance(rows, list):
        _bad(where + ".rows", "expected a list of rows")
    for i, row in enumerate(rows):
        _str_list(row, "%s.rows[%d]" % (where, i))


def parse_interpretation(text: str) -> Dict:
    try:
        interp = json.loads(text)
    except ValueError:
        raise BlockedError("bad_input", "The interpretation is not valid JSON.")
    if not isinstance(interp, dict):
        _bad("root", "expected an object")
    for i, point in enumerate(_dict_list(interp.get("points"), "points")):
        where = "points[%d]" % i
        _text(point, "title", where)
        _text(point, "line", where, required=False)
        _text(point, "more", where, required=False)
        _table(point.get("table"), where + ".table")
        _str_list(point.get("files", []), where + ".files")
    rest = interp.get("rest", {})
    if not isinstance(rest, dict):
        _bad("rest", "expected an object")
    _text(rest, "line", "rest", required=False)
    for i, group in enumerate(_dict_list(rest.get("groups", []), "rest.groups")):
        _text(group, "kind", "rest.groups[%d]" % i)
        _str_list(group.get("files", []), "rest.groups[%d].files" % i)
    for i, warn in enumerate(_dict_list(interp.get("warnings", []), "warnings")):
        where = "warnings[%d]" % i
        _text(warn, "name", where, required=False)
        _text(warn, "says", where)
        _text(warn, "change", where)
        if not isinstance(warn.get("rule"), dict):
            _bad(where + ".rule", "expected an object")
        _dict_list(warn.get("changes", []), where + ".changes")
    _dict_list(interp.get("comments", []), "comments")
    return interp


def _int(value) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


class _Index:
    def __init__(self, facts: Dict) -> None:
        self.hunks_by_file: Dict[str, List[Dict]] = {}
        for h in facts.get("hunks", []):
            self.hunks_by_file.setdefault(h["file"], []).append(h)
        self.rule_lines = {r["path"]: r.get("line_count", 0)
                           for r in facts.get("rule_files", [])}
        self.files = {f["path"]: f for f in facts.get("files", [])}
        # Side -> path as written in that version -> canonical (new) path.
        self.alias: Dict[str, Dict[str, str]] = {"new": {}, "old": {}}
        for f in facts.get("files", []):
            self.alias["new"][f["path"]] = f["path"]
            self.alias["old"].setdefault(f.get("old_path") or f["path"], f["path"])

    def canon(self, path) -> Optional[str]:
        """Canonical path for a file named without a side (either version)."""
        if not isinstance(path, str):
            return None
        return self.alias["new"].get(path) or self.alias["old"].get(path)

    def line_text(self, path, side: str, line: int) -> Optional[str]:
        """The text of a changed line, or None when that line is not in the diff."""
        if side not in ("new", "old") or not isinstance(path, str):
            return None
        canon = self.alias[side].get(path)
        for h in self.hunks_by_file.get(canon, []):
            lines, start = ((h["removed"], h["old_start"]) if side == "old"
                            else (h["added"], h["new_start"]))
            if 0 <= line - start < len(lines):
                return lines[line - start]
        return None


def _rule_ok(idx: _Index, rule: Dict) -> bool:
    file, line = rule.get("file"), _int(rule.get("line"))
    if not isinstance(file, str) or line is None or file not in idx.rule_lines:
        return False
    return 1 <= line <= idx.rule_lines[file]


def _check_change(idx: _Index, change: Dict) -> bool:
    line = _int(change.get("line"))
    return line is not None and idx.line_text(
        change.get("file"), change.get("side", "new"), line) is not None


def _guard_target_ids(facts: Dict, warn: Dict, where: str) -> None:
    """Internal target ids (R1...) must never reach the user."""
    ids = [t.get("id") for t in facts.get("targets") or [] if isinstance(t.get("id"), str)]
    for key in ("name", "says", "change"):
        text = warn.get(key) or ""
        for tid in ids:
            if tid and re.search(r"(?<![\w])%s(?![\w])" % re.escape(tid), text):
                _bad("%s.%s" % (where, key),
                     "it mentions the internal id %s; name the rule by its folder or file "
                     "name instead" % tid)


def _points(idx: _Index, interp: Dict, unverified: List[Dict]):
    out: List[Dict] = []
    placed = set()
    order = {id(p): n for n, p in enumerate(interp.get("points", []))}
    ranked = sorted(interp.get("points", []),
                    key=lambda p: (_int(p.get("order")) if _int(p.get("order")) is not None
                                   else 10 ** 6, order[id(p)]))
    for n, point in enumerate(ranked, start=1):
        files: List[Dict] = []
        seen = set()
        for raw in point.get("files") or []:
            canon = idx.canon(raw)
            if canon is None:
                files.append({"path": raw, "verified": False})
                unverified.append({"kind": "file", "citation": {"file": raw}})
            elif canon not in seen:
                seen.add(canon)
                placed.add(canon)
                files.append({"path": canon, "verified": True})
        out.append({"id": "p%d" % n, "order": n, "title": point["title"],
                    "line": point.get("line") or "", "more": point.get("more") or "",
                    "table": point.get("table"), "files": files})
    return out, placed


def _rest(idx: _Index, interp: Dict, placed: set, unverified: List[Dict]) -> Dict:
    groups: Dict[str, List[Dict]] = {}
    taken = set(placed)

    def add(kind: str, path: str) -> None:
        taken.add(path)
        f = idx.files[path]
        groups.setdefault(kind, []).append({
            "path": path, "verified": True,
            "mechanical_kind": f.get("mechanical_kind") if f.get("class") == "mechanical"
            else None})

    for group in (interp.get("rest") or {}).get("groups") or []:
        kind = group["kind"] if group["kind"] in REST_KINDS else "other"
        for raw in group.get("files") or []:
            canon = idx.canon(raw)
            if canon is None:
                groups.setdefault(kind, []).append({"path": raw, "verified": False})
                unverified.append({"kind": "file", "citation": {"file": raw}})
            elif canon not in taken:
                add(kind, canon)
    for path, f in idx.files.items():
        if path not in taken and f.get("class") == "mechanical":
            add("mechanical", path)
    for path, f in idx.files.items():
        if path not in taken:
            add(UNEXPLAINED, path)
    ordered = [{"kind": k, "files": groups[k]}
               for k in REST_KINDS + [UNEXPLAINED] if k in groups]
    return {"line": (interp.get("rest") or {}).get("line") or "", "groups": ordered}


def _warnings(repo: Path, facts: Dict, idx: _Index, interp: Dict,
              unverified: List[Dict]) -> List[Dict]:
    out: List[Dict] = []
    for n, warn in enumerate(interp.get("warnings") or []):
        _guard_target_ids(facts, warn, "warnings[%d]" % n)
        rule = {"file": warn["rule"].get("file"), "line": warn["rule"].get("line")}
        rule["verified"] = _rule_ok(idx, rule)
        rule["text"] = ""
        if rule["verified"]:
            lines = rules_mod.read_rule_text(repo, rule["file"])
            rule["text"] = lines[rule["line"] - 1].strip() if rule["line"] <= len(lines) else ""
        else:
            unverified.append({"kind": "rule", "citation": {
                "file": rule["file"], "line": rule["line"]}})
        changes = []
        for ch in warn.get("changes") or []:
            item = {"file": ch.get("file"), "line": ch.get("line"),
                    "side": ch.get("side", "new")}
            item["verified"] = _check_change(idx, item)
            if not item["verified"]:
                unverified.append({"kind": "change", "citation": {
                    k: v for k, v in item.items() if k != "verified"}})
            changes.append(item)
        out.append({"name": (warn.get("name") or "").strip()
                    or rules_mod.rule_name(str(rule["file"])),
                    "says": warn["says"], "change": warn["change"],
                    "rule": rule, "changes": changes,
                    "verified": rule["verified"] and all(c["verified"] for c in changes)})
    return out


def _comments(idx: _Index, interp: Dict, point_files: set, dropped: List[Dict]) -> List[Dict]:
    kept: List[Dict] = []
    seen = set()
    for raw in interp.get("comments") or []:
        side = raw.get("side", "new")
        pos = raw.get("pos", "before")
        line, text = _int(raw.get("line")), raw.get("text")
        canon = idx.alias.get(side, {}).get(raw.get("file")) if side in ("new", "old") else None
        code = idx.line_text(raw.get("file"), side, line) if line is not None else None
        key = (canon, side, line, pos)
        ok = (canon in point_files and code is not None and pos in POSITIONS
              and isinstance(text, str) and text.strip() and key not in seen
              and not IMPORT_RE.match(code))
        if not ok:
            dropped.append({"kind": "comment", "citation": {
                "file": raw.get("file"), "side": side, "line": raw.get("line")}})
            continue
        seen.add(key)
        kept.append({"file": canon, "side": side, "line": line, "pos": pos,
                     "text": text.strip()})
    return kept


def verify(repo: Path, facts: Dict, interp: Dict) -> Dict:
    idx = _Index(facts)
    unverified: List[Dict] = []
    dropped: List[Dict] = []
    points, placed = _points(idx, interp, unverified)
    rest = _rest(idx, interp, placed, unverified)
    warnings = _warnings(Path(repo), facts, idx, interp, unverified)
    comments = _comments(idx, interp, placed, dropped)
    out = {"points": points, "rest": rest, "warnings": warnings, "comments": comments,
           "unverified": unverified, "dropped": dropped}
    if "interpreted_in" in interp:
        out["interpreted_in"] = interp["interpreted_in"]
    return out


def write_verified(repo: Path, result: Dict) -> str:
    safe_write(repo, VERIFIED_REL, json.dumps(result, indent=2, ensure_ascii=False))
    return ".explain-changes/" + VERIFIED_REL


def summary(path: str, result: Dict) -> Dict:
    unexplained = [g for g in result["rest"]["groups"] if g["kind"] == UNEXPLAINED]
    return {"ok": True, "path": path, "unverified_count": len(result["unverified"]),
            "unexplained_count": len(unexplained[0]["files"]) if unexplained else 0,
            "dropped_comments": len(result["dropped"])}
