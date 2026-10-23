from __future__ import annotations

import json
import os
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
             "rules": []},
            {"path": "pnpm-lock.yaml", "old_path": None, "status": "modified",
             "class": "mechanical", "mechanical_kind": "lockfile", "additions": 5,
             "deletions": 5, "hunks": [], "rules": []},
        ],
        "hunks": [{"id": "h-1", "file": "src/a.ts", "new_start": 3, "new_lines": 2,
                   "old_start": 3, "old_lines": 1, "class": "logic", "rules": ["AGENTS.md:2"],
                   "added": ["x", "y"], "removed": ["z"], "changed_since_review": True,
                   "seen": False, "mechanical_kind": None}],
        "excluded": {"merges": ["b" * 40], "authors": ["bot@x.io"], "dropped_hunks": 0},
        "rule_files": [], "replacements": [{"old": "foo", "new": "bar", "hunk_ids": [],
                                           "files": ["a.ts", "b.ts", "c.ts"],
                                           "exceptions": [{"file": "d.ts", "hunk_ids": ["h-9"]}]}],
        "batches": [], "targets": [], "notices": [],
        "commits": [{"sha": "c" * 40, "subject": "Arregla el login", "email": "me@x.io"}],
        "commits_truncated": True,
        "totals": {"files": 2, "additions": 7, "deletions": 6,
                   "logic_lines": 3, "mechanical_lines": 10},
    }
    verified = {
        "interpreted_in": "same_conversation",
        "groups": [{"id": "g1", "name": "Nombre del grupo", "what": "Hace algo.", "order": 1,
                    "locations": [{"file": "src/a.ts", "start": 3, "end": 4, "side": "new",
                                   "verified": False}], "hunk_ids": ["h-1"]}],
        "rules": [{"rule": {"file": "AGENTS.md", "line": 2, "verified": True},
                   "status": "complies", "changes": [
                       {"file": "src/a.ts", "line": 3, "side": "new", "verified": True}],
                   "note": "ok", "verified": True}],
        "unverified": [{"kind": "location", "group": "g1",
                        "citation": {"file": "nope.ts", "start": 1, "end": 2}}],
    }
    return facts, verified


class RenderTests(unittest.TestCase):
    def test_render_sections_order_es(self):
        facts, verified = small()
        labels = report.LABELS["es"]
        text = report.render(facts, verified, labels)
        order = [labels[k] for k in ("h_summary", "h_rules", "h_groups", "h_mechanical",
                                     "h_unverified", "h_provenance")]
        pos = [text.index("## " + h) for h in order]
        self.assertEqual(pos, sorted(pos))
        self.assertIn("⚠", text)
        self.assertIn("nope.ts", text)
        self.assertIn(labels["changed_since_review"], text)
        self.assertIn(labels["same_conversation"], text)
        self.assertIn("foo", text)
        self.assertIn("d.ts", text)
        self.assertIn("+2", text)
        self.assertIn("bot@x.io", text)

    def test_user_text_cannot_break_structure(self):
        facts, verified = small()
        facts["files"][0]["path"] = "src/we`ird\n## Injected.ts"
        facts["hunks"][0]["file"] = facts["files"][0]["path"]
        facts["replacements"][0]["old"] = "a``b\n# H"
        verified["groups"][0]["name"] = "# Fake\n## Heading"
        verified["groups"][0]["what"] = "line1\n## Sneaky"
        verified["rules"][0]["note"] = "x\r\n## Note"
        verified["unverified"][0]["citation"]["file"] = "bad\n## Cite`.ts"
        text = report.render(facts, verified, report.LABELS["en"])
        heads = [l for l in text.split("\n") if l.startswith("#")]
        self.assertEqual(heads, [
            "# Change report", "## Summary", "## Rules", "### Complies", "## Logic changes",
            "### # Fake ## Heading", "## Mechanical changes", "### Lockfiles",
            "### Repeated replacements", "## Unverified citations", "## Provenance"])
        self.assertIn("``we`ird ## Injected.ts``", text.replace("`src/", "``"))
        self.assertIn("```a``b # H```", text)

    def test_provenance_lists_commits(self):
        facts, verified = small()
        text = report.render(facts, verified, report.LABELS["en"])
        self.assertIn("`cccccccccc` Arregla el login", text)
        self.assertIn(report.LABELS["en"]["commits_truncated"], text)
        facts["commits_truncated"] = False
        text = report.render(facts, verified, report.LABELS["en"])
        self.assertNotIn(report.LABELS["en"]["commits_truncated"], text)

    def test_no_rules_section_says_so(self):
        facts, verified = small()
        verified["rules"] = []
        text = report.render(facts, verified, report.LABELS["en"])
        self.assertIn(report.LABELS["en"]["no_rules"], text)
        self.assertNotIn(report.LABELS["en"]["same_conversation"] + "x", text)

    def test_not_same_conversation_omits_label(self):
        facts, verified = small()
        verified["interpreted_in"] = "subagent"
        text = report.render(facts, verified, report.LABELS["es"])
        self.assertNotIn(report.LABELS["es"]["same_conversation"], text)

    def test_ungrouped_group_renders(self):
        facts, verified = small()
        verified["groups"].append({"id": "ungrouped", "name": None, "what": "", "order": 999,
                                   "locations": [], "hunk_ids": [], "files": ["src/a.ts"]})
        text = report.render(facts, verified, report.LABELS["es"])
        self.assertIn(report.LABELS["es"]["ungrouped"], text)

    def test_label_keys_match(self):
        self.assertEqual(set(report.LABELS["en"]), set(report.LABELS["es"]))

    def test_label_keys_are_all_used_and_documented(self):
        import re
        from helpers import ROOT
        base = ROOT / "skills" / "explain-changes"
        source = (base / "scripts" / "explain_changes_lib" / "report.py").read_text(
            encoding="utf-8")
        used = set(re.findall(r'labels\["(\w+)"\]', source))
        used |= {"complies", "seems_not", "not_applicable"}  # labels[status]
        used |= {k for k in report.LABELS["en"] if k.startswith("kind_")}  # "kind_" + kind
        self.assertEqual(set(report.LABELS["en"]), used)
        doc = (base / "references" / "reporte.md").read_text(encoding="utf-8")
        documented = set(re.findall(r"^\| `(\w+)` \|", doc, re.M))
        self.assertEqual(documented, used)


class WriteReportTests(RepoTestCase):
    def pipeline(self, repo, interp=None):
        code, data = run_script(repo, "facts", "--from", "main")
        self.assertEqual(code, 0, data)
        code, data = run_script(repo, "verify",
                                stdin=json.dumps(interp or {"groups": []}))
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
        code, data = self.pipeline(repo)
        self.assertEqual(code, 0, data)
        self.assertTrue(data["ok"])
        repo.write("second.txt", "s\n")
        repo.commit("again")
        first = (repo.path / ".explain-changes" / "reporte.md").read_text(encoding="utf-8")
        self.assertNotIn("second.txt", first)
        code, data = self.pipeline(repo)
        self.assertEqual(code, 0, data)
        work = repo.path / ".explain-changes"
        reports = [p for p in work.rglob("reporte*")]
        self.assertEqual([p.name for p in reports], ["reporte.md"])
        text = reports[0].read_text(encoding="utf-8")
        self.assertIn("second.txt", text)
        self.assertEqual(data["path"], ".explain-changes/reporte.md")
        self.assertTrue(data["state_path"].startswith(".explain-changes/estado/"))

    def test_real_pipeline_rules_and_unverified(self):
        repo = self.make_repo()
        repo.write("AGENTS.md", "# rules\nbe kind\nbe brief\nbe clear\nbe fast\n")
        repo.write("a.txt", "base\n")
        repo.commit("base")
        repo.checkout("feat", create=True)
        repo.write("a.txt", "base\nnew\n")
        repo.commit("change")
        rule = lambda n, st: {"rule": {"file": "AGENTS.md", "line": n}, "status": st,
                              "changes": [{"file": "a.txt", "line": 2}], "note": "n%d" % n}
        interp = {"groups": [{"id": "g", "name": "G", "what": "w", "order": 1,
                              "locations": [{"file": "a.txt", "start": 2, "end": 2},
                                            {"file": "ghost.txt", "start": 1, "end": 1}]}],
                  "rules": [rule(2, "complies"), rule(3, "seems_not"),
                            rule(4, "not_applicable"), rule(99, "complies")]}
        code, data = self.pipeline(repo, interp)
        self.assertEqual(code, 0, data)
        text = (repo.path / ".explain-changes" / "reporte.md").read_text(encoding="utf-8")
        self.assertIn("- 3 reglas tocadas", text)
        self.assertIn("### Cumple", text)
        self.assertIn("### Parece no cumplir", text)
        self.assertIn("### No aplica", text)
        self.assertIn("## Citas no verificadas", text)
        self.assertIn("ghost.txt", text)
        self.assertIn("AGENTS.md:99", text)
        self.assertIn("⚠", text)

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
        junk = repo.path / ".explain-changes" / "estado" / "junk.json"
        junk.write_text("not json")
        code, data = self.pipeline(repo)
        self.assertEqual(code, 0, data)
        self.assertIsNone(load_state(repo.path, "gone"))
        self.assertIsNone(load_state(repo.path, "merged"))
        self.assertIsNotNone(load_state(repo.path, "feat"))
        self.assertTrue(junk.exists())
        files = sorted(p.name for p in (repo.path / ".explain-changes" / "estado").iterdir())
        self.assertEqual(len(files), 2, files)
        manifest = json.loads((repo.path / ".explain-changes" / ".manifest.json").read_text())
        self.assertEqual(len([f for f in manifest["files"] if f.startswith("estado/")]), 1)

    def test_only_new_keeps_previous_hunks_in_state(self):
        repo = self.feature("first\n")
        self.assertEqual(self.pipeline(repo)[0], 0)
        repo.write("b.txt", "b\n")
        repo.commit("more")
        code, data = run_script(repo, "facts", "--from", "main", "--only-new")
        self.assertEqual(code, 0, data)
        run_script(repo, "verify", stdin='{"groups": []}')
        self.assertEqual(run_script(repo, "report", "--lang", "en")[0], 0)
        state = load_state(repo.path, "feat")
        self.assertEqual(len(state["hunks"]), 2)

    def test_detached_head_has_no_state(self):
        repo = self.feature()
        repo.git("checkout", "-q", "--detach")
        code, data = self.pipeline(repo)
        self.assertEqual(code, 0, data)
        self.assertIsNone(data["state_path"])
        self.assertTrue((repo.path / ".explain-changes" / "reporte.md").exists())

    def test_labels_override_and_bad_input(self):
        repo = self.feature()
        run_script(repo, "facts", "--from", "main")
        run_script(repo, "verify", stdin='{"groups": []}')
        code, data = run_script(repo, "report", "--lang", "fr", "--labels-stdin",
                                stdin=json.dumps({"h_summary": "Résumé"}))
        self.assertEqual(code, 0, data)
        text = (repo.path / ".explain-changes" / "reporte.md").read_text(encoding="utf-8")
        self.assertIn("## Résumé", text)
        code, data = run_script(repo, "report", "--lang", "es", "--labels-stdin",
                                stdin="{nope")
        self.assertEqual((code, data["error"]["code"]), (2, "bad_input"))
        code, data = run_script(repo, "report", "--lang", "es", "--labels-stdin",
                                stdin="[1]")
        self.assertEqual((code, data["error"]["code"]), (2, "bad_input"))

    def test_report_without_flag_ignores_stdin(self):
        repo = self.feature()
        run_script(repo, "facts", "--from", "main")
        run_script(repo, "verify", stdin='{"groups": []}')
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
        self.assertFalse((repo.path / ".explain-changes" / "reporte.md").exists())
        self.assertFalse((repo.path / ".explain-changes" / "estado").exists())


if __name__ == "__main__":
    unittest.main()
