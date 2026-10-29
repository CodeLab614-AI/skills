"""fetch-code: download the exact source tarball and extract it member by member, safely.

The tarball is untrusted data. Nothing is ever executed, `extract`/`extractall` are never
used, links are never created and every path is checked against the destination."""
from __future__ import annotations

import json
import os
import re
import shutil
import tarfile
import tempfile
import zlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from . import dossier, frontmatter, meta as meta_mod, modes, net, store
from .errors import BlockedError

MAX_TARBALL = 300 * 1024 * 1024
MAX_FILE = 1024 * 1024
BINARY_SNIFF = 8 * 1024
IGNORED = frozenset(["node_modules", ".git", "dist", "build", ".next", "coverage", "vendor"])
_DRIVE = re.compile(r"^[A-Za-z]:")
INVENTORY = "_inventory.md"
MAX_EXAMPLES = 300
ROOT_DOCS = frozenset(["readme", "license", "licence", "copying", "changelog"])


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _label(profile: dict, ref: str) -> str:
    version = profile.get("version") or {}
    label = version.get("label") or meta_mod.label_for(ref)
    if not isinstance(label, str) or not label or label in (".", "..") \
            or "/" in label or "\\" in label or "\x00" in label:
        raise BlockedError("bad_input", "The version label %r cannot be used as a folder name." % (label,))
    return label


def _count_lines(data: bytes) -> int:
    text = data.decode("utf-8", errors="replace")
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _unsafe_name(name: str) -> bool:
    return (not name or name.startswith("/") or "\\" in name or "\x00" in name
            or bool(_DRIVE.match(name)) or ".." in name.split("/"))


def _inside(dest: Path, target: Path) -> bool:
    try:
        resolved = target.resolve()
    except (OSError, RuntimeError):
        return False
    return resolved == dest or dest in resolved.parents


def _safe_target(dest: Path, rel_parts: list) -> "Path | None":
    """Path under dest for rel_parts, or None if it could leave dest (resolved check plus
    a symlink check on every existing component)."""
    cur = dest
    for part in rel_parts:
        cur = cur / part
        if os.path.islink(str(cur)):
            return None
    return cur if _inside(dest, cur) else None


def _open_tar(tar_path: Path):
    try:
        return tarfile.open(str(tar_path), "r:gz")
    except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
        raise BlockedError("fetch_failed", "The download is not a readable .tar.gz archive: %s" % exc)


def _corrupt(exc: BaseException) -> BlockedError:
    return BlockedError("fetch_failed", "The archive is corrupt or truncated: %s" % exc)


def _split(member) -> "list | None":
    """Path parts of a member below the top folder, or None when the name is unsafe."""
    name = member.name
    if _unsafe_name(name):
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    return parts[1:]


def _read_small(tf, member) -> "bytes | None":
    if member.size > MAX_FILE:
        return None
    fh = tf.extractfile(member)
    if fh is None:
        return None
    data = fh.read(MAX_FILE + 1)
    return None if len(data) > MAX_FILE else data


def _pep503(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pyproject_names(text: str) -> set:
    names: set = set()
    section = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("["):
            m = re.match(r"^\[\s*([^\[\]]+?)\s*\]\s*(?:#.*)?$", s)
            section = m.group(1) if m else None
            continue
        if section in ("project", "tool.poetry"):
            m = re.match(r"""^name\s*=\s*(["'])(.*?)\1\s*(?:#.*)?$""", s)
            if m:
                names.add(m.group(2))
    return names


def _manifest_matches(data: bytes, registry: str, name: str) -> bool:
    text = data.decode("utf-8", errors="replace")
    if registry == "npm":
        try:
            doc = json.loads(text)
        except ValueError:
            return False
        return isinstance(doc, dict) and doc.get("name") == name
    wanted = _pep503(name)
    return any(_pep503(n) == wanted for n in _pyproject_names(text))


def _find_package_dir(tar_path: Path, registry: str, name: str) -> "str | None":
    """Folder (relative to the repo root, "" for the root) of the manifest that names the
    package: the root if it matches, else the shallowest match (then first by path)."""
    wanted = "package.json" if registry == "npm" else "pyproject.toml"
    found: list = []
    tf = _open_tar(tar_path)
    try:
        for member in tf:
            if not member.isreg() or member.size > MAX_FILE:
                continue
            rel_parts = _split(member)
            if not rel_parts or rel_parts[-1] != wanted:
                continue
            dirs = rel_parts[:-1]
            if any(p in IGNORED or p == "examples" for p in dirs):
                continue
            data = _read_small(tf, member)
            if data is not None and _manifest_matches(data, registry, name):
                found.append("/".join(dirs))
    except (tarfile.TarError, EOFError, zlib.error, OSError) as exc:
        raise _corrupt(exc)
    finally:
        tf.close()
    if not found:
        return None
    if "" in found:
        return ""
    return min(found, key=lambda d: (d.count("/"), d))


def _import_pattern(registry: str, name: str):
    if registry == "npm":
        return re.compile(r"""\b(?:from|import|require)\s*\(?\s*(['"])%s(?:/[^'"]*)?\1""" % re.escape(name))
    mod = re.escape(name.lower().replace("-", "_").replace(".", "_"))
    return re.compile(r"^[ \t]*(?:from[ \t]+%s(?:\.[\w.]+)?[ \t]+import\b|import[ \t]+%s(?:\.[\w.]+)?\b)"
                      % (mod, mod), re.M)


def _pick_examples(tar_path: Path, registry: str, name: str) -> set:
    """Up to MAX_EXAMPLES files of the root examples/ folder that import the package, spread
    round-robin across its first-level sub-folders (loose files are one group, key "", first;
    groups alphabetical, each group by path). Independent of the order of the tar members."""
    pattern = _import_pattern(registry, name)
    found: list = []
    tf = _open_tar(tar_path)
    try:
        for member in tf:
            if not member.isreg():
                continue
            rel_parts = _split(member)
            if not rel_parts or len(rel_parts) < 2 or rel_parts[0] != "examples":
                continue
            if any(p in IGNORED for p in rel_parts):
                continue
            data = _read_small(tf, member)
            if data is None or b"\x00" in data[:BINARY_SNIFF]:
                continue
            if pattern.search(data.decode("utf-8", errors="replace")):
                found.append("/".join(rel_parts))
    except (tarfile.TarError, EOFError, zlib.error, OSError) as exc:
        raise _corrupt(exc)
    finally:
        tf.close()
    groups: dict = {}
    for rel in found:
        parts = rel.split("/")
        groups.setdefault(parts[1] if len(parts) > 2 else "", []).append(rel)
    queues = [sorted(groups[k]) for k in sorted(groups)]
    picked: set = set()
    depth = 0
    while len(picked) < MAX_EXAMPLES and any(depth < len(q) for q in queues):
        for q in queues:
            if depth < len(q) and len(picked) < MAX_EXAMPLES:
                picked.add(q[depth])
        depth += 1
    return picked


def _package_of(profile: dict) -> "tuple | None":
    links = profile.get("links")
    pkg = links.get("package") if isinstance(links, dict) else None
    if isinstance(pkg, dict) and pkg.get("registry") in ("npm", "pypi") \
            and isinstance(pkg.get("name"), str) and pkg["name"].strip():
        return pkg["registry"], pkg["name"].strip()
    return None


def _is_root_doc(rel_parts: list) -> bool:
    if len(rel_parts) != 1:
        return False
    name = rel_parts[0]
    return name in ("package.json", "pyproject.toml") \
        or os.path.splitext(name)[0].lower() in ROOT_DOCS


def _under(rel: str, folder: str) -> bool:
    return rel == folder or rel.startswith(folder + "/")


def _extract(tar_path: Path, dest: Path, select=None, fresh: bool = True,
             track_unsaved: bool = False, only_new: bool = False) -> dict:
    """Extract member by member. `select(rel, member)` says whether a member is in the saved
    scope (None: everything). Returns files, skipped, unsaved (paths outside the scope), the
    list of files created and whether any member was in scope."""
    files: list = []
    skipped: list = []
    unsaved: list = []
    created: list = []
    if fresh:
        dest.mkdir(parents=True)
    else:
        dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()
    seen_ignored: set = set()
    found = False

    def skip(path: str, reason: str) -> None:
        skipped.append({"path": path, "reason": reason})

    tf = _open_tar(tar_path)
    try:
        for member in tf:
            name = member.name
            rel_parts = _split(member)
            if rel_parts is None:
                skip(name, "unsafe_path")
                continue
            if not rel_parts:
                continue  # top directory itself or a top-level entry
            rel = "/".join(rel_parts)
            if select is not None and not select(rel, rel_parts, member):
                if track_unsaved and not member.isdir():
                    unsaved.append(rel)
                continue
            found = True
            ignored_at = next((i for i, p in enumerate(rel_parts) if p in IGNORED), None)
            if ignored_at is not None:
                ignored_path = "/".join(rel_parts[:ignored_at + 1])
                if ignored_path not in seen_ignored:
                    seen_ignored.add(ignored_path)
                    skip(ignored_path, "ignored_dir")
                continue
            if member.issym() or member.islnk():
                skip(rel, "link")
                continue
            if not (member.isreg() or member.isdir()):
                skip(name, "unsafe_path")
                continue
            target = _safe_target(dest_resolved, rel_parts)
            if target is None:
                skip(name, "unsafe_path")
                continue
            if member.isdir():
                try:
                    target.mkdir(parents=True, exist_ok=True)
                except OSError:
                    skip(name, "unsafe_path")
                continue
            if only_new and target.is_file() and not os.path.islink(str(target)):
                continue  # already saved: left as it is
            if member.size > MAX_FILE:
                skip(rel, "too_large")
                continue
            fh = tf.extractfile(member)
            if fh is None:
                skip(name, "unsafe_path")
                continue
            data = fh.read(MAX_FILE + 1)
            if len(data) > MAX_FILE:
                skip(rel, "too_large")
                continue
            if b"\x00" in data[:BINARY_SNIFF]:
                skip(rel, "binary")
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                if os.path.islink(str(target)) or target.is_dir() or not _inside(dest_resolved, target.parent):
                    skip(name, "unsafe_path")
                    continue
                with open(str(target), "wb") as out:  # default permissions, no mode bits copied
                    out.write(data)
                created.append(target)
            except OSError:
                skip(name, "unsafe_path")
                continue
            files.append({"path": rel, "lines": _count_lines(data)})
    except (tarfile.TarError, EOFError, zlib.error, OSError) as exc:
        raise _corrupt(exc)
    finally:
        tf.close()
    files.sort(key=lambda f: f["path"])
    return {"files": files, "skipped": skipped, "unsaved": unsaved,
            "created": created, "found": found}


def _group_unsaved(unsaved: list, files: list) -> list:
    """One not_saved entry per folder: the shallowest folder with no saved file, or the
    folder itself when it also holds saved files; root files one by one."""
    saved_dirs: set = set()
    for f in files:
        parts = f["path"].split("/")[:-1]
        for i in range(1, len(parts) + 1):
            saved_dirs.add("/".join(parts[:i]))
    entries: set = set()
    for rel in unsaved:
        parts = rel.split("/")
        if len(parts) == 1:
            entries.add(rel)
            continue
        chosen = "/".join(parts[:-1])
        for i in range(1, len(parts)):
            folder = "/".join(parts[:i])
            if folder not in saved_dirs:
                chosen = folder
                break
        entries.add(chosen)
    return [{"path": p, "reason": "not_saved"} for p in sorted(entries)]


def _by_reason(skipped: list) -> dict:
    counts: dict = {}
    for entry in skipped:
        counts[entry["reason"]] = counts.get(entry["reason"], 0) + 1
    return counts


def _write_inventory(dest: Path, files: list, counts: dict, info: dict, not_saved: list) -> None:
    lines = ["# Code inventory", ""] + ["- %s (%d lines)" % (f["path"], f["lines"]) for f in files]
    if not_saved:
        lines += ["", "## Not saved", ""] + ["- %s" % e["path"] for e in not_saved]
    head = {"teach_me": "index"}
    for key in ("repo", "ref", "layout", "package_dir"):
        if key in info:
            head[key] = info[key]
    head.update({"files": files, "skipped": not_saved, "skipped_by_reason": counts})
    store.atomic_write(dest / INVENTORY, frontmatter.dump(head, "\n".join(lines) + "\n"))


def _read_inventory(final: Path) -> "dict | None":
    inv = final / INVENTORY
    if not inv.is_file():
        return None
    try:
        head, _ = frontmatter.parse(inv.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None
    return head if isinstance(head.get("files"), list) else None


def saved_inventory(meta: dict) -> "dict | None":
    """Inventory header of the code saved for the current version, None without one."""
    version = meta.get("version")
    label = version.get("label") if isinstance(version, dict) else None
    if not isinstance(label, str) or not label:
        return None
    names = meta["names"]
    return _read_inventory(store.dossier_dir(meta["id"]) / names["sources_dir"] / names["code_dir"] / label)


def _done(final: Path) -> "dict | None":
    head = _read_inventory(final)
    if head is None:
        return None
    counts = head.get("skipped_by_reason")
    out = {"ok": True, "files": len(head["files"]),
           "skipped_by_reason": counts if isinstance(counts, dict) else {},
           "path": str(final.resolve()),
           "layout": head.get("layout") if head.get("layout") in ("single", "monorepo", "full") else "single"}
    if out["layout"] == "monorepo" and isinstance(head.get("package_dir"), str):
        out["package_dir"] = head["package_dir"]
    return out


def _download(slug: str, ref: str, folder: Path, tmp: Path) -> None:
    url = "%s/%s/tar.gz/%s" % (net.base("codeload"), slug, quote(ref, safe="@/.-_"))
    resp = net.download(url, tmp, MAX_TARBALL)
    if resp.status != 200:
        what = "was not found" if resp.status == 404 else "answered HTTP %d" % resp.status
        raise BlockedError("fetch_failed", "The source for %s at ref %r %s (%s)."
                           % (slug, ref, what, url))


def _plan(tar_path: Path, package: "tuple | None") -> dict:
    """Decide the layout before anything is written."""
    notices: list = []
    if package is None:
        return {"layout": "single", "select": None, "notices": notices}
    registry, name = package
    pkg_dir = _find_package_dir(tar_path, registry, name)
    if pkg_dir is None:
        notices.append("package_dir_not_found")
        return {"layout": "single", "select": None, "notices": notices}
    if pkg_dir == "":
        return {"layout": "single", "select": None, "notices": notices}
    examples = _pick_examples(tar_path, registry, name)

    def select(rel, rel_parts, member):
        if _under(rel, pkg_dir):
            return True
        if member.isreg() and _is_root_doc(rel_parts):
            return True
        return rel in examples

    return {"layout": "monorepo", "select": select, "package_dir": pkg_dir, "notices": notices}


def fetch(dossier_id: str, repo: str, ref: str) -> dict:
    slug = meta_mod._repo_slug(repo)
    if not isinstance(ref, str) or not ref.strip() or "\x00" in ref:
        raise BlockedError("bad_input", "Give a non-empty --ref.")
    ref = ref.strip()
    dossier.require(dossier_id)
    profile, _ = dossier.load(dossier_id)
    label = _label(profile, ref)
    folder = store.dossier_dir(dossier_id)
    code_dir = folder / profile["names"]["sources_dir"] / profile["names"]["code_dir"]
    final = code_dir / label
    done = _done(final)
    if done is not None:
        return done

    fd, tmp_name = tempfile.mkstemp(dir=str(folder), prefix=".tmp-code-", suffix=".tar.gz")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        _download(slug, ref, folder, tmp)
        if modes.needs_full_code(profile.get("mode", "use")):
            plan = {"layout": "full", "select": None, "notices": []}  # the internals modes save it all
        else:
            plan = _plan(tmp, _package_of(profile))
        with store.locked(dossier_id):
            done = _done(final)
            if done is not None:
                return done
            code_dir.mkdir(parents=True, exist_ok=True)
            partial = code_dir / (label + ".partial")
            if partial.exists() or partial.is_symlink():
                shutil.rmtree(str(partial), ignore_errors=True)
            try:
                res = _extract(tmp, partial, plan["select"], track_unsaved=plan["select"] is not None)
                files = res["files"]
                not_saved = _group_unsaved(res["unsaved"], files)
                skipped = res["skipped"] + not_saved
                counts = _by_reason(skipped)
                info = {"repo": slug, "ref": ref, "layout": plan["layout"]}
                if plan["layout"] == "monorepo":
                    info["package_dir"] = plan["package_dir"]
                _write_inventory(partial, files, counts, info, not_saved)
                if final.exists() or final.is_symlink():
                    shutil.rmtree(str(final), ignore_errors=True)
                os.replace(str(partial), str(final))
            except BaseException:
                shutil.rmtree(str(partial), ignore_errors=True)
                raise
            profile, _ = dossier.load(dossier_id)
            cov = profile.setdefault("coverage", {"read": [], "skipped": [], "not_downloaded": []})
            current = cov.setdefault("skipped", [])
            for entry in skipped:
                if entry not in current:
                    current.append(entry)
            version = profile.get("version")
            if not isinstance(version, dict):
                version = profile["version"] = {}
            if not version.get("label"):
                version["label"] = label
            profile.setdefault("phases", {})["code"] = _now()
            profile["public_code"] = True
            dossier.save(dossier_id, profile)
        out = {"ok": True, "files": len(files), "skipped_by_reason": counts,
               "path": str(final.resolve()), "layout": plan["layout"]}
        if plan["layout"] == "monorepo":
            out["package_dir"] = plan["package_dir"]
        if plan["notices"]:
            out["notices"] = plan["notices"]
        return out
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _normalize_path(path) -> str:
    if not isinstance(path, str) or not path.strip() or path.startswith("/") or "\\" in path \
            or "\x00" in path or _DRIVE.match(path) or ".." in path.split("/"):
        raise BlockedError("bad_input", "--path must be a relative path inside the repository "
                           "(no absolute path, no '..', no backslash).")
    rel = "/".join(p for p in path.strip().split("/") if p not in ("", "."))
    if not rel:
        raise BlockedError("bad_input", "--path must name a folder or a file of the repository.")
    return rel


_NO_CODE = ("No code is saved for this version yet: run fetch-code <id> --repo <owner/name> "
            "--ref <ref> first. --path only adds to code that is already saved.")
_NEEDS_REPO_REF = ("The code of this version has no recorded repository and ref (it was saved "
                   "before they were kept): pass --repo and --ref together with --path.")


def _saved_target(dossier_id: str, repo, ref) -> tuple:
    """(profile, folder, final, head, slug, ref, label) of the code already saved for the
    current version; `repo`/`ref` override what the inventory recorded."""
    dossier.require(dossier_id)
    profile, _ = dossier.load(dossier_id)
    version = profile.get("version") if isinstance(profile.get("version"), dict) else {}
    ref = ref.strip() if isinstance(ref, str) and ref.strip() else None
    if isinstance(version.get("label"), str) and version["label"]:
        label = _label(profile, ref or "")
    elif ref:
        label = _label(profile, ref)
    else:
        raise BlockedError("bad_input", _NO_CODE)
    folder = store.dossier_dir(dossier_id)
    final = folder / profile["names"]["sources_dir"] / profile["names"]["code_dir"] / label
    head = _read_inventory(final)
    if head is None:
        raise BlockedError("bad_input", _NO_CODE)
    use_repo = repo or head.get("repo")
    use_ref = ref or head.get("ref")
    if not isinstance(use_repo, str) or not use_repo or not isinstance(use_ref, str) or not use_ref:
        raise BlockedError("bad_input", _NEEDS_REPO_REF)
    return folder, final, meta_mod._repo_slug(use_repo), use_ref, label


def _grow(dossier_id: str, target: tuple, select, covered, keep: tuple, layout=None,
          missing: "str | None" = None) -> dict:
    """Download the same version again and add what `select` picks to the saved code, leaving
    saved files alone. `covered(path)` says which not_saved entries this call settles; `keep`
    are the inventory keys carried over (plus `layout` when given). Rolls back on failure."""
    folder, final, slug, use_ref, label = target
    fd, tmp_name = tempfile.mkstemp(dir=str(folder), prefix=".tmp-code-", suffix=".tar.gz")
    os.close(fd)
    tmp = Path(tmp_name)
    created: list = []
    try:
        _download(slug, use_ref, folder, tmp)
        with store.locked(dossier_id):
            head = _read_inventory(final)
            if head is None:
                raise BlockedError("bad_input", _NO_CODE)
            old_files = [f for f in head.get("files", []) if isinstance(f, dict)]
            try:
                res = _extract(tmp, final, select, fresh=False, only_new=True)
                created = res["created"]
                if missing and not res["found"]:
                    raise BlockedError("path_not_found", missing % (slug, use_ref))
                by_path = {f["path"]: f for f in old_files if isinstance(f.get("path"), str)}
                for f in res["files"]:
                    by_path[f["path"]] = f
                files = [by_path[k] for k in sorted(by_path)]
                kept = [e for e in head.get("skipped", []) if isinstance(e, dict)
                        and not (e.get("reason") == "not_saved" and isinstance(e.get("path"), str)
                                 and covered(e["path"]))]
                removed = len(head.get("skipped", [])) - len(kept) if isinstance(head.get("skipped"), list) else 0
                profile, _ = dossier.load(dossier_id)
                cov = profile.setdefault("coverage", {"read": [], "skipped": [], "not_downloaded": []})
                current = cov.setdefault("skipped", [])
                cov["skipped"] = current = [
                    e for e in current if not (isinstance(e, dict) and e.get("reason") == "not_saved"
                                               and isinstance(e.get("path"), str)
                                               and covered(e["path"]))]
                counts = dict(head.get("skipped_by_reason") or {})
                counts["not_saved"] = counts.get("not_saved", 0) - removed
                for entry in res["skipped"]:
                    if entry not in current:
                        current.append(entry)
                        counts[entry["reason"]] = counts.get(entry["reason"], 0) + 1
                counts = {k: v for k, v in counts.items() if v > 0}
                info = {k: head[k] for k in keep if k in head}
                if layout:
                    info["layout"] = layout
                info = dict({"repo": slug, "ref": use_ref}, **info)
                _write_inventory(final, files, counts, info, kept)
                version = profile.get("version")
                if not isinstance(version, dict):
                    version = profile["version"] = {}
                if not version.get("label"):
                    version["label"] = label
                profile.setdefault("phases", {})["code"] = _now()
                profile["public_code"] = True
                dossier.save(dossier_id, profile)
            except BaseException:
                for target_file in created:
                    try:
                        target_file.unlink()
                    except OSError:
                        pass
                raise
        return {"res": res, "files": files, "counts": counts, "path": str(final.resolve())}
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def fetch_path(dossier_id: str, path: str, repo: "str | None" = None, ref: "str | None" = None) -> dict:
    """Download the same version again and save only one folder or file into it."""
    rel_path = _normalize_path(path)
    target = _saved_target(dossier_id, repo, ref)
    out = _grow(dossier_id, target, lambda r, parts, m: _under(r, rel_path),
                lambda p: _under(p, rel_path), ("layout", "package_dir"),
                missing="Nothing at or under %r exists in %%s at ref %%r." % rel_path)
    return {"ok": True, "files": len(out["res"]["files"]), "path": out["path"],
            "saved_path": rel_path, "skipped_by_reason": out["counts"]}


def fetch_full(dossier_id: str, repo: "str | None" = None, ref: "str | None" = None) -> dict:
    """Add every file the first fetch left out; layouts that already hold all of it are done."""
    dossier.require(dossier_id)
    profile, _ = dossier.load(dossier_id)
    head = saved_inventory(profile)
    if head is None:
        raise BlockedError("bad_input", _NO_CODE)
    if head.get("layout") in (None, "single", "full"):
        return {"ok": True, "added": 0, "already": True}
    out = _grow(dossier_id, _saved_target(dossier_id, repo, ref), None, lambda p: True, (), layout="full")
    return {"ok": True, "added": len(out["res"]["files"]), "files": len(out["files"]), "layout": "full"}
