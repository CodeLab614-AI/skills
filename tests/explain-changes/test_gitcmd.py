from __future__ import annotations

import subprocess
import sys

import pytest

import explain_helpers
from explain_helpers import run_script
from explain_changes_lib import gitcmd


class TestGitCmd:
    def test_run_git_env(self, make_repo):
        repo = make_repo()
        assert gitcmd.git_text(repo.path, ["config", "core.quotepath"]) == "off"
        with pytest.raises(gitcmd.GitError):
            gitcmd.run_git(repo.path, ["definitely-not-a-command"], check=True)
        res = gitcmd.run_git(repo.path, ["definitely-not-a-command"], check=False)
        assert res.code != 0

    def test_cli_not_a_repo_and_skeleton(self, make_repo):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            code, data = run_script(d, "detect")
            assert code == 2
            assert data["error"]["code"] == "not_a_git_repo"
        repo = make_repo()
        code, data = run_script(repo, "nope")
        assert code == 2
        assert data["error"]["code"] == "bad_input"

    def test_cli_bad_input_is_json_block(self, make_repo):
        repo = make_repo()
        for args in (["facts"], ["bundle"], ["nope"]):
            code, data = run_script(repo, *args)
            assert code == 2, args
            assert not data["ok"]
            assert data["error"]["code"] == "bad_input"

    def test_cli_help_exits_zero(self, make_repo):
        repo = make_repo()
        proc = subprocess.run([sys.executable, str(explain_helpers.SCRIPT), "--help"],
                              cwd=repo.path, capture_output=True)
        assert proc.returncode == 0
        assert b"usage" in proc.stdout

    def test_child_env_and_stdin(self, make_repo, monkeypatch):
        repo = make_repo()
        seen = {}
        real = subprocess.run

        def spy(*a, **kw):
            seen.update(kw)
            return real(*a, **kw)

        with monkeypatch.context() as mp:
            mp.setenv("GIT_DIR", "/nonexistent/bogus")
            mp.setenv("GIT_INDEX_FILE", "/nonexistent/idx")
            mp.setenv("GIT_WORK_TREE", "/nonexistent")
            mp.setattr(subprocess, "run", spy)
            res = gitcmd.run_git(repo.path, ["rev-parse", "--show-toplevel"])
        assert res.code == 0
        env = seen["env"]
        for key in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
            assert key not in env
        assert env["GIT_OPTIONAL_LOCKS"] == "0"
        assert env["LC_ALL"] == "C"
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert env["GIT_PAGER"] == "cat"
        assert seen["stdin"] is subprocess.DEVNULL

    def test_stdin_not_consumed_from_parent(self, make_repo):
        repo = make_repo()
        code = ("import sys; sys.path.insert(0, %r); "
                "from pathlib import Path; from explain_changes_lib import gitcmd; "
                "gitcmd.run_git(Path(%r), ['hash-object', '--stdin']); "
                "sys.stdout.write(sys.stdin.read())"
                % (str(explain_helpers.SCRIPTS), str(repo.path)))
        proc = subprocess.run([sys.executable, "-c", code], input=b"payload",
                              capture_output=True)
        assert proc.stdout == b"payload"
