"""Syllabus and topics: nothing unsupported or uncited reaches a topic file (spec 6, 7.2)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from . import dossier, frontmatter, modes, progress, sources, store, support
from .errors import BlockedError

BLOCK_KINDS = ("problem", "idea", "example", "predict", "internals", "pitfalls")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_TOPIC_KEYS = ("slug", "title", "objective", "why_here", "part", "depends_on", "sources")

_LABELS = {
    "es": {"syllabus": "Temario", "prereq": "Requisitos", "back": "Temario", "none": "(ninguno)",
           "problem": "El problema", "idea": "La idea", "example": "Ejemplo",
           "predict": "Predice antes de ver", "internals": "Por dentro",
           "pitfalls": "Errores comunes",
           "use": "Cómo se usa", "built": "Cómo está construida"},
    "en": {"syllabus": "Syllabus", "prereq": "Prerequisites", "back": "Syllabus", "none": "(none)",
           "problem": "The problem", "idea": "The idea", "example": "Example",
           "predict": "Predict first", "internals": "Internals",
           "pitfalls": "Pitfalls",
           "use": "How to use it", "built": "How it is built"},
}


def _bad(message: str) -> BlockedError:
    return BlockedError("bad_input", message)


def _lab(meta: dict, key: str) -> str:
    return _LABELS.get(meta.get("lang"), _LABELS["en"])[key]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stem(meta: dict) -> str:
    return Path(meta["names"]["syllabus"]).stem


def _link(number: int, slug: str) -> str:
    return "[[%02d-%s]]" % (number, slug)


def _topics_dir(folder: Path, meta: dict) -> Path:
    path = folder / meta["names"]["topics_dir"]
    path.mkdir(parents=True, exist_ok=True)
    return path


def _syllabus_path(folder: Path, meta: dict) -> Path:
    return folder / meta["names"]["syllabus"]


def _read(path: Path) -> "tuple[dict, str]":
    try:
        return frontmatter.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {}, ""


def _topic_files(folder: Path, meta: dict) -> dict:
    """slug -> (path, header) of every saved topic file."""
    found: dict = {}
    tdir = folder / meta["names"]["topics_dir"]
    if not tdir.is_dir():
        return found
    for path in sorted(tdir.glob("*.md")):
        head, _ = _read(path)
        if head.get("teach_me") == "topic" and isinstance(head.get("slug"), str):
            found[head["slug"]] = (path, head)
    return found


# --- syllabus ---------------------------------------------------------------------

def _validate_syllabus(data, allowed: tuple) -> list:
    if not isinstance(data, dict) or not isinstance(data.get("topics"), list) or not data["topics"]:
        raise _bad("Send an object with a non-empty topics list.")
    seen: list = []
    parts_seen: list = []
    for i, item in enumerate(data["topics"]):
        tag = "topic %d" % i
        if not isinstance(item, dict):
            raise _bad("%s must be an object." % tag)
        for key in ("slug", "title", "objective", "why_here"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise _bad("%s needs a non-empty %s." % (tag, key))
        slug = item["slug"]
        if not _SLUG.match(slug):
            raise _bad("%s: slug %r must match ^[a-z0-9][a-z0-9-]*$." % (tag, slug))
        if slug in seen:
            raise _bad("%s: slug %r is repeated." % (tag, slug))
        dep = item.get("depends_on", [])
        if not isinstance(dep, list) or any(not isinstance(d, str) for d in dep):
            raise _bad("%s: depends_on must be a list of slugs." % tag)
        for d in dep:
            if d not in seen:
                raise _bad("%s: depends_on %r is not an earlier topic." % (tag, d))
        if not isinstance(item.get("part"), str):
            raise _bad("%s needs a part." % tag)
        if item["part"] not in allowed:
            raise BlockedError("part_not_in_mode",
                               "%s: part %r is not in this mode's syllabus parts." % (tag, item["part"]))
        if item["part"] == "use" and any(p == "internals" for p in parts_seen):
            raise _bad("%s: use topics come first, before every internals topic." % tag)
        parts_seen.append(item["part"])
        cites = item.get("sources")
        if not isinstance(cites, list) or not cites:
            raise _bad("%s needs at least one source." % tag)
        seen.append(slug)
    return data["topics"]


def _syllabus_body(meta: dict, topics: list) -> str:
    lines = ["# %s" % _lab(meta, "syllabus"), ""]
    for part, heading in (("use", "use"), ("internals", "built")):
        group = [t for t in topics if t.get("part", "use") == part]
        if not group:
            continue
        lines += ["## %s" % _lab(meta, heading), ""]
        for t in group:
            lines.append("%02d. %s — %s %s" % (t["number"], t["title"], t["why_here"],
                                               _link(t["number"], t["slug"])))
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def save_syllabus(dossier_id: str, data) -> dict:
    dossier.require(dossier_id)
    with store.locked(dossier_id) as folder:
        meta, _ = dossier.load(dossier_id)
        allowed = modes.syllabus_parts(meta.get("mode", "use"))
        if not allowed:
            raise BlockedError("part_not_in_mode",
                               "Mode %r has no syllabus." % meta.get("mode"))
        items = _validate_syllabus(data, allowed)
        if any(t["part"] == "internals" for t in items) and meta.get("public_code") is False:
            raise BlockedError("no_public_code",
                               "This library has no public code, so it has no built syllabus.")
        wrapped = [{"text": t["title"], "kind": "fact", "sources": t["sources"]} for t in items]
        resolved, bad = sources.check_claims(dossier_id, wrapped)
        if bad:
            detail = "; ".join(
                "%s: %s" % (items[i]["slug"], ", ".join(
                    c.get("error", "unverified") for c in resolved[i]["sources"] if "error" in c)
                    or resolved[i].get("error", "unverified"))
                for i in bad)
            raise _bad("Unverified syllabus sources (%s)." % detail)
        topics = []
        for n, (t, r) in enumerate(zip(items, resolved), start=1):
            topics.append({"number": n, "slug": t["slug"], "title": t["title"],
                           "objective": t["objective"], "why_here": t["why_here"],
                           "part": t["part"], "depends_on": list(t.get("depends_on", [])),
                           "sources": r["sources"]})
        # Topics set aside by the current mode stay in the syllabus (spec 8.3).
        for old in _saved_topics(folder, meta):
            if modes.is_set_aside(meta, old) and old.get("slug") not in {t["slug"] for t in topics}:
                topics.append(dict(old, number=len(topics) + 1))
        header = {"teach_me": "syllabus", "saved_at": _now(), "topics": topics}
        store.atomic_write(_syllabus_path(folder, meta),
                           frontmatter.dump(header, _syllabus_body(meta, topics)))
        renamed = _renumber(folder, meta, topics)
        parts = list(meta.get("parts_done") or [])
        sent = ["use"] + (["built_syllabus"] if any(t["part"] == "internals" for t in items) else [])
        parts += [p for p in sent if p not in parts]
        meta["parts_done"] = parts
        meta["status"] = "ready"
        meta.setdefault("phases", {})["syllabus"] = _now()
        dossier.save(dossier_id, meta)
    return {"ok": True, "id": dossier_id, "topics": [
        {"number": t["number"], "slug": t["slug"], "title": t["title"]} for t in topics[:len(items)]],
        "renamed": renamed}


def _saved_topics(folder: Path, meta: dict) -> list:
    head, _ = _read(_syllabus_path(folder, meta))
    topics = head.get("topics") if head.get("teach_me") == "syllabus" else None
    return [t for t in topics if isinstance(t, dict)] if isinstance(topics, list) else []


def _renumber(folder: Path, meta: dict, topics: list) -> list:
    """Rewrite saved topic files under their new number; old names go away."""
    moved = []
    by_slug = {t["slug"]: t for t in topics}
    for slug, (path, head) in _topic_files(folder, meta).items():
        t = by_slug.get(slug)
        if t is None:
            continue
        head = dict(head, number=t["number"], title=t["title"], depends_on=list(t["depends_on"]))
        new = path.parent / ("%02d-%s.md" % (t["number"], slug))
        store.atomic_write(new, frontmatter.dump(head, _topic_body(meta, head, topics)))
        if new != path:
            path.unlink()
            moved.append({"from": path.name, "to": new.name})
    return moved


# --- topics -----------------------------------------------------------------------

def _validate_topic(data) -> None:
    if not isinstance(data, dict):
        raise _bad("The topic must be a JSON object.")
    if not isinstance(data.get("slug"), str) or not _SLUG.match(data["slug"]):
        raise _bad("slug must match ^[a-z0-9][a-z0-9-]*$.")
    blocks = data.get("blocks")
    if not isinstance(blocks, list) or len(blocks) != len(BLOCK_KINDS):
        raise _bad("blocks must be exactly: %s." % ", ".join(BLOCK_KINDS))
    for block, kind in zip(blocks, BLOCK_KINDS):
        if not isinstance(block, dict) or block.get("kind") != kind:
            raise _bad("blocks must be exactly, in order: %s." % ", ".join(BLOCK_KINDS))
        claims = block.get("claims")
        if not isinstance(claims, list) or not claims:
            raise _bad("block %r needs at least one claim." % kind)
        for j, claim in enumerate(claims):
            if not isinstance(claim, dict) or claim.get("kind") not in ("fact", "pedagogical"):
                raise _bad("block %r, claim %d: needs kind fact or pedagogical." % (kind, j))
        if "code" in block and not isinstance(block["code"], str):
            raise _bad("block %r: code must be a string." % kind)


def _topic_body(meta: dict, head: dict, topics: list) -> str:
    numbers = {t["slug"]: t["number"] for t in topics}
    pre = " ".join(_link(numbers[d], d) for d in head.get("depends_on", []) if d in numbers)
    lines = ["# %02d. %s" % (head["number"], head["title"]), "",
             "%s: %s — %s: [[%s]]" % (_lab(meta, "prereq"), pre or _lab(meta, "none"),
                                      _lab(meta, "back"), _stem(meta)), ""]
    for block in head["blocks"]:
        lines += ["## %s" % _lab(meta, block["kind"]), ""]
        lines += support.render_claims(block["claims"])
        if block.get("code"):
            lines += [support.fence(block["code"]), ""]
    return "\n".join(lines)


def _load_syllabus(folder: Path, meta: dict) -> list:
    path = _syllabus_path(folder, meta)
    head, _ = _read(path)
    if head.get("teach_me") != "syllabus" or not isinstance(head.get("topics"), list):
        raise _bad("This dossier has no syllabus yet; save it first.")
    return head["topics"]


def save_topic(dossier_id: str, data) -> dict:
    _validate_topic(data)
    support.check_blocks(data, data["blocks"])
    dossier.require(dossier_id)
    with store.locked(dossier_id) as folder:
        meta, _ = dossier.load(dossier_id)
        topics = _load_syllabus(folder, meta)
        entry = next((t for t in topics if t["slug"] == data["slug"]), None)
        if entry is None:
            raise BlockedError("topic_not_found",
                               "The syllabus has no topic %r." % data["slug"])
        modes.require_in_mode(meta, entry)
        resolved = support.resolve_blocks(dossier_id, data["blocks"])
        out_blocks = []
        for b, claims in zip(data["blocks"], resolved):
            item = {"kind": b["kind"], "claims": claims}
            if b.get("code"):
                item["code"] = b["code"]
                item["code_support"] = b["code_support"]
            out_blocks.append(item)
        head = {"teach_me": "topic", "number": entry["number"], "slug": entry["slug"],
                "title": entry["title"], "depends_on": list(entry.get("depends_on", [])),
                "support_checked_in": data["support_checked_in"], "saved_at": _now(),
                "blocks": out_blocks}
        path = _topics_dir(folder, meta) / ("%02d-%s.md" % (entry["number"], entry["slug"]))
        store.atomic_write(path, frontmatter.dump(head, _topic_body(meta, head, topics)))
        progress.clear_outdated(folder, meta, entry["slug"])
    return {"ok": True, "id": dossier_id, "slug": entry["slug"], "number": entry["number"],
            "path": str(path), "claims": sum(len(c) for c in resolved)}


def show_topic(dossier_id: str, slug: str) -> dict:
    dossier.require(dossier_id)
    meta, _ = dossier.load(dossier_id)
    found = _topic_files(store.dossier_dir(dossier_id), meta).get(slug)
    if found is None:
        raise BlockedError("topic_not_found", "No saved topic %r." % slug)
    return dict({"ok": True}, **found[1])
