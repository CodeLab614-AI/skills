"""Tests for detect: commits, merges and guided questions."""
from __future__ import annotations

import pytest

from explain_helpers import run_script


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


def _check_one_recommended(data):
    for q in data["questions"]:
        assert sum(1 for o in q["options"] if o["recommended"]) == 1, q["id"]


def _codes(data):
    return [n["code"] for n in data["notices"]]


class TestDetectCommits:
    @pytest.fixture(autouse=True)
    def _repo_factory(self, make_repo):
        self._make_repo = make_repo

    def _base_repo(self):
        repo = self._make_repo("main")
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
        assert [c["subject"] for c in data["own_commits"]] == ["f1"]
        assert data["foreign_merges"] == []

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
        assert data["foreign_merges"][0]["sha"] == merge_sha
        assert data["foreign_merges"][0]["branch_hint"] == "otra"
        assert data["foreign_merges"][0]["files"] == 1
        q = _question(data, "foreign_merges")
        assert _opt(q, "exclude")["recommended"]
        assert _opt(q, "exclude")["facts_args"] == ["--exclude-merge", merge_sha]
        assert _opt(q, "include")["facts_args"] == ["--include-merge", merge_sha]

    def test_other_author_commits(self):
        repo = self._base_repo()
        repo.checkout("feature", create=True)
        repo.write("f.txt", "f\n")
        sha = repo.commit("by ana", email="ana@empresa.com")
        data = _detect(repo)
        assert data["other_author_commits"] == [{"sha": sha, "email": "ana@empresa.com"}]
        q = _question(data, "other_authors")
        assert _opt(q, "exclude")["recommended"]
        assert not _opt(q, "include")["recommended"]
        assert "--exclude-author" in _opt(q, "exclude")["facts_args"]
        assert "ana@empresa.com" in _opt(q, "exclude")["facts_args"]

    def test_no_user_email_skips_author_check(self, tmp_path):
        repo = self._base_repo()
        repo.checkout("feature", create=True)
        repo.write("f.txt", "f\n")
        repo.commit("by ana", email="ana@empresa.com")
        repo.git("config", "--unset", "user.email")
        empty = tmp_path / "gitconfig"
        empty.write_text("")
        env = {"HOME": str(tmp_path), "GIT_CONFIG_GLOBAL": str(empty),
               "GIT_CONFIG_NOSYSTEM": "1"}
        data = _detect(repo, env=env)
        assert data["other_author_commits"] == []
        assert _question(data, "other_authors") is None
        assert "author_check_skipped" in _codes(data)

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
        assert data["merged"] == {"how": "merge", "commit": merge_sha}
        q = _question(data, "scope")
        _check_one_recommended(data)
        assert _opt(q, "merge_commit")["recommended"]
        assert _opt(q, "merge_commit")["facts_args"] == ["--commit", merge_sha]

        repo2 = self._base_repo()
        repo2.checkout("feat2", create=True)
        repo2.write("g.txt", "g\n")
        repo2.commit("g1")
        repo2.checkout("main")
        repo2.git("merge", "--squash", "feat2")
        squash_sha = repo2.commit("squashed")
        repo2.checkout("feat2")
        data2 = _detect(repo2)
        assert data2["merged"] == {"how": "squash", "commit": squash_sha}

    def test_merged_fast_forward(self):
        repo = self._base_repo()
        repo.checkout("feature", create=True)
        repo.write("f.txt", "f\n")
        head = repo.commit("f1")
        repo.checkout("main")
        repo.merge("feature", no_ff=False)
        repo.write("m.txt", "m\n")
        repo.commit("m1")
        repo.checkout("feature")
        data = _detect(repo)
        assert data["merged"] == {"how": "fast_forward", "commit": head}
        q = _question(data, "scope")
        # No merge commit exists, and the merge-base is HEAD itself (no whole_branch):
        # only the commit picker remains, so the question is auto-answered.
        assert q is None
        auto = [n for n in data["notices"] if n["code"] == "auto_answered"][0]["params"]
        assert auto["option"] == "other_commit"
        assert data["summary"]["scope_option"] == "other_commit"

    def test_merged_tree_recommends_whole_branch(self):
        repo = self._base_repo()
        repo.checkout("feature", create=True)
        repo.write("f.txt", "f\n")
        repo.commit("f1")
        repo.write("g.txt", "g\n")
        repo.commit("f2")
        repo.checkout("main")
        repo.write("f.txt", "f\n")
        repo.commit("retyped f")
        repo.write("g.txt", "g\n")
        tree_commit = repo.commit("retyped g")
        repo.checkout("feature")
        data = _detect(repo)
        assert data["merged"] == {"how": "tree", "commit": tree_commit}
        q = _question(data, "scope")
        _check_one_recommended(data)
        assert _opt(q, "whole_branch")["recommended"]
        assert _opt(q, "merge_commit") is None
        assert _opt(q, "other_commit") is not None

    def test_fresh_branch_at_base_tip_is_not_merged(self):
        repo = self._base_repo()
        repo.checkout("fresh", create=True)
        data = _detect(repo)
        assert data["merged"] is None
        assert "no_own_commits" in _codes(data)
        assert _question(data, "scope") is None
        assert data["summary"]["scope_option"] == "from_commit"
        assert "auto_answered" in _codes(data)
        repo.write("a.txt", "changed\n")
        data = _detect(repo)
        q = _question(data, "scope")
        assert [o["id"] for o in q["options"]] == ["from_commit", "uncommitted_only"]

    def test_merged_branch_with_previous_review_has_one_recommended(self, monkeypatch):
        from explain_changes_lib import detect as detect_mod
        repo = self._base_repo()
        repo.checkout("feature", create=True)
        repo.write("f.txt", "f\n")
        repo.commit("f1")
        repo.checkout("main")
        repo.merge("feature")
        repo.checkout("feature")
        old = {"branch": "feature", "head": "0" * 40, "reviewed_at": "x", "hunks": []}
        monkeypatch.setattr("explain_changes_lib.state.load_state", lambda *a, **k: old)
        data = detect_mod.detect(repo.path, fetch=False)
        _check_one_recommended(data)
        assert _opt(_question(data, "scope"), "merge_commit")["recommended"]

    def test_stale_branch_behind_moved_base_with_pending_changes(self):
        repo = self._base_repo()
        repo.checkout("feature", create=True)
        repo.checkout("main")
        repo.write("m.txt", "m\n")
        repo.commit("m1")
        repo.checkout("feature")
        repo.write("a.txt", "work\n")
        data = _detect(repo)
        q = _question(data, "scope")
        _check_one_recommended(data)
        assert _opt(q, "uncommitted_only")["recommended"]
        assert _opt(q, "merge_commit") is None
        assert _opt(q, "other_commit") is not None

    def test_unrelated_later_merge_on_base_is_not_how_merge(self):
        repo = self._base_repo()
        repo.checkout("feature", create=True)
        repo.write("f.txt", "f\n")
        head = repo.commit("f1")
        repo.checkout("main")
        repo.merge("feature", no_ff=False)
        repo.write("m.txt", "m\n")
        repo.commit("m1")
        repo.checkout("x", create=True)
        repo.write("x.txt", "x\n")
        repo.commit("x1")
        repo.checkout("main")
        repo.merge("x")
        repo.checkout("feature")
        data = _detect(repo)
        assert data["merged"] == {"how": "fast_forward", "commit": head}

    def test_diff_size_with_rename_and_untracked(self, make_repo, monkeypatch):
        from explain_changes_lib import detect as detect_mod
        repo = make_repo("main")
        repo.write("a.txt", "1\n2\n3\n4\n")
        repo.commit("init")
        repo.checkout("feature", create=True)
        repo.git("mv", "a.txt", "b.txt")
        repo.commit("rename")
        repo.write("n.txt", "x\ny\nz")
        repo.write("bin.dat", b"\0\1\2")
        calls = []

        def fake_find_rule_files(*args, **kwargs):
            calls.append(args)
            return []

        monkeypatch.setattr("explain_changes_lib.rules.find_rule_files", fake_find_rule_files)
        data = detect_mod.detect(repo.path, fetch=False)
        assert calls[-1][1] == ["b.txt", "bin.dat", "n.txt"]
        assert data["diff_size"] == {"files": 3, "lines": 3}

    def test_scope_question_variants(self):
        repo = self._base_repo()
        repo.checkout("feature", create=True)
        repo.write("f.txt", "f\n")
        repo.commit("f1")
        mb = repo.git("merge-base", "HEAD", "main")
        data = _detect(repo)
        q = _question(data, "scope")
        assert [o["id"] for o in q["options"]] == \
                         ["whole_branch", "from_commit", "uncommitted_only"]
        assert _opt(q, "whole_branch")["recommended"]
        assert _opt(q, "whole_branch")["facts_args"] == ["--from", mb]
        assert _opt(q, "uncommitted_only")["facts_args"] == \
                         ["--from", "HEAD", "--include-uncommitted"]
        assert _opt(q, "from_commit")["params"]["commits"][0]["subject"] == "f1"
        assert data["summary"]["scope_option"] == "whole_branch"

        # On the base branch with nothing to push: only from_commit, auto answered.
        repo.checkout("main")
        data = _detect(repo)
        assert data["on_base"]
        assert data["unpushed"] == 0
        assert _question(data, "scope") is None
        assert "auto_answered" in _codes(data)
        assert data["summary"]["scope_option"] == "from_commit"
        auto = [n for n in data["notices"] if n["code"] == "auto_answered"][0]["params"]
        assert auto["option"] == "from_commit"
        assert auto["facts_args"] == ["--from-commit"]
        assert auto["params"]["commits"][0]["subject"] == "init"

    def test_scope_only_new_with_last_review(self, monkeypatch):
        from explain_changes_lib import detect as detect_mod
        repo = self._base_repo()
        repo.checkout("feature", create=True)
        repo.write("f.txt", "f\n")
        repo.commit("f1")
        mb = repo.git("merge-base", "HEAD", "main")
        old = {"branch": "feature", "head": "0" * 40,
               "reviewed_at": "2026-01-01T00:00:00Z", "hunks": []}
        monkeypatch.setattr("explain_changes_lib.state.load_state", lambda *a, **k: old)
        data = detect_mod.detect(repo.path, fetch=False)
        q = _question(data, "scope")
        _check_one_recommended(data)
        assert _opt(q, "only_new")["recommended"]
        assert not _opt(q, "whole_branch")["recommended"]
        assert _opt(q, "only_new")["facts_args"] == ["--from", mb, "--only-new"]
        assert data["last_review"]["head"] == "0" * 40
        # Same head and clean tree: nothing new, so no only_new option.
        same = dict(old, head=repo.git("rev-parse", "HEAD"))
        monkeypatch.setattr("explain_changes_lib.state.load_state", lambda *a, **k: same)
        data = detect_mod.detect(repo.path, fetch=False)
        assert _opt(_question(data, "scope"), "only_new") is None

    def test_untracked_respects_gitignore(self):
        repo = self._base_repo()
        repo.write(".gitignore", "ignored.txt\n")
        repo.commit("ignore")
        repo.checkout("feature", create=True)
        repo.write("f.txt", "f\n")
        repo.commit("f1")
        repo.write("ignored.txt", "x\n")
        assert _detect(repo)["uncommitted"] == \
                         {"staged": 0, "unstaged": 0, "untracked": 0}
        repo.write("new.txt", "n\n")
        repo.write("a.txt", "changed\n")
        data = _detect(repo)
        assert data["uncommitted"] == {"staged": 0, "unstaged": 1, "untracked": 1}
        assert data["diff_size"]["files"] == 3
        scope = _question(data, "scope")
        assert "--include-uncommitted" in _opt(scope, "whole_branch")["facts_args"]

