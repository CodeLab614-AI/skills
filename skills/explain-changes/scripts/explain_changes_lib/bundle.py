"""Isolated input for the interpreter subagent: one batch, nothing else."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from . import rules
from .model import BlockedError


def _load_facts(repo: Path) -> Dict:
    path = Path(repo) / ".explain-changes" / "run" / "facts.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise BlockedError(
            "bad_input", "No usable .explain-changes/run/facts.json; run the facts "
            "subcommand first.")


def bundle(repo: Path, batch: int) -> Dict:
    facts = _load_facts(repo)
    ids = [b["id"] for b in facts.get("batches", [])]
    if batch not in ids:
        raise BlockedError("bad_input", "Batch %s does not exist (available: %s)."
                           % (batch, ids or "none"))
    targets = facts.get("targets") or []
    rule_paths: List[str] = [r["path"] for r in facts.get("rule_files", [])]
    for t in targets:
        if t["rule"]["file"] not in rule_paths:
            rule_paths.append(t["rule"]["file"])
    return {
        "facts_summary": {"range": facts.get("range"), "totals": facts.get("totals"),
                          "batches": facts.get("batches"), "batch": batch,
                          "replacements": facts.get("replacements", []),
                          "notices": facts.get("notices", [])},
        "logic_hunks": [h for h in facts.get("hunks", [])
                        if h.get("batch") == batch and h.get("class") == "logic"],
        "logic_files": [{"path": f["path"], "old_path": f.get("old_path"),
                         "status": f.get("status"), "rules": f.get("rules", []),
                         "was_mechanical": f.get("was_mechanical"),
                         "binary": f.get("binary", False),
                         "too_large": f.get("too_large", False)}
                        for f in facts.get("files", [])
                        if f.get("batch") == batch and f.get("class") == "logic"
                        and not f.get("hunks")],
        "mechanical_summary": [{"file": f["path"], "kind": f["mechanical_kind"]}
                               for f in facts.get("files", [])
                               if f.get("class") == "mechanical"],
        "rules": [{"path": p, "lines": [[n, t] for n, t in
                                         enumerate(rules.read_rule_text(repo, p), start=1)]}
                  for p in rule_paths],
        "targets": targets,
    }
