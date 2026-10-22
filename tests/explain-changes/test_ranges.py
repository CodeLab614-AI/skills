"""Tests for ranges and the basic facts command."""
from __future__ import annotations

import json
import os
import unittest
from collections import Counter

from helpers import RepoTestCase, run_script
from explain_changes_lib import ranges
from explain_changes_lib.model import Hunk

FACTS = ".explain-changes/run/facts.json"


def _facts(repo, *args):
    code, data = run_script(repo, "facts", *args)
    assert code == 0, data
    return json.loads((repo.path / FACTS).read_text(encoding="utf-8")), data


def _paths(facts):
    return sorted(f["path"] for f in facts["files"])


class FactsRangeTests(RepoTestCase):
    def _base(self):
        repo = self.make_repo("main")
        repo.write("a.ts", "a1\na2\na3\n")
        repo.write("b.ts", "b1\nb2\nb3\n")
        repo.commit("init")
        return repo

    def test_merge_from_main_never_appears(self):
        repo = self._base()
        repo.checkout("feature", create=True)
        repo.checkout("main")
        repo.write("b.ts", "b1\nB2\nb3\nb4\n")
        repo.commit("main change")
        repo.checkout("feature")
        repo.write("a.ts", "a1\nA2\na3\n")
        before = repo.commit("feature change")
        repo.merge("main")
        facts, out = _facts(repo, "--from", before)
        self.assertEqual(_paths(facts), [])
        facts, _ = _facts(repo, "--from", "main")
        self.assertEqual(_paths(facts), ["a.ts"])

    def test_merge_from_main_with_old_before_feature_commit(self):
        repo = self._base()
        repo.checkout("feature", create=True)
        base_commit = repo.git("rev-parse", "HEAD")
        repo.write("a.ts", "a1\nA2\na3\n")
        repo.commit("feature change")
        repo.checkout("main")
        repo.write("b.ts", "b1\nB2\nb3\n")
        repo.commit("main change")
        repo.checkout("feature")
        repo.merge("main")
        facts, _ = _facts(repo, "--from", base_commit)
        self.assertEqual(_paths(facts), ["a.ts"])

    def _other_branch(self):
        repo = self._base()
        repo.checkout("feature", create=True)
        repo.write("a.ts", "a1\nA2\na3\n")
        repo.commit("feature change")
        repo.checkout("main")
        repo.checkout("otra", create=True)
        repo.write("o.ts", "o1\no2\no3\n")
        repo.commit("otra work")
        repo.checkout("feature")
        repo.merge("otra")
        return repo, repo.git("rev-parse", "HEAD")

    def test_excluded_foreign_branch_subtracted(self):
        repo, merge = self._other_branch()
        facts, _ = _facts(repo, "--from", "main", "--exclude-merge", merge)
        self.assertEqual(_paths(facts), ["a.ts"])
        self.assertEqual(facts["excluded"]["merges"], [merge])
        self.assertTrue(facts["excluded"]["dropped_hunks"])

    def test_foreign_branch_without_exclusion_is_included(self):
        repo, merge = self._other_branch()
        facts, _ = _facts(repo, "--from", "main")
        self.assertEqual(_paths(facts), ["a.ts", "o.ts"])

    def test_user_edit_of_foreign_line_still_appears(self):
        repo, merge = self._other_branch()
        repo.write("o.ts", "o1\nmine\no3\n")
        repo.commit("edit foreign line")
        facts, _ = _facts(repo, "--from", "main", "--exclude-merge", merge)
        self.assertEqual(_paths(facts), ["a.ts", "o.ts"])
        hunk = [h for h in facts["hunks"] if h["file"] == "o.ts"][0]
        self.assertIn("mine", hunk["added"])

    def test_exclude_author(self):
        repo = self._base()
        repo.checkout("feature", create=True)
        repo.write("ana.ts", "x\ny\n")
        repo.commit("ana work", email="ana@empresa.com")
        repo.write("a.ts", "a1\nA2\na3\n")
        repo.commit("my work")
        facts, _ = _facts(repo, "--from", "main")
        self.assertEqual(_paths(facts), ["a.ts", "ana.ts"])
        facts, _ = _facts(repo, "--from", "main", "--exclude-author", "ana@empresa.com")
        self.assertEqual(_paths(facts), ["a.ts"])
        self.assertEqual(facts["excluded"]["authors"], ["ana@empresa.com"])

    def test_conflict_resolution_marked(self):
        repo = self._base()
        repo.checkout("feature", create=True)
        repo.write("a.ts", "a1\nfeature\na3\n")
        repo.commit("feature")
        repo.checkout("main")
        repo.write("a.ts", "a1\nmain\na3\n")
        repo.commit("main")
        repo.checkout("feature")
        proc = __import__("subprocess").run(
            ["git", "merge", "--no-ff", "-m", "merge main", "main"], cwd=repo.path,
            capture_output=True)
        self.assertNotEqual(proc.returncode, 0)
        repo.write("a.ts", "a1\nresolved by hand\na3\n")
        repo.git("add", "a.ts")
        repo.git("commit", "-q", "-m", "merge main")
        before = repo.git("rev-parse", "HEAD^1")
        facts, _ = _facts(repo, "--from", before)
        marked = [h for h in facts["hunks"] if h["resolved_in_merge"]]
        self.assertTrue(marked)
        self.assertEqual(marked[0]["file"], "a.ts")
        self.assertEqual(marked[0]["resolved_in_merge"], [2])

    def test_uncommitted_and_untracked_included(self):
        repo = self._base()
        repo.write("a.ts", "a1\nstaged\na3\n")
        repo.git("add", "a.ts")
        repo.write("b.ts", "b1\nunstaged\nb3\n")
        repo.write("new.ts", "n1\n")
        repo.write(".explain-changes/junk.txt", "x\n")
        facts, _ = _facts(repo, "--from", "HEAD", "--include-uncommitted")
        self.assertEqual(_paths(facts), ["a.ts", "b.ts", "new.ts"])
        statuses = {f["path"]: f["status"] for f in facts["files"]}
        self.assertEqual(statuses["new.ts"], "untracked")
        facts, _ = _facts(repo, "--from", "HEAD")
        self.assertEqual(_paths(facts), [])

    def test_commit_mode(self):
        repo = self._base()
        repo.write("a.ts", "a1\nA2\na3\n")
        repo.commit("one")
        repo.write("b.ts", "b1\nB2\nb3\n")
        sha = repo.commit("two")
        repo.write("c.ts", "c\n")
        repo.commit("three")
        facts, _ = _facts(repo, "--commit", sha)
        self.assertEqual(_paths(facts), ["b.ts"])
        self.assertEqual(facts["range"]["new"], sha)

    def test_commit_mode_root_commit(self):
        repo = self.make_repo("main")
        repo.write("a.ts", "a1\n")
        sha = repo.commit("root")
        facts, _ = _facts(repo, "--commit", sha)
        self.assertEqual(_paths(facts), ["a.ts"])

    def test_bad_ref_is_bad_input(self):
        repo = self._base()
        code, data = run_script(repo, "facts", "--from", "nope-nope")
        self.assertEqual(code, 2)
        self.assertEqual(data["error"]["code"], "bad_input")

    def test_facts_writes_only_run_file(self):
        repo = self._base()
        repo.checkout("feature", create=True)
        repo.write("a.ts", "a1\nA2\na3\n")
        repo.commit("feature change")
        code, out = run_script(repo, "facts", "--from", "main")
        self.assertEqual(code, 0, out)
        self.assertEqual(set(out), {"ok", "path", "totals", "batches", "notices"})
        self.assertEqual(out["totals"]["files"], 1)
        self.assertEqual(out["totals"]["logic_lines"], 2)
        self.assertEqual(repo.git("status", "--porcelain"), "")
        found = []
        for root, _dirs, files in os.walk(repo.path / ".explain-changes"):
            for name in files:
                found.append(os.path.relpath(os.path.join(root, name), repo.path))
        self.assertEqual(sorted(found), [".explain-changes/.manifest.json", FACTS])

    def test_facts_includes_rule_files(self):
        repo = self._base()
        repo.write("AGENTS.md", "rules\n")
        repo.commit("rules")
        repo.write("a.ts", "a1\nA2\na3\n")
        facts, _ = _facts(repo, "--from", "HEAD", "--include-uncommitted")
        self.assertIn("AGENTS.md", [r["path"] for r in facts["rule_files"]])


def _hunk(path, removed, added):
    return Hunk(file=path, old_start=1, old_lines=len(removed), new_start=1,
                new_lines=len(added), removed=removed, added=added)


class SubtractTests(unittest.TestCase):
    def test_dropped_only_if_all_lines_consumed(self):
        foreign = {"f": Counter({("+", "x"): 1, ("+", "y"): 1})}
        full, partial = _hunk("f", [], ["x", "y"]), _hunk("f", [], ["x", "mine"])
        kept, dropped = ranges.subtract([full, partial], foreign)
        self.assertEqual(kept, [partial])
        self.assertEqual(dropped, [full.id])

    def test_partial_match_does_not_consume(self):
        foreign = {"f": Counter({("+", "x"): 1})}
        partial, other = _hunk("f", [], ["x", "mine"]), _hunk("f", [], ["x"])
        kept, dropped = ranges.subtract([partial, other], foreign)
        self.assertEqual(kept, [partial])
        self.assertEqual(dropped, [other.id])

    def test_duplicates_consume_separately(self):
        foreign = {"f": Counter({("+", "x"): 1})}
        a, b = _hunk("f", [], ["x"]), _hunk("f", [], ["x"])
        b.id_override = a.id + "-2"
        kept, dropped = ranges.subtract([a, b], foreign)
        self.assertEqual(kept, [b])
        self.assertEqual(dropped, [a.id])

    def test_other_files_untouched(self):
        foreign = {"g": Counter({("+", "x"): 5})}
        h = _hunk("f", [], ["x"])
        self.assertEqual(ranges.subtract([h], foreign), ([h], []))


if __name__ == "__main__":
    unittest.main()
