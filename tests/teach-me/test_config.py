from __future__ import annotations


import teach_helpers  # noqa: F401
from teach_helpers import TempHome, run_script
from teach_me_lib import config, frontmatter, store
from teach_me_lib.errors import BlockedError
import pytest


class TestConfig:
    def test_created_with_defaults(self):
        with TempHome():
            data = config.load()
            path = store.home() / "config.md"
            assert path.exists()
            meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
            assert meta["teach_me"] == "config"
            assert set(meta["agents"]) == {"claude-code", "codex", "cursor", "opencode", "antigravity"}
            assert data["agents"] == meta["agents"]
            assert "not verified" in body
            assert "tested" in body

    def test_claude_code_defaults(self):
        with TempHome():
            assert config.for_agent("claude-code") == {
                "agent": "claude-code", "consult": "haiku", "support": "haiku",
                "grading": "sonnet", "grading_effort": "medium", "same_conversation": False}
            assert config.for_agent("Claude-Code")["consult"] == "haiku"

    def test_user_edits_preserved(self):
        with TempHome():
            config.load()
            path = store.home() / "config.md"
            meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
            meta["agents"]["claude-code"]["consult"] = "sonnet"
            path.write_text(frontmatter.dump(meta, body), encoding="utf-8")
            assert config.load()["agents"]["claude-code"]["consult"] == "sonnet"
            assert config.for_agent("claude-code")["consult"] == "sonnet"

    def test_unknown_agent_same_conversation(self):
        with TempHome():
            r = config.for_agent("mystery")
            assert r["same_conversation"]
            assert r["consult"] is None
            assert r["grading_effort"] is None
            empty = [a for a, row in config.load()["agents"].items() if not row]
            assert empty
            assert config.for_agent(empty[0])["same_conversation"]

    def test_unparseable_file_blocks_and_is_kept(self):
        with TempHome():
            path = store.home() / "config.md"
            path.write_text("garbage without front matter", encoding="utf-8")
            with pytest.raises(BlockedError) as cm:
                config.load()
            assert cm.value.code == "bad_input"
            assert "config.md" in cm.value.message
            assert path.read_text(encoding="utf-8") == "garbage without front matter"

    def test_cli(self):
        with TempHome():
            code, out = run_script("config")
            assert code == 0
            assert out["ok"]
            assert out["path"].endswith("config.md")
            assert "claude-code" in out["agents"]
            code, out = run_script("config", "--agent", "CLAUDE-code")
            assert out["grading"] == "sonnet"
            assert not out["same_conversation"]
            assert out["path"].endswith("config.md")

