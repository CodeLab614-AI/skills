"""Competitor candidates: package search in the registries (design section 8.1)."""
from __future__ import annotations

import hashlib
from urllib.parse import quote, urlsplit

from . import dossier, meta, net, store, urls
from .errors import BlockedError

PYPI_NO_SEARCH = ("PyPI has no search API; find candidates in the docs, the README or with the "
                  "agent's web search.")


def _repository(value):
    """https://github.com/<owner>/<name> for any GitHub URL, else the raw value, else None."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    text = raw[4:] if raw.startswith("git+") else raw
    try:
        norm = urls.normalize(text)
        host, *segs = norm.split("/")
        original = [s for s in urlsplit(text).path.split("/") if s]
    except (BlockedError, ValueError):
        return raw
    if host != "github.com" or len(segs) < 2:
        return raw
    name = original[1][:-4] if original[1].endswith(".git") else original[1]
    return "https://github.com/%s/%s" % (original[0], name)


def search_packages(dossier_id: str, registry: str, text: str, size: int = 10) -> dict:
    dossier.require(dossier_id)
    if registry == "pypi":
        raise BlockedError("search_not_available", PYPI_NO_SEARCH)
    if registry != "npm":
        raise BlockedError("bad_input", "Unknown registry %r." % (registry,))
    if not isinstance(text, str) or not text.strip():
        raise BlockedError("bad_input", "The search text is empty.")
    if not 1 <= size <= 20:
        raise BlockedError("bad_input", "--size must be between 1 and 20.")
    text = text.strip()

    url = "%s/-/v1/search?text=%s&size=%d" % (net.base("npm"), quote(text, safe=""), size)
    data, raw, final = meta._get_json(url, "npm search")
    results = []
    for obj in (data.get("objects") if isinstance(data, dict) else None) or []:
        pkg = obj.get("package") if isinstance(obj, dict) else None
        if not isinstance(pkg, dict) or not pkg.get("name"):
            continue
        links = pkg.get("links") if isinstance(pkg.get("links"), dict) else {}
        results.append({
            "name": pkg["name"], "version": pkg.get("version"),
            "description": pkg.get("description"),
            "repository": _repository(links.get("repository")),
            "npm_url": links.get("npm") or "https://www.npmjs.com/package/%s" % pkg["name"],
        })

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    with store.locked(dossier_id) as folder:
        profile, _ = dossier.load(dossier_id)
        meta_dir = folder / profile["names"]["sources_dir"] / profile["names"]["meta_dir"]
        meta_dir.mkdir(parents=True, exist_ok=True)
        store.atomic_write(meta_dir / ("search-npm-%s.md" % digest), meta._meta_markdown(final, raw))
    return {"ok": True, "registry": "npm", "results": results}
