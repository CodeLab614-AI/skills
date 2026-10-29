"""Syllabus and topics: nothing unsupported or uncited reaches a topic file (spec 6, 7.2)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from . import dossier, frontmatter, progress, sources, store
from .errors import BlockedError

BLOCK_KINDS = ("problem", "idea", "example", "predict", "internals", "pitfalls")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_TOPIC_KEYS = ("slug", "title", "objective", "why_here", "part", "depends_on", "sources")

_LABELS = {
    "es": {"syllabus": "Temario", "prereq": "Requisitos", "back": "Temario", "none": "(ninguno)",
           "problem": "El problema", "idea": "La idea", "example": "Ejemplo",
           "predict": "Predice antes de ver", "internals": "Por dentro",
           "pitfalls": "Errores comunes"},
    "en": {"syllabus": "Syllabus", "prereq": "Prerequisites", "back": "Syllabus", "none": "(none)",
           "problem": "The problem", "idea": "The idea", "example": "Example",
           "predict": "Predict first", "internals": "Internals",
           "pitfalls": "Pitfalls"},
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

def _validate_syllabus(data) -> list:
    if not isinstance(data, dict) or not isinstance(data.get("topics"), list) or not data["topics"]:
        raise _bad("Send an object with a non-empty topics list.")
    seen: list = []
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
        if item["part"] != "use":
            raise BlockedError("part_not_in_mode",
                               "%s: part %r is not in mode 'use'." % (tag, item["part"]))
        cites = item.get("sources")
        if not isinstance(cites, list) or not cites:
            raise _bad("%s needs at least one source." % tag)
        seen.append(slug)
    return data["topics"]


def _syllabus_body(meta: dict, topics: list) -> str:
    lines = ["# %s" % _lab(meta, "syllabus"), ""]
    for t in topics:
        lines.append("%02d. %s — %s %s" % (t["number"], t["title"], t["why_here"],
                                           _link(t["number"], t["slug"])))
    return "\n".join(lines) + "\n"


def save_syllabus(dossier_id: str, data) -> dict:
    items = _validate_syllabus(data)
    dossier.require(dossier_id)
    with store.locked(dossier_id) as folder:
        meta, _ = dossier.load(dossier_id)
        if meta.get("mode") != "use":
            raise BlockedError("part_not_in_mode", "The dossier mode is not 'use'.")
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
        header = {"teach_me": "syllabus", "saved_at": _now(), "topics": topics}
        store.atomic_write(_syllabus_path(folder, meta),
                           frontmatter.dump(header, _syllabus_body(meta, topics)))
        renamed = _renumber(folder, meta, topics)
        parts = list(meta.get("parts_done") or [])
        if "use" not in parts:
            parts.append("use")
        meta["parts_done"] = parts
        meta["status"] = "ready"
        meta.setdefault("phases", {})["syllabus"] = _now()
        dossier.save(dossier_id, meta)
    return {"ok": True, "id": dossier_id, "topics": [
        {"number": t["number"], "slug": t["slug"], "title": t["title"]} for t in topics],
        "renamed": renamed}


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


def _check_support(data: dict) -> None:
    if data.get("support_checked_in") not in ("subagent", "same_conversation"):
        raise BlockedError("support_not_checked",
                           "support_checked_in must be 'subagent' or 'same_conversation'.")
    missing, unsupported, code_missing, code_bad = [], [], [], []
    for block in data["blocks"]:
        for j, claim in enumerate(block["claims"]):
            where = "%s[%d]" % (block["kind"], j)
            verdict = claim.get("support")
            if verdict is None:
                if claim["kind"] == "fact":
                    missing.append(where)
            elif verdict != "supported":
                unsupported.append(where)
        if block.get("code"):
            verdict = block.get("code_support")
            if verdict is None:
                code_missing.append(block["kind"])
            elif verdict != "supported":
                code_bad.append(block["kind"])
    if missing or code_missing:
        parts = []
        if missing:
            parts.append("Fact claims without a support verdict: %s." % ", ".join(missing))
        if code_missing:
            parts.append("Code blocks without a support verdict: %s." % ", ".join(code_missing))
        raise BlockedError("support_not_checked", " ".join(parts))
    if unsupported or code_bad:
        parts = []
        if unsupported:
            parts.append("Unsupported or invalid verdicts, fix or remove: %s." % ", ".join(unsupported))
        if code_bad:
            parts.append("Code blocks unsupported or with an invalid verdict, fix or remove: %s."
                         % ", ".join(code_bad))
        raise BlockedError("unsupported_claims", " ".join(parts))


def _source_line(cite: dict) -> str:
    if cite["kind"] == "doc":
        return cite["url"]
    return "%s:%d-%d" % (cite["path"], cite["line_start"], cite["line_end"])


def _quote(text: str) -> str:
    return "\n".join("> " + ln if ln else ">" for ln in text.split("\n"))


def _fence(code: str) -> str:
    longest = max([len(m) for m in re.findall(r"`+", code)] + [2])
    ticks = "`" * (longest + 1)
    return "%s\n%s\n%s" % (ticks, code.rstrip("\n"), ticks)


def _topic_body(meta: dict, head: dict, topics: list) -> str:
    numbers = {t["slug"]: t["number"] for t in topics}
    pre = " ".join(_link(numbers[d], d) for d in head.get("depends_on", []) if d in numbers)
    lines = ["# %02d. %s" % (head["number"], head["title"]), "",
             "%s: %s — %s: [[%s]]" % (_lab(meta, "prereq"), pre or _lab(meta, "none"),
                                      _lab(meta, "back"), _stem(meta)), ""]
    for block in head["blocks"]:
        lines += ["## %s" % _lab(meta, block["kind"]), ""]
        for claim in block["claims"]:
            lines += [claim["text"], ""]
            for cite in claim.get("sources", []):
                lines += [_quote(cite["excerpt"]), ">", _quote("— " + _source_line(cite)), ""]
        if block.get("code"):
            lines += [_fence(block["code"]), ""]
    return "\n".join(lines)


def _load_syllabus(folder: Path, meta: dict) -> list:
    path = _syllabus_path(folder, meta)
    head, _ = _read(path)
    if head.get("teach_me") != "syllabus" or not isinstance(head.get("topics"), list):
        raise _bad("This dossier has no syllabus yet; save it first.")
    return head["topics"]


def save_topic(dossier_id: str, data) -> dict:
    _validate_topic(data)
    _check_support(data)
    dossier.require(dossier_id)
    with store.locked(dossier_id) as folder:
        meta, _ = dossier.load(dossier_id)
        topics = _load_syllabus(folder, meta)
        entry = next((t for t in topics if t["slug"] == data["slug"]), None)
        if entry is None:
            raise BlockedError("topic_not_found",
                               "The syllabus has no topic %r." % data["slug"])
        flat = [c for b in data["blocks"] for c in b["claims"]]
        resolved, bad = sources.check_claims(dossier_id, flat)
        if bad:
            where, k = [], 0
            for b in data["blocks"]:
                for j in range(len(b["claims"])):
                    if k in bad:
                        errs = sorted({c["error"] for c in resolved[k]["sources"] if "error" in c}
                                      | ({resolved[k]["error"]} if "error" in resolved[k] else set()))
                        where.append("%s[%d] (%s)" % (b["kind"], j, ", ".join(errs) or "unverified"))
                    k += 1
            raise BlockedError("unverified_claims",
                               "Citations not verified, fix or remove: %s." % "; ".join(where))
        out_blocks, k = [], 0
        for b in data["blocks"]:
            item = {"kind": b["kind"], "claims": resolved[k:k + len(b["claims"])]}
            k += len(b["claims"])
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
            "path": str(path), "claims": len(flat)}


def show_topic(dossier_id: str, slug: str) -> dict:
    dossier.require(dossier_id)
    meta, _ = dossier.load(dossier_id)
    found = _topic_files(store.dossier_dir(dossier_id), meta).get(slug)
    if found is None:
        raise BlockedError("topic_not_found", "No saved topic %r." % slug)
    return dict({"ok": True}, **found[1])
