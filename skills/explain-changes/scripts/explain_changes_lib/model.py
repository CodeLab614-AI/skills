from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional


class BlockedError(Exception):
    """An expected block; the CLI reports it with exit code 2."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def hunk_fingerprint(path: str, removed: List[str], added: List[str]) -> str:
    """sha1 of ``file \\0 -removed \\0 +added`` (shared contract)."""
    payload = (path + "\0" + "\n".join("-" + x for x in removed)
               + "\0" + "\n".join("+" + x for x in added))
    return hashlib.sha1(payload.encode("utf-8", "surrogateescape")).hexdigest()


@dataclass
class Hunk:
    file: str
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    removed: List[str]
    added: List[str]
    intraline: List[Dict] = field(default_factory=list)
    fingerprint: str = ""
    klass: str = "logic"
    mechanical_kind: Optional[str] = None
    resolved_in_merge: List[int] = field(default_factory=list)
    rules: List[str] = field(default_factory=list)
    batch: Optional[int] = None
    seen: bool = False
    changed_since_review: bool = False
    was_mechanical: Optional[str] = None
    # Set by the parser when the same change repeats inside one file.
    id_override: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.fingerprint:
            self.fingerprint = hunk_fingerprint(self.file, self.removed, self.added)

    @property
    def id(self) -> str:
        return self.id_override or "h-" + self.fingerprint[:12]

    def to_json(self) -> Dict:
        return {
            "id": self.id, "file": self.file,
            "old_start": self.old_start, "old_lines": self.old_lines,
            "new_start": self.new_start, "new_lines": self.new_lines,
            "removed": list(self.removed), "added": list(self.added),
            "intraline": [dict(i) for i in self.intraline],
            "fingerprint": self.fingerprint,
            "class": self.klass, "mechanical_kind": self.mechanical_kind,
            "resolved_in_merge": list(self.resolved_in_merge),
            "rules": list(self.rules), "batch": self.batch,
            "seen": self.seen, "changed_since_review": self.changed_since_review,
            "was_mechanical": self.was_mechanical,
        }


@dataclass
class FileChange:
    path: str
    status: str
    old_path: Optional[str] = None
    similarity: Optional[int] = None
    additions: int = 0
    deletions: int = 0
    old_mode: Optional[str] = None
    new_mode: Optional[str] = None
    binary: bool = False
    old_blob: Optional[str] = None
    new_blob: Optional[str] = None
    eol_only: bool = False
    encoding_issue: bool = False
    too_large: bool = False
    submodule: Optional[Dict] = None
    hunks: List[Hunk] = field(default_factory=list)
    klass: str = "logic"
    mechanical_kind: Optional[str] = None
    rules: List[str] = field(default_factory=list)
    was_mechanical: Optional[str] = None
    batch: Optional[int] = None

    def to_json(self) -> Dict:
        return {
            "path": self.path, "old_path": self.old_path, "status": self.status,
            "similarity": self.similarity,
            "additions": self.additions, "deletions": self.deletions,
            "old_mode": self.old_mode, "new_mode": self.new_mode,
            "binary": self.binary, "old_blob": self.old_blob,
            "new_blob": self.new_blob, "eol_only": self.eol_only,
            "encoding_issue": self.encoding_issue, "too_large": self.too_large,
            "submodule": dict(self.submodule) if self.submodule else None,
            "hunks": [h.id for h in self.hunks],
            "class": self.klass, "mechanical_kind": self.mechanical_kind,
            "rules": list(self.rules), "was_mechanical": self.was_mechanical,
            "batch": self.batch,
        }


@dataclass
class Target:
    """A rule target supplied by the agent: where a rule applies."""
    id: str
    rule_file: str
    rule_line: int
    paths: List[str] = field(default_factory=list)
    change_kinds: List[str] = field(default_factory=list)
    line_pattern: Optional[str] = None

    def to_json(self) -> Dict:
        return {
            "id": self.id,
            "rule": {"file": self.rule_file, "line": self.rule_line},
            "paths": list(self.paths), "change_kinds": list(self.change_kinds),
            "line_pattern": self.line_pattern,
        }
