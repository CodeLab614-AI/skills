"""Rule targets: parse, glob matching, and lifting matched hunks to logic."""
from __future__ import annotations

import fnmatch
import json
import re
from typing import List, Set

from . import mechanical
from .model import BlockedError, FileChange, Hunk, Target

KINDS = ("add", "modify", "delete", "rename", "mode", "add_dependency")
DEPENDENCY_FILES = ("package.json", "requirements*.txt", "pyproject.toml",
                    "Cargo.toml", "go.mod", "Gemfile", "composer.json")


def _bad(message: str) -> BlockedError:
    return BlockedError("bad_input", "Invalid targets: " + message)


def glob_to_regex(pattern: str) -> "re.Pattern[str]":
    """``**`` crosses folders, ``*`` and ``?`` do not."""
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("".join(out) + r"\Z", re.DOTALL)


def parse_targets(data: object) -> List[Target]:
    if not isinstance(data, list):
        raise _bad("expected a JSON list")
    targets: List[Target] = []
    for i, raw in enumerate(data):
        where = "item %d" % i
        if not isinstance(raw, dict):
            raise _bad(where + " is not an object")
        tid, rule = raw.get("id"), raw.get("rule")
        if not isinstance(tid, str) or not tid:
            raise _bad(where + ": id must be a non-empty string")
        if (not isinstance(rule, dict) or not isinstance(rule.get("file"), str)
                or not isinstance(rule.get("line"), int)
                or isinstance(rule.get("line"), bool)):
            raise _bad(where + ": rule must be {file: str, line: int}")
        paths = raw.get("paths", [])
        kinds = raw.get("change_kinds", [])
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise _bad(where + ": paths must be a list of strings")
        if not isinstance(kinds, list) or any(k not in KINDS for k in kinds):
            raise _bad(where + ": change_kinds must be a list of %s" % ", ".join(KINDS))
        pattern = raw.get("line_pattern")
        if pattern is not None:
            if not isinstance(pattern, str):
                raise _bad(where + ": line_pattern must be a string or null")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise _bad(where + ": line_pattern is not a valid regex (%s)" % exc)
        targets.append(Target(id=tid, rule_file=rule["file"], rule_line=rule["line"],
                              paths=list(paths), change_kinds=list(kinds),
                              line_pattern=pattern))
    return targets


def load_targets(text: str) -> List[Target]:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise _bad("not valid JSON (%s)" % exc)
    return parse_targets(data)


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def hunk_kinds(fc: FileChange, hunk: Hunk) -> Set[str]:
    kinds: Set[str] = set()
    if fc.status in ("added", "untracked"):
        kinds.add("add")
    if fc.status == "deleted" or (hunk.removed and not hunk.added):
        kinds.add("delete")
    if fc.status in ("modified", "renamed"):
        kinds.add("modify")
    if fc.status == "renamed":
        kinds.add("rename")
    if fc.old_mode != fc.new_mode and fc.old_mode and fc.new_mode:
        kinds.add("mode")
    name = _basename(fc.path)
    if hunk.added and any(fnmatch.fnmatchcase(name, p) for p in DEPENDENCY_FILES):
        kinds.add("add_dependency")
    return kinds


def file_kinds(fc: FileChange) -> Set[str]:
    kinds: Set[str] = set()
    if fc.status in ("added", "untracked"):
        kinds.add("add")
    if fc.status == "deleted":
        kinds.add("delete")
    if fc.status == "renamed":
        kinds.add("rename")
    if fc.old_mode != fc.new_mode and fc.old_mode and fc.new_mode:
        kinds.add("mode")
    return kinds


def _path_ok(regexes, fc: FileChange) -> bool:
    if not regexes:
        return True
    paths = [fc.path] + ([fc.old_path] if fc.old_path else [])
    return any(r.match(p) for r in regexes for p in paths)


def _matches(target: Target, regexes, pattern, fc: FileChange, hunk: Hunk) -> bool:
    if not _path_ok(regexes, fc):
        return False
    if target.change_kinds and not (set(target.change_kinds) & hunk_kinds(fc, hunk)):
        return False
    if pattern is not None:
        if not any(pattern.search(line) for line in hunk.added + hunk.removed):
            return False
    return True


def _lift_hunkless(fc: FileChange, targets: List[Target], compiled) -> None:
    """Files without hunks (pure rename, mode, binary) are matched by file kind."""
    kinds = file_kinds(fc)
    for target, (regexes, pattern) in zip(targets, compiled):
        if pattern is not None or not _path_ok(regexes, fc):
            continue
        if target.change_kinds and not (set(target.change_kinds) & kinds):
            continue
        if target.id not in fc.rules:
            fc.rules.append(target.id)
        if fc.klass != "logic":
            fc.was_mechanical = fc.was_mechanical or fc.mechanical_kind
        fc.klass, fc.mechanical_kind = "logic", None


def apply_targets(files: List[FileChange], hunks: List[Hunk],
                  targets: List[Target]) -> None:
    """Matched hunks become logic (even mechanical ones) and record the rule id."""
    compiled = [([glob_to_regex(p) for p in t.paths],
                 re.compile(t.line_pattern) if t.line_pattern is not None else None)
                for t in targets]
    touched: List[FileChange] = []
    for fc in files:
        if not fc.hunks:
            _lift_hunkless(fc, targets, compiled)
            continue
        hit = False
        for hunk in fc.hunks:
            for target, (regexes, pattern) in zip(targets, compiled):
                if not _matches(target, regexes, pattern, fc, hunk):
                    continue
                if target.id not in hunk.rules:
                    hunk.rules.append(target.id)
                if hunk.klass != "logic":
                    hunk.was_mechanical = hunk.was_mechanical or hunk.mechanical_kind
                    hunk.klass, hunk.mechanical_kind = "logic", None
                hit = True
        if hit:
            touched.append(fc)
    for fc in files:
        if fc.hunks:
            fc.rules = sorted(set(fc.rules) | {r for h in fc.hunks for r in h.rules})
    for fc in touched:
        if any(h.klass == "logic" for h in fc.hunks):
            fc.klass, fc.mechanical_kind = "logic", None
        else:
            mechanical.refresh_file_class(fc)
