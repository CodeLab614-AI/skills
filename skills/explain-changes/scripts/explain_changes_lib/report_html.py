"""report.html: one self-contained file (no external resources), light and dark.

Every value that comes from the repository or from the interpreter is escaped."""
from __future__ import annotations

import html
import textwrap
from typing import Dict, List, Optional, Tuple

from .highlight import comment_marks, highlight
from .labels import fill
from .richtext import one, strip_bold, to_html

NEW_STATUSES = ("untracked", "added")
WRAP = 88
MAX_LISTED = 5

CSS = """
:root{color-scheme:light dark;--bg:#fff;--fg:#37352f;--dim:#8a8a85;--line:#e9e9e7;--soft:#f7f6f3;
--ic:#c4554d;--icbg:rgba(135,131,120,.15);--add:rgba(46,160,67,.13);--del:rgba(248,81,73,.13);
--cbg:#fafaf8;--cfg:#24292e;--k:#d73a49;--s:#032f62;--c:#6a737d;--n:#005cc5;--t:#6f42c1;--f:#6f42c1;
--ex:#1a7f37;--hl:#f5c542;--warn:#b25b00}
@media (prefers-color-scheme:dark){:root{--bg:#191919;--fg:#e6e6e3;--dim:#9b9b96;--line:#2f2f2d;--soft:#252525;
--ic:#ff7369;--icbg:rgba(135,131,120,.25);--add:rgba(46,160,67,.2);--del:rgba(248,81,73,.2);
--cbg:#1f1f1f;--cfg:#d4d4d4;--k:#569cd6;--s:#ce9178;--c:#8b8b8b;--n:#b5cea8;--t:#4ec9b0;--f:#dcdcaa;
--ex:#7fd18b;--hl:#8a6d00;--warn:#f1b65c}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:800px;margin:0 auto;padding:48px 20px 80px}
.meta{font-size:13px;color:var(--dim);margin:0 0 20px}
h1{font-size:24px;line-height:1.3;font-weight:650;margin:0 0 16px}
p{margin:0 0 12px}b{font-weight:650}
code.ic{font:.86em ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--ic);
background:var(--icbg);padding:1px 5px;border-radius:4px;overflow-wrap:anywhere}
code.ic .dir{opacity:.55;font-weight:400}code.ic b{font-weight:700}
details>summary{cursor:pointer;list-style:none}details>summary::-webkit-details-marker{display:none}
ol.points{list-style:none;counter-reset:p;margin:0 0 20px;padding:0}
ol.points>li{counter-increment:p;border-top:1px solid var(--line)}
ol.points>li:last-child{border-bottom:1px solid var(--line)}
.pt>summary{display:grid;grid-template-columns:28px 1fr 16px;padding:12px 0}
.pt>summary:before{content:counter(p)".";color:var(--dim)}
.pt>summary:after,details.rest>summary:after,details.rule>summary:after{content:"›";color:var(--dim);
font-size:20px;line-height:1;justify-self:end;transition:transform .15s}
details[open]>summary:after{transform:rotate(90deg)}
.pt-body{padding:0 0 16px 28px}
.sub{font-size:12px;font-weight:650;letter-spacing:.05em;text-transform:uppercase;color:var(--dim);margin:16px 0 6px}
table.tb{width:100%;border-collapse:collapse;margin:4px 0 12px;font-size:14px}
table.tb th,table.tb td{border:1px solid var(--line);padding:6px 10px;text-align:left;vertical-align:top}
table.tb th{font-weight:500;color:var(--dim);background:var(--soft)}
details.rest{margin:0 0 20px}details.rest>summary{display:grid;grid-template-columns:1fr 16px;gap:6px}
.kind{margin:14px 0 4px;font-weight:600;font-size:15px}.kind span{color:var(--dim);font-weight:400}
details.file{border:1px solid var(--line);border-radius:6px;margin:6px 0}
details.file>summary{padding:6px 10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:14px}
.nums{margin-left:auto;font-size:13px;color:var(--dim);font-variant-numeric:tabular-nums}
.tag{font-size:11px;color:var(--dim);background:var(--soft);padding:1px 7px;border-radius:999px}
.hunk{background:var(--cbg);border-top:1px solid var(--line)}
pre{margin:0;padding:8px 0;overflow-x:auto;font:12.5px/1.65 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--cfg)}
.ln{display:block;padding:0 10px;white-space:pre}
.ln.add{background:var(--add)}.ln.del{background:var(--del)}.ln.hl{outline:2px solid var(--hl);outline-offset:-2px}
.ln .num{display:inline-block;width:42px;color:var(--dim);font-weight:400;user-select:none}
.ln .sg{display:inline-block;width:16px;color:var(--dim);user-select:none}
.ln.ex{color:var(--ex)}.ln.ex i{font-style:normal}.eol{color:var(--ex);font-style:normal}
.hl-k{color:var(--k)}.hl-s{color:var(--s)}.hl-c{color:var(--c);font-style:italic}.hl-n{color:var(--n)}
.hl-t{color:var(--t)}.hl-f{color:var(--f)}
.note,.dim{font-size:12px;color:var(--dim)}.note{padding:8px 12px;border-top:1px solid var(--line)}.note i{color:var(--ex);font-style:normal}
.warn-head{color:var(--warn);margin:20px 0 6px}
ul.rules{margin:0;padding-left:20px}ul.rules>li{margin-bottom:10px}
details.rule>summary{display:inline-block;color:var(--dim);font-size:14px;margin-top:2px}
details.rule>summary:after{display:inline-block;margin-left:6px;font-size:16px}
.orig{font-size:14px;margin:8px 0}.cite{margin-top:10px;font-size:14px}
.cite-code{border:1px solid var(--line);border-radius:6px;overflow:hidden;margin-top:4px}
footer{margin-top:40px;padding-top:14px;border-top:1px solid var(--line);font-size:12px;color:var(--dim)}
@media (max-width:560px){main{padding:28px 14px 60px}.pt-body{padding-left:0}}
"""


def esc(value) -> str:
    return html.escape(str(value))


def path_code(path: str) -> str:
    """File path as inline code: dim folder, bold name."""
    head, sep, base = str(path).rpartition("/")
    folder = '<span class="dir">%s/</span>' % esc(head) if sep else ""
    return '<code class="ic">%s<b>%s</b></code>' % (folder, esc(base))


def table_html(table: Optional[Dict]) -> str:
    if not table or not table.get("head"):
        return ""
    head = table["head"]
    cols = len(head)
    rows = []
    for row in table.get("rows") or []:
        cells = (list(row) + [""] * cols)[:cols]
        rows.append("<tr>%s</tr>" % "".join("<td>%s</td>" % to_html(c) for c in cells))
    return ('<table class="tb"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>'
            % ("".join("<th>%s</th>" % to_html(c) for c in head), "".join(rows)))


def paragraphs(text: str) -> str:
    blocks = [b.strip() for b in str(text).replace("\r", "").split("\n\n") if b.strip()]
    return "".join("<p>%s</p>" % to_html(" ".join(b.split("\n"))) for b in blocks)


class Renderer:
    def __init__(self, facts: Dict, verified: Dict, labels: Dict,
                 branch: Optional[str]) -> None:
        self.facts, self.verified, self.labels = facts, verified, labels
        self.branch = branch
        self.files = {f["path"]: f for f in facts.get("files", [])}
        self.hunks: Dict[str, List[Dict]] = {}
        for h in facts.get("hunks", []):
            self.hunks.setdefault(h["file"], []).append(h)
        self.comments: Dict[Tuple[str, str, int, str], str] = {}
        self.commented_files = set()
        for c in verified.get("comments") or []:
            self.comments[(c["file"], c["side"], c["line"], c["pos"])] = c["text"]
            self.commented_files.add(c["file"])

    # code ------------------------------------------------------------------
    def _comment_rows(self, path: str, indent: str, text: str) -> str:
        marks = comment_marks(path)
        width = max(WRAP - len(indent), 40)
        lines: List[str] = []
        for para in text.split("\n"):
            lines.extend(textwrap.wrap(para, width) or [""])
        if len(lines) == 1:
            body = [marks["line"] + " " + lines[0]]
        elif marks["open"]:
            body = [marks["open"]] + [marks["mid"] + l for l in lines] + [marks["close"]]
        else:
            body = [marks["mid"] + l for l in lines]
        return "".join(
            '<span class="ln ex"><span class="num"></span><span class="sg"></span>'
            "<i>%s%s</i></span>" % (esc(indent), esc(row)) for row in body)

    def _line(self, path: str, side: str, number: int, text: str, plain: bool,
              mark: Optional[Tuple[str, int]], commented: bool) -> str:
        out = []
        indent = text[:len(text) - len(text.lstrip())]
        if commented:
            above = self.comments.get((path, side, number, "before"))
            if above:
                out.append(self._comment_rows(path, indent, above))
        cls = "" if plain else (" add" if side == "new" else " del")
        if mark == (side, number):
            cls += " hl"
        sign = "" if plain else ("+" if side == "new" else "−")
        tail = ""
        if commented:
            after = self.comments.get((path, side, number, "after"))
            if after:
                tail = '  <i class="eol">%s %s</i>' % (
                    esc(comment_marks(path)["line"]), esc(one(after)))
        out.append('<span class="ln%s"><span class="num">%d</span><span class="sg">%s</span>%s%s</span>'
                   % (cls, number, sign, highlight(text, path), tail))
        return "".join(out)

    def hunk_html(self, hunk: Dict, plain: bool = False, commented: bool = False,
                  mark: Optional[Tuple[str, int]] = None) -> str:
        path = hunk["file"]
        rows = []
        if not plain:
            for i, text in enumerate(hunk["removed"]):
                rows.append(self._line(path, "old", hunk["old_start"] + i, text, plain,
                                       mark, commented))
        for i, text in enumerate(hunk["added"]):
            rows.append(self._line(path, "new", hunk["new_start"] + i, text, plain,
                                   mark, commented))
        return '<div class="hunk"><pre>%s</pre></div>' % "".join(rows)

    def file_html(self, path: str, tag: Optional[str] = None, commented: bool = False,
                  mechanical_kind: Optional[str] = None) -> str:
        info = self.files.get(path, {})
        plain = info.get("status") in NEW_STATUSES
        tags = []
        if plain:
            tags.append(self.labels["tag_new"])
        if commented and path in self.commented_files:
            tags.append(self.labels["tag_explained"])
        if mechanical_kind:
            tags.append(self.labels.get("kind_" + mechanical_kind, mechanical_kind))
        if tag:
            tags.append(tag)
        tag_html = "".join(' <span class="tag">%s</span>' % esc(t) for t in tags)
        nums = '<span class="nums">+%d −%d</span>' % (info.get("additions", 0),
                                                     info.get("deletions", 0))
        hunks = sorted(self.hunks.get(path, []), key=lambda h: (h["new_start"], h["old_start"]))
        body = "".join(self.hunk_html(h, plain, commented) for h in hunks) or (
            '<p class="dim" style="padding:8px 12px;margin:0">%s</p>' % esc(self.labels["no_text_lines"]))
        note = ""
        if commented and path in self.commented_files:
            note = '<div class="note">%s</div>' % esc(self.labels["comment_note"])
        return ('<details class="file"><summary>%s%s%s</summary>%s%s</details>'
                % (path_code(path), tag_html, nums, body, note))

    def unverified_file(self, path: str) -> str:
        return '<p class="dim">⚠ %s: %s</p>' % (esc(self.labels["unverified_citation"]),
                                                  path_code(path))

    # sections --------------------------------------------------------------
    def points_html(self, model: Dict) -> str:
        items = []
        for p, shown in zip(self.verified.get("points") or [], model["points"]):
            files = "".join(self.file_html(f["path"], commented=True) if f["verified"]
                            else self.unverified_file(f["path"]) for f in p["files"])
            sub = '<div class="sub">%s · %d</div>' % (esc(self.labels["code_title"]),
                                                      len(p["files"])) if files else ""
            items.append(
                '<li><details class="pt"><summary><span><b>%s</b> %s</span></summary>'
                '<div class="pt-body">%s%s%s%s</div></details></li>'
                % (to_html(shown["title"]), to_html(shown["line"]), paragraphs(p.get("more") or ""),
                   table_html(p.get("table")), sub, files))
        return '<ol class="points">%s</ol>' % "".join(items) if items else ""

    def rest_html(self, model: Dict) -> str:
        groups = (self.verified.get("rest") or {}).get("groups") or []
        if not model["rest"] and not model["unexplained"]:
            return ""
        parts = []
        for g in groups:
            files = g.get("files") or []
            parts.append('<div class="kind">%s <span>· %d</span></div>'
                         % (esc(self.labels.get("kind_" + g["kind"], g["kind"])), len(files)))
            for f in files:
                if not f.get("verified", True):
                    parts.append(self.unverified_file(f["path"]))
                    continue
                tag = self.labels["tag_unexplained"] if g["kind"] == "unexplained" else None
                parts.append(self.file_html(f["path"], tag=tag,
                                            mechanical_kind=f.get("mechanical_kind")))
        head = ""
        if model["rest"]:
            head = ('<details class="rest"><summary><span><b>%s</b> %s</span></summary>%s</details>'
                    % (esc(model["rest"]["head"]), to_html(model["rest"]["line"]),
                       "".join(parts)))
        else:
            head = '<details class="rest"><summary><b>%s</b></summary>%s</details>' % (
                esc(model["unexplained"]["head"]), "".join(parts))
        return head

    def unexplained_html(self, model: Dict) -> str:
        un = model["unexplained"]
        if not un or not model["rest"]:
            return ""
        listed = [path_code(p) for p in un["files"][:MAX_LISTED]]
        more = len(un["files"]) - MAX_LISTED
        if more > 0:
            listed.append(esc(fill(self.labels["and_more"], n=more)))
        return "<p><b>%s</b> %s</p>" % (esc(un["head"]), ", ".join(listed))

    def _cited_hunk(self, change: Dict) -> str:
        side, number = change.get("side", "new"), change["line"]
        for h in self.hunks.get(self._canon(change["file"], side), []):
            lines, start = ((h["removed"], h["old_start"]) if side == "old"
                            else (h["added"], h["new_start"]))
            if 0 <= number - start < len(lines):
                plain = self.files.get(h["file"], {}).get("status") in NEW_STATUSES
                return '<div class="cite-code">%s</div>' % self.hunk_html(
                    h, plain=plain, mark=(side, number))
        return ""

    def _canon(self, path: str, side: str) -> str:
        if side == "old":
            for f in self.files.values():
                if (f.get("old_path") or f["path"]) == path:
                    return f["path"]
        return path

    def warnings_html(self, model: Dict) -> str:
        items = []
        for w, shown in zip(self.verified.get("warnings") or [], model["warnings"]):
            mark = "" if shown["verified"] else ' <span class="tag">⚠ %s</span>' % esc(
                self.labels["unverified_citation"])
            rule = w["rule"]
            ref = "%s:%s" % (rule.get("file"), rule.get("line"))
            if rule.get("verified"):
                orig = '<div class="orig">%s: <q>%s</q><br><code class="ic">%s</code></div>' % (
                    esc(self.labels["rule_original"]), esc(rule.get("text") or ""), esc(ref))
            else:
                orig = '<div class="orig">⚠ %s: <code class="ic">%s</code></div>' % (
                    esc(self.labels["unverified_citation"]), esc(ref))
            cites = []
            for c in w["changes"]:
                where = self.labels["old_version" if c.get("side") == "old" else "new_version"]
                label = '%s <span class="dim">:%s (%s)</span>' % (
                    path_code(c["file"]) if isinstance(c.get("file"), str) else "", esc(c.get("line")),
                    esc(where))
                if c.get("verified"):
                    cites.append('<div class="cite">%s%s</div>' % (label, self._cited_hunk(c)))
                else:
                    cites.append('<div class="cite">⚠ %s: %s</div>' % (
                        esc(self.labels["unverified_citation"]), label))
            items.append('<li>%s%s<br><details class="rule"><summary>%s</summary>%s%s</details></li>'
                         % (to_html(shown["text"]), mark, esc(self.labels["see_rule"]), orig,
                            "".join(cites)))
        if not items:
            return ""
        return '<p class="warn-head"><b>%s</b></p><ul class="rules">%s</ul>' % (
            esc(self.labels["warn_head"]), "".join(items))

    def footer_html(self) -> str:
        rng = self.facts.get("range") or {}
        spec = rng.get("spec") or {}
        ex = self.facts.get("excluded") or {}
        labels = self.labels
        none = labels["none"]

        def code(value) -> str:
            return '<code class="ic">%s</code>' % esc(value)

        start = spec.get("from") or spec.get("from_commit") or spec.get("commit") or rng.get("old")
        parts = ["%s %s" % (labels["from"], code(start)),
                 "%s %s" % (labels["to"], code(str(rng["new"])[:10]) if rng.get("new")
                            else esc(labels["working_tree"])),
                 "%s %s" % (labels["base"], code(str(rng.get("old"))[:10])),
                 "%s: %s" % (labels["excluded_merges"], ", ".join(
                     code(s[:10]) for s in ex.get("merges") or []) or esc(none)),
                 "%s: %s" % (labels["excluded_authors"], ", ".join(
                     code(a) for a in ex.get("authors") or []) or esc(none))]
        if self.verified.get("interpreted_in") == "same_conversation":
            parts.append(esc(labels["same_conversation"]))
        return "<footer>%s: %s</footer>" % (esc(labels["reviewed"]), " · ".join(parts))

    def meta_html(self) -> str:
        totals = self.facts.get("totals") or {}
        name = self.branch or self.labels["no_branch"]
        return '<p class="meta">%s · %s · +%d −%d</p>' % (
            esc(name), esc(fill(self.labels["count_files_one" if totals.get("files") == 1
                                            else "count_files_many"], n=totals.get("files", 0))),
            totals.get("additions", 0), totals.get("deletions", 0))


def render_html(facts: Dict, verified: Dict, labels: Dict, branch: Optional[str] = None,
                lang: str = "en") -> str:
    from .report import summary_model  # late import: report imports this module
    model = summary_model(facts, verified, labels)
    r = Renderer(facts, verified, labels, branch)
    body = [r.meta_html(), "<h1>%s</h1>" % to_html(model["lead"]), r.points_html(model),
            r.rest_html(model), r.unexplained_html(model),
            r.warnings_html(model), r.footer_html()]
    return ('<!doctype html>\n<html lang="%s"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>%s</title><style>%s</style></head><body><main>%s</main></body></html>\n"
            % (esc(lang), esc(strip_bold(labels["page_title"])), CSS, "".join(body)))
