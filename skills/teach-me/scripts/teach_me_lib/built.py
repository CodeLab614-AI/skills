"""The how-it-is-built tour of mode 2 (spec 8.4, 8.5): saved like the overview, about the real code."""
from __future__ import annotations

from datetime import datetime, timezone

from . import code, dossier, frontmatter, modes, store, support
from .errors import BlockedError

SECTIONS = ("map", "connections", "walkthrough", "design_decisions")

_LABELS = {
    "es": {"map": "Mapa de las piezas", "connections": "Cómo se conectan",
           "walkthrough": "Qué pasa por dentro", "design_decisions": "Decisiones de diseño"},
    "en": {"map": "Map of the pieces", "connections": "How they connect",
           "walkthrough": "What happens inside", "design_decisions": "Design decisions"},
}


def _bad(message: str) -> BlockedError:
    return BlockedError("bad_input", message)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate(data) -> list:
    if not isinstance(data, dict) or not isinstance(data.get("sections"), list):
        raise _bad("Send an object with a sections list.")
    sections = data["sections"]
    kinds = [s.get("kind") if isinstance(s, dict) else None for s in sections]
    if kinds != list(SECTIONS):
        raise _bad("sections must be exactly, in order: %s." % ", ".join(SECTIONS))
    for sec in sections:
        support.check_claims_shape(sec.get("claims"), "section %r" % sec["kind"])
        if "code" in sec and not isinstance(sec["code"], str):
            raise _bad("section %r: code must be a string." % sec["kind"])
    cited = any(isinstance(s, dict) and s.get("kind") == "code"
                for sec in sections for c in sec["claims"]
                for s in (c.get("sources") if isinstance(c.get("sources"), list) else []))
    if not cited:
        raise BlockedError("no_code_citations",
                           "The tour is about the code: cite at least one code excerpt (kind code).")
    return sections


def _body(meta: dict, head: dict) -> str:
    lab = _LABELS.get(meta.get("lang"), _LABELS["en"])
    lines = ["# %s" % meta.get("name", lab["map"]), ""]
    for sec in head["sections"]:
        lines += ["## %s" % lab[sec["kind"]], ""] + support.render_claims(sec["claims"])
        if sec.get("code"):
            lines += [support.fence(sec["code"]), ""]
    return "\n".join(lines)


def _code_saved(meta: dict) -> bool:
    version = meta.get("version")
    label = version.get("label") if isinstance(version, dict) else None
    if not isinstance(label, str) or not label:
        return False
    names = meta["names"]
    final = store.dossier_dir(meta["id"]) / names["sources_dir"] / names["code_dir"] / label
    return code._read_inventory(final) is not None


def save_built(dossier_id: str, data) -> dict:
    blocks = _validate(data)
    support.check_blocks(data, blocks)
    dossier.require(dossier_id)
    with store.locked(dossier_id) as folder:
        meta, _ = dossier.load(dossier_id)
        if "built_tour" not in modes.parts_for(meta.get("mode", "use")):
            raise BlockedError("part_not_in_mode", "The dossier mode does not include the built tour.")
        if meta.get("public_code") is False:
            raise BlockedError("no_public_code",
                               "This library has no public code, so the tour cannot be built.")
        if not _code_saved(meta):
            raise BlockedError("code_not_saved", code._NO_CODE)
        resolved = support.resolve_blocks(dossier_id, blocks)
        sections = []
        for b, claims in zip(blocks, resolved):
            item = {"kind": b["kind"], "claims": claims}
            if b.get("code"):
                item["code"] = b["code"]
                item["code_support"] = b["code_support"]
            sections.append(item)
        head = {"teach_me": "built", "support_checked_in": data["support_checked_in"],
                "saved_at": _now(), "sections": sections}
        path = folder / meta["names"]["built"]
        store.atomic_write(path, frontmatter.dump(head, _body(meta, head)))
        parts = list(meta.get("parts_done") or [])
        if "built_tour" not in parts:
            parts.append("built_tour")
        meta["parts_done"] = parts
        meta.setdefault("phases", {})["built"] = _now()
        dossier.save(dossier_id, meta)
    return {"ok": True, "id": dossier_id, "path": str(path),
            "claims": sum(len(c) for c in resolved)}
