"""Competitor candidates: package search in the registries (design section 8.1)."""
from __future__ import annotations

import hashlib
from urllib.parse import quote, urlsplit

from . import dossier, docs, meta, net, store, urls
from .errors import BlockedError

README_LIMIT = 1024 * 1024
STALE_SUFFIXES = ("npm.md", "pypi.md", "github.md", "github-commit.md", "github-readme.md")

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


def fetch_competitor(dossier_id: str, repo: str, npm: "str | None", pypi: "str | None") -> dict:
    """Verify one competitor from real data and keep its README as a citable page."""
    if npm and pypi:
        raise BlockedError("bad_input", "Give --npm or --pypi, not both.")
    slug = meta._repo_slug(repo)
    dossier.require(dossier_id)

    api = net.base("github_api")
    notices: list = []
    files: dict = {}
    pkg = None
    if npm or pypi:
        pkg, md_name, text, final = meta.registry_package("npm" if npm else "pypi", npm or pypi)
        files[md_name] = meta._meta_markdown(final, text)

    data, text, final = meta._get_json("%s/repos/%s" % (api, slug), "GitHub repository %s" % slug)
    files["github.md"] = meta._meta_markdown(final, text)
    last_commit_at = None
    branch = data.get("default_branch")
    if branch:
        cdata, ctext, cfinal = meta._get_json(
            "%s/repos/%s/commits/%s" % (api, slug, quote(branch, safe="/")),
            "the head commit of %s" % slug)
        last_commit_at = ((cdata.get("commit") or {}).get("committer") or {}).get("date")
        files["github-commit.md"] = meta._meta_markdown(cfinal, ctext)
    full_name = data.get("full_name") or slug

    lic_pkg = pkg["license"] if pkg else None
    lic_repo = meta._repo_license(data)
    match = meta._same_license(lic_pkg, lic_repo)
    if match is False:
        notices.append("license_mismatch")

    tag = meta.find_tag(slug, pkg["name"], pkg["latest"]) if pkg else None
    released_at, source = meta.release_date(slug, tag)

    readme_url = None
    readme_text = None
    got = meta._get_json("%s/repos/%s/readme" % (api, slug), "the README of %s" % slug,
                         missing_ok=True)
    if got is not None:
        readme_url = got[0].get("download_url") if isinstance(got[0], dict) else None
        files["github-readme.md"] = meta._meta_markdown(got[2], got[1])
    if readme_url:
        try:
            resp = net.get(readme_url, README_LIMIT)
        except BlockedError:
            resp = None
        if resp is not None and resp.status == 200:
            readme_text = docs._decode(resp.body, resp.content_type)
    if readme_text is None:
        readme_url = None
        notices.append("no_readme")

    entry = {
        "repo": slug.lower(), "url": "https://github.com/%s" % full_name,
        "package": {"registry": pkg["registry"], "name": pkg["name"]} if pkg else None,
        "latest": pkg["latest"] if pkg else None,
        "license": {"registry": lic_pkg, "repo": lic_repo, "match": match},
        "activity": {"last_release_at": released_at, "release_source": source,
                     "last_commit_at": last_commit_at},
        "readme_url": readme_url, "fetched_at": meta._now(),
    }

    key = slug.lower()
    prefix = "competitor-%s-" % key.replace("/", "__")
    with store.locked(dossier_id) as folder:
        profile, _ = dossier.load(dossier_id)
        if readme_text is not None:
            # the same URL form fetch-docs stores and sources._resolve_doc looks up (no .md suffix)
            docs.store_page(dossier_id, docs.clean_url(readme_url) or readme_url, readme_text, "md")
        meta_dir = folder / profile["names"]["sources_dir"] / profile["names"]["meta_dir"]
        meta_dir.mkdir(parents=True, exist_ok=True)
        # only this competitor's files (a prefix glob would also catch acme/widget-extra)
        for suffix in STALE_SUFFIXES:
            (meta_dir / (prefix + suffix)).unlink(missing_ok=True)
        for name, body in files.items():
            store.atomic_write(meta_dir / (prefix + name), body)
        found = profile.get("competitors")
        found = found if isinstance(found, dict) else {}
        found[key] = entry
        profile["competitors"] = found
        dossier.save(dossier_id, profile)
    return dict(entry, ok=True, notices=notices)
