"""The overview report of mode 1 and `show-part` (spec 6, 8.2)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from . import docs, dossier, frontmatter, modes, store, support
from .errors import BlockedError

SECTIONS = ("what", "use_cases", "works_with", "example", "competitors")
MAX_ROWS = 5
SHOW_PARTS = {"overview": "overview", "built": "built"}

_LABELS = {
    "es": {"what": "Qué es y qué hace", "use_cases": "Para qué sirve",
           "works_with": "Con qué se usa", "example": "Cómo se ve usarlo",
           "competitors": "Competidores directos", "coverage": "Cobertura",
           "columns": ("Nombre", "Qué hace", "Licencia", "Última versión", "Último release",
                       "Último commit", "Diferencia"),
           "none": "(ninguno)", "pages": "Páginas de documentación: %d leídas o guardadas, %d sin descargar.",
           "read": "Leído", "skipped": "Omitido", "not_downloaded": "Sin descargar"},
    "en": {"what": "What it is and what it does", "use_cases": "What it is for",
           "works_with": "What it is used with", "example": "What using it looks like",
           "competitors": "Direct competitors", "coverage": "Coverage",
           "columns": ("Name", "What it does", "Licence", "Latest version", "Last release",
                       "Last commit", "Difference"),
           "none": "(none)", "pages": "Documentation pages: %d downloaded, %d not downloaded.",
           "read": "Read", "skipped": "Skipped", "not_downloaded": "Not downloaded"},
}


def _bad(message: str) -> BlockedError:
    return BlockedError("bad_input", message)


def _lab(meta: dict) -> dict:
    return _LABELS.get(meta.get("lang"), _LABELS["en"])


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate(data) -> "tuple[list, list]":
    """Return (section blocks, competitor row blocks) after checking the payload shape."""
    if not isinstance(data, dict) or not isinstance(data.get("sections"), list):
        raise _bad("Send an object with a sections list.")
    sections = data["sections"]
    kinds = [s.get("kind") if isinstance(s, dict) else None for s in sections]
    if kinds != list(SECTIONS):
        raise _bad("sections must be exactly, in order: %s." % ", ".join(SECTIONS))
    blocks, rows = [], []
    for sec in sections[:-1]:
        support.check_claims_shape(sec.get("claims"), "section %r" % sec["kind"])
        if "code" in sec and not isinstance(sec["code"], str):
            raise _bad("section %r: code must be a string." % sec["kind"])
        blocks.append(sec)
    raw = sections[-1].get("rows")
    if not isinstance(raw, list) or len(raw) > MAX_ROWS:
        raise _bad("competitors needs a rows list of 0 to %d items." % MAX_ROWS)
    for i, item in enumerate(raw):
        tag = "competitors[%d]" % i
        if not isinstance(item, dict) or not isinstance(item.get("competitor"), str) \
                or not item["competitor"].strip():
            raise _bad("%s needs a competitor (owner/name)." % tag)
        pair = [item.get("one_liner"), item.get("difference")]
        support.check_claims_shape(pair, tag, ("fact",))
        rows.append({"kind": tag, "claims": pair})
    return blocks, rows


def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def _dash(value) -> str:
    return _cell(value) if isinstance(value, str) and value.strip() else "-"


def _licence(entry: dict) -> str:
    lic = entry.get("license") if isinstance(entry.get("license"), dict) else {}
    return _dash(lic.get("registry") or lic.get("repo"))


def _coverage_lines(meta: dict, folder: Path) -> list:
    lab = _lab(meta)
    names = meta["names"]
    pages = docs._read_pages(folder / names["sources_dir"] / names["docs_dir"]) or []
    ok = sum(1 for p in pages if isinstance(p, dict) and p.get("state") == "ok")
    lines = [lab["pages"] % (ok, len(pages) - ok), ""]
    cov = meta.get("coverage") if isinstance(meta.get("coverage"), dict) else {}
    for key in ("read", "skipped", "not_downloaded"):
        items = cov.get(key)
        count = len(items) if isinstance(items, list) else 0
        lines.append("- %s: %d" % (lab[key], count))
    return lines + [""]


def _body(meta: dict, head: dict, entries: dict, folder: Path) -> str:
    lab = _lab(meta)
    lines = ["# %s" % meta.get("name", lab["what"]), ""]
    for sec in head["sections"][:-1]:
        lines += ["## %s" % lab[sec["kind"]], ""] + support.render_claims(sec["claims"])
        if sec.get("code"):
            lines += [support.fence(sec["code"]), ""]
    rows = head["sections"][-1]["rows"]
    lines += ["## %s" % lab["competitors"], ""]
    if not rows:
        lines += [lab["none"], ""]
    else:
        cols = lab["columns"]
        lines += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for row in rows:
            e = entries[row["competitor"].lower()]
            act = e.get("activity") if isinstance(e.get("activity"), dict) else {}
            lines.append("| " + " | ".join([
                "[%s](%s)" % (_cell(row["competitor"]), _cell(e.get("url", ""))),
                _cell(row["one_liner"]["text"]), _licence(e), _dash(e.get("latest")),
                _dash(act.get("last_release_at")), _dash(act.get("last_commit_at")),
                _cell(row["difference"]["text"])]) + " |")
        lines.append("")
        for row in rows:
            lines += ["### %s" % row["competitor"], ""]
            lines += support.render_claims([row["one_liner"], row["difference"]])
    lines += ["## %s" % lab["coverage"], ""] + _coverage_lines(meta, folder)
    return "\n".join(lines)


def save_overview(dossier_id: str, data) -> dict:
    blocks, rows = _validate(data)
    support.check_blocks(data, blocks + rows)
    dossier.require(dossier_id)
    with store.locked(dossier_id) as folder:
        meta, _ = dossier.load(dossier_id)
        if "overview" not in modes.parts_for(meta.get("mode", "use")):
            raise BlockedError("part_not_in_mode", "The dossier mode does not include the overview.")
        entries = meta.get("competitors") if isinstance(meta.get("competitors"), dict) else {}
        asked = data["sections"][-1]["rows"]
        for i, item in enumerate(asked):
            if item["competitor"].lower() not in entries:
                raise BlockedError("competitor_not_fetched",
                                   "competitors[%d]: %r was not fetched; run fetch-competitor first."
                                   % (i, item["competitor"]))
        resolved = support.resolve_blocks(dossier_id, blocks + rows)
        sections = []
        for b, claims in zip(blocks, resolved):
            item = {"kind": b["kind"], "claims": claims}
            if b.get("code"):
                item["code"] = b["code"]
                item["code_support"] = b["code_support"]
            sections.append(item)
        out_rows = [{"competitor": a["competitor"], "one_liner": pair[0], "difference": pair[1]}
                    for a, pair in zip(asked, resolved[len(blocks):])]
        sections.append({"kind": "competitors", "rows": out_rows})
        head = {"teach_me": "overview", "support_checked_in": data["support_checked_in"],
                "saved_at": _now(), "sections": sections}
        path = folder / meta["names"]["overview"]
        store.atomic_write(path, frontmatter.dump(head, _body(meta, head, entries, folder)))
        parts = list(meta.get("parts_done") or [])
        if "overview" not in parts:
            parts.append("overview")
        meta["parts_done"] = parts
        meta["status"] = "ready"
        meta.setdefault("phases", {})["overview"] = _now()
        dossier.save(dossier_id, meta)
    return {"ok": True, "id": dossier_id, "path": str(path),
            "claims": sum(len(c) for c in resolved), "competitors": len(out_rows)}


def show_part(dossier_id: str, part: str) -> dict:
    if part not in SHOW_PARTS:
        raise _bad("part must be one of: %s." % ", ".join(SHOW_PARTS))
    dossier.require(dossier_id)
    meta, _ = dossier.load(dossier_id)
    path = store.dossier_dir(dossier_id) / meta["names"][part]
    try:
        head, _ = frontmatter.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        head = {}
    if not head:
        raise BlockedError("part_not_saved", "The %s part is not saved yet." % part)
    return dict({"ok": True}, **head)
