"""Docs contract: README links resolve, docs/ holds only usage docs, block codes are documented."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "explain-changes.md"
BLOCK_CODES = (
    "not_a_git_repo", "rebase_in_progress", "merge_in_progress", "unresolved_conflicts",
    "shallow_no_merge_base", "no_base_branch", "not_excluded", "bad_input",
)


class DocsTest(unittest.TestCase):
    def test_readme_links_to_docs_resolve(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        links = re.findall(r"\]\((docs/[^)#]*)", text)
        self.assertTrue(links, "README must link to docs/")
        for link in links:
            self.assertTrue((ROOT / link).is_file(), link)

    def test_readme_is_bilingual_with_placeholder(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("npx skills add CodeLab614-AI/skills --skill explain-changes", text)
        self.assertIn("English", text)
        self.assertIn("Español", text)
        en = text.split("### Invocation lock per agent")[1].split("### License")[0]
        es = text.split("### Candado de invocación por agente")[1].split("### Licencia")[0]
        for agent in ("Claude Code", "Codex", "Cursor", "OpenCode", "Antigravity"):
            self.assertIn("| " + agent + " |", en, agent)
            self.assertIn("| " + agent + " |", es, agent)
        self.assertIn("not verified", en.lower())
        self.assertIn("no verificado", es.lower())
        self.assertNotIn("to be verified", text)
        self.assertNotIn("por verificar", text)

    def test_codex_policy_file_and_docs_section(self):
        yaml = (ROOT / "skills/explain-changes/agents/openai.yaml").read_text(encoding="utf-8")
        self.assertRegex(yaml, r"(?m)^policy:\s*\n\s+allow_implicit_invocation: false\s*$")
        section = DOC.read_text(encoding="utf-8").split("## Invocation lock per agent")[1]
        for agent in ("Claude Code", "Codex", "Cursor", "OpenCode", "Antigravity"):
            self.assertIn(agent, section, agent)

    def test_docs_dir_has_only_usage_markdown(self):
        files = [p for p in (ROOT / "docs").rglob("*") if p.is_file()]
        self.assertEqual([p.name for p in files], ["explain-changes.md"])

    def test_every_block_code_is_documented(self):
        text = DOC.read_text(encoding="utf-8")
        scripts = ROOT / "skills/explain-changes/scripts"
        files = [scripts / "explain_changes.py"] + sorted((scripts / "explain_changes_lib").glob("*.py"))
        source = "".join(p.read_text(encoding="utf-8") for p in files)
        for code in BLOCK_CODES:
            self.assertIn('"%s"' % code, source, code)
            self.assertRegex(text, r"(?m)^#{2,4} .*`%s`" % code)
        for extra in ("fetch_failed", "Python"):
            self.assertIn(extra, text)


if __name__ == "__main__":
    unittest.main()
