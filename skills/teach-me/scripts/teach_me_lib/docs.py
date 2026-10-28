"""Documentation discovery and download (design section 7.1, phase 2).

Network reads happen outside the dossier lock; the lock only wraps writes.
Downloaded content is data: it is stored and never executed or obeyed.
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from . import dossier, frontmatter, html2md, net, store, urls
from .errors import BlockedError

PAGE_LIMIT = 2000
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_INDEX_BYTES = 5 * 1024 * 1024
MAX_SITEMAPS = 50
SAVE_EVERY = 25
MAX_NAME = 180

_ASSET_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".css", ".js", ".json",
              ".xml", ".zip", ".gz", ".tgz", ".pdf", ".woff", ".woff2", ".ttf", ".mp4", ".mp3")
_MD_LINK = re.compile(r"\[[^\]]*\]\(\s*<?([^)\s>]+)>?[^)]*\)")
_BARE_URL = re.compile(r"https?://[^\s<>\")\]]+")
_CHARSET = re.compile(r"charset\s*=\s*[\"']?([\w.-]+)", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _decode(body: bytes, content_type: str) -> str:
    match = _CHARSET.search(content_type or "")
    for charset in ([match.group(1)] if match else []) + ["utf-8"]:
        try:
            return body.decode(charset, errors="replace")
        except LookupError:
            continue
    return body.decode("utf-8", errors="replace")


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return "%s://%s" % (parts.scheme, parts.netloc)


def clean_url(raw: str, base: "str | None" = None) -> "str | None":
    """Absolute http(s) URL without query/fragment/trailing slash/.md suffix, or None."""
    try:
        full = urljoin(base, raw.strip()) if base else raw.strip()
        parts = urlsplit(full)
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            return None
        path = parts.path.rstrip("/")
        if path.lower().endswith(".md"):
            path = path[:-3]
        if path.lower().endswith(_ASSET_EXT):
            return None
        return "%s://%s%s" % (parts.scheme.lower(), parts.netloc, path)
    except ValueError:
        return None


def _probe(url: str) -> "net.Response | None":
    """A discovery read: any failure just means 'not there'."""
    try:
        resp = net.get(url, MAX_INDEX_BYTES)
    except BlockedError:
        return None
    return resp if resp.status == 200 else None


def _in_scope(candidates, docs_norm: str) -> list:
    seen: set = set()
    out: list = []
    for raw in candidates:
        if raw is None:
            continue
        try:
            norm = urls.normalize(raw)
        except BlockedError:
            continue
        if norm in seen or not urls.matches(norm, docs_norm):
            continue
        seen.add(norm)
        out.append(raw)
    return out


def _llms_urls(text: str, base: str) -> list:
    found = [(m.start(), m.group(1)) for m in _MD_LINK.finditer(text)]
    found += [(m.start(), m.group(0).rstrip(".,;")) for m in _BARE_URL.finditer(text)]
    found.sort(key=lambda item: item[0])
    return [clean_url(raw, base) for _pos, raw in found]


def _sitemap_locs(text: str) -> "tuple[str, list]":
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return "", []
    kind = root.tag.rsplit("}", 1)[-1]
    locs = [(el.text or "").strip() for el in root.iter() if el.tag.rsplit("}", 1)[-1] == "loc"]
    return kind, [loc for loc in locs if loc]


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def _sha(parts) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part)
    return h.hexdigest()


def collect(docs_url: str) -> "tuple[str, list, str]":
    """Find the documentation pages. Reads the network only and writes nothing.

    Returns (method, page_urls, fingerprint). The fingerprint is the sha256 of the raw
    bytes of the index used (for the links fallback, of the sorted URL list).
    """
    docs_norm = urls.normalize(docs_url)
    base = clean_url(docs_url)
    if base is None:
        raise BlockedError("bad_input", "not_a_url: %r is not an http(s) URL." % (docs_url,))
    origin = _origin(base)

    for candidate in (base + "/llms.txt", origin + "/llms.txt"):
        resp = _probe(candidate)
        if resp is None or resp.body.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
            continue
        found = _in_scope(_llms_urls(_decode(resp.body, resp.content_type), candidate), docs_norm)
        if found:
            return "llms_txt", found, _sha([resp.body])

    resp = _probe(origin + "/sitemap.xml")
    if resp is not None:
        queue, bodies, locs, seen = [(resp, None)], [], [], set()
        read = 0
        while queue and read < MAX_SITEMAPS:
            current, _src = queue.pop(0)
            read += 1
            bodies.append(current.body)
            kind, items = _sitemap_locs(_decode(current.body, current.content_type))
            if kind == "sitemapindex":
                for item in items:
                    child = clean_url_keep(item)
                    if child and child not in seen:
                        seen.add(child)
                        sub = _probe(child)
                        if sub is not None:
                            queue.append((sub, child))
            else:
                locs += [clean_url(item) for item in items]
        found = _in_scope(locs, docs_norm)
        if found:
            return "sitemap", found, _sha(bodies)

    try:
        resp = net.get(base, MAX_INDEX_BYTES)
    except BlockedError:
        resp = None
    if resp is None or resp.status != 200:
        raise BlockedError("fetch_failed", "Could not read the documentation at %s." % docs_url)
    parser = _LinkParser()
    try:
        parser.feed(_decode(resp.body, resp.content_type))
        parser.close()
    except Exception:
        pass
    found = _in_scope([base] + [clean_url(h, resp.final_url or base) for h in parser.hrefs], docs_norm)
    return "links", found, _sha([("\n".join(sorted(found))).encode("utf-8")])


def clean_url_keep(raw: str) -> "str | None":
    """Like clean_url but keeps the path as is (sitemap files end in .xml)."""
    try:
        parts = urlsplit(raw.strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    return "%s://%s%s" % (parts.scheme.lower(), parts.netloc, parts.path)


# --- _pages.md and page files -------------------------------------------------

def _docs_dir(folder: Path, meta: dict) -> Path:
    return folder / meta["names"]["sources_dir"] / meta["names"]["docs_dir"]


def _read_pages(docs_dir: Path) -> "list | None":
    path = docs_dir / "_pages.md"
    if not path.is_file():
        return None
    try:
        head, _ = frontmatter.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None
    pages = head.get("pages")
    return pages if isinstance(pages, list) else None


def _write_pages(docs_dir: Path, pages: list) -> None:
    lines = ["# Pages", ""] + ["- %s %s" % (p["state"], p["url"]) for p in pages]
    store.atomic_write(
        docs_dir / "_pages.md",
        frontmatter.dump({"teach_me": "index", "pages": pages}, "\n".join(lines) + "\n"))


def _file_name(url: str) -> str:
    stem = re.sub(r"[^\w.\-~%@+,=:!$&'()*;]", "_", urls.normalize(url).replace("/", "__"))
    name = stem + ".md"
    if len(name) > MAX_NAME:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
        name = stem[:MAX_NAME - len(".md") - 11] + "-" + digest + ".md"
    return name


def page_path(dossier_id: str, url: str) -> "Path | None":
    meta, _ = dossier.load(dossier_id)
    path = _docs_dir(store.dossier_dir(dossier_id), meta) / _file_name(url)
    return path if path.is_file() else None


def _entry(url: str, state: str = "pending", reason=None) -> dict:
    return {"url": url, "state": state, "reason": reason}


# --- discover -----------------------------------------------------------------

def discover(dossier_id: str, docs_url: str) -> dict:
    urls.normalize(docs_url)
    dossier.require(dossier_id)
    method, found, fingerprint = collect(docs_url)
    with store.locked(dossier_id) as folder:
        meta, _ = dossier.load(dossier_id)
        docs_dir = _docs_dir(folder, meta)
        docs_dir.mkdir(parents=True, exist_ok=True)
        pages = _read_pages(docs_dir) or []
        known = {urls.normalize(p["url"]) for p in pages}
        coverage = meta.setdefault("coverage", {"read": [], "skipped": [], "not_downloaded": []})
        dropped = coverage.setdefault("not_downloaded", [])
        dropped_urls = {e.get("url") for e in dropped if isinstance(e, dict)}
        over = 0
        for url in found:
            norm = urls.normalize(url)
            if norm in known:
                continue
            known.add(norm)
            if len(pages) < PAGE_LIMIT:
                pages.append(_entry(url))
            else:
                over += 1
                if url not in dropped_urls:
                    dropped.append({"url": url, "reason": "page_limit"})
        _write_pages(docs_dir, pages)
        version = meta.get("version")
        if not isinstance(version, dict):
            version = {}
        version["docs_fingerprint"] = fingerprint
        meta["version"] = version
        meta.setdefault("phases", {})["docs_discover"] = _now()
        dossier.save(dossier_id, meta)
    return {"ok": True, "method": method, "page_count": len(pages),
            "not_downloaded": over, "fingerprint": fingerprint}


# --- fetch --------------------------------------------------------------------

def _looks_like_html(text: str) -> bool:
    return text.lstrip()[:15].lower().startswith(("<!doctype", "<html"))


def _download(url: str) -> "tuple[str, str] | str":
    """Return (origin, markdown) or a short failure reason."""
    try:
        resp = net.get(url + ".md", MAX_PAGE_BYTES)
        ctype = resp.content_type.split(";")[0].strip().lower()
        if resp.status == 200 and ctype != "text/html":
            text = _decode(resp.body, resp.content_type)
            if text.strip() and not _looks_like_html(text):
                return "md", text
    except BlockedError:
        pass
    try:
        resp = net.get(url, MAX_PAGE_BYTES)
    except BlockedError as exc:
        return exc.code if exc.code == "too_large" else "%s: %s" % (exc.code, exc.message)
    if resp.status != 200:
        return "http_%d" % resp.status
    ctype = resp.content_type.split(";")[0].strip().lower()
    text = _decode(resp.body, resp.content_type)
    if ctype in ("", "text/html", "application/xhtml+xml") or _looks_like_html(text):
        if ctype not in ("", "text/html", "application/xhtml+xml") and not _looks_like_html(text):
            return "unsupported_content_type"
        return "html", html2md.convert(text)
    if ctype.startswith("text/"):
        return "md", text
    return "unsupported_content_type"


def _flush(dossier_id: str, results: list, extra_urls: list, finish: bool) -> None:
    """Write page files and fold the results into _pages.md under the lock."""
    with store.locked(dossier_id) as folder:
        meta, _ = dossier.load(dossier_id)
        docs_dir = _docs_dir(folder, meta)
        docs_dir.mkdir(parents=True, exist_ok=True)
        pages = _read_pages(docs_dir) or []
        index = {urls.normalize(p["url"]): p for p in pages}
        for url in extra_urls:
            if urls.normalize(url) not in index:
                entry = _entry(url)
                pages.append(entry)
                index[urls.normalize(url)] = entry
        for url, outcome in results:
            entry = index.get(urls.normalize(url))
            if entry is None:
                continue
            if isinstance(outcome, tuple):
                origin, markdown = outcome
                store.atomic_write(docs_dir / _file_name(url), frontmatter.dump(
                    {"teach_me": "page", "url": url, "fetched_at": _now(), "origin": origin},
                    markdown))
                entry["state"], entry["reason"] = "ok", None
            else:
                entry["state"], entry["reason"] = "failed", outcome
        _write_pages(docs_dir, pages)
        if finish and not any(p["state"] == "pending" for p in pages):
            meta.setdefault("phases", {})["docs"] = _now()
            dossier.save(dossier_id, meta)


def fetch(dossier_id: str, url: "str | None") -> dict:
    dossier.require(dossier_id)
    meta, _ = dossier.load(dossier_id)
    docs_dir = _docs_dir(store.dossier_dir(dossier_id), meta)
    pages = _read_pages(docs_dir)
    extra: list = []
    if url is None:
        if pages is None:
            raise BlockedError("bad_input", "There is no page list yet. Run discover-docs first.")
        todo = [p["url"] for p in pages if p["state"] in ("pending", "failed")]
        already = sum(1 for p in pages if p["state"] == "ok")
    else:
        cleaned = clean_url(url)
        if cleaned is None:
            raise BlockedError("bad_input", "not_a_url: %r is not an http(s) URL." % (url,))
        urls.normalize(cleaned)
        known = {urls.normalize(p["url"]): p for p in (pages or [])}
        entry = known.get(urls.normalize(cleaned))
        if entry is not None and entry["state"] == "ok":
            todo, already = [], 1
        else:
            todo, already = [entry["url"] if entry else cleaned], 0
            if entry is None:
                extra = [cleaned]

    downloaded = 0
    failed: list = []
    batch: list = []
    if not todo and extra:
        _flush(dossier_id, [], extra, False)
    for target in todo:
        outcome = _download(target)
        batch.append((target, outcome))
        if isinstance(outcome, tuple):
            downloaded += 1
        else:
            failed.append({"url": target, "reason": outcome})
        if len(batch) >= SAVE_EVERY:
            _flush(dossier_id, batch, extra, False)
            batch, extra = [], []
    if batch or extra or url is None:
        _flush(dossier_id, batch, extra, url is None)
    return {"ok": True, "downloaded": downloaded, "already": already, "failed": failed}
