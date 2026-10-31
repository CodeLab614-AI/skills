"""Robustness: UTF-8 I/O, FIFOs, huge argv, untracked notices and large diffs."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from explain_helpers import SCRIPT, run_script

FACTS = ".explain-changes/run/facts.json"
ASCII_ENV = {"PYTHONIOENCODING": "ascii", "LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0"}


def _raw(repo, *args, stdin=None, env=None):
    full = dict(os.environ)
    full.update(env or {})
    proc = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=repo.path, env=full,
                          input=stdin, stdin=None if stdin is not None else subprocess.DEVNULL,
                          capture_output=True)
    return proc


class TestUtf8Io:
    @pytest.fixture(autouse=True)
    def _repo_factory(self, make_repo):
        self._make_repo = make_repo

    def _repo(self):
        repo = self._make_repo("main")
        repo.write("a.txt", "a\n")
        repo.commit("init")
        repo.checkout("feature", create=True)
        repo.write("café/日本.txt", "x\n")
        repo.commit("add \U0001F680 rocket")
        return repo

    def test_cli_outputs_utf8_under_an_ascii_locale(self):
        repo = self._repo()
        proc = _raw(repo, "detect", "--no-fetch", env=ASCII_ENV)
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout.decode("utf-8"))
        assert "\U0001F680" in proc.stdout.decode("utf-8")
        assert data["ok"]
        proc = _raw(repo, "facts", "--from", "main", env=ASCII_ENV)
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout.decode("utf-8"))["ok"]
        assert _raw(repo, "verify", stdin=b'{"points": []}').returncode == 0
        proc = _raw(repo, "report", "--lang", "es", env=ASCII_ENV)
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout.decode("utf-8"))["ok"]

    def test_non_ascii_paths_reach_the_disk_under_an_ascii_locale(self, make_repo):
        repo = make_repo("main")
        repo.write("a.txt", "a\n")
        repo.commit("init")
        repo.checkout("feature", create=True)
        repo.write("café/AGENTS.md", "rule @réglas.md\n")
        repo.write("café/réglas.md", "more\n")
        repo.write("café/日本.txt", "x\n")
        repo.commit("add non-ascii files")
        repo.write("café/nuevo.txt", "untracked\n")
        proc = _raw(repo, "facts", "--from", "main", "--include-uncommitted", env=ASCII_ENV)
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout.decode("utf-8"))
        assert data["ok"], data
        facts = json.loads((repo.path / FACTS).read_text(encoding="utf-8"))
        assert "café/AGENTS.md" in json.dumps(facts, ensure_ascii=False)
        assert "café/réglas.md" in json.dumps(facts, ensure_ascii=False)
        assert "café/nuevo.txt" in json.dumps(facts, ensure_ascii=False)

    def test_non_utf8_stdin_is_bad_input(self):
        repo = self._repo()
        assert _raw(repo, "facts", "--from", "main").returncode == 0
        for args in (("verify",), ("report", "--lang", "es", "--labels-stdin"),
                     ("facts", "--from", "main", "--targets-stdin")):
            proc = _raw(repo, *args, stdin=b'{"groups": "\xff\xfe"}', env=ASCII_ENV)
            assert proc.returncode == 2, (args, proc.stdout, proc.stderr)
            out = json.loads(proc.stdout.decode("utf-8"))
            assert out["error"]["code"] == "bad_input", args

    def test_utf8_stdin_is_read_under_an_ascii_locale(self):
        repo = self._repo()
        assert _raw(repo, "facts", "--from", "main").returncode == 0
        assert _raw(repo, "verify", stdin=b'{"points": []}').returncode == 0
        labels = json.dumps({"summary": "Résumé \U0001F680"}, ensure_ascii=False)
        proc = _raw(repo, "report", "--lang", "es", "--labels-stdin",
                    stdin=labels.encode("utf-8"), env=ASCII_ENV)
        assert proc.returncode == 0, proc.stderr


class TestUntrackedSkip:
    @pytest.fixture(autouse=True)
    def _repo_factory(self, make_repo):
        self._make_repo = make_repo

    def _repo(self):
        repo = self._make_repo("main")
        repo.write("a.txt", "a\n")
        repo.commit("init")
        return repo

    def _facts(self, repo):
        code, data = run_script(repo, "facts", "--from", "HEAD", "--include-uncommitted")
        assert code == 0, data
        return data

    def test_fifo_is_skipped_with_a_notice(self, monkeypatch):
        from explain_changes_lib import diffparse
        repo = self._repo()
        os.mkfifo(str(repo.path / "pipe"))
        repo.write("real.txt", "r\n")
        listing = SimpleNamespace(out=b"pipe\0real.txt\0")
        notices = []
        monkeypatch.setattr(diffparse, "run_git", lambda *a, **k: listing)
        files = diffparse.untracked_files(repo.path, notices)  # must not block
        assert [f.path for f in files] == ["real.txt"]
        assert notices == [{"code": "untracked_skipped",
                                    "params": {"path": "pipe", "reason": "not_regular_file"}}]

    def test_nested_repo_and_unreadable_file_get_notices(self, request):
        repo = self._repo()
        nested = repo.path / "inner"
        nested.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=nested, check=True)
        (nested / "x.txt").write_text("x\n")
        secret = repo.write("secret.txt", "s\n")
        secret.chmod(0)
        request.addfinalizer(lambda: secret.chmod(0o644))
        data = self._facts(repo)
        paths = sorted(n["params"]["path"] for n in data["notices"]
                       if n["code"] == "untracked_skipped")
        expect = ["inner/"] + ([] if os.geteuid() == 0 else ["secret.txt"])
        assert paths == expect


class TestHugeArgv:
    def test_tree_heuristic_degrades_when_argv_is_too_long(self, make_repo, monkeypatch):
        from explain_changes_lib import detect
        repo = make_repo("main")
        repo.write("a.txt", "a\n")
        repo.commit("init")
        repo.checkout("feature", create=True)
        repo.write("f.txt", "f\n")
        repo.commit("f1")
        real = detect.run_git

        def fake(r, args, **kw):
            if "--" in args and args[:2] == ["diff", "--quiet"]:
                raise OSError(7, "Argument list too long")
            return real(r, args, **kw)

        notices = []
        monkeypatch.setattr(detect, "run_git", fake)
        merged = detect.find_merged(repo.path, repo.git("merge-base", "HEAD", "main"),
                                    "main", notices)
        assert merged is None
        assert notices == [{"code": "heuristic_skipped", "params": {"heuristic": "tree"}}]


@pytest.mark.skipif(bool(os.environ.get("CI_SLOW")), reason="CI_SLOW is set")
class TestLargeDiffPerformance:
    def test_1000_renamed_files_with_edits_finish_quickly(self, make_repo):
        repo = make_repo("main")
        body = "".join("line %d of the file\n" % i for i in range(12))
        for i in range(1000):
            repo.write("src/old/f%04d.txt" % i, "id %d\n%s" % (i, body))
        repo.commit("init")
        repo.checkout("feature", create=True)
        for i in range(1000):
            (repo.path / "src" / "old" / ("f%04d.txt" % i)).unlink()
            repo.write("src/new/g%04d.txt" % i,
                       "id %d\n%s" % (i, body.replace("line 5 ", "LINE 5 ")))
        repo.commit("rename and edit")
        start = time.monotonic()
        code, data = run_script(repo, "facts", "--from", "main")
        elapsed = time.monotonic() - start
        assert code == 0, data
        assert data["totals"]["files"] == 1000
        assert elapsed < 20, "facts took %.1fs" % elapsed
        print("\nperf: 1000 renamed files -> facts in %.1fs" % elapsed, file=sys.stderr)


class TestBlobHeads:
    def test_heads_are_bounded_and_missing_objects_skipped(self, make_repo):
        from explain_changes_lib import gitcmd
        repo = make_repo("main")
        repo.write("big.txt", "# @generated\n" + "x" * 50000)
        repo.write("small.txt", "hi\n")
        repo.commit("init")
        big = repo.git("rev-parse", "HEAD:big.txt")
        small = repo.git("rev-parse", "HEAD:small.txt")
        heads = gitcmd.blob_heads(repo.path, [big, "0" * 40, small], 8192)
        assert sorted(heads) == sorted([big, small])
        assert len(heads[big]) == 8192
        assert heads[big].startswith(b"# @generated\n")
        assert heads[small] == b"hi\n"
        assert gitcmd.blob_heads(repo.path, [], 8192) == {}


class TestPatchSplitFallback:
    def test_type_change_falls_back_to_per_file_diffs(self, make_repo):
        repo = make_repo("main")
        repo.write("a.txt", "a\nb\n")
        repo.write("t.txt", "t\n")
        repo.commit("init")
        repo.checkout("feature", create=True)
        repo.write("a.txt", "a\nB\n")
        (repo.path / "t.txt").unlink()
        os.symlink("a.txt", str(repo.path / "t.txt"))
        repo.commit("typechange")
        code, data = run_script(repo, "facts", "--from", "main")
        assert code == 0, data
        facts = json.loads((repo.path / FACTS).read_text(encoding="utf-8"))
        a = next(f for f in facts["files"] if f["path"] == "a.txt")
        assert a["status"] == "modified"
        assert len([h for h in facts["hunks"] if h["file"] == "a.txt"]) == 1

