"""Contract tests for SKILL.md: frontmatter, subcommands, references and CLI flags."""
from __future__ import annotations

import argparse
import re
import sys
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


class TestSkillMd:
    def test_frontmatter(self):
        meta, _ = _frontmatter(_read())
        assert meta.get("name") == "teach-me"
        assert meta.get("disable-model-invocation") == "true"
        assert "explicitly" in meta.get("description", "")

    def test_every_subcommand_documented(self):
        _, body = _frontmatter(_read())
        subs = _subcommands()
        assert subs
        for sub in subs:
            assert 'teach_me.py" %s' % sub in body, sub

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
        assert flags
        assert sorted(flags - known) == []

    def test_references_exist(self):
        _, body = _frontmatter(_read())
        for name in REFERENCES:
            ref = "references/%s.md" % name
            assert ref in body, ref
            assert (SKILL_DIR / ref).is_file(), ref

    def test_no_coming_soon_and_new_modes_named(self):
        body = _frontmatter(_read())[1]
        assert "coming soon" not in body.lower()
        for name in ("set-mode", "save-overview", "save-built", "search-packages",
                     "fetch-competitor", "fetch-code <id> --full"):
            assert name in body, name

    def test_openai_yaml_disables_implicit(self):
        text = (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")
        assert re.search(r"(?m)^\s*allow_implicit_invocation:\s*false\s*$", text)

