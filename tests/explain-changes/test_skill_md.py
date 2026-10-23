"""Contract tests for SKILL.md: frontmatter, subcommands, references and CLI flags."""
from __future__ import annotations

import argparse
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / "skills" / "explain-changes"
SCRIPTS = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS))

SUBCOMMANDS = ("detect", "facts", "bundle", "verify", "report")


def _read() -> str:
    return (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")


def _frontmatter(text: str):
    lines = text.split("\n")
    assert lines[0].strip() == "---", "SKILL.md must start with frontmatter"
    end = lines.index("---", 1)
    meta = {}
    for line in lines[1:end]:
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta, "\n".join(lines[end + 1:])


class SkillMdTests(unittest.TestCase):
    def test_skill_md_contract(self):
        meta, body = _frontmatter(_read())
        self.assertEqual(meta.get("name"), "explain-changes")
        self.assertEqual(meta.get("disable-model-invocation"), "true")
        self.assertIn("explicitly", meta.get("description", ""))
        self.assertIn("scripts/explain_changes.py", body)
        for sub in SUBCOMMANDS:
            self.assertRegex(body, r"explain_changes\.py\" %s\b" % sub)
        refs = set(re.findall(r"references/[\w.-]+\.md", body))
        self.assertTrue(refs)
        for ref in refs:
            self.assertTrue((SKILL_DIR / ref).is_file(), ref)

    def test_every_flag_exists_in_the_parser(self):
        from explain_changes import build_parser
        parser = build_parser()
        known = set()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for sub in action.choices.values():
                    for sub_action in sub._actions:
                        known.update(sub_action.option_strings)
        _, body = _frontmatter(_read())
        body = re.sub(r"`python3? --version`", "", body)  # the interpreter's own flag
        flags = set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", body))
        self.assertTrue(flags)
        self.assertEqual(sorted(flags - known), [])

    def test_reporte_lists_every_english_label_key(self):
        from explain_changes_lib.labels import LABELS
        text = (SKILL_DIR / "references" / "reporte.md").read_text(encoding="utf-8")
        section = text.split("## Label keys", 1)[1]
        keys = re.findall(r"^\| `([a-z_]+)` \|", section, re.M)
        self.assertEqual(sorted(keys), sorted(LABELS["en"].keys()))


if __name__ == "__main__":
    unittest.main()
