from __future__ import annotations

import json
import re

from explain_helpers import run_script
from test_report import small

from explain_changes_lib import report
from explain_changes_lib.highlight import highlight

LABELS = report.LABELS["es"]


def render(facts=None, verified=None, labels=LABELS, branch="feat/x"):
    if facts is None:
        facts, verified = small()
    return report.render_html(facts, verified, labels, branch, "es")


class TestSelfContained:
    def test_no_external_resources_and_no_scripts(self):
        text = render()
        for needle in ("http://", "https://", "<script", "<link", "src=", "@import", "url(",
                       "<img", "<iframe"):
            assert needle not in text, needle
        assert text.startswith("<!doctype html>")
        assert '<html lang="es">' in text
        assert "prefers-color-scheme:dark" in text
        assert "color-scheme:light dark" in text

    def test_everything_from_the_repo_is_escaped(self):
        facts, verified = small()
        evil = "<script>alert(1)</script>"
        facts["files"][0]["path"] = "src/%s.ts" % evil
        facts["hunks"][0]["file"] = facts["files"][0]["path"]
        facts["hunks"][0]["added"][0] = "const s = '%s';" % evil
        verified["points"][0]["title"] = evil
        verified["points"][0]["line"] = "x " + evil
        verified["points"][0]["more"] = evil
        verified["points"][0]["files"][0]["path"] = facts["files"][0]["path"]
        verified["points"][0]["table"]["rows"][0][1] = evil
        verified["comments"][0]["file"] = facts["files"][0]["path"]
        verified["comments"][1]["file"] = facts["files"][0]["path"]
        verified["comments"][0]["text"] = evil
        verified["warnings"][0]["rule"]["text"] = evil
        verified["warnings"][0]["says"] = evil
        verified["warnings"][0]["changes"][0]["file"] = facts["files"][0]["path"]
        verified["rest"]["line"] = evil
        facts["range"]["spec"]["from"] = evil
        facts["excluded"]["authors"] = [evil]
        text = render(facts, verified, branch=evil)
        assert "<script" not in text
        assert "&lt;script&gt;" in text
        text = render(facts, verified, dict(LABELS, tag_new=evil, page_title=evil))
        assert "<script" not in text


class TestStructure:
    def test_summary_points_and_closed_details(self):
        text = render()
        assert '<p class="meta">feat/x · 3 archivos · +8 −6</p>' in text
        assert "<h1>3 archivos, pero lo importante es 1 cosa:</h1>" in text
        assert text.count('<details class="pt">') == 1
        assert not re.search(r"<details[^>]* open", text)
        assert "<b>Nuevo <code class=\"ic\">helper</code></b>" in text
        assert "<p>Más <b>detalle</b>.</p><p>Otro párrafo.</p>" in text
        assert '<table class="tb"><thead><tr><th>Parámetro</th><th>Qué es</th>' in text
        assert "<td><code class=\"ic\">x</code></td><td>Un valor</td>" in text
        # the same summary the conversation shows
        assert "Lo demás (2 archivos):" in text
        assert "Ojo con tus reglas:" in text
        assert "Tu regla <b>preserve-comments</b> dice: «no borres comentarios»." in text
        assert "Qué se revisó:" in text

    def test_file_header_new_files_and_diff_style(self):
        text = render()
        assert '<code class="ic"><span class="dir">src/</span><b>a.ts</b></code>' in text
        assert '<span class="nums">+2 −1</span>' in text
        modified = text.split('<b>a.ts</b>')[1].split("</details>")[0]
        assert 'class="ln del"' in modified
        assert 'class="ln add"' in modified
        assert "explicado" in modified
        new = text.split('<b>b.test.ts</b>')[1].split("</details>")[0]
        assert ">nuevo<" in new
        assert 'class="ln add"' not in new
        assert 'class="ln del"' not in new
        assert "explicado" not in new

    def test_explanatory_comments_are_marked_and_unnumbered(self):
        text = render()
        a = text.split('<b>a.ts</b>')[1].split("</details>")[0]
        ex = re.findall(r'<span class="ln ex">(.*?)</i></span>', a)
        assert len(ex) == 4  # /*  Declara  Segunda  */
        assert all('<span class="num"></span>' in e for e in ex)
        assert a.index("/*") < a.index("Declara")
        assert a.index("Declara") < a.index("Segunda")
        assert '<i class="eol">// devuelve y</i>' in a
        assert a.count(LABELS["comment_note"]) == 1
        b = text.split('<b>b.test.ts</b>')[1].split("</details>")[0]
        assert LABELS["comment_note"] not in b

    def test_single_line_comment_above_uses_double_slash(self):
        facts, verified = small()
        verified["comments"] = [{"file": "src/a.ts", "side": "new", "line": 4, "pos": "before",
                                 "text": "Corto."}]
        text = render(facts, verified)
        assert "// Corto." in text
        assert "/*" not in text.split('<b>a.ts</b>')[1].split("</details>")[0]

    def test_rest_groups_and_unexplained_tag(self):
        facts, verified = small()
        verified["rest"]["groups"].append(
            {"kind": "unexplained", "files": [{"path": "src/a.ts", "verified": True}]})
        verified["rest"]["groups"].append(
            {"kind": "docs", "files": [{"path": "ghost.md", "verified": False}]})
        text = render(facts, verified)
        rest = text.split('<details class="rest">')[1]
        assert "Pruebas" in rest
        assert "Cambios mecánicos" in rest
        assert "<span>· 1</span>" in rest
        assert ">lockfile<" in rest
        assert "la IA no lo explicó" in rest
        assert "Sin agrupar (1 archivo):" in text
        assert "⚠ cita no verificada" in rest
        assert "ghost.md" in rest

    def test_unverified_point_file_has_no_code(self):
        facts, verified = small()
        verified["points"][0]["files"].append({"path": "ghost.ts", "verified": False})
        text = render(facts, verified)
        assert text.count("ghost.ts") == 1
        assert "⚠ cita no verificada" in text

    def test_rule_warning_shows_rule_and_highlighted_lines(self):
        text = render()
        block = text.split('<ul class="rules">')[1]
        assert "Ver la regla y el código" in block
        assert "Texto original: <q>Keep comments.</q>" in block
        assert ".agents/rules/preserve-comments/RULE.md:2" in block
        assert ":3 (versión anterior)" in block
        assert block.count(" hl") == 1
        marked = re.search(r'<span class="ln del hl">(.*?)</span></span>', block)
        assert marked is not None
        assert "// old" in marked.group(1)

    def test_unverified_warning_citations_show_no_code(self):
        facts, verified = small()
        warn = verified["warnings"][0]
        warn["verified"] = False
        warn["rule"].update(verified=False, text="")
        warn["changes"].append({"file": "src/a.ts", "line": 99, "side": "new", "verified": False})
        warn["changes"][0]["verified"] = False
        text = render(facts, verified)
        block = text.split('<ul class="rules">')[1]
        assert 'class="hunk"' not in block
        assert "<q>" not in block
        assert block.count("⚠") >= 4

    def test_no_legends_cards_bars_or_checkboxes(self):
        text = render()
        for needle in ("<input", "checkbox", "<progress", "legend", "review", "revisar",
                       "típico"):
            assert needle not in text.replace("Qué se revisó", ""), needle

    def test_only_one_inline_code_color(self):
        css = render().split("<style>")[1].split("</style>")[0]
        assert len(re.findall(r"code\.ic\{[^}]*color:var\(--ic\)", css)) == 1
        assert re.findall(r"\.ent|\.kind-|--c-file|--c-fn", css) == []


class TestHighlight:
    def test_tokens(self):
        line = highlight("const n = foo(1, 'a'); // note", "src/a.ts")
        for cls in ("hl-k", "hl-n", "hl-s", "hl-f", "hl-c"):
            assert cls in line
        assert "hl-t" in highlight("let x: Foo", "a.ts")
        assert '<span class="hl-c"># hi</span>' in highlight("# hi", "a.py")
        assert "hl-k" in highlight("def f(): return None", "a.py")
        assert "hl-" not in highlight("plain text 12", "notes.md").replace("hl-n", "")

    def test_escapes_and_never_loses_text(self):
        line = '<a href="x">&amp;</a> `t` // <b>'
        out = highlight(line, "a.tsx")
        assert "<a" not in out
        import html
        assert html.unescape(re.sub(r"</?span[^>]*>", "", out)) == line


class TestNoInternalIds:
    def test_target_ids_never_reach_the_reports(self, make_repo):
        repo = make_repo()
        repo.write(".agents/rules/preserve-comments/RULE.md", "# preserve\nKeep comments.\n")
        repo.write("src/a.ts", "// keep me\nexport const a = 1;\n")
        repo.commit("base")
        repo.checkout("feat", create=True)
        repo.write("src/a.ts", "export const a = 2;\n")
        repo.commit("change")
        targets = [{"id": "R1", "rule": {"file": ".agents/rules/preserve-comments/RULE.md",
                                         "line": 2}, "paths": ["**/*.ts"],
                    "change_kinds": ["modify"], "line_pattern": "keep"},
                   {"id": "R2", "rule": {"file": ".agents/rules/preserve-comments/RULE.md",
                                         "line": 1}, "paths": ["**/*.ts"], "change_kinds": []}]
        code, data = run_script(repo, "facts", "--from", "main", "--targets-stdin",
                                stdin=json.dumps(targets))
        assert code == 0, data
        facts = json.loads((repo.path / ".explain-changes/run/facts.json").read_text())
        assert "R1" in json.dumps(facts)  # the ids do exist internally
        interp = {"points": [{"title": "Cambio", "line": "l", "files": ["src/a.ts"]}],
                  "warnings": [{"says": "conserva los comentarios",
                                "change": "Se borró `// keep me`.",
                                "rule": {"file": ".agents/rules/preserve-comments/RULE.md",
                                         "line": 2},
                                "changes": [{"file": "src/a.ts", "line": 1, "side": "old"}]}]}
        assert run_script(repo, "verify", stdin=json.dumps(interp))[0] == 0
        code, data = run_script(repo, "report", "--lang", "es")
        assert code == 0, data
        work = repo.path / ".explain-changes"
        for name in ("report.md", "report.html"):
            text = (work / name).read_text(encoding="utf-8")
            assert not re.search(r"\bR\d+\b", text), name
            assert "preserve-comments" in text, name
        # ...and an interpretation that leaks an id is refused before anything is written
        interp["warnings"][0]["change"] = "Rompe R1"
        code, data = run_script(repo, "verify", stdin=json.dumps(interp))
        assert (code, data["error"]["code"]) == (2, "bad_input")
        assert "R1" in data["error"]["message"]

    def test_rule_name_comes_from_folder_or_file(self):
        from explain_changes_lib.rules import rule_name
        assert rule_name(".agents/rules/preserve-comments/RULE.md") == "preserve-comments"
        assert rule_name(".agents/rules/hooks.md") == "hooks"
        assert rule_name(".cursor/rules/style.mdc") == "style"
        assert rule_name("AGENTS.md") == "AGENTS"
        assert rule_name(".cursorrules") == "cursorrules"
        assert rule_name("docs/api/README.md") == "api"

