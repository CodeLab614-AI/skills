"""Progress file: per-topic status by slug (spec 7.4, 11). Helpers here do NOT take the lock."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import dossier, frontmatter, sources, store

_LABELS = {
    "es": {"title": "Avance", "topic": "Tema", "status": "Estado", "best": "Mejor nota",
           "attempts": "Intentos", "pending": "Pendientes", "skipped": "Saltados",
           "none": "(ninguno)"},
    "en": {"title": "Progress", "topic": "Topic", "status": "Status", "best": "Best score",
           "attempts": "Attempts", "pending": "Pending", "skipped": "Skipped",
           "none": "(none)"},
}


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _path(folder: Path, meta: dict) -> Path:
    return folder / meta["names"]["progress"]


def _blank() -> dict:
    return {"teach_me": "progress", "current": None, "last_session": None,
            "topics": {}, "reviews": []}


def load(folder: Path, meta: dict) -> dict:
    """Read the progress header; a missing or unreadable file gives a blank one."""
    try:
        head, _ = frontmatter.parse(_path(folder, meta).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        head = {}
    out = _blank()
    if head.get("teach_me") == "progress":
        out.update({k: head[k] for k in ("current", "last_session", "topics", "reviews")
                    if k in head})
    if not isinstance(out["topics"], dict):
        out["topics"] = {}
    if not isinstance(out["reviews"], list):
        out["reviews"] = []
    return out


def entry(head: dict, slug: str) -> dict:
    topics = head["topics"]
    if slug not in topics:
        topics[slug] = {"status": "not_started", "best": None, "attempts": [],
                        "doubts": [], "outdated": False, "asked": []}
    return topics[slug]


def _title(folder: Path, meta: dict, slug: str) -> str:
    syl, _ = _read(folder / meta["names"]["syllabus"])
    for t in syl.get("topics") or []:
        if t.get("slug") == slug:
            return t.get("title", slug)
    return slug


def _read(path: Path) -> "tuple[dict, str]":
    try:
        return frontmatter.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {}, ""


def _body(folder: Path, meta: dict, head: dict) -> str:
    lab = _LABELS.get(meta.get("lang"), _LABELS["en"])
    lines = ["# %s" % lab["title"], "",
             "| %s | %s | %s | %s |" % (lab["topic"], lab["status"], lab["best"], lab["attempts"]),
             "|---|---|---|---|"]
    for slug, t in head["topics"].items():
        best = "-" if t.get("best") is None else "%s%%" % t["best"]
        lines.append("| %s | %s | %s | %d |" % (_title(folder, meta, slug), t.get("status"),
                                               best, len(t.get("attempts", []))))
    for key, status in (("pending", "pending"), ("skipped", "skipped")):
        names = [s for s, t in head["topics"].items() if t.get("status") == status]
        lines += ["", "## %s" % lab[key], ""]
        lines += ["- %s" % _title(folder, meta, s) for s in names] or [lab["none"]]
    return "\n".join(lines) + "\n"


def write(folder: Path, meta: dict, head: dict) -> None:
    head = dict(head, teach_me="progress")
    ordered = {k: head[k] for k in ("teach_me", "current", "last_session", "topics", "reviews")}
    store.atomic_write(_path(folder, meta),
                       frontmatter.dump(ordered, _body(folder, meta, head)))


def asked(dossier_id: str, slug: str) -> list:
    """Normalized prompts already asked for the topic. Read-only."""
    meta, _ = dossier.load(dossier_id)
    head = load(store.dossier_dir(dossier_id), meta)
    value = (head["topics"].get(slug) or {}).get("asked")
    return list(value) if isinstance(value, list) else []


def record_exam(dossier_id: str, slug: str, attempt: int, average: float, passed: bool,
                prompts: list) -> None:
    folder = store.dossier_dir(dossier_id)
    meta, _ = dossier.load(dossier_id)
    head = load(folder, meta)
    t = entry(head, slug)
    if passed:
        t["status"] = "passed"
    elif t["status"] != "passed":
        t["status"] = "pending"
    t["best"] = average if t.get("best") is None else max(t["best"], average)
    t["attempts"].append({"attempt": attempt, "average": average, "passed": passed,
                          "date": today()})
    for prompt in prompts:
        norm = sources.normalize(prompt)
        if norm not in t["asked"]:
            t["asked"].append(norm)
    write(folder, meta, head)


def record_review(dossier_id: str, review: dict) -> None:
    folder = store.dossier_dir(dossier_id)
    meta, _ = dossier.load(dossier_id)
    head = load(folder, meta)
    head["reviews"].append(review)
    write(folder, meta, head)
