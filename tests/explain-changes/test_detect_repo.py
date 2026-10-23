"""Tests for detect: repo state, blocks and base branch."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import RepoTestCase, run_script


def _clone(test: unittest.TestCase, src: Path, *extra: str) -> Path:
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    dest = Path(tmp.name).resolve() / "clone"
    subprocess.run(["git", "clone", "-q", *extra, src.as_uri(), str(dest)],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(dest), "config", "user.email", "me@x.io"], check=True)
    subprocess.run(["git", "-C", str(dest), "config", "user.name", "Me"], check=True)
    return dest


def _codes(data: dict) -> list:
    return [n["code"] for n in data.get("notices", [])]


class DetectRepoTests(RepoTestCase):
    def test_not_a_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, data = run_script(Path(tmp), "detect")
        self.assertEqual(code, 2)
        self.assertEqual(data["error"]["code"], "not_a_git_repo")

    def test_base_prefers_origin_head(self):
        src = self.make_repo("main")
        src.write("a.txt", "a\n")
        src.commit("init")
        clone = _clone(self, src.path)
        subprocess.run(["git", "-C", str(clone), "checkout", "-q", "-b", "feat"], check=True)
        code, data = run_script(clone, "detect")
        self.assertEqual(code, 0, data)
        self.assertEqual(data["base"], "origin/main")
        self.assertEqual(data["base_source"], "origin/HEAD")
        self.assertEqual(data["fetch"], "ok")
        self.assertTrue(data["merge_base"])
        self.assertTrue(data["ok"])

    def test_no_fetch_flag_skips_fetch(self):
        src = self.make_repo("main")
        src.write("a.txt", "a\n")
        src.commit("init")
        clone = _clone(self, src.path)
        code, data = run_script(clone, "detect", "--no-fetch")
        self.assertEqual(code, 0, data)
        self.assertEqual(data["fetch"], "skipped")

    def test_base_fallback_order_without_remote(self):
        repo = self.make_repo("feature")
        repo.write("a.txt", "a\n")
        repo.commit("init")
        repo.checkout("develop", create=True)
        repo.checkout("master", create=True)
        repo.checkout("feature")
        code, data = run_script(repo, "detect")
        self.assertEqual(code, 0, data)
        self.assertEqual(data["base"], "master")
        self.assertEqual(data["base_source"], "local")
        self.assertEqual(data["fetch"], "skipped")

        repo.git("branch", "-D", "master")
        code, data = run_script(repo, "detect")
        self.assertEqual(code, 0, data)
        self.assertEqual(data["base"], "develop")

        repo.git("branch", "-D", "develop")
        code, data = run_script(repo, "detect")
        self.assertEqual(code, 2)
        self.assertEqual(data["error"]["code"], "no_base_branch")

    def test_fetch_failure_is_notice(self):
        repo = self.make_repo("main")
        repo.write("a.txt", "a\n")
        repo.commit("init")
        repo.checkout("feat", create=True)
        repo.git("remote", "add", "origin", str(repo.path / "does-not-exist"))
        code, data = run_script(repo, "detect")
        self.assertEqual(code, 0, data)
        self.assertTrue(data["ok"])
        self.assertEqual(data["fetch"], "failed")
        self.assertIn("fetch_failed", _codes(data))
        self.assertEqual(data["base"], "main")

    def test_detached_head(self):
        repo = self.make_repo("main")
        repo.write("a.txt", "a\n")
        sha = repo.commit("init")
        repo.git("checkout", "-q", "--detach", sha)
        code, data = run_script(repo, "detect")
        self.assertEqual(code, 0, data)
        self.assertTrue(data["detached"])
        self.assertIsNone(data["branch"])
        self.assertEqual(data["head"], sha)

    def test_shallow_without_merge_base(self):
        src = self.make_repo("main")
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
        clone = _clone(self, src.path, "--depth", "1", "--no-single-branch")
        subprocess.run(["git", "-C", str(clone), "checkout", "-q", "feat"], check=True)
        code, data = run_script(clone, "detect", "--no-fetch")
        self.assertEqual(code, 2, data)
        self.assertEqual(data["error"]["code"], "shallow_no_merge_base")
        self.assertIn("--unshallow", data["error"]["message"])

    def test_blocks_on_rebase_merge_and_conflicts(self):
        repo = self.make_repo("main")
        repo.write("a.txt", "a\n")
        sha = repo.commit("init")
        git_dir = repo.path / ".git"

        (git_dir / "rebase-merge").mkdir()
        code, data = run_script(repo, "detect")
        self.assertEqual((code, data["error"]["code"]), (2, "rebase_in_progress"))
        (git_dir / "rebase-merge").rmdir()

        (git_dir / "MERGE_HEAD").write_text(sha + "\n")
        code, data = run_script(repo, "detect")
        self.assertEqual((code, data["error"]["code"]), (2, "merge_in_progress"))
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
        self.assertNotEqual(proc.returncode, 0)
        (git_dir / "MERGE_HEAD").unlink()  # leave only the unmerged entries
        self.assertTrue(repo.git("ls-files", "-u"))
        code, data = run_script(repo, "detect")
        self.assertEqual((code, data["error"]["code"]), (2, "unresolved_conflicts"))

    def test_branch_with_slash(self):
        repo = self.make_repo("main")
        repo.write("a.txt", "a\n")
        repo.commit("init")
        repo.checkout("feature/a/b", create=True)
        code, data = run_script(repo, "detect")
        self.assertEqual(code, 0, data)
        self.assertEqual(data["branch"], "feature/a/b")
        self.assertFalse(data["detached"])
        self.assertFalse(data["shallow"])


if __name__ == "__main__":
    unittest.main()
