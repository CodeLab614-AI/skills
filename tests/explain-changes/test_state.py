"""Tests for per-branch review state and --only-new."""
from __future__ import annotations

import json
import re

import pytest

from explain_helpers import run_script
from explain_changes_lib import state
from explain_changes_lib.facts import collect_facts
from explain_changes_lib.model import Hunk
from explain_changes_lib.ranges import RangeSpec


def _hunk(file, added=(), removed=(), start=1):
    return Hunk(file=file, old_start=start, old_lines=len(removed), new_start=start,
                new_lines=len(added), removed=list(removed), added=list(added))


def _a(n):
    return "".join("a%d\n" % i for i in range(1, n + 1))


class TestStateKey:
    def test_state_key_with_slash(self):
        k1, k2 = state.state_key("feature/a"), state.state_key("feature__a")
        assert k1 != k2
        for k in (k1, k2, state.state_key("wëird name:1")):
            assert re.search(r"^[A-Za-z0-9._-]+$", k)
        assert re.search(r"^feature__a-[0-9a-f]{8}$", k1)
        assert state.state_key("wëird name:1").startswith("w_ird_name_1-")

    def test_mark_new_is_a_multiset(self):
        saved = state.build_state("b", "h", [_hunk("a.ts", ["x"])])
        hunks = [_hunk("a.ts", ["x"], start=1), _hunk("a.ts", ["x"], start=9)]
        state.mark_new(hunks, saved)
        assert [h.seen for h in hunks] == [True, False]
        assert [h.changed_since_review for h in hunks] == [False, False]

    def test_changed_since_review_on_overlap(self):
        saved = state.build_state("b", "h", [_hunk("a.ts", ["x", "y"], start=10)])
        near, far, other = (_hunk("a.ts", ["z", "y"], start=11),
                            _hunk("a.ts", ["q"], start=40), _hunk("b.ts", ["z"], start=10))
        state.mark_new([near, far, other], saved)
        assert [h.changed_since_review for h in (near, far, other)] == \
                         [True, False, False]


class TestStateFlow:
    @pytest.fixture(autouse=True)
    def _repo_factory(self, make_repo):
        self._make_repo = make_repo

    def _setup(self):
        repo = self._make_repo()
        repo.write("a.ts", _a(30))
        repo.write("b.ts", "b1\nb2\n")
        repo.commit("init")
        repo.checkout("feature", create=True)
        repo.write("a.ts", _a(30).replace("a5\n", "a5 changed\n"))
        repo.commit("review me")
        return repo

    def _facts(self, repo, only_new=False):
        return collect_facts(repo.path, RangeSpec(from_ref="main"), only_new=only_new)

    def _review(self, repo, branch="feature"):
        facts = self._facts(repo)
        saved = state.build_state(branch, repo.git("rev-parse", "HEAD"), facts["hunks"],
                                  [f["path"] for f in facts["files"]])
        rel = state.save_state(repo.path, branch, saved)
        assert rel == ".explain-changes/state/%s.json" % state.state_key(branch)
        return saved

    def test_save_and_load_roundtrip(self):
        repo = self._setup()
        saved = self._review(repo)
        loaded = state.load_state(repo.path, "feature")
        assert loaded == saved
        assert set(loaded) == {"branch", "head", "reviewed_at", "hunks", "files"}
        assert set(loaded["hunks"][0]) == \
                         {"fingerprint", "file", "new_start", "new_lines"}
        assert state.load_state(repo.path, "other") is None

    def test_only_new_after_review(self):
        repo = self._setup()
        self._review(repo)
        repo.write("a.ts", _a(30).replace("a5\n", "a5 again\n"))
        repo.write("b.ts", "b1\nb2 new\n")
        repo.commit("more")
        full = self._facts(repo)
        assert {h["file"] for h in full["hunks"]} == {"a.ts", "b.ts"}
        facts = self._facts(repo, only_new=True)
        assert {h["file"] for h in facts["hunks"]} == {"a.ts", "b.ts"}
        by = {h["file"]: h for h in facts["hunks"]}
        assert by["a.ts"]["changed_since_review"]
        assert not by["b.ts"]["changed_since_review"]
        assert not any(h["seen"] for h in facts["hunks"])
        assert facts["totals"]["files"] == 2

    def test_only_new_drops_seen_files_and_rebatches(self):
        repo = self._setup()
        self._review(repo)
        repo.write("b.ts", "b1\nb2 new\n")
        repo.commit("more")
        full = self._facts(repo)
        seen = {h["file"]: h["seen"] for h in full["hunks"]}
        assert seen == {"a.ts": True, "b.ts": False}
        facts = self._facts(repo, only_new=True)
        assert [f["path"] for f in facts["files"]] == ["b.ts"]
        assert facts["totals"]["files"] == 1
        assert facts["totals"]["logic_lines"] == 2
        assert [b["paths"] for b in facts["batches"]] == [["b.ts"]]

    def test_rewritten_history_uses_fingerprints(self):
        repo = self._setup()
        self._review(repo)
        old = repo.git("rev-parse", "HEAD")
        repo.git("commit", "-q", "--amend", "-m", "reworded",
                 env={"GIT_COMMITTER_DATE": "2030-01-01T00:00:00"})
        assert old != repo.git("rev-parse", "HEAD")
        code, data = run_script(repo, "detect", "--no-fetch")
        assert code == 0, data
        review = data["last_review"]
        assert not review["head_reachable"]
        assert review["head"] == old
        assert "history_rewritten" in [n["code"] for n in data["notices"]]
        facts = self._facts(repo, only_new=True)
        assert facts["hunks"] == []
        assert facts["files"] == []
        assert facts["batches"] == []
        assert facts["totals"]["files"] == 0

    def test_last_review_counts_new_work(self):
        repo = self._setup()
        self._review(repo)
        code, data = run_script(repo, "detect", "--no-fetch")
        assert data["last_review"]["new_commits"] == 0
        assert data["last_review"]["new_files"] == 0
        assert data["last_review"]["head_reachable"]
        assert "history_rewritten" not in [n["code"] for n in data["notices"]]
        repo.write("b.ts", "b1\nb2 new\n")
        repo.commit("more")
        repo.write("c.ts", "c\n")
        code, data = run_script(repo, "detect", "--no-fetch")
        assert data["last_review"]["new_commits"] == 1
        assert data["last_review"]["new_files"] == 2

    def test_hunkless_file_seen_by_path(self, make_repo):
        repo = make_repo()
        repo.write("a.ts", "a\n")
        repo.write("old.bin", b"\0\1\2\3")
        repo.commit("init")
        repo.checkout("feature", create=True)
        repo.git("mv", "old.bin", "new.bin")
        repo.commit("rename")
        facts = self._facts(repo)
        assert facts["hunks"] == []
        assert [f["path"] for f in facts["files"]] == ["new.bin"]
        saved = state.build_state("feature", repo.git("rev-parse", "HEAD"), [],
                                  [f["path"] for f in facts["files"]])
        state.save_state(repo.path, "feature", saved)
        assert self._facts(repo, only_new=True)["files"] == []
        repo.write("a.ts", "a2\n")
        repo.commit("edit")
        assert [f["path"] for f in self._facts(repo, only_new=True)["files"]] == \
                         ["a.ts"]

    def test_detached_no_state(self):
        repo = self._setup()
        self._review(repo)
        repo.git("checkout", "-q", "--detach")
        code, data = run_script(repo, "detect", "--no-fetch")
        assert code == 0, data
        assert data["detached"]
        assert data["last_review"] is None
        facts = self._facts(repo, only_new=True)
        assert len(facts["hunks"]) == 1
        assert not facts["hunks"][0]["seen"]
        with pytest.raises(ValueError):
            state.save_state(repo.path, "", {})

    def _write_state(self, repo, data, branch="feature"):
        path = repo.path / ".explain-changes" / "state" / (state.state_key(branch) + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")

    def test_malformed_state_is_no_state(self):
        repo = self._setup()
        good = self._review(repo)
        h = good["hunks"][0]
        bad = [
            dict(good, hunks=[dict(h, new_start="3")]),
            dict(good, hunks=[dict(h, new_lines=True)]),
            dict(good, hunks=[dict(h, fingerprint=["x"])]),
            dict(good, hunks=[dict(h, file=5)]),
            dict(good, hunks=["nope"]),
            dict(good, files=5),
            dict(good, files=[["a"]]),
            dict(good, head=7),
            "[1, 2]", "{not json",
        ]
        for data in bad:
            self._write_state(repo, data)
            assert state.load_state(repo.path, "feature") is None, data
            facts = self._facts(repo, only_new=True)
            assert len(facts["hunks"]) == 1
            code, det = run_script(repo, "detect", "--no-fetch")
            assert code == 0, det
            assert det["last_review"] is None

    def test_state_of_another_branch_is_ignored(self):
        repo = self._setup()
        good = self._review(repo)
        self._write_state(repo, dict(good, branch="other"))
        assert state.load_state(repo.path, "feature") is None

    def test_long_branch_name_key_fits_filesystem(self):
        repo = self._setup()
        name = "feature/" + "x" * 292
        key = state.state_key(name)
        assert len(key) <= 120
        assert re.search(r"-[0-9a-f]{8}$", key)
        assert key != state.state_key(name + "y")
        saved = state.build_state(name, "h", [])
        state.save_state(repo.path, name, saved)
        assert state.load_state(repo.path, name) == saved

    def test_state_survives_cleanup_and_facts(self):
        from explain_changes_lib.workspace import cleanup_previous
        repo = self._setup()
        self._review(repo)
        path = repo.path / ".explain-changes" / "state" / (state.state_key("feature") + ".json")
        cleanup_previous(repo.path)
        assert path.is_file()
        self._facts(repo)
        assert path.is_file()
        assert state.load_state(repo.path, "feature") is not None

