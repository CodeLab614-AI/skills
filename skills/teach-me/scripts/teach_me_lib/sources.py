"""Citations to literal excerpts: the anti-invention check (spec section 6). Read-only."""
from __future__ import annotations

import re
from pathlib import Path

from . import docs, dossier, frontmatter, store
from .errors import BlockedError

MAX_QUOTE = 500
MAX_CODE_LINES = 40
_LINK = re.compile(r"!?\[([^\]]*)\]\(([^)]*)\)")
_DROP = set("*_`#")


def _bad(message: str) -> BlockedError:
    return BlockedError("bad_input", message)


def _map_normalized(text: str) -> "tuple[str, list]":
    """Normalized text plus, per normalized char, its (start, end) offsets in `text`."""
    raw = []  # (char, start, end)
    pos = 0
    for m in _LINK.finditer(text):
        for i in range(pos, m.start()):
            raw.append((text[i], i, i + 1))
        label = m.group(1)
        base = m.start(1)
        for j, ch in enumerate(label):
            start = m.start() if j == 0 else base + j
            end = m.end() if j == len(label) - 1 else base + j + 1
            raw.append((ch, start, end))
        pos = m.end()
    for i in range(pos, len(text)):
        raw.append((text[i], i, i + 1))
    chars: list = []
    spans: list = []
    for ch, start, end in raw:
        if ch in _DROP:
            continue
        if ch.isspace():
            if chars and chars[-1] == " ":
                spans[-1] = (spans[-1][0], end)
                continue
            chars.append(" ")
            spans.append((start, end))
            continue
        for low in ch.lower():
            chars.append(low)
            spans.append((start, end))
    while chars and chars[-1] == " ":
        chars.pop()
        spans.pop()
    while chars and chars[0] == " ":
        chars.pop(0)
        spans.pop(0)
    return "".join(chars), spans


def normalize(text: str) -> str:
    """Collapse whitespace, lowercase, drop * _ ` #, and reduce [text](url) to text."""
    return _map_normalized(text)[0]


def _find_literal(body: str, quote: str) -> "str | None":
    needle = normalize(quote)
    if not needle:
        return None
    hay, spans = _map_normalized(body)
    at = hay.find(needle)
    if at < 0:
        return None
    start = spans[at][0]
    end = spans[at + len(needle) - 1][1]
    while start > 0 and body[start - 1] in _DROP:  # keep adjacent markup, e.g. `code`
        start -= 1
    while end < len(body) and body[end] in _DROP:
        end += 1
    return body[start:end].strip()


# --- shape validation ---------------------------------------------------------------

def _validate(claims) -> None:
    if not isinstance(claims, list):
        raise _bad("claims must be a list.")
    for i, claim in enumerate(claims):
        tag = "claim %d" % i
        if not isinstance(claim, dict):
            raise _bad("%s must be an object." % tag)
        if not isinstance(claim.get("text"), str) or not claim["text"].strip():
            raise _bad("%s needs a non-empty text." % tag)
        if claim.get("kind") not in ("fact", "pedagogical"):
            raise _bad("%s: kind must be fact or pedagogical." % tag)
        sources = claim.get("sources", [])
        if sources is None:
            sources = []
        if not isinstance(sources, list):
            raise _bad("%s: sources must be a list." % tag)
        for j, cite in enumerate(sources):
            ctag = "%s, source %d" % (tag, j)
            if not isinstance(cite, dict):
                raise _bad("%s must be an object." % ctag)
            kind = cite.get("kind")
            if kind == "doc":
                if not isinstance(cite.get("url"), str) or not cite["url"]:
                    raise _bad("%s: doc needs a url." % ctag)
                q = cite.get("quote")
                if not isinstance(q, str) or not 1 <= len(q) <= MAX_QUOTE:
                    raise _bad("%s: quote must be 1 to %d characters." % (ctag, MAX_QUOTE))
            elif kind == "code":
                if not isinstance(cite.get("path"), str) or not cite["path"]:
                    raise _bad("%s: code needs a path." % ctag)
                for key in ("line_start", "line_end"):
                    v = cite.get(key)
                    if not isinstance(v, int) or isinstance(v, bool):
                        raise _bad("%s: %s must be an integer." % (ctag, key))
            else:
                raise _bad("%s: kind must be doc or code." % ctag)


# --- resolving ------------------------------------------------------------------------

def _resolve_doc(dossier_id: str, cite: dict) -> dict:
    url = cite["url"]
    page = docs.page_path(dossier_id, docs.clean_url(url) or url)
    if page is None:
        return {"error": "page_not_downloaded"}
    try:
        _, body = frontmatter.parse(page.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {"error": "page_not_downloaded"}
    found = _find_literal(body, cite["quote"])
    return {"excerpt": found} if found is not None else {"error": "quote_not_found"}


def _code_root(dossier_id: str, meta: dict) -> "Path | None":
    label = (meta.get("version") or {}).get("label")
    if not isinstance(label, str) or not label or label in (".", "..") or "/" in label \
            or "\\" in label:
        return None
    names = meta["names"]
    return store.dossier_dir(dossier_id) / names["sources_dir"] / names["code_dir"] / label


def _resolve_code(root: "Path | None", cite: dict) -> dict:
    rel = cite["path"]
    if root is None or "\x00" in rel or rel.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", rel) \
            or ".." in re.split(r"[\\/]", rel):
        return {"error": "file_not_found"}
    try:
        target = (root / rel).resolve()
        target.relative_to(root.resolve())
        if not target.is_file():
            return {"error": "file_not_found"}
        text = target.read_bytes().decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return {"error": "file_not_found"}
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    lines = [ln[:-1] if ln.endswith("\r") else ln for ln in lines]
    start, end = cite["line_start"], cite["line_end"]
    if start < 1 or end < start or end > len(lines):
        return {"error": "line_out_of_range"}
    if end - start + 1 > MAX_CODE_LINES:
        return {"error": "too_many_lines"}
    return {"excerpt": "\n".join(lines[start - 1:end])}


def check_claims(dossier_id: str, claims) -> "tuple[list, list]":
    """Return (resolved claims, indices of unverified claims). Raises bad_input on bad shape."""
    dossier.require(dossier_id)
    _validate(claims)
    meta, _ = dossier.load(dossier_id)
    root = _code_root(dossier_id, meta)
    resolved: list = []
    unverified: list = []
    for i, claim in enumerate(claims):
        out = dict(claim)
        cites = []
        for cite in claim.get("sources") or []:
            item = dict(cite)
            item.pop("excerpt", None)
            item.pop("error", None)
            item.update(_resolve_doc(dossier_id, cite) if cite["kind"] == "doc"
                        else _resolve_code(root, cite))
            cites.append(item)
        out["sources"] = cites
        out.pop("error", None)
        ok = all("excerpt" in c for c in cites)
        if claim["kind"] == "fact" and not cites:
            ok = False
            out["error"] = "no_sources"
        out["verified"] = ok
        if not ok:
            unverified.append(i)
        resolved.append(out)
    return resolved, unverified


def resolve(dossier_id: str, claims) -> list:
    return check_claims(dossier_id, claims)[0]
