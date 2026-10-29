"""Small, forgiving HTML to Markdown converter (html.parser only)."""
from __future__ import annotations

import re
from html.parser import HTMLParser

_SKIP = ("script", "style", "nav", "footer", "header", "noscript", "template")
_BLOCKS = ("p", "div", "section", "article", "main", "aside", "ul", "ol", "dl", "dt", "dd",
           "blockquote", "figure", "figcaption", "details", "summary", "form", "hr", "body")
_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
_WS = re.compile(r"\s+")


class _Converter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list = []        # (text, group): same-group blocks join with a single newline
        self.inline: list = []
        self.prefix = ""
        self.tight = ""
        self.skip_tag = None
        self.skip_depth = 0
        self.pre: "list | None" = None
        self.links: list = []         # (href, start index in inline)
        self.row: "list | None" = None
        self.in_cell = False
        self.rows_in_table = 0

    # -- helpers
    def _flush(self) -> None:
        text = _WS.sub(" ", "".join(self.inline)).strip()
        self.inline = []
        if text:
            self.blocks.append((self.prefix + text, self.tight))
        self.prefix, self.tight = "", ""

    # -- tags
    def handle_starttag(self, tag, attrs):
        if self.skip_tag is not None:
            if tag == self.skip_tag:
                self.skip_depth += 1
            return
        if tag in _SKIP:
            self._flush()
            self.skip_tag, self.skip_depth = tag, 1
            return
        if self.pre is not None:
            return
        if tag in _HEADINGS:
            self._flush()
            self.prefix = "#" * int(tag[1]) + " "
        elif tag == "li":
            self._flush()
            self.prefix, self.tight = "- ", "li"
        elif tag == "pre":
            self._flush()
            self.pre = []
        elif tag == "br":
            self._flush()
        elif tag == "code":
            self.inline.append("`")
        elif tag in ("strong", "b"):
            self.inline.append("**")
        elif tag in ("em", "i"):
            self.inline.append("*")
        elif tag == "a":
            href = dict(attrs).get("href")
            self.links.append((href, len(self.inline)))
        elif tag == "table":
            self._flush()
            self.rows_in_table = 0
        elif tag == "tr":
            self._flush()
            self.row = []
        elif tag in ("td", "th"):
            self._flush()
            self.in_cell = True
        elif tag in _BLOCKS:
            self._flush()

    def handle_startendtag(self, tag, attrs):
        if self.skip_tag is None and tag in ("br", "hr"):
            self._flush()

    def handle_endtag(self, tag):
        if self.skip_tag is not None:
            if tag == self.skip_tag:
                self.skip_depth -= 1
                if self.skip_depth == 0:
                    self.skip_tag = None
            return
        if self.pre is not None:
            if tag == "pre":
                code = "".join(self.pre).strip("\n")
                self.pre = None
                if code.strip():
                    self.blocks.append(("```\n" + code + "\n```", ""))
            return
        if tag in _HEADINGS or tag in _BLOCKS or tag == "li":
            self._flush()
        elif tag == "code":
            self.inline.append("`")
        elif tag in ("strong", "b"):
            self.inline.append("**")
        elif tag in ("em", "i"):
            self.inline.append("*")
        elif tag == "a":
            if self.links:
                href, start = self.links.pop()
                text = "".join(self.inline[start:]).strip()
                if href and text and not href.lower().startswith("javascript:"):
                    del self.inline[start:]
                    self.inline.append("[%s](%s)" % (text, href))
        elif tag in ("td", "th"):
            if self.in_cell:
                cell = _WS.sub(" ", "".join(self.inline)).strip().replace("|", "\\|")
                self.inline = []
                self.in_cell = False
                if self.row is not None:
                    self.row.append(cell)
        elif tag == "tr":
            self._end_row()
        elif tag == "table":
            self._end_row()

    def _end_row(self) -> None:
        if self.row:
            self.blocks.append(("| " + " | ".join(self.row) + " |", "row"))
            if self.rows_in_table == 0:
                self.blocks.append(("|" + "---|" * len(self.row), "row"))
            self.rows_in_table += 1
        self.row = None

    def handle_data(self, data):
        if self.skip_tag is not None:
            return
        if self.pre is not None:
            self.pre.append(data)
        else:
            self.inline.append(data)

    def finish(self) -> str:
        self.close()
        if self.pre:
            code = "".join(self.pre).strip("\n")
            if code.strip():
                self.blocks.append(("```\n" + code + "\n```", ""))
            self.pre = None
        self._end_row()
        self._flush()
        out: list = []
        prev_tight = ""
        for text, tight in self.blocks:
            if out:
                out.append("\n" if (tight and tight == prev_tight) else "\n\n")
            out.append(text)
            prev_tight = tight
        return re.sub(r"\n{3,}", "\n\n", "".join(out)).strip() + "\n" if out else ""


def convert(html: str) -> str:
    conv = _Converter()
    try:
        conv.feed(html)
    except Exception:  # malformed input must not abort a whole run
        pass
    return conv.finish()
