from __future__ import annotations

import unittest

import helpers
from helpers import RepoTestCase, run_script
from explain_changes_lib import gitcmd


class GitCmdTest(RepoTestCase):
    def test_run_git_env(self):
        repo = self.make_repo()
        self.assertEqual(gitcmd.git_text(repo.path, ["config", "core.quotepath"]), "off")
        with self.assertRaises(gitcmd.GitError):
            gitcmd.run_git(repo.path, ["definitely-not-a-command"], check=True)
        res = gitcmd.run_git(repo.path, ["definitely-not-a-command"], check=False)
        self.assertNotEqual(res.code, 0)

    def test_cli_not_a_repo_and_skeleton(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            code, data = run_script(d, "detect")
            self.assertEqual(code, 2)
            self.assertEqual(data["error"]["code"], "not_a_git_repo")
        repo = self.make_repo()
        code, data = run_script(repo, "bundle", "--batch", "1")
        self.assertEqual(code, 1)
        self.assertEqual(data["error"]["code"], "not_implemented")


if __name__ == "__main__":
    unittest.main()
