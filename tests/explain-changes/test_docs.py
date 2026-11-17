"""Docs contract: README links resolve, docs/ holds only usage docs, block codes are documented."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "explain-changes.md"
BLOCK_CODES = (
    "not_a_git_repo", "rebase_in_progress", "merge_in_progress", "unresolved_conflicts",
    "shallow_no_merge_base", "no_base_branch", "not_excluded", "bad_input",
)


class TestDocs:
    def test_readme_links_to_docs_resolve(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        links = re.findall(r"\]\((docs/[^)#]*)", text)
        assert links, "README must link to docs/"
        for link in links:
            assert (ROOT / link).is_file(), link

    def test_readme_is_bilingual_with_placeholder(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "npx skills add CodeLab614-AI/skills --skill explain-changes" in text
        assert "English" in text
        assert "Español" in text
        en = text.split("### Invocation lock per agent")[1].split("### License")[0]
        es = text.split("### Candado de invocación por agente")[1].split("### Licencia")[0]
        for agent in ("Claude Code", "Codex", "Cursor", "OpenCode", "Antigravity"):
            assert "| " + agent + " |" in en, agent
            assert "| " + agent + " |" in es, agent
        assert "not verified" in en.lower()
        assert "no verificado" in es.lower()
        assert "to be verified" not in text
        assert "por verificar" not in text

    def test_codex_policy_file_and_docs_section(self):
        yaml = (ROOT / "skills/explain-changes/agents/openai.yaml").read_text(encoding="utf-8")
        assert re.search(r"(?m)^policy:\s*\n\s+allow_implicit_invocation: false\s*$", yaml)
        section = DOC.read_text(encoding="utf-8").split("## Invocation lock per agent")[1]
        for agent in ("Claude Code", "Codex", "Cursor", "OpenCode", "Antigravity"):
            assert agent in section, agent

    def test_docs_dir_has_only_usage_markdown(self):
        files = [p for p in (ROOT / "docs").iterdir() if p.is_file()]
        assert sorted(p.name for p in files) == ["explain-changes.md", "teach-me.md"]

    def test_every_block_code_is_documented(self):
        text = DOC.read_text(encoding="utf-8")
        scripts = ROOT / "skills/explain-changes/scripts"
        files = [scripts / "explain_changes.py"] + sorted((scripts / "explain_changes_lib").glob("*.py"))
        source = "".join(p.read_text(encoding="utf-8") for p in files)
        for code in BLOCK_CODES:
            assert '"%s"' % code in source, code
            assert re.search(r"(?m)^#{2,4} .*`%s`" % code, text)
        for extra in ("fetch_failed", "Python"):
            assert extra in text

    def test_final_review_contracts_are_documented(self):
        skill = (ROOT / "skills/explain-changes/SKILL.md").read_text(encoding="utf-8")
        for needle in ("untracked_skipped", "heuristic_skipped", "--from-commit",
                       "untrusted data", "PowerShell"):
            assert needle in skill, needle
        doc = DOC.read_text(encoding="utf-8")
        for needle in ("--from-commit", "inclusive", "file mode", "PowerShell"):
            assert needle in doc, needle
        workflow = (ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")
        assert re.search(r"(?m)^permissions: \{\}$", workflow)
        assert len(re.findall(r"(?m)^    permissions:\n      contents: read$", workflow)) == 2
        assert not re.search(r":\s*write\b", workflow)

    def test_usage_doc_describes_the_two_minute_summary(self):
        doc = DOC.read_text(encoding="utf-8")
        for needle in ("under two minutes", "report.md", "report.html", "state/", "Watch your rules",
                       "The rest", "not grouped", "explained"):
            assert needle in doc, needle
        for old in ("reporte.md", "estado/", "walkthrough", "group by group", "Ungrouped"):
            assert old not in doc, old
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "group by group" not in readme
        assert "grupo por grupo" not in readme
