"""Line-by-line syntax highlighting for the HTML report (no external resources)."""
from __future__ import annotations

import html
import re
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Dict, Pattern

C_KEYWORDS = (
    "import export from default type interface function const let var return if else for while "
    "do switch case break continue new class extends implements async await try catch finally "
    "throw typeof instanceof void delete in of as enum static public private protected readonly "
    "abstract this super yield null undefined true false number string boolean any never unknown "
    "package fn pub struct impl use mod match func go defer chan").split()
PY_KEYWORDS = (
    "def class return if elif else for while in not and or is import from as with try except "
    "finally raise pass break continue lambda yield None True False async await global "
    "nonlocal del assert self").split()
C_EXT = {"ts", "tsx", "js", "jsx", "mjs", "cjs", "java", "kt", "swift", "go", "rs", "c", "h",
         "cpp", "cs", "php", "dart", "scala", "vue", "svelte"}
HASH_EXT = {"py", "pyi", "sh", "bash", "zsh", "yml", "yaml", "toml", "rb", "ini", "cfg", "conf"}
PY_EXT = {"py", "pyi"}
JSON_EXT = {"json", "jsonc"}


def family(path: str) -> str:
    """``c`` (// and /* */ comments), ``hash`` (# comments), ``json`` or ``plain``."""
    name = PurePosixPath(path).name.lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    if ext in C_EXT:
        return "c"
    if ext in HASH_EXT or name in ("makefile", "dockerfile"):
        return "hash"
    if ext in JSON_EXT:
        return "json"
    return "plain"


def _alt(words) -> str:
    return r"\b(?:%s)\b" % "|".join(re.escape(w) for w in words)


@lru_cache(maxsize=None)
def _pattern(kind: str, is_python: bool) -> Pattern:
    if kind == "c":
        comment = r"//.*$|/\*.*?\*/|^\s*(?:/\*.*|\*/|\* .*|\*)$"
    elif kind == "hash":
        comment = r"#.*$"
    else:
        comment = r"(?!)"
    keywords = PY_KEYWORDS if is_python else (C_KEYWORDS if kind == "c" else [])
    if kind == "json":
        keywords = ["true", "false", "null"]
    parts = [r"(?P<c>%s)" % comment,
             r"(?P<s>'''.*?'''|\"\"\".*?\"\"\"|'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\""
             r"|`(?:[^`\\]|\\.)*`)"]
    if keywords:
        parts.append(r"(?P<k>%s)" % _alt(keywords))
    parts.append(r"(?P<n>\b\d[\d_.]*\b)")
    if kind in ("c", "hash"):
        parts.append(r"(?P<t>\b[A-Z][A-Za-z0-9_]*\b)")
        parts.append(r"(?P<f>\b[A-Za-z_$][\w$]*(?=\())")
    return re.compile("|".join(parts))


def highlight(line: str, path: str) -> str:
    """Escaped HTML for one source line, with ``<span class="hl-x">`` tokens."""
    kind = family(path)
    name = PurePosixPath(path).name.lower()
    pattern = _pattern(kind, name.rsplit(".", 1)[-1] in PY_EXT)
    out, pos = [], 0
    for m in pattern.finditer(line):
        if m.start() == m.end():
            continue
        out.append(html.escape(line[pos:m.start()]))
        out.append('<span class="hl-%s">%s</span>' % (m.lastgroup, html.escape(m.group())))
        pos = m.end()
    out.append(html.escape(line[pos:]))
    return "".join(out)


def comment_marks(path: str) -> Dict[str, str]:
    """Comment syntax used for the report's own explanations in this kind of file."""
    if family(path) == "hash":
        return {"line": "#", "open": "", "mid": "# ", "close": ""}
    return {"line": "//", "open": "/*", "mid": " * ", "close": " */"}
