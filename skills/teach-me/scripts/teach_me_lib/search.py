"""Local search over a dossier: on-the-fly chunking plus BM25 Okapi (spec section 9). Read-only."""
from __future__ import annotations

import math
import re
from pathlib import Path

from . import code as code_mod
from . import dossier, frontmatter, store
from .errors import BlockedError

K1 = 1.2
B = 0.75
WINDOW = 60
OVERLAP = 10
MAX_TEXT = 1200
MIN_K, MAX_K = 1, 50
_RUN = re.compile(r"[^\W_]+(?:[_-]+[^\W_]+)*")
_WORD = re.compile(r"[^\W_]+")
_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)[ \t#]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _camel_parts(word: str) -> list:
    """Split one alphanumeric word at lower->Upper, Upper->Upper+lower and letter<->digit edges."""
    parts: list = []
    cur = ""
    for i, ch in enumerate(word):
        if cur:
            prev = cur[-1]
            nxt = word[i + 1] if i + 1 < len(word) else ""
            if (prev.isdigit() != ch.isdigit()
                    or (prev.islower() and ch.isupper())
                    or (prev.isupper() and ch.isupper() and nxt.islower())):
                parts.append(cur)
                cur = ""
        cur += ch
    if cur:
        parts.append(cur)
    return parts


def tokenize(text: str) -> list:
    """Lowercase search terms from `text`.

    Rule: a run is a maximal stretch of Unicode letters/digits, optionally joined by `_` or `-`
    (anything else, spaces and punctuation included, separates runs). For each word of a run
    (words are split at `_`/`-`) the whole lowercase word is emitted, then, if camelCase,
    PascalCase or letter/digit boundaries split it into several parts, each part. When a run has
    several words, the lowercase words joined together are emitted last.
    `generateText` -> generatetext, generate, text; `max_tokens` -> max, tokens, maxtokens;
    `HTTPServer2` -> httpserver2, http, server, 2; `Instalación` -> instalación.
    """
    out: list = []
    for run in _RUN.findall(text):
        words = _WORD.findall(run)
        for word in words:
            out.append(word.lower())
            parts = _camel_parts(word)
            if len(parts) > 1:
                out.extend(p.lower() for p in parts)
        if len(words) > 1:
            out.append("".join(w.lower() for w in words))
    return out


# --- chunking ---------------------------------------------------------------------------

def _doc_chunks(path: Path, url: str, body: str) -> list:
    """Split a page body by Markdown headings (# to ######), ignoring fenced code blocks."""
    chunks: list = []
    heading = ""
    lines: list = []
    fence = ""

    def flush() -> None:
        text = "\n".join(lines).strip()
        if text:
            chunks.append({"text": text, "citation": {"kind": "doc", "url": url, "heading": heading}})

    for line in body.split("\n"):
        line = line.rstrip("\r")
        m = _FENCE.match(line)
        if m:
            mark = m.group(1)
            if not fence:
                fence = mark[0] * 3
            elif mark[0] == fence[0] and len(mark) >= 3 and line.strip().strip(mark[0]) == "":
                fence = ""
        elif not fence:
            h = _HEADING.match(line)
            if h:
                flush()
                heading = h.group(2).strip()
                lines = [line]
                continue
        lines.append(line)
    flush()
    return chunks


def _docs_chunks(dossier_id: str, meta: dict) -> list:
    names = meta["names"]
    folder = store.dossier_dir(dossier_id) / names["sources_dir"] / names["docs_dir"]
    out: list = []
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.md")):
        if path.name.startswith("_") or not path.is_file():
            continue
        try:
            head, body = frontmatter.parse(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        url = head.get("url")
        if head.get("teach_me") != "page" or not isinstance(url, str) or not url:
            continue
        out.extend(_doc_chunks(path, url, body))
    return out


def _windows(lines: list) -> list:
    if len(lines) <= WINDOW:
        return [(1, len(lines))] if lines else []
    step = WINDOW - OVERLAP
    wins = []
    start = 1
    while True:
        end = min(start + WINDOW - 1, len(lines))
        wins.append((start, end))
        if end == len(lines):
            return wins
        start += step


def _code_chunks(dossier_id: str, meta: dict) -> list:
    label = (meta.get("version") or {}).get("label")
    names = meta["names"]
    if not isinstance(label, str) or not label or label in (".", "..") or "/" in label \
            or "\\" in label or label.endswith(".partial"):
        return []
    root = store.dossier_dir(dossier_id) / names["sources_dir"] / names["code_dir"] / label
    inv = root / code_mod.INVENTORY
    try:
        head, _ = frontmatter.parse(inv.read_text(encoding="utf-8"))
        real_root = root.resolve()
    except (OSError, UnicodeDecodeError):
        return []
    files = head.get("files")
    if not isinstance(files, list):
        return []
    rels = sorted({f["path"] for f in files if isinstance(f, dict) and isinstance(f.get("path"), str)})
    out: list = []
    for rel in rels:
        if rel.startswith(("/", "\\")) or ".." in re.split(r"[\\/]", rel) or "\x00" in rel:
            continue
        try:
            target = (root / rel).resolve()
            target.relative_to(real_root)
            if not target.is_file():
                continue
            text = target.read_bytes().decode("utf-8", errors="replace")
        except (OSError, ValueError):
            continue
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        lines = [ln[:-1] if ln.endswith("\r") else ln for ln in lines]
        for a, b in _windows(lines):
            out.append({"text": "\n".join(lines[a - 1:b]),
                        "citation": {"kind": "code", "path": rel, "line_start": a, "line_end": b}})
    return out


def chunks(dossier_id: str) -> list:
    """All searchable chunks, docs first and then code, each `{"text", "citation"}`."""
    dossier.require(dossier_id)
    meta, _ = dossier.load(dossier_id)
    return _docs_chunks(dossier_id, meta) + _code_chunks(dossier_id, meta)


# --- ranking ----------------------------------------------------------------------------

def query(dossier_id: str, q: str, k: int = 5) -> dict:
    """BM25 Okapi (k1=1.2, b=0.75; idf = ln(1 + (N-df+0.5)/(df+0.5))) over `chunks`."""
    dossier.require(dossier_id)
    if not isinstance(k, int) or isinstance(k, bool) or not MIN_K <= k <= MAX_K:
        raise BlockedError("bad_input", "k must be an integer from %d to %d." % (MIN_K, MAX_K))
    terms = list(dict.fromkeys(tokenize(q)))
    if not terms:
        raise BlockedError("bad_input", "The query has no searchable words.")
    items = chunks(dossier_id)
    counts = []
    for item in items:
        tf: dict = {}
        toks = tokenize(item["text"])
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        counts.append((tf, len(toks)))
    n = len(items)
    avg = (sum(length for _, length in counts) / n) if n else 0.0
    idf = {}
    for t in terms:
        df = sum(1 for tf, _ in counts if t in tf)
        idf[t] = math.log(1 + (n - df + 0.5) / (df + 0.5))
    scored = []
    for pos, (tf, length) in enumerate(counts):
        score = 0.0
        for t in terms:
            f = tf.get(t, 0)
            if f:
                score += idf[t] * f * (K1 + 1) / (f + K1 * (1 - B + B * length / avg))
        if score > 0:
            scored.append((-score, pos))
    scored.sort()  # ties keep chunk order: docs before code, then path, then position
    results = [{"score": round(-s, 4), "text": items[pos]["text"][:MAX_TEXT],
                "citation": items[pos]["citation"]} for s, pos in scored[:k]]
    return {"ok": True, "results": results}
