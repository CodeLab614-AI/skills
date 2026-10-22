"""Tests for rule-file discovery."""
from __future__ import annotations

import os
import unittest

from helpers import RepoTestCase, run_script

from explain_changes_lib import rules


class RulesTests(RepoTestCase):
    def test_order_and_dedup(self):
        repo = self.make_repo()
        for p in [".cursor/rules/b.mdc", ".cursor/rules/a.mdc", ".agents/rules/z.md",
                  ".agents/rules/sub/a.md", "AGENTS.md", "CLAUDE.md", ".cursorrules",
                  ".github/copilot-instructions.md", ".windsurfrules", "CONTRIBUTING.md",
                  "pkg/AGENTS.md"]:
            repo.write(p, "line1\nline2\n")
        found = rules.find_rule_files(repo.path, ["pkg/x.ts", "pkg/y.ts", "AGENTS.md"])
        self.assertEqual([f["path"] for f in found], [
            ".agents/rules/sub/a.md", ".agents/rules/z.md", "AGENTS.md", "CLAUDE.md",
            ".cursor/rules/a.mdc", ".cursor/rules/b.mdc", ".cursorrules",
            ".github/copilot-instructions.md", ".windsurfrules", "CONTRIBUTING.md",
            "pkg/AGENTS.md"])
        self.assertEqual(found[0]["line_count"], 2)
        self.assertIsNone(found[0]["imported_from"])

    def test_claude_md_imports(self):
        repo = self.make_repo()
        repo.write("CLAUDE.md", "Ver @docs/style.md y @~/x.md y @docs/missing.md\n"
                   "```\n@docs/fenced.md\n```\nmail me@docs/email.md\n")
        repo.write("docs/style.md", "a\n")
        repo.write("docs/fenced.md", "b\n")
        repo.write("docs/email.md", "c\n")
        found = rules.find_rule_files(repo.path, [])
        self.assertEqual([(f["path"], f["imported_from"]) for f in found],
                         [("CLAUDE.md", None), ("docs/style.md", "CLAUDE.md")])

    def test_import_cycles_and_depth(self):
        repo = self.make_repo()
        repo.write("CLAUDE.md", "@a.md\n")
        repo.write("a.md", "@b.md @CLAUDE.md\n")
        repo.write("b.md", "@a.md\n")
        found = rules.find_rule_files(repo.path, [])
        self.assertEqual([f["path"] for f in found], ["CLAUDE.md", "a.md", "b.md"])
        repo.write("CLAUDE.md", "@c1.md\n")
        for i in range(1, 9):
            repo.write(f"c{i}.md", f"@c{i + 1}.md\n")
        repo.write("c9.md", "end\n")
        paths = [f["path"] for f in rules.find_rule_files(repo.path, [])]
        self.assertEqual(paths, ["CLAUDE.md", "c1.md", "c2.md", "c3.md", "c4.md", "c5.md"])

    def test_import_outside_repo_via_symlink_ignored(self):
        repo = self.make_repo()
        outside = self.make_repo()
        outside.write("secret.md", "s\n")
        os.symlink(outside.path / "secret.md", repo.path / "link.md")
        repo.write("CLAUDE.md", "@link.md\n")
        repo.write("AGENTS.md", "x\n")
        os.symlink(outside.path / "secret.md", repo.path / ".windsurfrules")
        paths = [f["path"] for f in rules.find_rule_files(repo.path, [])]
        self.assertEqual(paths, ["AGENTS.md", "CLAUDE.md"])
        self.assertEqual(rules.read_rule_text(repo.path, "link.md"), [])

    def test_nested_agents_md(self):
        repo = self.make_repo()
        repo.write("pkg/AGENTS.md", "p\n")
        repo.write("other/AGENTS.md", "o\n")
        found = rules.find_rule_files(repo.path, ["pkg/a/x.ts"])
        self.assertEqual([f["path"] for f in found], ["pkg/AGENTS.md"])

    def test_read_rule_text_decodes_with_replace(self):
        repo = self.make_repo()
        repo.write("AGENTS.md", b"ok\n\xff bad\n")
        lines = rules.read_rule_text(repo.path, "AGENTS.md")
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], "ok")

    def test_detect_reports_rule_files(self):
        repo = self.make_repo()
        repo.write("a.txt", "1\n")
        repo.commit("base")
        repo.checkout("feat", create=True)
        repo.write("AGENTS.md", "rules\n")
        repo.write("pkg/AGENTS.md", "more\n")
        repo.write("pkg/a.txt", "2\n")
        repo.commit("work")
        code, data = run_script(repo, "detect", "--no-fetch")
        self.assertEqual(code, 0, data)
        self.assertEqual([f["path"] for f in data["rule_files"]],
                         ["AGENTS.md", "pkg/AGENTS.md"])
        self.assertEqual(data["summary"]["rule_count"], 2)


if __name__ == "__main__":
    unittest.main()
