from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest import mock

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

    def test_cli_bad_input_is_json_block(self):
        repo = self.make_repo()
        for args in (["facts"], ["bundle"], ["nope"]):
            code, data = run_script(repo, *args)
            self.assertEqual(code, 2, args)
            self.assertFalse(data["ok"])
            self.assertEqual(data["error"]["code"], "bad_input")

    def test_cli_help_exits_zero(self):
        repo = self.make_repo()
        proc = subprocess.run([sys.executable, str(helpers.SCRIPT), "--help"],
                              cwd=repo.path, capture_output=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn(b"usage", proc.stdout)

    def test_child_env_and_stdin(self):
        repo = self.make_repo()
        seen = {}
        real = subprocess.run

        def spy(*a, **kw):
            seen.update(kw)
            return real(*a, **kw)

        with mock.patch.dict(os.environ, {"GIT_DIR": "/nonexistent/bogus",
                                          "GIT_INDEX_FILE": "/nonexistent/idx",
                                          "GIT_WORK_TREE": "/nonexistent"}):
            with mock.patch.object(subprocess, "run", spy):
                res = gitcmd.run_git(repo.path, ["rev-parse", "--show-toplevel"])
        self.assertEqual(res.code, 0)
        env = seen["env"]
        for key in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
            self.assertNotIn(key, env)
        self.assertEqual(env["GIT_OPTIONAL_LOCKS"], "0")
        self.assertEqual(env["LC_ALL"], "C")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(env["GIT_PAGER"], "cat")
        self.assertIs(seen["stdin"], subprocess.DEVNULL)

    def test_stdin_not_consumed_from_parent(self):
        repo = self.make_repo()
        code = ("import sys; sys.path.insert(0, %r); "
                "from pathlib import Path; from explain_changes_lib import gitcmd; "
                "gitcmd.run_git(Path(%r), ['hash-object', '--stdin']); "
                "sys.stdout.write(sys.stdin.read())"
                % (str(helpers.SCRIPTS), str(repo.path)))
        proc = subprocess.run([sys.executable, "-c", code], input=b"payload",
                              capture_output=True)
        self.assertEqual(proc.stdout, b"payload")


if __name__ == "__main__":
    unittest.main()
