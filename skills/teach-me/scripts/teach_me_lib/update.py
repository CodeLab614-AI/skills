"""Detect a new version of a studied library. Read-only: no lock, writes nothing."""
from __future__ import annotations

from . import docs, dossier, meta
from .errors import BlockedError


def check(dossier_id: str) -> dict:
    dossier.require(dossier_id)
    profile, _ = dossier.load(dossier_id)
    version = profile.get("version") or {}
    kind = version.get("kind")
    if not kind:
        raise BlockedError("bad_input", "The dossier has no stored version yet; run fetch-meta first.")
    links = profile.get("links") or {}

    if kind == "package":
        pkg = links.get("package")
        if not isinstance(pkg, dict) or not pkg.get("name"):
            raise BlockedError("bad_input", "The profile has no package link; run update-profile first.")
        latest = meta.registry_package(pkg.get("registry"), pkg["name"])[0]["latest"]
        changed = latest != version.get("value")
        new_tag = None
        if changed and links.get("repo"):
            new_tag = meta.find_tag(meta._repo_slug(links["repo"]), pkg["name"], latest)
        return {"ok": True, "changed": changed, "kind": "package",
                "from": version.get("value"), "to": latest, "new_tag": new_tag}

    if kind == "snapshot":
        if not links.get("repo"):
            raise BlockedError("bad_input", "The profile has no repo link; run update-profile first.")
        sha = meta.head_sha(meta._repo_slug(links["repo"]))
        code_changed = sha != version.get("sha")
        docs_changed = False
        if links.get("docs") and version.get("docs_fingerprint"):
            _m, _pages, fingerprint = docs.collect(links["docs"])
            docs_changed = fingerprint != version["docs_fingerprint"]
        return {"ok": True, "changed": code_changed or docs_changed, "kind": "snapshot",
                "from": version.get("sha"), "to": sha, "new_tag": None,
                "code_changed": code_changed, "docs_changed": docs_changed}

    raise BlockedError("bad_input", "Unknown version kind %r." % (kind,))
