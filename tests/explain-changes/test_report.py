from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest

import helpers
from helpers import RepoTestCase, run_script

from explain_changes_lib import report
from explain_changes_lib.state import load_state


def small():
    facts = {
        "range": {"old": "a" * 40, "new": None, "spec": {
            "from": "main", "commit": None, "include_uncommitted": False,
            "exclude_merges": [], "include_merges": [], "exclude_authors": []}},
        "files": [
            {"path": "src/a.ts", "old_path": None, "status": "modified", "class": "logic",
             "mechanical_kind": None, "additions": 2, "deletions": 1, "hunks": ["h-1"],
             "rules": ["R1"]},
            {"path": "src/b.test.ts", "old_path": None, "status": "untracked", "class": "logic",
             "mechanical_kind": None, "additions": 1, "deletions": 0, "hunks": ["h-2"],
             "rules": []},
            {"path": "pnpm-lock.yaml", "old_path": None, "status": "modified",
             "class": "mechanical", "mechanical_kind": "lockfile", "additions": 5,
             "deletions": 5, "hunks": [], "rules": []},
        ],
        "hunks": [{"id": "h-1", "file": "src/a.ts", "new_start": 3, "new_lines": 2,
                   "old_start": 3, "old_lines": 1, "class": "logic", "rules": ["R1"],
                   "added": ["const x = 1;", "  return y;"], "removed": ["// old"],
                   "changed_since_review": True, "seen": False, "mechanical_kind": None},
                  {"id": "h-2", "file": "src/b.test.ts", "new_start": 1, "new_lines": 1,
                   "old_start": 0, "old_lines": 0, "class": "logic", "rules": [],
                   "added": ["test('a', () => {});"], "removed": [],
                   "changed_since_review": False, "seen": False, "mechanical_kind": None}],
        "excluded": {"merges": ["b" * 40], "authors": ["bot@x.io"], "dropped_hunks": 0},
        "rule_files": [], "replacements": [], "batches": [], "targets": [], "notices": [],
        "commits": [], "commits_truncated": False,
        "totals": {"files": 3, "additions": 8, "deletions": 6,
                   "logic_lines": 4, "mechanical_lines": 10},
    }
    verified = {
        "interpreted_in": "same_conversation",
        "points": [{"id": "p1", "order": 1, "title": "Nuevo `helper`",
                    "line": "en `src/`: hace algo.", "more": "Más **detalle**.\n\nOtro párrafo.",
                    "table": {"head": ["Parámetro", "Qué es"], "rows": [["`x`", "Un valor"]]},
                    "files": [{"path": "src/a.ts", "verified": True}]}],
        "rest": {"line": "pruebas y lockfile.", "groups": [
            {"kind": "tests", "files": [{"path": "src/b.test.ts", "verified": True,
                                         "mechanical_kind": None}]},
            {"kind": "mechanical", "files": [{"path": "pnpm-lock.yaml", "verified": True,
                                              "mechanical_kind": "lockfile"}]}]},
        "warnings": [{"name": "preserve-comments", "says": "no borres comentarios",
                      "change": "Se borró un comentario en `src/a.ts`.",
                      "rule": {"file": ".agents/rules/preserve-comments/RULE.md", "line": 2,
                               "verified": True, "text": "Keep comments."},
                      "changes": [{"file": "src/a.ts", "line": 3, "side": "old",
                                   "verified": True}], "verified": True}],
        "comments": [{"file": "src/a.ts", "side": "new", "line": 3, "pos": "before",
                      "text": "Declara `x`.\nSegunda línea."},
                     {"file": "src/a.ts", "side": "new", "line": 4, "pos": "after",
                      "text": "devuelve y"}],
        "unverified": [], "dropped": [],
    }
    return facts, verified


class RenderTests(unittest.TestCase):
    def test_markdown_is_the_conversation_summary(self):
        facts, verified = small()
        text = report.render(facts, verified, report.LABELS["es"])
        self.assertEqual(text, "\n".join([
            "3 archivos, pero lo importante es 1 cosa:",
            "",
            "1. **Nuevo `helper`** en `src/`: hace algo.",
            "",
            "**Lo demás (2 archivos):** pruebas y lockfile.",
            "",
            "**Ojo con tus reglas:**",
            "",
            "- Se borró un comentario en `src/a.ts`. Tu regla **preserve-comments** dice: "
            "«no borres comentarios».",
            ""]))

    def test_lead_variants(self):
        facts, verified = small()
        labels = report.LABELS["en"]
        verified["points"] = verified["points"] * 2
        self.assertTrue(report.render(facts, verified, labels).startswith(
            "3 files, but what matters is 2 things:"))
        verified["points"] = []
        self.assertTrue(report.render(facts, verified, labels).startswith(
            "3 files, with no logic changes to highlight."))
        facts["totals"]["files"] = 1
        self.assertTrue(report.render(facts, verified, labels).startswith("1 file, with"))
        facts["totals"]["files"] = 0
        verified["rest"] = {"line": "", "groups": []}
        verified["warnings"] = []
        self.assertEqual(report.render(facts, verified, labels),
                         "There are no changes to explain.\n")

    def test_no_warnings_means_no_warning_section(self):
        facts, verified = small()
        verified["warnings"] = []
        text = report.render(facts, verified, report.LABELS["es"])
        self.assertNotIn("Ojo con tus reglas", text)

    def test_unverified_warning_is_marked_and_unexplained_is_listed(self):
        facts, verified = small()
        verified["warnings"][0]["verified"] = False
        files = ["f%d.ts" % i for i in range(7)]
        verified["rest"]["groups"].append(
            {"kind": "unexplained", "files": [{"path": p, "verified": True} for p in files]})
        text = report.render(facts, verified, report.LABELS["es"])
        self.assertIn("⚠ cita no verificada", text)
        self.assertIn("**Sin agrupar (7 archivos):** `f0.ts`, `f1.ts`, `f2.ts`, `f3.ts`, "
                      "`f4.ts`, y 2 más", text)
        self.assertIn("**Lo demás (2 archivos):**", text)  # unexplained files are not "the rest"

    def test_user_text_cannot_break_structure(self):
        facts, verified = small()
        verified["points"][0]["title"] = "# Fake\n## Heading **x**"
        verified["points"][0]["line"] = "line1\n## Sneaky `a``b`"
        verified["warnings"][0]["change"] = "x\r\n## Note"
        verified["rest"]["line"] = "a\n# H"
        text = report.render(facts, verified, report.LABELS["en"])
        self.assertFalse([l for l in text.split("\n") if l.startswith("#")])
        self.assertIn("1. **# Fake ## Heading x**", text)
        self.assertEqual(text.count("\n\n"), 4)

    def test_no_internal_ids_in_markdown(self):
        facts, verified = small()
        text = report.render(facts, verified, report.LABELS["es"])
        self.assertNotRegex(text, r"\bR\d+\b")
        self.assertNotIn("h-1", text)

    def test_label_keys_match(self):
        self.assertEqual(set(report.LABELS["en"]), set(report.LABELS["es"]))

    def test_label_keys_are_all_used_and_documented(self):
        from helpers import ROOT
        base = ROOT / "skills" / "explain-changes"
        lib = base / "scripts" / "explain_changes_lib"
        source = "".join((lib / name).read_text(encoding="utf-8")
                         for name in ("report.py", "report_html.py"))
        used = {k for k in report.LABELS["en"] if '"%s"' % k in source or k.startswith("kind_")}
        self.assertEqual(set(report.LABELS["en"]), used)
        doc = (base / "references" / "report-format.md").read_text(encoding="utf-8")
        documented = set(re.findall(r"^\| `(\w+)` \|", doc, re.M))
        self.assertEqual(documented, used)

    def test_fill_leaves_foreign_braces_alone(self):
        from explain_changes_lib.labels import fill
        self.assertEqual(fill("{a} {b} {c}", a="{b}", b="x"), "{b} x {c}")


class WriteReportTests(RepoTestCase):
    def pipeline(self, repo, interp=None):
        code, data = run_script(repo, "facts", "--from", "main")
        self.assertEqual(code, 0, data)
        code, data = run_script(repo, "verify",
                                stdin=json.dumps(interp or {"points": []}))
        self.assertEqual(code, 0, data)
        return run_script(repo, "report", "--lang", "es")

    def feature(self, text="one\n"):
        repo = self.make_repo()
        repo.write("a.txt", "base\n")
        repo.commit("base")
        repo.checkout("feat", create=True)
        repo.write("a.txt", "base\n" + text)
        repo.commit("change")
        return repo

    def test_previous_report_replaced(self):
        repo = self.feature("first\n")
        interp = {"points": [{"title": "T", "files": ["a.txt"]}]}
        code, data = self.pipeline(repo, interp)
        self.assertEqual(code, 0, data)
        self.assertTrue(data["ok"])
        repo.write("second.txt", "s\n")
        repo.commit("again")
        work = repo.path / ".explain-changes"
        self.assertNotIn("second.txt", (work / "report.html").read_text(encoding="utf-8"))
        interp["points"][0]["files"].append("second.txt")
        code, data = self.pipeline(repo, interp)
        self.assertEqual(code, 0, data)
        reports = sorted(p.name for p in work.rglob("report*"))
        self.assertEqual(reports, ["report.html", "report.md"])
        self.assertIn("second.txt", (work / "report.html").read_text(encoding="utf-8"))
        self.assertEqual(data["path"], ".explain-changes/report.md")
        self.assertEqual(data["html_path"], ".explain-changes/report.html")
        self.assertTrue(data["state_path"].startswith(".explain-changes/state/"))

    def test_real_pipeline_warnings_and_unverified(self):
        repo = self.make_repo()
        repo.write("AGENTS.md", "# rules\nbe kind\nbe brief\nbe clear\nbe fast\n")
        repo.write("a.txt", "base\n")
        repo.commit("base")
        repo.checkout("feat", create=True)
        repo.write("a.txt", "base\nnew\n")
        repo.commit("change")
        warn = lambda n: {"says": "be kind", "change": "Algo pasó.", "name": "kindness",
                          "rule": {"file": "AGENTS.md", "line": n},
                          "changes": [{"file": "a.txt", "line": 2}]}
        interp = {"points": [{"title": "Nuevo", "line": "l", "files": ["a.txt"]}],
                  "warnings": [warn(2), warn(99)]}
        code, data = self.pipeline(repo, interp)
        self.assertEqual(code, 0, data)
        text = (repo.path / ".explain-changes" / "report.md").read_text(encoding="utf-8")
        self.assertIn("1 archivo, pero lo importante es 1 cosa:", text)
        self.assertEqual(text.count("Tu regla **kindness** dice: «be kind»."), 2)
        self.assertEqual(text.count("⚠ cita no verificada"), 1)
        self.assertNotIn("AGENTS.md", text)
        html = (repo.path / ".explain-changes" / "report.html").read_text(encoding="utf-8")
        self.assertIn("AGENTS.md:99", html)

    def test_stale_state_cleanup(self):
        repo = self.feature()
        repo.checkout("gone", create=True)
        repo.write("g.txt", "g\n")
        repo.commit("g")
        self.assertEqual(self.pipeline(repo)[0], 0)
        gone = load_state(repo.path, "gone")
        self.assertIsNotNone(gone)
        repo.checkout("main")
        repo.git("branch", "-D", "gone")
        repo.checkout("merged", create=True)
        repo.write("m.txt", "m\n")
        repo.commit("m")
        self.assertEqual(self.pipeline(repo)[0], 0)
        repo.checkout("main")
        repo.git("merge", "-q", "--ff-only", "merged")
        repo.checkout("feat")
        junk = repo.path / ".explain-changes" / "state" / "junk.json"
        junk.write_text("not json")
        code, data = self.pipeline(repo)
        self.assertEqual(code, 0, data)
        self.assertIsNone(load_state(repo.path, "gone"))
        self.assertIsNone(load_state(repo.path, "merged"))
        self.assertIsNotNone(load_state(repo.path, "feat"))
        self.assertTrue(junk.exists())
        files = sorted(p.name for p in (repo.path / ".explain-changes" / "state").iterdir())
        self.assertEqual(len(files), 2, files)
        manifest = json.loads((repo.path / ".explain-changes" / ".manifest.json").read_text())
        self.assertEqual(len([f for f in manifest["files"] if f.startswith("state/")]), 1)

    def test_only_new_keeps_previous_hunks_in_state(self):
        repo = self.feature("first\n")
        self.assertEqual(self.pipeline(repo)[0], 0)
        repo.write("b.txt", "b\n")
        repo.commit("more")
        code, data = run_script(repo, "facts", "--from", "main", "--only-new")
        self.assertEqual(code, 0, data)
        run_script(repo, "verify", stdin='{"points": []}')
        self.assertEqual(run_script(repo, "report", "--lang", "en")[0], 0)
        state = load_state(repo.path, "feat")
        self.assertEqual(len(state["hunks"]), 2)

    def test_detached_head_has_no_state(self):
        repo = self.feature()
        repo.git("checkout", "-q", "--detach")
        code, data = self.pipeline(repo)
        self.assertEqual(code, 0, data)
        self.assertIsNone(data["state_path"])
        self.assertTrue((repo.path / ".explain-changes" / "report.md").exists())

    def test_labels_override_and_bad_input(self):
        repo = self.feature()
        run_script(repo, "facts", "--from", "main")
        run_script(repo, "verify", stdin='{"points": []}')
        code, data = run_script(repo, "report", "--lang", "fr", "--labels-stdin",
                                stdin=json.dumps({"lead_none": "{files} : rien de plus"}))
        self.assertEqual(code, 0, data)
        text = (repo.path / ".explain-changes" / "report.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("1 file : rien de plus\n"))
        code, data = run_script(repo, "report", "--lang", "es", "--labels-stdin",
                                stdin="{nope")
        self.assertEqual((code, data["error"]["code"]), (2, "bad_input"))
        code, data = run_script(repo, "report", "--lang", "es", "--labels-stdin",
                                stdin="[1]")
        self.assertEqual((code, data["error"]["code"]), (2, "bad_input"))

    def test_report_without_flag_ignores_stdin(self):
        repo = self.feature()
        run_script(repo, "facts", "--from", "main")
        run_script(repo, "verify", stdin='{"points": []}')
        proc = subprocess.Popen([sys.executable, str(helpers.SCRIPT), "report", "--lang", "es"],
                                cwd=repo.path, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            proc.wait(timeout=30)  # stdin stays open and is never written
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            self.fail("report blocked on stdin")
        finally:
            proc.stdin.close()
            out = proc.stdout.read()
            proc.stdout.close()
            proc.stderr.close()
        self.assertEqual(proc.returncode, 0, out)
        code, data = run_script(repo, "report", "--lang", "es", "--labels-stdin", stdin="{nope")
        self.assertEqual((code, data["error"]["code"]), (2, "bad_input"))

    def test_facts_commits(self):
        repo = self.make_repo()
        repo.write("a.txt", "base\n")
        repo.commit("base")
        repo.checkout("feat", create=True)
        repo.write("a.txt", "base\n1\n")
        repo.commit("mine one")
        repo.write("a.txt", "base\n1\n2\n")
        repo.commit("bot change", email="bot@x.io")
        repo.write("a.txt", "base\n1\n2\n3\n")
        sha = repo.commit("mine two")
        run_script(repo, "facts", "--from", "main", "--exclude-author", "bot@x.io")
        facts = json.loads((repo.path / ".explain-changes/run/facts.json").read_text())
        self.assertEqual([c["subject"] for c in facts["commits"]], ["mine one", "mine two"])
        self.assertEqual(facts["commits"][1]["sha"], sha)
        self.assertEqual(facts["commits"][0]["email"], "me@x.io")
        self.assertFalse(facts["commits_truncated"])
        run_script(repo, "facts", "--commit", sha)
        facts = json.loads((repo.path / ".explain-changes/run/facts.json").read_text())
        self.assertEqual([c["subject"] for c in facts["commits"]], ["mine two"])
        run_script(repo, "facts", "--from", "HEAD", "--include-uncommitted")
        facts = json.loads((repo.path / ".explain-changes/run/facts.json").read_text())
        self.assertEqual(facts["commits"], [])

    def test_facts_commits_capped(self):
        repo = self.make_repo()
        repo.write("a.txt", "base\n")
        repo.commit("base")
        repo.checkout("feat", create=True)
        for i in range(52):
            repo.git("commit", "-q", "--allow-empty", "-m", "c%d" % i)
        run_script(repo, "facts", "--from", "main")
        facts = json.loads((repo.path / ".explain-changes/run/facts.json").read_text())
        self.assertEqual(len(facts["commits"]), 50)
        self.assertTrue(facts["commits_truncated"])

    def test_missing_inputs_is_bad_input(self):
        repo = self.feature()
        code, data = run_script(repo, "report", "--lang", "es")
        self.assertEqual((code, data["error"]["code"]), (2, "bad_input"))
        run_script(repo, "facts", "--from", "main")
        code, data = run_script(repo, "report", "--lang", "es")
        self.assertEqual((code, data["error"]["code"]), (2, "bad_input"))

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0,
                     "running as root: chmod cannot make info/exclude unwritable")
    def test_refuses_when_not_excludable(self):
        repo = self.feature()
        run = repo.path / ".explain-changes" / "run"
        run.mkdir(parents=True)
        facts, verified = small()
        (run / "facts.json").write_text(json.dumps(facts))
        (run / "verified.json").write_text(json.dumps(verified))
        exclude = repo.path / ".git" / "info" / "exclude"
        exclude.parent.mkdir(exist_ok=True)
        if not exclude.exists():
            exclude.write_text("")
        os.chmod(exclude, 0o444)
        self.addCleanup(os.chmod, exclude, 0o644)
        code, data = run_script(repo, "report", "--lang", "es")
        self.assertEqual((code, data["error"]["code"]), (2, "not_excluded"), data)
        self.assertFalse((repo.path / ".explain-changes" / "report.md").exists())
        self.assertFalse((repo.path / ".explain-changes" / "state").exists())


if __name__ == "__main__":
    unittest.main()
