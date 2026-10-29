"""Progress file: per-topic status by slug (spec 7.4, 11). Helpers here do NOT take the lock."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import dossier, frontmatter, modes, sources, store
from .errors import BlockedError

_LABELS = {
    "es": {"title": "Avance", "number": "N.º", "topic": "Tema", "status": "Estado",
           "best": "Mejor nota", "attempts": "Intentos", "outdated": "Desactualizado",
           "yes": "sí", "no": "no", "pending": "Pendientes", "skipped": "Saltados",
           "none": "(ninguno)"},
    "en": {"title": "Progress", "number": "No.", "topic": "Topic", "status": "Status",
           "best": "Best score", "attempts": "Attempts", "outdated": "Outdated",
           "yes": "yes", "no": "no", "pending": "Pending", "skipped": "Skipped",
           "none": "(none)"},
}
_NEEDS_REVIEW_STATUSES = ("passed", "pending")
MAX_DOUBT = 500


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


_local_today = today  # for functions whose `today` parameter shadows the function


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


def _read(path: Path) -> "tuple[dict, str]":
    try:
        return frontmatter.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {}, ""


def _syllabus(folder: Path, meta: dict, required: bool = False) -> list:
    head, _ = _read(folder / meta["names"]["syllabus"])
    topics = head.get("topics") if head.get("teach_me") == "syllabus" else None
    if not isinstance(topics, list):
        if required:
            raise BlockedError("bad_input", "This dossier has no syllabus yet; save it first.")
        return []
    return topics


def _status(head: dict, slug: str) -> str:
    return (head["topics"].get(slug) or {}).get("status") or "not_started"


def _body(folder: Path, meta: dict, head: dict) -> str:
    lab = _LABELS.get(meta.get("lang"), _LABELS["en"])
    syl = _syllabus(folder, meta)
    rows = [(t.get("number", "-"), t.get("slug"), t.get("title", t.get("slug"))) for t in syl]
    lines = ["# %s" % lab["title"], "",
             "| %s | %s | %s | %s | %s | %s |" % (lab["number"], lab["topic"], lab["status"],
                                                 lab["best"], lab["attempts"], lab["outdated"]),
             "|---|---|---|---|---|---|"]
    for number, slug, title in rows:
        t = head["topics"].get(slug) or {}
        best = "-" if t.get("best") is None else "%s%%" % t["best"]
        lines.append("| %s | %s | %s | %s | %d | %s |" % (
            number, title, _status(head, slug), best, len(t.get("attempts") or []),
            lab["yes"] if t.get("outdated") else lab["no"]))
    for key in ("pending", "skipped"):
        lines += ["", "## %s" % lab[key], ""]
        lines += ["- %s" % title for _n, slug, title in rows if _status(head, slug) == key] \
            or [lab["none"]]
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


def clear_outdated(folder: Path, meta: dict, slug: str) -> None:
    """Called by save_topic inside its own lock; rewrites only if the flag was set."""
    head = load(folder, meta)
    t = head["topics"].get(slug)
    if isinstance(t, dict) and t.get("outdated"):
        t["outdated"] = False
        write(folder, meta, head)


def _needs_review(head: dict, topics: list, today_: str) -> bool:
    last = head.get("last_session")
    if not last or last == today_:
        return False
    return any(_status(head, t.get("slug")) in _NEEDS_REVIEW_STATUSES for t in topics)


def _view(head: dict, syl: list) -> list:
    out = []
    for t in syl:
        slug = t.get("slug")
        deps = [d for d in (t.get("depends_on") or [])
                if _status(head, d) in ("pending", "skipped")]
        entry_ = head["topics"].get(slug) or {}
        out.append({"number": t.get("number"), "slug": slug, "title": t.get("title", slug),
                    "status": _status(head, slug), "best": entry_.get("best"),
                    "outdated": bool(entry_.get("outdated")), "at_risk": deps})
    return out


def _payload(meta: dict, head: dict, syl: list, today_: str) -> dict:
    view = _view(head, syl)
    return {"ok": True, "mode": meta.get("mode"), "current": head.get("current"),
            "topics": view,
            "pending": [t["slug"] for t in view if t["status"] == "pending"],
            "skipped": [t["slug"] for t in view if t["status"] == "skipped"],
            "needs_review": _needs_review(head, syl, today_)}


def show(dossier_id: str, today: "str | None" = None) -> dict:
    dossier.require(dossier_id)
    meta, _ = dossier.load(dossier_id)
    folder = store.dossier_dir(dossier_id)
    syl = _syllabus(folder, meta, required=True)
    return _payload(meta, load(folder, meta), syl, today or _local_today())


def _mutate(dossier_id: str, slug: "str | None", fn, in_mode: bool = False) -> dict:
    """require -> locked -> load -> write. fn(head, syl, meta) returns the extra payload.
    in_mode: refuse a topic that is set aside in the current mode."""
    dossier.require(dossier_id)
    with store.locked(dossier_id) as folder:
        meta, _ = dossier.load(dossier_id)
        syl = _syllabus(folder, meta, required=slug is not None)
        found = next((t for t in syl if t.get("slug") == slug), None) if slug is not None else None
        if slug is not None and found is None:
            raise BlockedError("topic_not_found", "The syllabus has no topic %r." % slug)
        if in_mode and found is not None:
            modes.require_in_mode(meta, found)
        head = load(folder, meta)
        extra = fn(head, syl, meta)
        write(folder, meta, head)
    return extra


def start(dossier_id: str, slug: str) -> dict:
    def fn(head, syl, meta):
        t = entry(head, slug)
        if t["status"] in ("not_started", "skipped"):
            t["status"] = "in_progress"
        head["current"] = slug
        row = next(r for r in _view(head, syl) if r["slug"] == slug)
        return dict({"ok": True}, **row)
    return _mutate(dossier_id, slug, fn, in_mode=True)


def doubt(dossier_id: str, slug: str, text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise BlockedError("bad_input", "The doubt is empty.")
    if len(text) > MAX_DOUBT:
        raise BlockedError("bad_input", "A doubt has at most %d characters." % MAX_DOUBT)

    def fn(head, syl, meta):
        t = entry(head, slug)
        t["doubts"].append(text)
        return {"ok": True, "slug": slug, "doubts": len(t["doubts"])}
    return _mutate(dossier_id, slug, fn, in_mode=True)


def skip(dossier_id: str, slug: str) -> dict:
    def fn(head, syl, meta):
        t = entry(head, slug)
        changed = t["status"] != "passed"
        if changed:
            t["status"] = "skipped"
        return {"ok": True, "slug": slug, "status": t["status"], "changed": changed}
    return _mutate(dossier_id, slug, fn, in_mode=True)


def outdated(dossier_id: str, slug: str) -> dict:
    def fn(head, syl, meta):
        entry(head, slug)["outdated"] = True
        return {"ok": True, "slug": slug, "outdated": True}
    return _mutate(dossier_id, slug, fn)


def touch(dossier_id: str, today: "str | None" = None) -> dict:
    day = today or _local_today()

    def fn(head, syl, meta):
        previous = head.get("last_session")
        needs = _needs_review(head, syl, day)
        head["last_session"] = day
        return {"ok": True, "needs_review": needs, "previous_session": previous}
    return _mutate(dossier_id, None, fn)
