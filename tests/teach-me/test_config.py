from __future__ import annotations

import unittest

import helpers  # noqa: F401
from helpers import TempHome, run_script
from teach_me_lib import config, frontmatter, store
from teach_me_lib.errors import BlockedError


class ConfigTest(unittest.TestCase):
    def test_created_with_defaults(self):
        with TempHome():
            data = config.load()
            path = store.home() / "config.md"
            self.assertTrue(path.exists())
            meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
            self.assertEqual(meta["teach_me"], "config")
            self.assertEqual(set(meta["agents"]), {"claude-code", "codex", "cursor", "opencode", "antigravity"})
            self.assertEqual(data["agents"], meta["agents"])
            self.assertIn("not verified", body)
            self.assertIn("tested", body)

    def test_claude_code_defaults(self):
        with TempHome():
            self.assertEqual(config.for_agent("claude-code"), {
                "agent": "claude-code", "consult": "haiku", "support": "haiku",
                "grading": "sonnet", "grading_effort": "medium", "same_conversation": False})
            self.assertEqual(config.for_agent("Claude-Code")["consult"], "haiku")

    def test_user_edits_preserved(self):
        with TempHome():
            config.load()
            path = store.home() / "config.md"
            meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
            meta["agents"]["claude-code"]["consult"] = "sonnet"
            path.write_text(frontmatter.dump(meta, body), encoding="utf-8")
            self.assertEqual(config.load()["agents"]["claude-code"]["consult"], "sonnet")
            self.assertEqual(config.for_agent("claude-code")["consult"], "sonnet")

    def test_unknown_agent_same_conversation(self):
        with TempHome():
            r = config.for_agent("mystery")
            self.assertTrue(r["same_conversation"])
            self.assertIsNone(r["consult"])
            self.assertIsNone(r["grading_effort"])
            empty = [a for a, row in config.load()["agents"].items() if not row]
            self.assertTrue(empty)
            self.assertTrue(config.for_agent(empty[0])["same_conversation"])

    def test_unparseable_file_blocks_and_is_kept(self):
        with TempHome():
            path = store.home() / "config.md"
            path.write_text("garbage without front matter", encoding="utf-8")
            with self.assertRaises(BlockedError) as cm:
                config.load()
            self.assertEqual(cm.exception.code, "bad_input")
            self.assertIn("config.md", cm.exception.message)
            self.assertEqual(path.read_text(encoding="utf-8"), "garbage without front matter")

    def test_cli(self):
        with TempHome():
            code, out = run_script("config")
            self.assertEqual(code, 0)
            self.assertTrue(out["ok"])
            self.assertTrue(out["path"].endswith("config.md"))
            self.assertIn("claude-code", out["agents"])
            code, out = run_script("config", "--agent", "CLAUDE-code")
            self.assertEqual(out["grading"], "sonnet")
            self.assertFalse(out["same_conversation"])
            self.assertTrue(out["path"].endswith("config.md"))


if __name__ == "__main__":
    unittest.main()
