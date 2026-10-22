"""Tests for detect: commits, merges and guided questions."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import RepoTestCase, run_script


def _detect(repo, *extra, env=None):
    code, data = run_script(repo, "detect", "--no-fetch", *extra, env=env)
    assert code == 0, data
    return data


def _question(data, qid):
    for q in data["questions"]:
        if q["id"] == qid:
            return q
    return None


def _opt(question, oid):
    for o in question["options"]:
        if o["id"] == oid:
            return o
    return None


def _codes(data):
    return [n["code"] for n in data["notices"]]


class DetectCommitsTests(RepoTestCase):
    def _base_repo(self):
        repo = self.make_repo("main")
        repo.write("a.txt", "a\n")
        repo.commit("init")
        return repo

    def test_main_merged_into_branch_not_counted(self):
        repo = self._base_repo()
        repo.checkout("feature", create=True)
        repo.write("f.txt", "f\n")
        repo.commit("f1")
        repo.checkout("main")
        repo.write("m.txt", "m\n")
        repo.commit("m1")
        repo.checkout("feature")
        repo.merge("main")
        data = _detect(repo)
        self.assertEqual([c["subject"] for c in data["own_commits"]], ["f1"])
        self.assertEqual(data["foreign_merges"], [])

    def test_foreign_branch_merge_detected(self):
        repo = self._base_repo()
        repo.checkout("otra", create=True)
        repo.write("o.txt", "o\n")
        repo.commit("o1")
        repo.checkout("main")
        repo.checkout("feature", create=True)
        repo.write("f.txt", "f\n")
        repo.commit("f1")
        repo.merge("otra")
        merge_sha = repo.git("rev-parse", "HEAD")
        data = _detect(repo)
        self.assertEqual(data["foreign_merges"][0]["sha"], merge_sha)
        self.assertEqual(data["foreign_merges"][0]["branch_hint"], "otra")
        self.assertEqual(data["foreign_merges"][0]["files"], 1)
        q = _question(data, "foreign_merges")
        self.assertTrue(_opt(q, "exclude")["recommended"])
        self.assertEqual(_opt(q, "exclude")["facts_args"], ["--exclude-merge", merge_sha])
        self.assertEqual(_opt(q, "include")["facts_args"], ["--include-merge", merge_sha])

    def test_other_author_commits(self):
        repo = self._base_repo()
        repo.checkout("feature", create=True)
        repo.write("f.txt", "f\n")
        sha = repo.commit("by ana", email="ana@empresa.com")
        data = _detect(repo)
        self.assertEqual(data["other_author_commits"], [{"sha": sha, "email": "ana@empresa.com"}])
        q = _question(data, "other_authors")
        self.assertIn("--exclude-author", _opt(q, "exclude")["facts_args"])
        self.assertIn("ana@empresa.com", _opt(q, "exclude")["facts_args"])

    def test_no_user_email_skips_author_check(self):
        repo = self._base_repo()
        repo.checkout("feature", create=True)
        repo.write("f.txt", "f\n")
        repo.commit("by ana", email="ana@empresa.com")
        repo.git("config", "--unset", "user.email")
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "gitconfig"
            empty.write_text("")
            env = {"HOME": tmp, "GIT_CONFIG_GLOBAL": str(empty),
                   "GIT_CONFIG_NOSYSTEM": "1"}
            data = _detect(repo, env=env)
        self.assertEqual(data["other_author_commits"], [])
        self.assertIsNone(_question(data, "other_authors"))
        self.assertIn("author_check_skipped", _codes(data))

    def test_merged_normal_and_squash(self):
        repo = self._base_repo()
        repo.checkout("feature", create=True)
        repo.write("f.txt", "f\n")
        repo.commit("f1")
        repo.checkout("main")
        repo.merge("feature")
        merge_sha = repo.git("rev-parse", "HEAD")
        repo.checkout("feature")
        data = _detect(repo)
        self.assertEqual(data["merged"], {"how": "merge", "commit": merge_sha})
        q = _question(data, "scope")
        self.assertTrue(_opt(q, "merge_commit")["recommended"])
        self.assertEqual(_opt(q, "merge_commit")["facts_args"], ["--commit", merge_sha])

        repo2 = self._base_repo()
        repo2.checkout("feat2", create=True)
        repo2.write("g.txt", "g\n")
        repo2.commit("g1")
        repo2.checkout("main")
        repo2.git("merge", "--squash", "feat2")
        squash_sha = repo2.commit("squashed")
        repo2.checkout("feat2")
        data2 = _detect(repo2)
        self.assertEqual(data2["merged"], {"how": "squash", "commit": squash_sha})

    def test_scope_question_variants(self):
        repo = self._base_repo()
        repo.checkout("feature", create=True)
        repo.write("f.txt", "f\n")
        repo.commit("f1")
        mb = repo.git("merge-base", "HEAD", "main")
        data = _detect(repo)
        q = _question(data, "scope")
        self.assertEqual([o["id"] for o in q["options"]],
                         ["whole_branch", "from_commit", "uncommitted_only"])
        self.assertTrue(_opt(q, "whole_branch")["recommended"])
        self.assertEqual(_opt(q, "whole_branch")["facts_args"], ["--from", mb])
        self.assertEqual(_opt(q, "uncommitted_only")["facts_args"],
                         ["--from", "HEAD", "--include-uncommitted"])
        self.assertEqual(_opt(q, "from_commit")["params"]["commits"][0]["subject"], "f1")
        self.assertEqual(data["summary"]["scope_option"], "whole_branch")

        # On the base branch with nothing to push: only from_commit, auto answered.
        repo.checkout("main")
        data = _detect(repo)
        self.assertTrue(data["on_base"])
        self.assertEqual(data["unpushed"], 0)
        self.assertIsNone(_question(data, "scope"))
        self.assertIn("auto_answered", _codes(data))
        self.assertEqual(data["summary"]["scope_option"], "from_commit")

    def test_scope_only_new_with_last_review(self):
        from explain_changes_lib import detect as detect_mod
        repo = self._base_repo()
        repo.checkout("feature", create=True)
        repo.write("f.txt", "f\n")
        repo.commit("f1")
        mb = repo.git("merge-base", "HEAD", "main")
        old = {"branch": "feature", "head": "0" * 40,
               "reviewed_at": "2026-01-01T00:00:00Z", "hunks": []}
        with mock.patch("explain_changes_lib.state.load_state", return_value=old):
            data = detect_mod.detect(repo.path, fetch=False)
        q = _question(data, "scope")
        self.assertTrue(_opt(q, "only_new")["recommended"])
        self.assertFalse(_opt(q, "whole_branch")["recommended"])
        self.assertEqual(_opt(q, "only_new")["facts_args"], ["--from", mb, "--only-new"])
        self.assertEqual(data["last_review"]["head"], "0" * 40)
        # Same head and clean tree: nothing new, so no only_new option.
        same = dict(old, head=repo.git("rev-parse", "HEAD"))
        with mock.patch("explain_changes_lib.state.load_state", return_value=same):
            data = detect_mod.detect(repo.path, fetch=False)
        self.assertIsNone(_opt(_question(data, "scope"), "only_new"))

    def test_untracked_respects_gitignore(self):
        repo = self._base_repo()
        repo.write(".gitignore", "ignored.txt\n")
        repo.commit("ignore")
        repo.checkout("feature", create=True)
        repo.write("ignored.txt", "x\n")
        self.assertEqual(_detect(repo)["uncommitted"],
                         {"staged": 0, "unstaged": 0, "untracked": 0})
        repo.write("new.txt", "n\n")
        repo.write("a.txt", "changed\n")
        data = _detect(repo)
        self.assertEqual(data["uncommitted"], {"staged": 0, "unstaged": 1, "untracked": 1})
        self.assertEqual(data["diff_size"]["files"], 2)
        scope = _question(data, "scope")
        self.assertIn("--include-uncommitted", _opt(scope, "whole_branch")["facts_args"])


if __name__ == "__main__":
    unittest.main()
