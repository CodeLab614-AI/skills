"""Contract tests for SKILL.md: frontmatter, subcommands, references and CLI flags."""
from __future__ import annotations

import argparse
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / "skills" / "teach-me"
sys.path.insert(0, str(SKILL_DIR / "scripts"))

REFERENCES = ("research", "sources", "lessons", "exams", "consult", "overview", "built")


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


def _subcommands() -> dict:
    from teach_me import build_parser
    for action in build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


class SkillMdTests(unittest.TestCase):
    def test_frontmatter(self):
        meta, _ = _frontmatter(_read())
        self.assertEqual(meta.get("name"), "teach-me")
        self.assertEqual(meta.get("disable-model-invocation"), "true")
        self.assertIn("explicitly", meta.get("description", ""))

    def test_every_subcommand_documented(self):
        _, body = _frontmatter(_read())
        subs = _subcommands()
        self.assertTrue(subs)
        for sub in subs:
            self.assertIn('teach_me.py" %s' % sub, body, sub)

    def test_every_flag_exists_in_the_parser(self):
        known = {"--help"}
        for sub in _subcommands().values():
            for action in sub._actions:
                known.update(action.option_strings)
        texts = [_frontmatter(_read())[1]]
        for name in REFERENCES:
            texts.append((SKILL_DIR / "references" / ("%s.md" % name)).read_text(encoding="utf-8"))
        body = re.sub(r"`python3? --version`", "", "\n".join(texts))
        flags = set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", body))
        self.assertTrue(flags)
        self.assertEqual(sorted(flags - known), [])

    def test_references_exist(self):
        _, body = _frontmatter(_read())
        for name in REFERENCES:
            ref = "references/%s.md" % name
            self.assertIn(ref, body, ref)
            self.assertTrue((SKILL_DIR / ref).is_file(), ref)

    def test_no_coming_soon_and_new_modes_named(self):
        body = _frontmatter(_read())[1]
        self.assertNotIn("coming soon", body.lower())
        for name in ("set-mode", "save-overview", "save-built", "search-packages",
                     "fetch-competitor", "fetch-code <id> --full"):
            self.assertIn(name, body, name)

    def test_openai_yaml_disables_implicit(self):
        text = (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^\s*allow_implicit_invocation:\s*false\s*$")


if __name__ == "__main__":
    unittest.main()
