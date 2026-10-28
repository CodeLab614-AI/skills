"""fetch-code: download the exact source tarball and extract it member by member, safely.

The tarball is untrusted data. Nothing is ever executed, `extract`/`extractall` are never
used, links are never created and every path is checked against the destination."""
from __future__ import annotations

import os
import re
import shutil
import tarfile
import tempfile
import zlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from . import dossier, frontmatter, meta as meta_mod, net, store
from .errors import BlockedError

MAX_TARBALL = 300 * 1024 * 1024
MAX_FILE = 1024 * 1024
BINARY_SNIFF = 8 * 1024
IGNORED = frozenset(["node_modules", ".git", "dist", "build", ".next", "coverage", "vendor"])
_DRIVE = re.compile(r"^[A-Za-z]:")
INVENTORY = "_inventory.md"


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


def _extract(tar_path: Path, dest: Path) -> "tuple[list, list]":
    files: list = []
    skipped: list = []
    dest.mkdir(parents=True)
    dest_resolved = dest.resolve()
    seen_ignored: set = set()

    def skip(path: str, reason: str) -> None:
        skipped.append({"path": path, "reason": reason})

    try:
        tf = tarfile.open(str(tar_path), "r:gz")
    except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
        raise BlockedError("fetch_failed", "The download is not a readable .tar.gz archive: %s" % exc)
    try:
        for member in tf:
            name = member.name
            if _unsafe_name(name):
                skip(name, "unsafe_path")
                continue
            parts = [p for p in name.split("/") if p not in ("", ".")]
            rel_parts = parts[1:]
            if not rel_parts:
                continue  # top directory itself or a top-level entry
            rel = "/".join(rel_parts)
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
            except OSError:
                skip(name, "unsafe_path")
                continue
            files.append({"path": rel, "lines": _count_lines(data)})
    except (tarfile.TarError, EOFError, zlib.error, OSError) as exc:
        raise BlockedError("fetch_failed", "The archive is corrupt or truncated: %s" % exc)
    finally:
        tf.close()
    files.sort(key=lambda f: f["path"])
    return files, skipped


def _by_reason(skipped: list) -> dict:
    counts: dict = {}
    for entry in skipped:
        counts[entry["reason"]] = counts.get(entry["reason"], 0) + 1
    return counts


def _write_inventory(dest: Path, files: list, counts: dict) -> None:
    lines = ["# Code inventory", ""] + ["- %s (%d lines)" % (f["path"], f["lines"]) for f in files]
    store.atomic_write(dest / INVENTORY, frontmatter.dump(
        {"teach_me": "index", "files": files, "skipped_by_reason": counts},
        "\n".join(lines) + "\n"))


def _done(final: Path) -> "dict | None":
    inv = final / INVENTORY
    if not inv.is_file():
        return None
    try:
        head, _ = frontmatter.parse(inv.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None
    files = head.get("files")
    if not isinstance(files, list):
        return None
    counts = head.get("skipped_by_reason")
    return {"ok": True, "files": len(files),
            "skipped_by_reason": counts if isinstance(counts, dict) else {},
            "path": str(final.resolve())}


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

    url = "%s/%s/tar.gz/%s" % (net.base("codeload"), slug, quote(ref, safe="@/.-_"))
    fd, tmp_name = tempfile.mkstemp(dir=str(folder), prefix=".tmp-code-", suffix=".tar.gz")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        resp = net.download(url, tmp, MAX_TARBALL)
        if resp.status != 200:
            what = "was not found" if resp.status == 404 else "answered HTTP %d" % resp.status
            raise BlockedError("fetch_failed", "The source for %s at ref %r %s (%s)."
                               % (slug, ref, what, url))
        with store.locked(dossier_id):
            done = _done(final)
            if done is not None:
                return done
            code_dir.mkdir(parents=True, exist_ok=True)
            partial = code_dir / (label + ".partial")
            if partial.exists() or partial.is_symlink():
                shutil.rmtree(str(partial), ignore_errors=True)
            try:
                files, skipped = _extract(tmp, partial)
                counts = _by_reason(skipped)
                _write_inventory(partial, files, counts)
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
        return {"ok": True, "files": len(files), "skipped_by_reason": counts,
                "path": str(final.resolve())}
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
