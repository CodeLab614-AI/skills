"""Tests for per-branch review state and --only-new."""
from __future__ import annotations

import json
import re
import unittest

from helpers import RepoTestCase, run_script
from explain_changes_lib import state
from explain_changes_lib.facts import collect_facts
from explain_changes_lib.model import Hunk
from explain_changes_lib.ranges import RangeSpec


def _hunk(file, added=(), removed=(), start=1):
    return Hunk(file=file, old_start=start, old_lines=len(removed), new_start=start,
                new_lines=len(added), removed=list(removed), added=list(added))


def _a(n):
    return "".join("a%d\n" % i for i in range(1, n + 1))


class StateKeyTests(unittest.TestCase):
    def test_state_key_with_slash(self):
        k1, k2 = state.state_key("feature/a"), state.state_key("feature__a")
        self.assertNotEqual(k1, k2)
        for k in (k1, k2, state.state_key("wëird name:1")):
            self.assertRegex(k, r"^[A-Za-z0-9._-]+$")
        self.assertRegex(k1, r"^feature__a-[0-9a-f]{8}$")
        self.assertTrue(state.state_key("wëird name:1").startswith("w_ird_name_1-"))

    def test_mark_new_is_a_multiset(self):
        saved = state.build_state("b", "h", [_hunk("a.ts", ["x"])])
        hunks = [_hunk("a.ts", ["x"], start=1), _hunk("a.ts", ["x"], start=9)]
        state.mark_new(hunks, saved)
        self.assertEqual([h.seen for h in hunks], [True, False])
        self.assertEqual([h.changed_since_review for h in hunks], [False, False])

    def test_changed_since_review_on_overlap(self):
        saved = state.build_state("b", "h", [_hunk("a.ts", ["x", "y"], start=10)])
        near, far, other = (_hunk("a.ts", ["z", "y"], start=11),
                            _hunk("a.ts", ["q"], start=40), _hunk("b.ts", ["z"], start=10))
        state.mark_new([near, far, other], saved)
        self.assertEqual([h.changed_since_review for h in (near, far, other)],
                         [True, False, False])


class StateFlowTests(RepoTestCase):
    def _setup(self):
        repo = self.make_repo()
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
        self.assertEqual(rel, ".explain-changes/estado/%s.json" % state.state_key(branch))
        return saved

    def test_save_and_load_roundtrip(self):
        repo = self._setup()
        saved = self._review(repo)
        loaded = state.load_state(repo.path, "feature")
        self.assertEqual(loaded, saved)
        self.assertEqual(set(loaded), {"branch", "head", "reviewed_at", "hunks", "files"})
        self.assertEqual(set(loaded["hunks"][0]),
                         {"fingerprint", "file", "new_start", "new_lines"})
        self.assertIsNone(state.load_state(repo.path, "other"))

    def test_only_new_after_review(self):
        repo = self._setup()
        self._review(repo)
        repo.write("a.ts", _a(30).replace("a5\n", "a5 again\n"))
        repo.write("b.ts", "b1\nb2 new\n")
        repo.commit("more")
        full = self._facts(repo)
        self.assertEqual({h["file"] for h in full["hunks"]}, {"a.ts", "b.ts"})
        facts = self._facts(repo, only_new=True)
        self.assertEqual({h["file"] for h in facts["hunks"]}, {"a.ts", "b.ts"})
        by = {h["file"]: h for h in facts["hunks"]}
        self.assertTrue(by["a.ts"]["changed_since_review"])
        self.assertFalse(by["b.ts"]["changed_since_review"])
        self.assertFalse(any(h["seen"] for h in facts["hunks"]))
        self.assertEqual(facts["totals"]["files"], 2)

    def test_only_new_drops_seen_files_and_rebatches(self):
        repo = self._setup()
        self._review(repo)
        repo.write("b.ts", "b1\nb2 new\n")
        repo.commit("more")
        full = self._facts(repo)
        seen = {h["file"]: h["seen"] for h in full["hunks"]}
        self.assertEqual(seen, {"a.ts": True, "b.ts": False})
        facts = self._facts(repo, only_new=True)
        self.assertEqual([f["path"] for f in facts["files"]], ["b.ts"])
        self.assertEqual(facts["totals"]["files"], 1)
        self.assertEqual(facts["totals"]["logic_lines"], 2)
        self.assertEqual([b["paths"] for b in facts["batches"]], [["b.ts"]])

    def test_rewritten_history_uses_fingerprints(self):
        repo = self._setup()
        self._review(repo)
        old = repo.git("rev-parse", "HEAD")
        repo.git("commit", "-q", "--amend", "-m", "reworded",
                 env={"GIT_COMMITTER_DATE": "2030-01-01T00:00:00"})
        self.assertNotEqual(old, repo.git("rev-parse", "HEAD"))
        code, data = run_script(repo, "detect", "--no-fetch")
        self.assertEqual(code, 0, data)
        review = data["last_review"]
        self.assertFalse(review["head_reachable"])
        self.assertEqual(review["head"], old)
        self.assertIn("history_rewritten", [n["code"] for n in data["notices"]])
        facts = self._facts(repo, only_new=True)
        self.assertEqual(facts["hunks"], [])
        self.assertEqual(facts["files"], [])
        self.assertEqual(facts["batches"], [])
        self.assertEqual(facts["totals"]["files"], 0)

    def test_last_review_counts_new_work(self):
        repo = self._setup()
        self._review(repo)
        code, data = run_script(repo, "detect", "--no-fetch")
        self.assertEqual(data["last_review"]["new_commits"], 0)
        self.assertEqual(data["last_review"]["new_files"], 0)
        self.assertTrue(data["last_review"]["head_reachable"])
        self.assertNotIn("history_rewritten", [n["code"] for n in data["notices"]])
        repo.write("b.ts", "b1\nb2 new\n")
        repo.commit("more")
        repo.write("c.ts", "c\n")
        code, data = run_script(repo, "detect", "--no-fetch")
        self.assertEqual(data["last_review"]["new_commits"], 1)
        self.assertEqual(data["last_review"]["new_files"], 2)

    def test_hunkless_file_seen_by_path(self):
        repo = self.make_repo()
        repo.write("a.ts", "a\n")
        repo.write("old.bin", b"\0\1\2\3")
        repo.commit("init")
        repo.checkout("feature", create=True)
        repo.git("mv", "old.bin", "new.bin")
        repo.commit("rename")
        facts = self._facts(repo)
        self.assertEqual(facts["hunks"], [])
        self.assertEqual([f["path"] for f in facts["files"]], ["new.bin"])
        saved = state.build_state("feature", repo.git("rev-parse", "HEAD"), [],
                                  [f["path"] for f in facts["files"]])
        state.save_state(repo.path, "feature", saved)
        self.assertEqual(self._facts(repo, only_new=True)["files"], [])
        repo.write("a.ts", "a2\n")
        repo.commit("edit")
        self.assertEqual([f["path"] for f in self._facts(repo, only_new=True)["files"]],
                         ["a.ts"])

    def test_detached_no_state(self):
        repo = self._setup()
        self._review(repo)
        repo.git("checkout", "-q", "--detach")
        code, data = run_script(repo, "detect", "--no-fetch")
        self.assertEqual(code, 0, data)
        self.assertTrue(data["detached"])
        self.assertIsNone(data["last_review"])
        facts = self._facts(repo, only_new=True)
        self.assertEqual(len(facts["hunks"]), 1)
        self.assertFalse(facts["hunks"][0]["seen"])
        with self.assertRaises(ValueError):
            state.save_state(repo.path, "", {})


if __name__ == "__main__":
    unittest.main()
