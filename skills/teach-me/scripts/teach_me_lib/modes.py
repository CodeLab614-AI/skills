"""The four modes: which pieces each one builds, and changing mode on a dossier.

A piece is a part of the dossier a mode needs (the overview, the use syllabus,
the built tour, ...). `parts_done` in the profile records the pieces made; a mode
change never deletes any: pieces the new mode does not use are only set aside.

Pure helpers come first and import nothing from the package, because `dossier`
imports this module; `set_mode` imports `dossier` and `code` lazily.
"""
from __future__ import annotations

PARTS = {
    "overview": ("overview",),
    "overview-internals": ("overview", "built_tour"),
    "use": ("use",),
    "use-internals": ("use", "built_syllabus"),
}
SYLLABUS_PARTS = {
    "overview": (),
    "overview-internals": (),
    "use": ("use",),
    "use-internals": ("use", "internals"),
}
_INTERNALS = ("overview-internals", "use-internals")


def _check(mode: str) -> None:
    if mode not in PARTS:
        from .errors import BlockedError
        raise BlockedError("bad_input", "Unknown mode %r. Allowed: %s." % (mode, ", ".join(PARTS)))


def parts_for(mode: str) -> tuple:
    _check(mode)
    return PARTS[mode]


def syllabus_parts(mode: str) -> tuple:
    _check(mode)
    return SYLLABUS_PARTS[mode]


def is_set_aside(meta: dict, topic: dict) -> bool:
    """A syllabus topic is set aside when its part is not one of the current mode's;
    a topic without a part (older data) counts as `use`."""
    part = topic.get("part") if isinstance(topic.get("part"), str) else "use"
    return part not in syllabus_parts(meta.get("mode", "use"))


def require_in_mode(meta: dict, topic: dict) -> None:
    from .errors import BlockedError
    if is_set_aside(meta, topic):
        raise BlockedError("part_not_in_mode",
                           "Topic %r is set aside in mode %r; switch mode to work on it."
                           % (topic.get("slug"), meta.get("mode")))


def needs_public_code(mode: str) -> bool:
    _check(mode)
    return mode in _INTERNALS


def needs_full_code(mode: str) -> bool:
    _check(mode)
    return mode in _INTERNALS


def _done(meta: dict) -> list:
    done = meta.get("parts_done")
    return list(done) if isinstance(done, list) else []


def missing_parts(meta: dict) -> list:
    done = _done(meta)
    return [p for p in parts_for(meta.get("mode", "use")) if p not in done]


def set_aside_parts(meta: dict, mode: str) -> list:
    wanted = parts_for(mode)
    return [p for p in _done(meta) if p not in wanted]


def _saved_layout(meta: dict) -> "str | None":
    """`layout` from the code inventory of the current version, None without one."""
    from . import code, store
    version = meta.get("version")
    label = version.get("label") if isinstance(version, dict) else None
    if not isinstance(label, str) or not label:
        return None
    names = meta["names"]
    final = store.dossier_dir(meta["id"]) / names["sources_dir"] / names["code_dir"] / label
    head = code._read_inventory(final)
    return head.get("layout") if head else None


def set_mode(dossier_id: str, mode: str) -> dict:
    from . import dossier, store
    from .errors import BlockedError
    _check(mode)
    dossier.require(dossier_id)
    with store.locked(dossier_id):
        meta, _ = dossier.load(dossier_id)
        if needs_public_code(mode) and meta.get("public_code") is False:
            raise BlockedError("no_public_code",
                               "This library has no public code, so %r cannot be built." % mode)
        previous = meta.get("mode")
        meta["mode"] = mode
        dossier.save(dossier_id, meta)
        full = needs_full_code(mode) and _saved_layout(meta) == "monorepo"
        return {"ok": True, "id": dossier_id, "mode": mode, "previous_mode": previous,
                "missing_parts": missing_parts(meta), "set_aside_parts": set_aside_parts(meta, mode),
                "needs_full_code": full}
