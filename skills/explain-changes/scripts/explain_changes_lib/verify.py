"""Verification of the interpreter's citations and coverage of logic changes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from .model import BlockedError
from .workspace import safe_write

VERIFIED_REL = "run/verified.json"
UNGROUPED_ID = "ungrouped"


def load_facts(repo: Path) -> Dict:
    path = Path(repo) / ".explain-changes" / "run/facts.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise BlockedError(
            "bad_input", "No usable .explain-changes/run/facts.json; run the facts "
            "subcommand first.")


def parse_interpretation(text: str) -> Dict:
    try:
        interp = json.loads(text)
    except ValueError:
        raise BlockedError("bad_input", "The interpretation is not valid JSON.")
    if not isinstance(interp, dict) or not isinstance(interp.get("groups"), list) \
            or not all(isinstance(g, dict) for g in interp["groups"]):
        raise BlockedError("bad_input", "The interpretation must be an object with a "
                           "'groups' list.")
    if not isinstance(interp.get("rules", []), list):
        raise BlockedError("bad_input", "'rules' must be a list.")
    return interp


def _int(value) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _hunk_range(hunk: Dict, side: str):
    if side == "old":
        return hunk["old_start"], hunk["old_start"] + max(hunk["old_lines"], 1) - 1
    return hunk["new_start"], hunk["new_start"] + max(hunk["new_lines"], 1) - 1


class _Index:
    def __init__(self, facts: Dict) -> None:
        self.hunks_by_file: Dict[str, List[Dict]] = {}
        for h in facts.get("hunks", []):
            self.hunks_by_file.setdefault(h["file"], []).append(h)
        self.rule_lines = {r["path"]: r.get("line_count", 0)
                           for r in facts.get("rule_files", [])}
        # Alias (new or old path) -> canonical new path.
        self.alias: Dict[str, str] = {}
        self.hunkless: Dict[str, str] = {}  # alias -> path, logic files without hunks
        for f in facts.get("files", []):
            self.alias[f["path"]] = f["path"]
            if f.get("old_path"):
                self.alias.setdefault(f["old_path"], f["path"])
            if f.get("class") == "logic" and not f.get("hunks"):
                self.hunkless[f["path"]] = f["path"]
                if f.get("old_path"):
                    self.hunkless.setdefault(f["old_path"], f["path"])

    def match(self, file, start: int, end: int, side: str):
        """Return (valid, hunk ids hit, hunkless path or None)."""
        canon = self.alias.get(file, file)
        hits = []
        for h in self.hunks_by_file.get(canon, []):
            lo, hi = _hunk_range(h, side)
            if start <= hi and end >= lo:
                hits.append(h)
        if hits:
            return True, hits, None
        if file in self.hunkless:
            return True, [], self.hunkless[file]
        return False, [], None


def _check_location(idx: _Index, loc: Dict):
    start, end = _int(loc.get("start")), _int(loc.get("end"))
    side = loc.get("side", "new")
    file = loc.get("file")
    if side not in ("new", "old") or not isinstance(file, str) \
            or start is None or end is None or start > end:
        return False, [], None
    return idx.match(file, start, end, side)


def _check_line(idx: _Index, cite: Dict):
    line = _int(cite.get("line"))
    side = cite.get("side", "new")
    file = cite.get("file")
    if side not in ("new", "old") or not isinstance(file, str) or line is None:
        return False
    return idx.match(file, line, line, side)[0]


def _check_rule(idx: _Index, rule: Dict) -> bool:
    file, line = rule.get("file"), _int(rule.get("line"))
    if not isinstance(file, str) or line is None or file not in idx.rule_lines:
        return False
    return 1 <= line <= idx.rule_lines[file]


def verify(repo: Path, facts: Dict, interp: Dict) -> Dict:
    idx = _Index(facts)
    logic_ids = [h["id"] for h in facts.get("hunks", []) if h.get("class") == "logic"]
    logic_set = set(logic_ids)
    covered_hunks = set()
    covered_files = set()
    unverified: List[Dict] = []
    groups: List[Dict] = []

    for group in interp.get("groups", []):
        g = dict(group)
        ids: List[str] = []
        locs = []
        for loc in group.get("locations") or []:
            ok, hits, path = _check_location(idx, loc if isinstance(loc, dict) else {})
            loc = dict(loc) if isinstance(loc, dict) else {"raw": loc}
            loc["verified"] = ok
            locs.append(loc)
            if not ok:
                unverified.append({"kind": "location", "group": group.get("id"),
                                   "citation": {k: v for k, v in loc.items()
                                                if k != "verified"}})
            for h in hits:
                if h["id"] in logic_set:
                    covered_hunks.add(h["id"])
                    if h["id"] not in ids:
                        ids.append(h["id"])
            if path:
                covered_files.add(path)
        g["locations"] = locs
        g["hunk_ids"] = ids
        groups.append(g)

    rules = []
    for item in interp.get("rules", []):
        item = dict(item) if isinstance(item, dict) else {}
        rule = dict(item.get("rule") or {})
        rule["verified"] = _check_rule(idx, rule)
        if not rule["verified"]:
            unverified.append({"kind": "rule", "citation": {
                k: v for k, v in rule.items() if k != "verified"}})
        changes = []
        for ch in item.get("changes") or []:
            ch = dict(ch) if isinstance(ch, dict) else {}
            ch["verified"] = _check_line(idx, ch)
            if not ch["verified"]:
                unverified.append({"kind": "change", "citation": {
                    k: v for k, v in ch.items() if k != "verified"}})
            changes.append(ch)
        item["rule"], item["changes"] = rule, changes
        item["verified"] = rule["verified"]
        rules.append(item)

    missing_hunks = [i for i in logic_ids if i not in covered_hunks]
    missing_files = [f["path"] for f in facts.get("files", [])
                     if f.get("class") == "logic" and not f.get("hunks")
                     and f["path"] not in covered_files]
    if missing_hunks or missing_files:
        groups.append({"id": UNGROUPED_ID, "name": None, "what": "", "order": 999,
                       "locations": [], "hunk_ids": missing_hunks,
                       "files": missing_files})

    out = dict(interp)
    out["groups"], out["rules"], out["unverified"] = groups, rules, unverified
    return out


def write_verified(repo: Path, result: Dict) -> str:
    safe_write(repo, VERIFIED_REL, json.dumps(result, indent=2, ensure_ascii=False))
    return ".explain-changes/" + VERIFIED_REL


def summary(path: str, result: Dict) -> Dict:
    ung = [g for g in result["groups"] if g["id"] == UNGROUPED_ID]
    count = (len(ung[0]["hunk_ids"]) + len(ung[0].get("files", []))) if ung else 0
    return {"ok": True, "path": path, "unverified_count": len(result["unverified"]),
            "ungrouped_count": count}
