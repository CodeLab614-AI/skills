from __future__ import annotations

import subprocess
import unittest

import helpers
from helpers import RepoTestCase
from explain_changes_lib import workspace
from explain_changes_lib.model import BlockedError


class WorkspaceTest(RepoTestCase):
    def test_ensure_excluded_adds_line_once(self):
        repo = self.make_repo()
        workspace.ensure_excluded(repo.path)
        workspace.ensure_excluded(repo.path)
        text = (repo.path / ".git" / "info" / "exclude").read_text()
        self.assertEqual(text.splitlines().count("/.explain-changes/"), 1)
        res = subprocess.run(["git", "check-ignore", ".explain-changes/a"],
                             cwd=repo.path, capture_output=True)
        self.assertEqual(res.returncode, 0)

    def test_safe_write_rejects_escape(self):
        repo = self.make_repo()
        for bad in ("../x", "/tmp/x"):
            with self.assertRaises(ValueError):
                workspace.safe_write(repo.path, bad, "")
        self.assertFalse((repo.path.parent / "x").exists())

    def test_safe_write_rejects_symlink_escape(self):
        repo = self.make_repo()
        workspace.safe_write(repo.path, "a.txt", "1")
        outside = repo.path.parent / "outside-dir"
        outside.mkdir(exist_ok=True)
        self.addCleanup(outside.rmdir)
        (repo.path / ".explain-changes" / "link").symlink_to(outside)
        with self.assertRaises(ValueError):
            workspace.safe_write(repo.path, "link/f.txt", "x")
        self.assertEqual(list(outside.iterdir()), [])

    def test_safe_write_blocks_when_not_excluded(self):
        repo = self.make_repo()
        # a negation rule makes the directory un-ignorable
        (repo.path / ".gitignore").write_text("!/.explain-changes/\n!/.explain-changes/**\n")
        # info/exclude has lower precedence than .gitignore, so this must block
        with self.assertRaises(BlockedError) as ctx:
            workspace.ensure_excluded(repo.path)
        self.assertEqual(ctx.exception.code, "not_excluded")

    def test_cleanup_only_deletes_manifest_files(self):
        repo = self.make_repo()
        workspace.safe_write(repo.path, "report.md", "r")
        workspace.safe_write(repo.path, "state/a.json", "{}")
        workspace.safe_write(repo.path, "run/facts.json", "{}")
        mine = repo.path / ".explain-changes" / "mio.txt"
        mine.write_text("keep")
        removed = workspace.cleanup_previous(repo.path)
        self.assertIn("report.md", removed)
        self.assertIn("run/facts.json", removed)
        self.assertTrue(mine.exists())
        self.assertTrue((repo.path / ".explain-changes" / "state" / "a.json").exists())
        self.assertFalse((repo.path / ".explain-changes" / "report.md").exists())


if __name__ == "__main__":
    unittest.main()
