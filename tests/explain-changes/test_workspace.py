from __future__ import annotations

import subprocess

import pytest

import explain_helpers
from explain_changes_lib import workspace
from explain_changes_lib.model import BlockedError


class TestWorkspace:
    def test_ensure_excluded_adds_line_once(self, make_repo):
        repo = make_repo()
        workspace.ensure_excluded(repo.path)
        workspace.ensure_excluded(repo.path)
        text = (repo.path / ".git" / "info" / "exclude").read_text()
        assert text.splitlines().count("/.explain-changes/") == 1
        res = subprocess.run(["git", "check-ignore", ".explain-changes/a"],
                             cwd=repo.path, capture_output=True)
        assert res.returncode == 0

    def test_safe_write_rejects_escape(self, make_repo):
        repo = make_repo()
        for bad in ("../x", "/tmp/x"):
            with pytest.raises(ValueError):
                workspace.safe_write(repo.path, bad, "")
        assert not (repo.path.parent / "x").exists()

    def test_safe_write_rejects_symlink_escape(self, make_repo, tmp_path):
        repo = make_repo()
        workspace.safe_write(repo.path, "a.txt", "1")
        outside = tmp_path / "outside-dir"
        outside.mkdir()
        (repo.path / ".explain-changes" / "link").symlink_to(outside)
        with pytest.raises(ValueError):
            workspace.safe_write(repo.path, "link/f.txt", "x")
        assert list(outside.iterdir()) == []

    def test_safe_write_blocks_when_not_excluded(self, make_repo):
        repo = make_repo()
        # a negation rule makes the directory un-ignorable
        (repo.path / ".gitignore").write_text("!/.explain-changes/\n!/.explain-changes/**\n")
        # info/exclude has lower precedence than .gitignore, so this must block
        with pytest.raises(BlockedError) as ctx:
            workspace.ensure_excluded(repo.path)
        assert ctx.value.code == "not_excluded"

    def test_cleanup_only_deletes_manifest_files(self, make_repo):
        repo = make_repo()
        workspace.safe_write(repo.path, "report.md", "r")
        workspace.safe_write(repo.path, "state/a.json", "{}")
        workspace.safe_write(repo.path, "run/facts.json", "{}")
        mine = repo.path / ".explain-changes" / "mio.txt"
        mine.write_text("keep")
        removed = workspace.cleanup_previous(repo.path)
        assert "report.md" in removed
        assert "run/facts.json" in removed
        assert mine.exists()
        assert (repo.path / ".explain-changes" / "state" / "a.json").exists()
        assert not (repo.path / ".explain-changes" / "report.md").exists()
