"""Tests for repeated-replacement detection."""
from __future__ import annotations

import json
import unittest

from helpers import RepoTestCase, run_script
from explain_changes_lib.model import Hunk
from explain_changes_lib.replacements import find_repeated_replacements

FACTS = ".explain-changes/run/facts.json"


def _facts(repo, *args):
    code, data = run_script(repo, "facts", *args)
    assert code == 0, data
    return json.loads((repo.path / FACTS).read_text(encoding="utf-8"))


def _hunk(file, removed, added):
    return Hunk(file=file, old_start=1, old_lines=len(removed), new_start=1,
                new_lines=len(added), removed=removed, added=added)


class ReplacementTests(RepoTestCase):
    def _base(self, files):
        repo = self.make_repo("main")
        for p, t in files.items():
            repo.write(p, t)
        repo.commit("init")
        repo.checkout("feature", create=True)
        return repo

    def test_rename_identifier_in_four_files_with_one_exception(self):
        files = {"f%d.ts" % i: "const a = fetchData(%d);\n" % i for i in range(4)}
        files["f4.ts"] = "const a = fetchData(4);\nconst b = 1;\n"
        repo = self._base(files)
        for i in range(4):
            repo.write("f%d.ts" % i, "const a = loadData(%d);\n" % i)
        repo.write("f4.ts", "const a = loadData(4);\nconst b = 2;\n")
        repo.commit("rename")
        facts = _facts(repo, "--from", "main")
        self.assertEqual(len(facts["replacements"]), 1)
        rep = facts["replacements"][0]
        self.assertEqual((rep["old"], rep["new"]), ("fetchData", "loadData"))
        self.assertEqual(rep["files"], ["f0.ts", "f1.ts", "f2.ts", "f3.ts"])
        by_file = {h["file"]: h for h in facts["hunks"]}
        for i in range(4):
            h = by_file["f%d.ts" % i]
            self.assertEqual((h["class"], h["mechanical_kind"]),
                             ("mechanical", "repeated_replacement"))
            self.assertIn(h["id"], rep["hunk_ids"])
        self.assertEqual(by_file["f4.ts"]["class"], "logic")
        self.assertEqual(rep["exceptions"],
                         [{"file": "f4.ts", "hunk_ids": [by_file["f4.ts"]["id"]]}])
        f0 = next(f for f in facts["files"] if f["path"] == "f0.ts")
        self.assertEqual((f0["class"], f0["mechanical_kind"]),
                         ("mechanical", "repeated_replacement"))
        f4 = next(f for f in facts["files"] if f["path"] == "f4.ts")
        self.assertEqual(f4["class"], "logic")

    def test_two_files_not_enough(self):
        repo = self._base({"a.ts": "fetchData();\n", "b.ts": "fetchData();\n"})
        repo.write("a.ts", "loadData();\n")
        repo.write("b.ts", "loadData();\n")
        repo.commit("rename")
        facts = _facts(repo, "--from", "main")
        self.assertEqual(facts["replacements"], [])
        self.assertTrue(all(h["class"] == "logic" for h in facts["hunks"]))

    def test_partial_token_not_matched(self):
        files = {"f%d.ts" % i: "x = data;\n" for i in range(3)}
        files["m.ts"] = "metadata = data;\n"
        repo = self._base(files)
        for i in range(3):
            repo.write("f%d.ts" % i, "x = info;\n")
        repo.write("m.ts", "metadata = info;\n")
        repo.commit("rename")
        facts = _facts(repo, "--from", "main")
        rep = facts["replacements"][0]
        self.assertEqual(rep["files"], ["f0.ts", "f1.ts", "f2.ts"])
        m = next(h for h in facts["hunks"] if h["file"] == "m.ts")
        self.assertEqual(m["class"], "logic")
        self.assertEqual([e["file"] for e in rep["exceptions"]], ["m.ts"])

    def test_partial_token_everywhere_is_nothing(self):
        files = {"f%d.ts" % i: "metadata = data;\n" for i in range(3)}
        repo = self._base(files)
        for i in range(3):
            repo.write("f%d.ts" % i, "metadata = info;\n")
        repo.commit("rename")
        facts = _facts(repo, "--from", "main")
        self.assertEqual(facts["replacements"], [])
        self.assertTrue(all(h["class"] == "logic" for h in facts["hunks"]))


class UnitTests(unittest.TestCase):
    def _three(self, old, new):
        return [_hunk("f%d" % i, [old], [new]) for i in range(3)]

    def test_unequal_counts_never_pure(self):
        hs = [_hunk("f%d" % i, ["a(x)", "b"], ["c(x)"]) for i in range(3)]
        self.assertEqual(find_repeated_replacements(hs), [])
        self.assertTrue(all(h.klass == "logic" for h in hs))

    def test_two_different_tokens_in_hunk_not_pure(self):
        hs = self._three("foo(bar)", "baz(qux)")
        self.assertEqual(find_repeated_replacements(hs), [])

    def test_multi_line_hunk_pure(self):
        hs = [_hunk("f%d" % i, ["foo(1)", "x = foo"], ["bar(1)", "x = bar"])
              for i in range(3)]
        reps = find_repeated_replacements(hs)
        self.assertEqual([(r["old"], r["new"]) for r in reps], [("foo", "bar")])
        self.assertTrue(all(h.mechanical_kind == "repeated_replacement" for h in hs))

    def test_only_logic_hunks_considered(self):
        hs = self._three("foo()", "bar()")
        hs[0].klass, hs[0].mechanical_kind = "mechanical", "whitespace"
        self.assertEqual(find_repeated_replacements(hs), [])
        self.assertEqual(hs[0].mechanical_kind, "whitespace")

    def test_numbers_and_literals_never_qualify(self):
        for old, new in (("30", "60"), ("true", "false"), ("null", "x"),
                         ("None", "y"), ("a1", "30")):
            hs = self._three("t = %s;" % old, "t = %s;" % new)
            self.assertEqual(find_repeated_replacements(hs), [], (old, new))
            self.assertTrue(all(h.klass == "logic" for h in hs))

    def test_identifier_rename_still_qualifies(self):
        hs = self._three("old_name(1);", "$newName(1);")
        self.assertEqual(len(find_repeated_replacements(hs)), 1)

    def test_exceptions_exclude_hunks_marked_by_other_pairs(self):
        hs = ([_hunk("a%d" % i, ["foo(x)"], ["baz(x)"]) for i in range(3)]
              + [_hunk("b%d" % i, ["x();"], ["baz();"]) for i in range(3)])
        reps = find_repeated_replacements(hs)
        self.assertEqual([(r["old"], r["new"]) for r in reps],
                         [("foo", "baz"), ("x", "baz")])
        self.assertEqual([r["exceptions"] for r in reps], [[], []])

    def test_deterministic_order(self):
        hs = (self._three("zeta()", "eta()")
              + [_hunk("g%d" % i, ["alpha()"], ["beta()"]) for i in range(3)])
        reps = find_repeated_replacements(hs)
        self.assertEqual([r["old"] for r in reps], ["alpha", "zeta"])
        self.assertEqual(reps[0]["files"], ["g0", "g1", "g2"])


if __name__ == "__main__":
    unittest.main()
