from __future__ import annotations

import json
import re
import unittest

from helpers import RepoTestCase, run_script
from test_report import small

from explain_changes_lib import report
from explain_changes_lib.highlight import highlight

LABELS = report.LABELS["es"]


def render(facts=None, verified=None, labels=LABELS, branch="feat/x"):
    if facts is None:
        facts, verified = small()
    return report.render_html(facts, verified, labels, branch, "es")


class SelfContainedTests(unittest.TestCase):
    def test_no_external_resources_and_no_scripts(self):
        text = render()
        for needle in ("http://", "https://", "<script", "<link", "src=", "@import", "url(",
                       "<img", "<iframe"):
            self.assertNotIn(needle, text, needle)
        self.assertTrue(text.startswith("<!doctype html>"))
        self.assertIn('<html lang="es">', text)
        self.assertIn("prefers-color-scheme:dark", text)
        self.assertIn("color-scheme:light dark", text)

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
        self.assertNotIn("<script", text)
        self.assertIn("&lt;script&gt;", text)
        text = render(facts, verified, dict(LABELS, tag_new=evil, page_title=evil))
        self.assertNotIn("<script", text)


class StructureTests(unittest.TestCase):
    def test_summary_points_and_closed_details(self):
        text = render()
        self.assertIn('<p class="meta">feat/x · 3 archivos · +8 −6</p>', text)
        self.assertIn("<h1>3 archivos, pero lo importante es 1 cosa:</h1>", text)
        self.assertEqual(text.count('<details class="pt">'), 1)
        self.assertNotRegex(text, r"<details[^>]* open")
        self.assertIn("<b>Nuevo <code class=\"ic\">helper</code></b>", text)
        self.assertIn("<p>Más <b>detalle</b>.</p><p>Otro párrafo.</p>", text)
        self.assertIn('<table class="tb"><thead><tr><th>Parámetro</th><th>Qué es</th>', text)
        self.assertIn("<td><code class=\"ic\">x</code></td><td>Un valor</td>", text)
        # the same summary the conversation shows
        self.assertIn("Lo demás (2 archivos):", text)
        self.assertIn("Ojo con tus reglas:", text)
        self.assertIn("Tu regla <b>preserve-comments</b> dice: «no borres comentarios».", text)
        self.assertIn("Qué se revisó:", text)

    def test_file_header_new_files_and_diff_style(self):
        text = render()
        self.assertIn('<code class="ic"><span class="dir">src/</span><b>a.ts</b></code>', text)
        self.assertIn('<span class="nums">+2 −1</span>', text)
        modified = text.split('<b>a.ts</b>')[1].split("</details>")[0]
        self.assertIn('class="ln del"', modified)
        self.assertIn('class="ln add"', modified)
        self.assertIn("explicado", modified)
        new = text.split('<b>b.test.ts</b>')[1].split("</details>")[0]
        self.assertIn(">nuevo<", new)
        self.assertNotIn('class="ln add"', new)
        self.assertNotIn('class="ln del"', new)
        self.assertNotIn("explicado", new)

    def test_explanatory_comments_are_marked_and_unnumbered(self):
        text = render()
        a = text.split('<b>a.ts</b>')[1].split("</details>")[0]
        ex = re.findall(r'<span class="ln ex">(.*?)</i></span>', a)
        self.assertEqual(len(ex), 4)  # /*  Declara  Segunda  */
        self.assertTrue(all('<span class="num"></span>' in e for e in ex))
        self.assertLess(a.index("/*"), a.index("Declara"))
        self.assertLess(a.index("Declara"), a.index("Segunda"))
        self.assertIn('<i class="eol">// devuelve y</i>', a)
        self.assertEqual(a.count(LABELS["comment_note"]), 1)
        b = text.split('<b>b.test.ts</b>')[1].split("</details>")[0]
        self.assertNotIn(LABELS["comment_note"], b)

    def test_single_line_comment_above_uses_double_slash(self):
        facts, verified = small()
        verified["comments"] = [{"file": "src/a.ts", "side": "new", "line": 4, "pos": "before",
                                 "text": "Corto."}]
        text = render(facts, verified)
        self.assertIn("// Corto.", text)
        self.assertNotIn("/*", text.split('<b>a.ts</b>')[1].split("</details>")[0])

    def test_rest_groups_and_unexplained_tag(self):
        facts, verified = small()
        verified["rest"]["groups"].append(
            {"kind": "unexplained", "files": [{"path": "src/a.ts", "verified": True}]})
        verified["rest"]["groups"].append(
            {"kind": "docs", "files": [{"path": "ghost.md", "verified": False}]})
        text = render(facts, verified)
        rest = text.split('<details class="rest">')[1]
        self.assertIn("Pruebas", rest)
        self.assertIn("Cambios mecánicos", rest)
        self.assertIn("<span>· 1</span>", rest)
        self.assertIn(">lockfile<", rest)
        self.assertIn("la IA no lo explicó", rest)
        self.assertIn("Sin agrupar (1 archivo):", text)
        self.assertIn("⚠ cita no verificada", rest)
        self.assertIn("ghost.md", rest)

    def test_unverified_point_file_has_no_code(self):
        facts, verified = small()
        verified["points"][0]["files"].append({"path": "ghost.ts", "verified": False})
        text = render(facts, verified)
        self.assertEqual(text.count("ghost.ts"), 1)
        self.assertIn("⚠ cita no verificada", text)

    def test_rule_warning_shows_rule_and_highlighted_lines(self):
        text = render()
        block = text.split('<ul class="rules">')[1]
        self.assertIn("Ver la regla y el código", block)
        self.assertIn("Texto original: <q>Keep comments.</q>", block)
        self.assertIn(".agents/rules/preserve-comments/RULE.md:2", block)
        self.assertIn(":3 (versión anterior)", block)
        self.assertEqual(block.count(" hl"), 1)
        marked = re.search(r'<span class="ln del hl">(.*?)</span></span>', block)
        self.assertIsNotNone(marked)
        self.assertIn("// old", marked.group(1))

    def test_unverified_warning_citations_show_no_code(self):
        facts, verified = small()
        warn = verified["warnings"][0]
        warn["verified"] = False
        warn["rule"].update(verified=False, text="")
        warn["changes"].append({"file": "src/a.ts", "line": 99, "side": "new", "verified": False})
        warn["changes"][0]["verified"] = False
        text = render(facts, verified)
        block = text.split('<ul class="rules">')[1]
        self.assertNotIn('class="hunk"', block)
        self.assertNotIn("<q>", block)
        self.assertGreaterEqual(block.count("⚠"), 4)

    def test_no_legends_cards_bars_or_checkboxes(self):
        text = render()
        for needle in ("<input", "checkbox", "<progress", "legend", "review", "revisar",
                       "típico"):
            self.assertNotIn(needle, text.replace("Qué se revisó", ""), needle)

    def test_only_one_inline_code_color(self):
        css = render().split("<style>")[1].split("</style>")[0]
        self.assertEqual(len(re.findall(r"code\.ic\{[^}]*color:var\(--ic\)", css)), 1)
        self.assertEqual(re.findall(r"\.ent|\.kind-|--c-file|--c-fn", css), [])


class HighlightTests(unittest.TestCase):
    def test_tokens(self):
        line = highlight("const n = foo(1, 'a'); // note", "src/a.ts")
        for cls in ("hl-k", "hl-n", "hl-s", "hl-f", "hl-c"):
            self.assertIn(cls, line)
        self.assertIn("hl-t", highlight("let x: Foo", "a.ts"))
        self.assertIn('<span class="hl-c"># hi</span>', highlight("# hi", "a.py"))
        self.assertIn("hl-k", highlight("def f(): return None", "a.py"))
        self.assertNotIn("hl-", highlight("plain text 12", "notes.md").replace("hl-n", ""))

    def test_escapes_and_never_loses_text(self):
        line = '<a href="x">&amp;</a> `t` // <b>'
        out = highlight(line, "a.tsx")
        self.assertNotIn("<a", out)
        import html
        self.assertEqual(html.unescape(re.sub(r"</?span[^>]*>", "", out)), line)


class NoInternalIdsTests(RepoTestCase):
    def test_target_ids_never_reach_the_reports(self):
        repo = self.make_repo()
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
        self.assertEqual(code, 0, data)
        facts = json.loads((repo.path / ".explain-changes/run/facts.json").read_text())
        self.assertIn("R1", json.dumps(facts))  # the ids do exist internally
        interp = {"points": [{"title": "Cambio", "line": "l", "files": ["src/a.ts"]}],
                  "warnings": [{"says": "conserva los comentarios",
                                "change": "Se borró `// keep me`.",
                                "rule": {"file": ".agents/rules/preserve-comments/RULE.md",
                                         "line": 2},
                                "changes": [{"file": "src/a.ts", "line": 1, "side": "old"}]}]}
        self.assertEqual(run_script(repo, "verify", stdin=json.dumps(interp))[0], 0)
        code, data = run_script(repo, "report", "--lang", "es")
        self.assertEqual(code, 0, data)
        work = repo.path / ".explain-changes"
        for name in ("report.md", "report.html"):
            text = (work / name).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"\bR\d+\b", name)
            self.assertIn("preserve-comments", text, name)
        # ...and an interpretation that leaks an id is refused before anything is written
        interp["warnings"][0]["change"] = "Rompe R1"
        code, data = run_script(repo, "verify", stdin=json.dumps(interp))
        self.assertEqual((code, data["error"]["code"]), (2, "bad_input"))
        self.assertIn("R1", data["error"]["message"])

    def test_rule_name_comes_from_folder_or_file(self):
        from explain_changes_lib.rules import rule_name
        self.assertEqual(rule_name(".agents/rules/preserve-comments/RULE.md"), "preserve-comments")
        self.assertEqual(rule_name(".agents/rules/hooks.md"), "hooks")
        self.assertEqual(rule_name(".cursor/rules/style.mdc"), "style")
        self.assertEqual(rule_name("AGENTS.md"), "AGENTS")
        self.assertEqual(rule_name(".cursorrules"), "cursorrules")
        self.assertEqual(rule_name("docs/api/README.md"), "api")


if __name__ == "__main__":
    unittest.main()
