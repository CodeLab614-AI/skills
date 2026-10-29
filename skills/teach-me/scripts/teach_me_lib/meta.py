"""Package and repository metadata: registries, GitHub API, licence check, tag lookup."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import quote

from . import dossier, frontmatter, net, store, urls
from .errors import BlockedError

MAX_BYTES = 5 * 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_json(url: str, what: str, missing_ok: bool = False):
    """(data, raw_text, final_url); with missing_ok a 404 gives None instead of raising."""
    resp = net.get(url, MAX_BYTES)
    if resp.status == 404 and missing_ok:
        return None
    if resp.status == 404:
        raise BlockedError("fetch_failed", "%s was not found (HTTP 404)." % what)
    if resp.status != 200:
        raise BlockedError("fetch_failed", "%s answered HTTP %d." % (what, resp.status))
    try:
        text = resp.body.decode("utf-8")
        return json.loads(text), text, resp.final_url
    except (UnicodeDecodeError, ValueError):
        raise BlockedError("fetch_failed", "%s did not return valid JSON." % what)


def _meta_markdown(url: str, raw_text: str) -> str:
    try:
        raw_text = json.dumps(json.loads(raw_text), indent=2, ensure_ascii=False)
    except ValueError:
        pass
    longest = max([len(m) for m in re.findall(r"`+", raw_text)] + [0])
    fence = "`" * max(3, longest + 1)
    body = "%sjson\n%s\n%s\n" % (fence, raw_text, fence)
    return frontmatter.dump({"teach_me": "meta", "url": url, "fetched_at": _now()}, body)


def _clean_license(value):
    if isinstance(value, dict):
        value = value.get("type") or value.get("spdx_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _repo_license(data):
    """SPDX id of the GitHub repository licence; NOASSERTION (not recognised) is None."""
    lic = _clean_license((data.get("license") or {}).get("spdx_id"))
    return None if lic and lic.upper() == "NOASSERTION" else lic


def _same_license(a, b):
    if not a or not b:
        return None
    return a.lower() == b.lower()


def label_for(text: str) -> str:
    return re.sub(r"[/@]", "_", text)


def _repo_slug(repo: str) -> str:
    text = repo.strip()
    if "/" in text and not text.lower().startswith(("http://", "https://")) \
            and re.match(r"^[\w.-]+/[\w.-]+$", text):
        return text[:-4] if text.endswith(".git") else text
    root = urls.root_for(text)
    parts = root.split("/")
    if parts[0] != "github.com" or len(parts) < 3:
        raise BlockedError("bad_input", "The repository must be OWNER/NAME or a GitHub URL.")
    return "%s/%s" % (parts[1], parts[2])


def find_tag(repo: str, package: str, version: str) -> "str | None":
    api = net.base("github_api")
    for tag in ("%s@%s" % (package, version), "v%s" % version, version,
                "%s-v%s" % (package, version)):
        resp = net.get("%s/repos/%s/git/ref/tags/%s" % (api, repo, quote(tag, safe="@/")), MAX_BYTES)
        if resp.status == 200:
            return tag
    return None


def registry_package(registry: str, name: str):
    """Latest version of one package. Returns (pkg, meta_file_name, raw_text, final_url)."""
    if registry == "npm":
        url = "%s/%s" % (net.base("npm"), quote(name, safe="@").replace("/", "%2F"))
        url += "/latest"  # one small version document, not the full packument
        data, text, final = _get_json(url, "npm package %s" % name)
        latest = data.get("version") if isinstance(data, dict) else None
        if not latest or not isinstance(latest, str):
            raise BlockedError("fetch_failed", "npm package %s has no latest version." % name)
        lic = _clean_license(data.get("license"))
        return ({"registry": "npm", "name": name, "latest": latest, "license": lic},
                "npm.md", text, final)
    if registry == "pypi":
        url = "%s/%s/json" % (net.base("pypi"), quote(name, safe=""))
        data, text, final = _get_json(url, "PyPI package %s" % name)
        info = data.get("info") or {}
        latest = info.get("version")
        if not latest:
            raise BlockedError("fetch_failed", "PyPI package %s has no version." % name)
        lic = _clean_license(info.get("license_expression"))
        if not lic:
            short = _clean_license(info.get("license"))
            lic = short if short and len(short) <= 100 and "\n" not in short else None
        return ({"registry": "pypi", "name": name, "latest": latest, "license": lic},
                "pypi.md", text, final)
    raise BlockedError("bad_input", "Unknown registry %r." % (registry,))


def head_sha(slug: str) -> "str | None":
    """Head commit sha of the default branch of OWNER/NAME (GitHub API)."""
    api = net.base("github_api")
    data, _t, _f = _get_json("%s/repos/%s" % (api, slug), "GitHub repository %s" % slug)
    branch = data.get("default_branch")
    if not branch:
        return None
    cdata, _t, _f = _get_json("%s/repos/%s/commits/%s" % (api, slug, quote(branch, safe="/")),
                              "the head commit of %s" % slug)
    return cdata.get("sha")


def _get_json_or_none(url: str, what: str):
    """The JSON document, or None on a 404; every other failure still raises."""
    got = _get_json(url, what, missing_ok=True)
    return got[0] if got else None


def _tag_commit_date(slug: str, tag: str) -> "str | None":
    """Committer date of the commit a tag points to (follows an annotated tag once)."""
    api = net.base("github_api")
    ref = _get_json_or_none("%s/repos/%s/git/ref/tags/%s" % (api, slug, quote(tag, safe="@/")),
                            "tag %s" % tag)
    obj = (ref or {}).get("object") or {}
    if obj.get("type") == "tag" and obj.get("sha"):
        annotated = _get_json_or_none("%s/repos/%s/git/tags/%s" % (api, slug, quote(obj["sha"], safe="")),
                                      "annotated tag %s" % tag)
        obj = (annotated or {}).get("object") or {}
    if obj.get("type") != "commit" or not obj.get("sha"):
        return None
    commit = _get_json_or_none("%s/repos/%s/commits/%s" % (api, slug, quote(obj["sha"], safe="")),
                               "the commit of tag %s" % tag)
    return (((commit or {}).get("commit") or {}).get("committer") or {}).get("date")


def release_date(slug: str, tag: "str | None") -> "tuple[str | None, str | None]":
    """(iso_date, source) of the last release: the exact tag's release, else its commit date.

    Without a tag it is the repository's latest release. In a monorepo that one may belong to
    another package, which is why the tag comes first. A 404 means "no release", not an error."""
    api = net.base("github_api")
    if tag:
        data = _get_json_or_none("%s/repos/%s/releases/tags/%s" % (api, slug, quote(tag, safe="@/")),
                                 "the release of tag %s" % tag)
        date = data.get("published_at") if isinstance(data, dict) else None
        if date:
            return date, "release"
        date = _tag_commit_date(slug, tag)
        return (date, "tag_commit") if date else (None, None)
    data = _get_json_or_none("%s/repos/%s/releases/latest" % (api, slug),
                             "the latest release of %s" % slug)
    date = data.get("published_at") if isinstance(data, dict) else None
    return (date, "latest_release") if date else (None, None)


def fetch_meta(dossier_id: str, npm: "str | None", pypi: "str | None",
               repo: "str | None") -> dict:
    if npm and pypi:
        raise BlockedError("bad_input", "Give --npm or --pypi, not both.")
    if not (npm or pypi or repo):
        raise BlockedError("bad_input", "Give at least one of --npm, --pypi or --repo.")
    slug = _repo_slug(repo) if repo else None
    dossier.require(dossier_id)

    files: dict = {}
    notices: list = []
    out: dict = {"ok": True}
    pkg = None
    if npm or pypi:
        pkg, md_name, text, final = registry_package("npm" if npm else "pypi", npm or pypi)
        files[md_name] = _meta_markdown(final, text)
    if pkg:
        out["package"] = pkg

    repo_info = None
    last_commit_at = None
    if slug:
        api = net.base("github_api")
        data, text, final = _get_json("%s/repos/%s" % (api, slug), "GitHub repository %s" % slug)
        files["github.md"] = _meta_markdown(final, text)
        branch = data.get("default_branch")
        head_sha = None
        if branch:
            cdata, ctext, cfinal = _get_json(
                "%s/repos/%s/commits/%s" % (api, slug, quote(branch, safe="/")),
                "the head commit of %s" % slug)
            head_sha = cdata.get("sha")
            last_commit_at = ((cdata.get("commit") or {}).get("committer") or {}).get("date")
            files["github-commit.md"] = _meta_markdown(cfinal, ctext)
        repo_lic = _repo_license(data)  # NOASSERTION: GitHub did not recognise it, so unknown
        repo_info = {
            "full_name": data.get("full_name") or slug, "default_branch": branch,
            "size_kb": data.get("size"),
            "license_spdx": repo_lic,
            "head_sha": head_sha, "pushed_at": data.get("pushed_at"),
        }
        out["repo"] = repo_info

    lic_pkg = pkg["license"] if pkg else None
    lic_repo = repo_info["license_spdx"] if repo_info else None
    match = _same_license(lic_pkg, lic_repo)
    out["license"] = {"registry": lic_pkg, "repo": lic_repo, "match": match}
    if match is False:
        notices.append("license_mismatch")

    tag = None
    sha = repo_info["head_sha"] if repo_info else None
    if pkg and slug:
        tag = find_tag(slug, pkg["name"], pkg["latest"])
        if tag is None:
            notices.append("tag_not_found")
    if pkg:
        label = label_for(tag) if tag else (sha or pkg["latest"])
        version = {"kind": "package", "value": pkg["latest"], "tag": tag, "sha": sha,
                   "label": label, "docs_fingerprint": None, "other_packages": {}}
    elif sha:
        version = {"kind": "snapshot", "value": sha, "tag": None, "sha": sha,
                   "label": sha, "docs_fingerprint": None, "other_packages": {}}
    else:
        version = None
    out["tag"] = tag
    if slug:
        released_at, source = release_date(slug, tag)
        out["activity"] = {"last_release_at": released_at, "release_source": source,
                           "last_commit_at": last_commit_at}
    out["notices"] = notices

    with store.locked(dossier_id) as folder:
        profile, _ = dossier.load(dossier_id)
        meta_dir = folder / profile["names"]["sources_dir"] / profile["names"]["meta_dir"]
        meta_dir.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            store.atomic_write(meta_dir / name, text)
        if version is not None:
            old = profile.get("version") or {}
            version["docs_fingerprint"] = old.get("docs_fingerprint")
            profile["version"] = version
        profile["license"] = out["license"]
        if "activity" in out:
            profile["activity"] = out["activity"]
        profile.setdefault("phases", {})["meta"] = _now()
        dossier.save(dossier_id, profile)
        if slug and profile.get("status") == "investigating":
            repo_root = urls.root_for("https://github.com/" + slug)
            same = [dossier._summary(m) for m in dossier.find_all()
                    if m.get("id") != dossier_id and repo_root in m.get("roots", [])]
            if same:
                out["same_repo_as"] = same
    return out
