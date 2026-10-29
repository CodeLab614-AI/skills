"""Worker models per agent, kept in <home>/config.md (the person may edit it)."""
from __future__ import annotations

from . import frontmatter, store
from .errors import BlockedError

CODEX_DOC = "https://learn.chatgpt.com/docs/agent-configuration/subagents"

DEFAULT_AGENTS = {
    "claude-code": {"consult": "haiku", "support": "haiku", "grading": "sonnet", "grading_effort": "medium"},
    "codex": {"consult": "gpt-6-luna", "support": "gpt-6-luna"},
    "cursor": {},
    "opencode": {},
    "antigravity": {},
}

_FIELDS = ("consult", "support", "grading", "grading_effort")

_STATUS = {
    "claude-code": "tested",
    "codex": "not verified (consult and support from %s; grading left empty)" % CODEX_DOC,
    "cursor": "not verified",
    "opencode": "not verified",
    "antigravity": "not verified",
}


def _path():
    return store.home() / "config.md"


def _cell(value) -> str:
    return str(value) if value else "-"


def _body() -> str:
    lines = [
        "# teach-me worker models",
        "",
        "Each worker runs as a subagent with the model of the row for the agent in use.",
        "",
        "- consult: answers the person's doubts from the dossier.",
        "- support: checks each claim against its excerpt.",
        "- grading: grades the exams (effort = reasoning effort).",
        "",
        "| agent | consult | support | grading | effort | status |",
        "|---|---|---|---|---|---|",
    ]
    for name, row in DEFAULT_AGENTS.items():
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            name, _cell(row.get("consult")), _cell(row.get("support")),
            _cell(row.get("grading")), _cell(row.get("grading_effort")), _STATUS[name]))
    lines += [
        "",
        "You may edit the values in the front matter at the top of this file; your edits are kept.",
        "An empty row (`{}`) or a missing agent means the work is done in the same conversation.",
        "",
    ]
    return "\n".join(lines)


def load() -> dict:
    path = _path()
    if not path.exists():
        meta = {"teach_me": "config", "agents": {k: dict(v) for k, v in DEFAULT_AGENTS.items()}}
        store.atomic_write(path, frontmatter.dump(meta, _body()))
        return meta
    try:
        meta, _ = frontmatter.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        meta = {}
    if not isinstance(meta.get("agents"), dict):
        raise BlockedError("bad_input", "Cannot read the worker models file: %s. Fix or delete it." % path)
    return meta


def for_agent(agent: str) -> dict:
    agents = load()["agents"]
    key = str(agent).strip().lower()
    row = {}
    for name, value in agents.items():
        if str(name).lower() == key and isinstance(value, dict):
            row = value
            break
    out = {"agent": key}
    for f in _FIELDS:
        v = row.get(f)
        out[f] = v if v else None
    out["same_conversation"] = not any(
        isinstance(row.get(f), str) and row.get(f).strip() for f in ("consult", "support", "grading"))
    return out
