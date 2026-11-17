"""Tests for detect: repo state, blocks and base branch."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from explain_helpers import run_script


def _clone(tmp_path: Path, src: Path, *extra: str) -> Path:
    dest = tmp_path.resolve() / "clone"
    subprocess.run(["git", "clone", "-q", *extra, src.as_uri(), str(dest)],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(dest), "config", "user.email", "me@x.io"], check=True)
    subprocess.run(["git", "-C", str(dest), "config", "user.name", "Me"], check=True)
    return dest


def _codes(data: dict) -> list:
    return [n["code"] for n in data.get("notices", [])]


class TestDetectRepo:
    def test_not_a_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, data = run_script(Path(tmp), "detect")
        assert code == 2
        assert data["error"]["code"] == "not_a_git_repo"

    def test_base_prefers_origin_head(self, make_repo, tmp_path):
        src = make_repo("main")
        src.write("a.txt", "a\n")
        src.commit("init")
        clone = _clone(tmp_path, src.path)
        subprocess.run(["git", "-C", str(clone), "checkout", "-q", "-b", "feat"], check=True)
        code, data = run_script(clone, "detect")
        assert code == 0, data
        assert data["base"] == "origin/main"
        assert data["base_source"] == "origin/HEAD"
        assert data["fetch"] == "ok"
        assert data["merge_base"]
        assert data["ok"]

    def test_no_fetch_flag_skips_fetch(self, make_repo, tmp_path):
        src = make_repo("main")
        src.write("a.txt", "a\n")
        src.commit("init")
        clone = _clone(tmp_path, src.path)
        code, data = run_script(clone, "detect", "--no-fetch")
        assert code == 0, data
        assert data["fetch"] == "skipped"

    def test_base_fallback_order_without_remote(self, make_repo):
        repo = make_repo("feature")
        repo.write("a.txt", "a\n")
        repo.commit("init")
        repo.checkout("develop", create=True)
        repo.checkout("master", create=True)
        repo.checkout("feature")
        code, data = run_script(repo, "detect")
        assert code == 0, data
        assert data["base"] == "master"
        assert data["base_source"] == "local"
        assert data["fetch"] == "skipped"

        repo.git("branch", "-D", "master")
        code, data = run_script(repo, "detect")
        assert code == 0, data
        assert data["base"] == "develop"

        repo.git("branch", "-D", "develop")
        code, data = run_script(repo, "detect")
        assert code == 2
        assert data["error"]["code"] == "no_base_branch"

    def test_fetch_failure_is_notice(self, make_repo):
        repo = make_repo("main")
        repo.write("a.txt", "a\n")
        repo.commit("init")
        repo.checkout("feat", create=True)
        repo.git("remote", "add", "origin", str(repo.path / "does-not-exist"))
        code, data = run_script(repo, "detect")
        assert code == 0, data
        assert data["ok"]
        assert data["fetch"] == "failed"
        assert "fetch_failed" in _codes(data)
        assert data["base"] == "main"

    def test_detached_head(self, make_repo):
        repo = make_repo("main")
        repo.write("a.txt", "a\n")
        sha = repo.commit("init")
        repo.git("checkout", "-q", "--detach", sha)
        code, data = run_script(repo, "detect")
        assert code == 0, data
        assert data["detached"]
        assert data["branch"] is None
        assert data["head"] == sha

    def test_shallow_without_merge_base(self, make_repo, tmp_path):
        src = make_repo("main")
        src.write("a.txt", "a\n")
        src.commit("init")
        src.write("a.txt", "b\n")
        src.commit("main 2")
        src.checkout("feat", create=True)
        src.git("reset", "-q", "--hard", "HEAD~1")
        src.write("f.txt", "f\n")
        src.commit("feat 1")
        src.write("f.txt", "g\n")
        src.commit("feat 2")
        src.checkout("main")
        clone = _clone(tmp_path, src.path, "--depth", "1", "--no-single-branch")
        subprocess.run(["git", "-C", str(clone), "checkout", "-q", "feat"], check=True)
        code, data = run_script(clone, "detect", "--no-fetch")
        assert code == 2, data
        assert data["error"]["code"] == "shallow_no_merge_base"
        assert "--unshallow" in data["error"]["message"]

    def test_blocks_on_rebase_merge_and_conflicts(self, make_repo):
        repo = make_repo("main")
        repo.write("a.txt", "a\n")
        sha = repo.commit("init")
        git_dir = repo.path / ".git"

        (git_dir / "rebase-merge").mkdir()
        code, data = run_script(repo, "detect")
        assert (code, data["error"]["code"]) == (2, "rebase_in_progress")
        (git_dir / "rebase-merge").rmdir()

        (git_dir / "MERGE_HEAD").write_text(sha + "\n")
        code, data = run_script(repo, "detect")
        assert (code, data["error"]["code"]) == (2, "merge_in_progress")
        (git_dir / "MERGE_HEAD").unlink()

        # Real unmerged index entries via a conflicting merge-less setup.
        repo.checkout("other", create=True)
        repo.write("a.txt", "other\n")
        repo.commit("other")
        repo.checkout("main")
        repo.write("a.txt", "main\n")
        repo.commit("main change")
        proc = subprocess.run(["git", "merge", "-q", "other"], cwd=repo.path,
                              capture_output=True)
        assert proc.returncode != 0
        (git_dir / "MERGE_HEAD").unlink()  # leave only the unmerged entries
        assert repo.git("ls-files", "-u")
        code, data = run_script(repo, "detect")
        assert (code, data["error"]["code"]) == (2, "unresolved_conflicts")

    def test_branch_with_slash(self, make_repo):
        repo = make_repo("main")
        repo.write("a.txt", "a\n")
        repo.commit("init")
        repo.checkout("feature/a/b", create=True)
        code, data = run_script(repo, "detect")
        assert code == 0, data
        assert data["branch"] == "feature/a/b"
        assert not data["detached"]
        assert not data["shallow"]
