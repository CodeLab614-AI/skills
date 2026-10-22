"""Orchestrates ``facts``: ranges -> parse -> subtract -> pipeline -> write."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import mechanical, ranges, replacements, rules
from .diffparse import diff_files, untracked_files
from .model import FileChange, Hunk
from .ranges import RangeSpec
from .workspace import cleanup_previous, safe_write

FACTS_REL = "run/facts.json"
FACTS_PATH = ".explain-changes/" + FACTS_REL


class FactsContext:
    """Mutable state shared by the pipeline steps."""

    def __init__(self, repo: Path, spec: RangeSpec, targets: Optional[List[Dict]],
                 only_new: bool, files: List[FileChange], hunks: List[Hunk]) -> None:
        self.repo, self.spec, self.targets, self.only_new = repo, spec, targets, only_new
        self.files, self.hunks = files, hunks
        self.batches: List[Dict] = []
        self.notices: List[Dict] = []
        self.replacements: List[Dict] = []


Step = Callable[[FactsContext], None]


def classify(ctx: FactsContext) -> None:
    """Mechanical vs logic (lockfile, generated, whitespace, pure move)."""
    mechanical.classify(ctx.repo, ctx.files, ctx.hunks)


def repeated_replacements(ctx: FactsContext) -> None:
    """Token replacements repeated across files; pure hunks become mechanical."""
    ctx.replacements = replacements.find_repeated_replacements(ctx.hunks)
    marked = {id(h) for h in ctx.hunks if h.mechanical_kind == replacements.KIND}
    for fc in ctx.files:
        if any(id(h) in marked for h in fc.hunks):
            mechanical.refresh_file_class(fc)


def targets_and_batches(ctx: FactsContext) -> None:
    """Task 9: rule targets and batches. No-op until then."""


def review_state(ctx: FactsContext) -> None:
    """Task 11: per-branch state and --only-new. No-op until then."""


PIPELINE: List[Step] = [classify, repeated_replacements, targets_and_batches, review_state]


def compute_totals(files: List[FileChange], hunks: List[Hunk]) -> Dict[str, int]:
    logic = sum(len(h.removed) + len(h.added) for h in hunks if h.klass == "logic")
    mech = sum(len(h.removed) + len(h.added) for h in hunks if h.klass != "logic")
    return {"files": len(files),
            "additions": sum(f.additions for f in files),
            "deletions": sum(f.deletions for f in files),
            "logic_lines": logic, "mechanical_lines": mech}


def _apply_subtraction(ctx: FactsContext, foreign: ranges.ForeignLines) -> List[str]:
    kept, dropped = ranges.subtract(ctx.hunks, foreign)
    if not dropped:
        return dropped
    keep_ids = {id(h) for h in kept}
    survivors: List[FileChange] = []
    for fc in ctx.files:
        if not fc.hunks:
            survivors.append(fc)
            continue
        fc.hunks = [h for h in fc.hunks if id(h) in keep_ids]
        if not fc.hunks:
            continue  # every hunk was foreign: the file is not the user's change
        fc.additions = sum(len(h.added) for h in fc.hunks)
        fc.deletions = sum(len(h.removed) for h in fc.hunks)
        survivors.append(fc)
    ctx.files, ctx.hunks = survivors, kept
    return dropped


def collect_facts(repo: Path, spec: RangeSpec, targets: Optional[List[Dict]] = None,
                  only_new: bool = False) -> Dict:
    repo = Path(repo)
    spec = ranges.normalize_spec(repo, spec)
    old, new = ranges.resolve_range(repo, spec)
    files = diff_files(repo, old, new)
    if new is None:
        tracked = {f.path for f in files}
        files += [f for f in untracked_files(repo) if f.path not in tracked]
    hunks = [h for f in files for h in f.hunks]
    ctx = FactsContext(repo, spec, targets, only_new, files, hunks)

    foreign = ranges.foreign_lines(repo, spec, old, new)
    dropped = _apply_subtraction(ctx, foreign)
    merges = ranges.merges_in_range(repo, spec, old, new)
    ranges.mark_resolved_in_merge(repo, ctx.hunks, merges)
    excluded_merges = ranges.excluded_merges(repo, spec, old, new)

    for step in PIPELINE:
        step(ctx)

    facts = {
        "ok": True,
        "range": {"old": old, "new": new, "spec": spec.to_json()},
        "files": [f.to_json() for f in ctx.files],
        "hunks": [h.to_json() for h in ctx.hunks],
        "excluded": {"merges": excluded_merges,
                     "authors": list(spec.exclude_authors),
                     "dropped_hunks": dropped},
        "rule_files": rules.find_rule_files(repo, [f.path for f in ctx.files]),
        "replacements": ctx.replacements,
        "batches": ctx.batches,
        "totals": compute_totals(ctx.files, ctx.hunks),
        "notices": ctx.notices,
    }
    cleanup_previous(repo)
    safe_write(repo, FACTS_REL, json.dumps(facts, ensure_ascii=False, indent=1))
    facts["path"] = FACTS_PATH
    return facts


def summary(facts: Dict) -> Dict:
    return {"ok": True, "path": facts["path"], "totals": facts["totals"],
            "batches": facts["batches"], "notices": facts["notices"]}
