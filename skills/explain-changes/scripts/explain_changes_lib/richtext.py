"""The report texts allow only `inline code` and **bold**; everything else is plain text.

The same text becomes Markdown (report.md) or escaped HTML (report.html)."""
from __future__ import annotations

import html
import re

TOKEN = re.compile(r"`([^`\n]+)`|\*\*([^*\n]+)\*\*")


def one(value) -> str:
    """Single-line text: every line break collapses to one space."""
    return " ".join(str(value).splitlines())


def code_md(value) -> str:
    """Inline code span whose fence is longer than any backtick run inside."""
    text = one(value)
    longest = max([len(m) for m in re.findall(r"`+", text)] or [0])
    fence = "`" * (longest + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return fence + pad + text + pad + fence


def strip_bold(value) -> str:
    return one(value).replace("**", "")


def to_markdown(text) -> str:
    text = one(text)
    out, pos = [], 0
    for m in TOKEN.finditer(text):
        out.append(text[pos:m.start()])
        out.append(code_md(m.group(1)) if m.group(1) is not None else "**%s**" % m.group(2))
        pos = m.end()
    out.append(text[pos:])
    return "".join(out)


def to_html(text) -> str:
    text = one(text)
    out, pos = [], 0
    for m in TOKEN.finditer(text):
        out.append(html.escape(text[pos:m.start()]))
        if m.group(1) is not None:
            out.append('<code class="ic">%s</code>' % html.escape(m.group(1)))
        else:
            out.append("<b>%s</b>" % html.escape(m.group(2)))
        pos = m.end()
    out.append(html.escape(text[pos:]))
    return "".join(out)
