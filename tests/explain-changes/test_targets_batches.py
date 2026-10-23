"""Tests for rule targets, batching and the bundle subcommand."""
from __future__ import annotations

import json
import unittest

from helpers import RepoTestCase, run_script
from explain_changes_lib.batches import make_batches
from explain_changes_lib.model import BlockedError, FileChange, Hunk
from explain_changes_lib.targets import glob_to_regex, load_targets

FACTS = ".explain-changes/run/facts.json"


def _hunk(file, added=(), removed=()):
    return Hunk(file=file, old_start=1, old_lines=len(removed), new_start=1,
                new_lines=len(added), removed=list(removed), added=list(added))


def _synthetic(sizes):
    """sizes: {path: logic_lines} -> (files, hunks)."""
    files, hunks = [], []
    for path, n in sizes.items():
        h = _hunk(path, added=["x%d" % i for i in range(n)])
        files.append(FileChange(path=path, status="modified", hunks=[h]))
        hunks.append(h)
    return files, hunks


class GlobTests(unittest.TestCase):
    def test_glob(self):
        r = glob_to_regex("src/**/*.ts")
        self.assertTrue(r.match("src/a.ts"))
        self.assertTrue(r.match("src/x/y/a.ts"))
        self.assertFalse(r.match("lib/a.ts"))
        self.assertFalse(glob_to_regex("*.md").match("docs/a.md"))
        self.assertTrue(glob_to_regex("*.md").match("a.md"))

    def test_load_targets_invalid(self):
        for bad in ("not json", "{}", '[{"id": "R1"}]',
                    '[{"id":"R1","rule":{"file":"a","line":1},"paths":[],'
                    '"change_kinds":["bogus"],"line_pattern":null}]',
                    '[{"id":"R1","rule":{"file":"a","line":1},"paths":[],'
                    '"change_kinds":[],"line_pattern":"("}]'):
            with self.assertRaises(BlockedError) as cm:
                load_targets(bad)
            self.assertEqual(cm.exception.code, "bad_input")


class TargetFlowTests(RepoTestCase):
    def _facts(self, repo, targets=None, *args):
        stdin = json.dumps(targets) if targets is not None else None
        extra = ["--targets-stdin"] if targets is not None else []
        code, data = run_script(repo, "facts", "--from", "main", *extra, *args, stdin=stdin)
        self.assertEqual(code, 0, data)
        return json.loads((repo.path / FACTS).read_text(encoding="utf-8"))

    def _target(self, paths, kinds, pattern=None, tid="R1"):
        return {"id": tid, "rule": {"file": "CLAUDE.md", "line": 3},
                "paths": paths, "change_kinds": kinds, "line_pattern": pattern}

    def test_rule_lifts_mechanical_to_logic(self):
        repo = self.make_repo()
        repo.write("types/api.ts", "// @generated\nexport type A = 1;\nexport type B = 2;\n")
        repo.commit("init")
        repo.checkout("feature", create=True)
        repo.write("types/api.ts", "// @generated\nexport type A = 1;\n")
        repo.commit("drop")
        base = self._facts(repo)
        self.assertEqual(base["hunks"][0]["class"], "mechanical")
        facts = self._facts(repo, [self._target(["types/**"], ["delete"])])
        h = facts["hunks"][0]
        self.assertEqual((h["class"], h["rules"], h["was_mechanical"]),
                         ("logic", ["R1"], "generated"))
        f = facts["files"][0]
        self.assertEqual((f["class"], f["mechanical_kind"]), ("logic", None))
        self.assertEqual(f["rules"], ["R1"])
        self.assertEqual(facts["targets"][0]["id"], "R1")
        self.assertEqual(facts["totals"]["logic_lines"], 1)

    def test_hunkless_rename_and_mode_lifted(self):
        repo = self.make_repo()
        repo.write("old/name.txt", "".join("line %d\n" % i for i in range(20)))
        repo.write("run.sh", "echo hi\n")
        repo.commit("init")
        repo.checkout("feature", create=True)
        repo.git("mv", "old/name.txt", "new_name.txt")
        (repo.path / "run.sh").chmod(0o755)
        repo.commit("mv and chmod")
        base = self._facts(repo)
        by = {f["path"]: f for f in base["files"]}
        self.assertEqual(by["new_name.txt"]["mechanical_kind"], "move")
        facts = self._facts(repo, [self._target([], ["rename"]),
                                   self._target([], ["mode"], tid="R2"),
                                   self._target([], ["rename"], pattern="x", tid="R3")])
        by = {f["path"]: f for f in facts["files"]}
        mv = by["new_name.txt"]
        self.assertEqual((mv["class"], mv["mechanical_kind"], mv["rules"], mv["was_mechanical"]),
                         ("logic", None, ["R1"], "move"))
        sh = by["run.sh"]
        self.assertEqual((sh["class"], sh["rules"], sh["was_mechanical"]),
                         ("logic", ["R2"], None))

    def test_lifted_replacements_are_pruned(self):
        repo = self.make_repo()
        for i in range(4):
            repo.write("f%d.ts" % i, "const a = fetchData(%d);\n" % i)
        repo.commit("init")
        repo.checkout("feature", create=True)
        for i in range(4):
            repo.write("f%d.ts" % i, "const a = loadData(%d);\n" % i)
        repo.commit("rename")
        self.assertEqual(len(self._facts(repo)["replacements"][0]["files"]), 4)
        facts = self._facts(repo, [self._target(["f0.ts"], ["modify"])])
        rep = facts["replacements"][0]
        self.assertEqual(rep["files"], ["f1.ts", "f2.ts", "f3.ts"])
        by = {h["file"]: h for h in facts["hunks"]}
        self.assertNotIn(by["f0.ts"]["id"], rep["hunk_ids"])
        self.assertEqual(len(rep["hunk_ids"]), 3)
        facts = self._facts(repo, [self._target([], ["modify"])])
        self.assertEqual(facts["replacements"], [])

    def test_non_matching_target_leaves_hunk(self):
        repo = self.make_repo()
        repo.write("src/a.ts", "a\n")
        repo.commit("init")
        repo.checkout("feature", create=True)
        repo.write("src/a.ts", "b\n")
        repo.commit("edit")
        facts = self._facts(repo, [self._target(["lib/**"], ["modify"]),
                                   self._target([], ["delete"], tid="R2")])
        self.assertEqual(facts["hunks"][0]["rules"], [])
        facts = self._facts(repo, [self._target([], ["modify"], pattern="^b$"),
                                   self._target([], ["modify"], pattern="zzz", tid="R2")])
        self.assertEqual(facts["hunks"][0]["rules"], ["R1"])

    def test_add_dependency_kind(self):
        repo = self.make_repo()
        repo.write("package.json", '{\n  "name": "x"\n}\n')
        repo.write("src/a.ts", "a\n")
        repo.commit("init")
        repo.checkout("feature", create=True)
        repo.write("package.json", '{\n  "name": "x",\n  "dependencies": {"left-pad": "1"}\n}\n')
        repo.write("src/a.ts", "b\n")
        repo.commit("dep")
        facts = self._facts(repo, [self._target([], ["add_dependency"])])
        by = {h["file"]: h for h in facts["hunks"]}
        self.assertEqual(by["package.json"]["rules"], ["R1"])
        self.assertEqual(by["src/a.ts"]["rules"], [])

    def test_add_kind_and_bad_stdin(self):
        repo = self.make_repo()
        repo.write("a.txt", "a\n")
        repo.commit("init")
        repo.checkout("feature", create=True)
        repo.write("new.txt", "n\n")
        repo.commit("add")
        facts = self._facts(repo, [self._target([], ["add"])])
        self.assertEqual(facts["hunks"][0]["rules"], ["R1"])
        code, data = run_script(repo, "facts", "--from", "main", "--targets-stdin",
                                stdin="nope")
        self.assertEqual((code, data["error"]["code"]), (2, "bad_input"))

    def test_small_diff_single_batch(self):
        repo = self.make_repo()
        repo.write("a/x.txt", "a\n")
        repo.commit("init")
        repo.checkout("feature", create=True)
        repo.write("a/x.txt", "b\n")
        repo.commit("edit")
        facts = self._facts(repo)
        self.assertEqual(facts["batches"], [{"id": 1, "paths": ["a/x.txt"], "logic_lines": 2}])
        self.assertEqual(facts["hunks"][0]["batch"], 1)


class BatchTests(unittest.TestCase):
    def test_batches_split_by_top_folder(self):
        files, hunks = _synthetic({"apps/web/a.ts": 1200, "apps/api/b.ts": 900,
                                   "packages/ui/c.ts": 300})
        batches = make_batches(files, hunks)
        self.assertEqual(len(batches), 2)
        seen = [p for b in batches for p in b["paths"]]
        self.assertEqual(sorted(seen), sorted(set(seen)))
        self.assertEqual(sum(b["logic_lines"] for b in batches), 2400)
        self.assertEqual([b["id"] for b in batches], [1, 2])
        for h in hunks:
            self.assertIn(h.batch, (1, 2))

    def test_total_small_is_one_batch(self):
        files, hunks = _synthetic({"apps/web/a.ts": 200, "apps/api/b.ts": 100,
                                   "packages/ui/c.ts": 100})
        batches = make_batches(files, hunks)
        self.assertEqual([(b["id"], b["logic_lines"]) for b in batches], [(1, 400)])

    def test_big_group_split_by_second_segment_and_indivisible_alone(self):
        files, hunks = _synthetic({"apps/web/a.ts": 1000, "apps/api/b.ts": 1000,
                                   "big.ts": 2000})
        batches = make_batches(files, hunks)
        alone = [b for b in batches if b["paths"] == ["big.ts"]]
        self.assertEqual(len(alone), 1)
        self.assertEqual(len(batches), 3)

    def test_mechanical_does_not_count_or_batch(self):
        files, hunks = _synthetic({"a/x.ts": 10})
        hunks[0].klass = "mechanical"
        batches = make_batches(files, hunks)
        self.assertEqual(batches, [])
        self.assertIsNone(hunks[0].batch)


class BundleTests(RepoTestCase):
    def test_bundle_contains_only_batch(self):
        repo = self.make_repo()
        repo.write("CLAUDE.md", "line one\nline two\nrule three\n")
        repo.write("apps/web/a.ts", "".join("a%d\n" % i for i in range(1)))
        repo.write("apps/api/b.ts", "b\n")
        repo.write("lock/yarn.lock", "x\n")
        repo.commit("init")
        repo.checkout("feature", create=True)
        repo.write("apps/web/a.ts", "".join("n%d\n" % i for i in range(1000)))
        repo.write("apps/api/b.ts", "".join("m%d\n" % i for i in range(900)))
        repo.write("lock/yarn.lock", "y\n")
        repo.commit("big")
        target = {"id": "R1", "rule": {"file": "CLAUDE.md", "line": 3},
                  "paths": ["apps/**"], "change_kinds": ["modify"], "line_pattern": None}
        code, data = run_script(repo, "facts", "--from", "main", "--targets-stdin",
                                stdin=json.dumps([target]))
        self.assertEqual(code, 0, data)
        self.assertEqual(len(data["batches"]), 2)
        code, b1 = run_script(repo, "bundle", "--batch", "1")
        code2, b2 = run_script(repo, "bundle", "--batch", "2")
        self.assertEqual((code, code2), (0, 0), (b1, b2))
        files1 = {h["file"] for h in b1["logic_hunks"]}
        files2 = {h["file"] for h in b2["logic_hunks"]}
        self.assertTrue(files1 and files2)
        self.assertFalse(files1 & files2)
        self.assertEqual(files1 | files2, {"apps/web/a.ts", "apps/api/b.ts"})
        self.assertEqual(b2["mechanical_summary"], [{"file": "lock/yarn.lock", "kind": "lockfile"}])
        self.assertEqual(b2["rules"], [{"path": "CLAUDE.md", "lines": [
            [1, "line one"], [2, "line two"], [3, "rule three"]]}])
        self.assertEqual(b2["targets"][0]["id"], "R1")
        self.assertIn("totals", b2["facts_summary"])
        self.assertIn("batches", b2["facts_summary"])

    def test_bundle_lists_lifted_hunkless_files(self):
        repo = self.make_repo()
        repo.write("old/name.txt", "".join("line %d\n" % i for i in range(20)))
        repo.commit("init")
        repo.checkout("feature", create=True)
        repo.git("mv", "old/name.txt", "new_name.txt")
        repo.commit("mv")
        target = {"id": "R1", "rule": {"file": "CLAUDE.md", "line": 1}, "paths": [],
                  "change_kinds": ["rename"], "line_pattern": None}
        code, data = run_script(repo, "facts", "--from", "main", "--targets-stdin",
                                stdin=json.dumps([target]))
        self.assertEqual(code, 0, data)
        self.assertEqual(data["batches"], [{"id": 1, "paths": ["new_name.txt"], "logic_lines": 1}])
        code, b = run_script(repo, "bundle", "--batch", "1")
        self.assertEqual(code, 0, b)
        self.assertEqual(b["logic_files"], [{
            "path": "new_name.txt", "old_path": "old/name.txt", "status": "renamed",
            "rules": ["R1"], "was_mechanical": "move", "binary": False, "too_large": False}])
        self.assertEqual(b["mechanical_summary"], [])

    def test_bundle_errors(self):
        repo = self.make_repo()
        repo.write("a", "a\n")
        repo.commit("init")
        code, data = run_script(repo, "bundle", "--batch", "1")
        self.assertEqual((code, data["error"]["code"]), (2, "bad_input"))
        self.assertIn("facts", data["error"]["message"])
        repo.checkout("feature", create=True)
        repo.write("a", "b\n")
        repo.commit("e")
        run_script(repo, "facts", "--from", "main")
        code, data = run_script(repo, "bundle", "--batch", "9")
        self.assertEqual((code, data["error"]["code"]), (2, "bad_input"))


if __name__ == "__main__":
    unittest.main()
