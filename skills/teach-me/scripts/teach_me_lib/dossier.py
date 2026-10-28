"""Dossiers: profile header, lookup by URL roots, list, init, add-root, load/save.

Locking rule (one rule for every caller): `load`, `save` and the helpers in this
module NEVER take `store.locked`, because the lock is not reentrant. The public
write entry points (`init`, `add_root`, and in later tasks every subcommand that
writes) take `store.locked(id)` once and may then call `load`/`save` freely.
Every write entry point on an existing dossier calls `require(id)` BEFORE
locking, because `store.locked` creates the folder and must not do so for
unknown ids.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import frontmatter, names as names_mod, store, urls
from .errors import BlockedError

MODES = ("overview", "overview-internals", "use", "use-internals")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

_MODE_LABELS = {
    "es": {"overview": "Saber qué es", "overview-internals": "Saber qué es y cómo está construida",
           "use": "Estudiar cómo se usa", "use-internals": "Estudiar cómo se usa y cómo está construida"},
    "en": {"overview": "Know what it is", "overview-internals": "Know what it is and how it is built",
           "use": "Study how to use it", "use-internals": "Study how to use it and how it is built"},
}
_STATUS_LABELS = {
    "es": {"investigating": "Investigando", "ready": "Listo"},
    "en": {"investigating": "Investigating", "ready": "Ready"},
}
_BODY_LABELS = {
    "es": {"summary": "Resumen", "roots": "Raíces (URLs)", "mode": "Modo", "status": "Estado",
           "version": "Versión", "license": "Licencia", "links": "Enlaces", "none": "(sin datos)"},
    "en": {"summary": "Summary", "roots": "Roots (URLs)", "mode": "Mode", "status": "Status",
           "version": "Version", "license": "License", "links": "Links", "none": "(no data)"},
}


def _label(table: dict, lang: str, key: str) -> str:
    return table.get(lang, table["en"]).get(key, key)


# --- reading -----------------------------------------------------------------

def _profile_path(folder: Path) -> "Path | None":
    """The first-level .md whose header says teach_me == profile (name-independent)."""
    try:
        entries = sorted(folder.glob("*.md"))
    except OSError:
        return None
    for path in entries:
        meta = _read_meta(path)
        if meta.get("teach_me") == "profile":
            return path
    return None


def _read_meta(path: Path) -> dict:
    try:
        meta, _ = frontmatter.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {}
    return meta


def find_all() -> list:
    root = store.home()
    found = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        path = _profile_path(folder)
        if path is not None:
            meta = _read_meta(path)
            meta.setdefault("id", folder.name)
            found.append(meta)
    return found


def require(dossier_id: str) -> None:
    """Raise dossier_not_found unless the dossier folder has a profile. Creates nothing."""
    if _profile_path(store.dossier_dir(dossier_id)) is None:
        raise BlockedError("dossier_not_found", "No dossier named %r." % dossier_id)


def load(dossier_id: str) -> "tuple[dict, str]":
    path = _profile_path(store.dossier_dir(dossier_id))
    if path is None:
        raise BlockedError("dossier_not_found", "No dossier named %r." % dossier_id)
    return frontmatter.parse(path.read_text(encoding="utf-8"))


# --- writing -----------------------------------------------------------------

def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def _version_text(version) -> str:
    if isinstance(version, dict):
        return str(version.get("value") or version.get("label") or "")
    return str(version or "")


def _profile_body(meta: dict) -> str:
    lang = meta.get("lang", "en")
    lab = lambda k: _label(_BODY_LABELS, lang, k)  # noqa: E731
    lines = ["# %s" % (meta.get("name") or meta.get("id", "")), ""]
    if meta.get("one_liner"):
        lines += [str(meta["one_liner"]), ""]
    lines.append("- **%s:** %s" % (lab("mode"), _label(_MODE_LABELS, lang, meta.get("mode", "use"))))
    lines.append("- **%s:** %s" % (lab("status"), _label(_STATUS_LABELS, lang, meta.get("status", ""))))
    lines.append("- **%s:** %s" % (lab("version"), _version_text(meta.get("version")) or lab("none")))
    lic = meta.get("license")
    lic_text = ", ".join("%s" % v for v in lic.values() if v) if isinstance(lic, dict) else str(lic or "")
    lines.append("- **%s:** %s" % (lab("license"), lic_text or lab("none")))
    lines += ["", "## %s" % lab("roots"), ""]
    lines += ["- %s" % r for r in meta.get("roots", [])] or [lab("none")]
    links = meta.get("links")
    if isinstance(links, dict) and links:
        lines += ["", "## %s" % lab("links"), ""]
        lines += ["- %s: %s" % (k, v) for k, v in links.items()]
    return "\n".join(lines) + "\n"


def _index_body(profiles: list) -> str:
    lines = ["# teach-me", "",
             "| Library | URLs | Version | Mode | Status |", "|---|---|---|---|---|"]
    for meta in profiles:
        lang = meta.get("lang", "en")
        lines.append("| %s | %s | %s | %s | %s |" % (
            _cell(meta.get("name") or meta.get("id", "")),
            _cell(", ".join(meta.get("roots", []))),
            _cell(_version_text(meta.get("version"))),
            _cell(_label(_MODE_LABELS, lang, meta.get("mode", "use"))),
            _cell(_label(_STATUS_LABELS, lang, meta.get("status", ""))),
        ))
    return "\n".join(lines) + "\n"


def _write_index() -> None:
    text = frontmatter.dump({"teach_me": "index"}, _index_body(find_all()))
    store.atomic_write(store.home() / "README.md", text)


def save(dossier_id: str, meta: dict) -> None:
    """Write the profile (header from `meta`, body regenerated) and the root README.

    Does not take the dossier lock; the caller must already hold it.
    """
    folder = store.dossier_dir(dossier_id)
    path = _profile_path(folder) or folder / meta["names"]["profile"]
    store.atomic_write(path, frontmatter.dump(meta, _profile_body(meta)))
    _write_index()


# --- lookup ------------------------------------------------------------------

def _summary(meta: dict) -> dict:
    return {"id": meta.get("id"), "name": meta.get("name"), "roots": list(meta.get("roots", []))}


def lookup(url: str) -> dict:
    norm = urls.normalize(url)
    key = norm
    if norm.split("/")[0] in ("github.com", "npmjs.com", "pypi.org"):
        key = urls.root_for(url)  # case-insensitive registry roots
    profiles = find_all()
    best = 0
    winners: list = []
    for meta in profiles:
        longest = max((len(r) for r in meta.get("roots", []) if urls.matches(key, r)), default=0)
        if not longest:
            continue
        if longest > best:
            best, winners = longest, [meta]
        elif longest == best:
            winners.append(meta)
    if len(winners) == 1:
        meta = winners[0]
        return {"ok": True, "match": "existing", "normalized": norm, "id": meta["id"],
                "status": meta.get("status"), "mode": meta.get("mode")}
    if winners:
        return {"ok": True, "match": "ambiguous", "normalized": norm,
                "candidates": [_summary(m) for m in winners]}
    unit = urls.domain_unit(norm)
    same = [m for m in profiles
            if any(urls.domain_unit(r) == unit for r in m.get("roots", []))]
    if same:
        return {"ok": True, "match": "ambiguous", "normalized": norm,
                "candidates": [_summary(m) for m in same]}
    return {"ok": True, "match": "new", "normalized": norm}


def list_all() -> list:
    return [{"id": m.get("id"), "name": m.get("name"), "roots": m.get("roots", []),
             "mode": m.get("mode"), "version": m.get("version"), "status": m.get("status")}
            for m in find_all()]


# --- init / add-root ---------------------------------------------------------

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:64].strip("-")


def _raw_name(root: str) -> str:
    host, *segs = root.split("/")
    if host == "github.com" and len(segs) >= 2:
        return segs[1]
    if host == "npmjs.com" and segs[:1] == ["package"] and len(segs) >= 2:
        return "/".join(segs[1:])
    if host == "pypi.org" and segs[:1] == ["project"] and len(segs) >= 2:
        return segs[1]
    bare = host.split(":")[0]
    labels = bare.split(".")
    if len(labels) > 1:
        labels = labels[:-1]
    return " ".join([".".join(labels)] + segs)


def _free_id(base: str) -> str:
    base = _slug(base) or "dossier"
    candidate, n = base, 1
    while (store.home() / candidate).exists():
        n += 1
        suffix = "-%d" % n
        candidate = base[:64 - len(suffix)].rstrip("-") + suffix
    if not _ID_RE.match(candidate):
        raise BlockedError("bad_input", "Cannot derive a valid dossier id from this URL.")
    return candidate


def _existing_info(meta: dict, created: bool) -> dict:
    return {"ok": True, "created": created, "id": meta["id"], "name": meta.get("name"),
            "lang": meta.get("lang"), "mode": meta.get("mode"), "status": meta.get("status"),
            "names": meta.get("names"), "roots": meta.get("roots", []),
            "path": str(store.dossier_dir(meta["id"]))}


def init(url: str, lang: str, mode: str, custom_names: "dict | None") -> dict:
    if mode != "use":
        raise BlockedError("mode_not_available",
                           "Mode %r is not available yet; only 'use' is." % mode)
    if not isinstance(lang, str) or not lang.strip():
        raise BlockedError("bad_input", "A language code is required.")
    lang = lang.strip()
    resolved = names_mod.resolve(lang, custom_names)
    found = lookup(url)
    if found["match"] == "existing":
        return _existing_info(load(found["id"])[0], False)
    if found["match"] == "ambiguous":
        ids = ", ".join(c["id"] for c in found["candidates"])
        raise BlockedError("ambiguous_url",
                           "This URL may belong to an existing dossier (%s). Ask the person." % ids)
    root = urls.root_for(url)
    raw = _raw_name(root)
    dossier_id = _free_id(raw)
    with store.locked(dossier_id) as folder:
        for sub in (resolved["topics_dir"], resolved["exams_dir"]):
            (folder / sub).mkdir(parents=True, exist_ok=True)
        sources = folder / resolved["sources_dir"]
        for sub in (resolved["docs_dir"], resolved["code_dir"], resolved["meta_dir"]):
            (sources / sub).mkdir(parents=True, exist_ok=True)
        meta = {
            "teach_me": "profile", "id": dossier_id, "lang": lang, "names": resolved,
            "mode": "use", "parts_done": [], "public_code": None, "status": "investigating",
            "phases": {}, "roots": [root], "input_url": url.strip(),
            "name": raw if " " not in raw else dossier_id,
            "one_liner": "", "links": {}, "license": {}, "version": {},
            "coverage": {"read": [], "skipped": [], "not_downloaded": []},
        }
        save(dossier_id, meta)
    return _existing_info(meta, True)


def add_root(dossier_id: str, url: str) -> dict:
    root = urls.root_for(url)
    require(dossier_id)
    with store.locked(dossier_id):
        meta, _ = load(dossier_id)
        roots = list(meta.get("roots", []))
        added = root not in roots
        if added:
            roots.append(root)
            meta["roots"] = roots
            save(dossier_id, meta)
    return {"ok": True, "id": dossier_id, "root": root, "added": added, "roots": roots}
