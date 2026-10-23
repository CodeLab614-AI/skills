from __future__ import annotations

import json
import unittest

from helpers import RepoTestCase, run_script

from explain_changes_lib.verify import verify


def lines(n, prefix="l"):
    return "".join("%s%d\n" % (prefix, i) for i in range(1, n + 1))


class VerifyTests(RepoTestCase):
    def setup_facts(self, targets=None):
        repo = self.make_repo()
        repo.write(".agents/rules/preserve-comments/RULE.md", "# rules\nKeep comments.\n" * 5)
        repo.write("src/a.ts", lines(60))
        repo.write("src/b.test.ts", lines(5))
        repo.write("package-lock.json", "{}\n")
        repo.commit("base")
        repo.checkout("feat", create=True)
        a = lines(60).replace("l5\n", "L5\n").replace("l30\n", "L30\n")
        repo.write("src/a.ts", a)
        repo.write("src/b.test.ts", lines(5).replace("l2\n", "X2\n"))
        repo.write("package-lock.json", '{"a":1}\n')
        repo.write("src/new.ts", "import x from 'y';\nconst a = 1;\nconst b = 2;\n")
        repo.commit("change")
        args = ["facts", "--from", "main"]
        stdin = None
        if targets:
            args.append("--targets-stdin")
            stdin = json.dumps(targets)
        code, data = run_script(repo, *args, stdin=stdin)
        self.assertEqual(code, 0, data)
        facts = json.loads((repo.path / ".explain-changes/run/facts.json").read_text())
        return repo, facts

    def point(self, files, **extra):
        return dict({"title": "T", "line": "l", "more": "m", "files": files}, **extra)

    def test_points_rest_and_automatic_groups(self):
        repo, facts = self.setup_facts()
        interp = {"points": [self.point(["src/new.ts", "ghost.ts"]),
                             self.point(["src/a.ts"], order=0)],
                  "rest": {"line": "tests", "groups": [
                      {"kind": "tests", "files": ["src/b.test.ts"]},
                      {"kind": "weird-kind", "files": ["src/a.ts"]}]}}
        out = verify(repo.path, facts, interp)
        self.assertEqual([p["id"] for p in out["points"]], ["p1", "p2"])
        self.assertEqual(out["points"][0]["files"], [{"path": "src/a.ts", "verified": True}])
        self.assertEqual(out["points"][1]["files"], [
            {"path": "src/new.ts", "verified": True}, {"path": "ghost.ts", "verified": False}])
        kinds = {g["kind"]: [f["path"] for f in g["files"]] for g in out["rest"]["groups"]}
        # a file already in a point is not repeated in "the rest"
        self.assertEqual(kinds, {"tests": ["src/b.test.ts"], "mechanical": ["package-lock.json"]})
        self.assertEqual(out["rest"]["groups"][1]["files"][0]["mechanical_kind"], "lockfile")
        self.assertEqual([u["kind"] for u in out["unverified"]], ["file"])

    def test_unplaced_logic_goes_to_unexplained_and_nothing_is_lost(self):
        repo, facts = self.setup_facts()
        out = verify(repo.path, facts, {"points": [self.point(["src/a.ts"])]})
        kinds = {g["kind"]: [f["path"] for f in g["files"]] for g in out["rest"]["groups"]}
        self.assertEqual(kinds["unexplained"], ["src/b.test.ts", "src/new.ts"])
        placed = {f["path"] for p in out["points"] for f in p["files"]}
        placed |= {f["path"] for g in out["rest"]["groups"] for f in g["files"]}
        self.assertEqual(placed, {f["path"] for f in facts["files"]})

    def test_comments_must_exist_in_the_diff(self):
        repo, facts = self.setup_facts()
        c = lambda **kw: dict({"file": "src/new.ts", "side": "new", "line": 2, "pos": "before",
                               "text": "explica"}, **kw)
        interp = {"points": [self.point(["src/new.ts"])], "comments": [
            c(),                         # valid
            c(line=2),                   # duplicate
            c(line=2, pos="after"),      # valid: same line, other position
            c(line=1),                   # an import: never commented
            c(line=99),                  # not in the diff
            c(side="old"),               # a new file has no old lines
            c(file="src/a.ts", line=5),  # file is not in a point
            c(pos="middle"),             # bad position
            c(text=" "),                 # empty text
            c(line="2"),                 # not an integer
        ]}
        out = verify(repo.path, facts, interp)
        self.assertEqual([(m["line"], m["pos"]) for m in out["comments"]],
                         [(2, "before"), (2, "after")])
        self.assertEqual(len(out["dropped"]), 8)

    def test_old_side_comment_and_rename_aliases(self):
        repo = self.make_repo()
        repo.write("old/x.ts", lines(20))
        repo.commit("base")
        repo.checkout("feat", create=True)
        (repo.path / "new").mkdir()
        repo.git("mv", "old/x.ts", "new/x.ts")
        repo.write("new/x.ts", lines(20).replace("l10\n", "L10\n"))
        repo.commit("mv+edit")
        self.assertEqual(run_script(repo, "facts", "--from", "main")[0], 0)
        facts = json.loads((repo.path / ".explain-changes/run/facts.json").read_text())
        cm = lambda f, side: {"file": f, "side": side, "line": 10, "text": "t"}
        out = verify(repo.path, facts, {"points": [self.point(["old/x.ts"])], "comments": [
            cm("old/x.ts", "old"), cm("old/x.ts", "new"),
            cm("new/x.ts", "new"), cm("new/x.ts", "old")]})
        self.assertEqual(out["points"][0]["files"], [{"path": "new/x.ts", "verified": True}])
        self.assertEqual([(m["file"], m["side"]) for m in out["comments"]],
                         [("new/x.ts", "old"), ("new/x.ts", "new")])

    def warning(self, **kw):
        base = {"says": "keep comments", "change": "A comment was removed.",
                "rule": {"file": ".agents/rules/preserve-comments/RULE.md", "line": 2},
                "changes": [{"file": "src/a.ts", "line": 5, "side": "new"}]}
        base.update(kw)
        return base

    def test_rule_warnings_and_citations(self):
        repo, facts = self.setup_facts()
        warn = self.warning(changes=[{"file": "src/a.ts", "line": 5, "side": "new"},
                                     {"file": "src/a.ts", "line": 5, "side": "old"},
                                     {"file": "src/a.ts", "line": 6, "side": "new"},
                                     {"file": "ghost.ts", "line": 1}])
        out = verify(repo.path, facts, {"points": [], "warnings": [
            warn, self.warning(rule={"file": "AGENTS.md", "line": 3}, changes=[])]})
        first, second = out["warnings"]
        self.assertEqual(first["name"], "preserve-comments")  # taken from the folder
        self.assertTrue(first["rule"]["verified"])
        self.assertEqual(first["rule"]["text"], "Keep comments.")
        self.assertEqual([c["verified"] for c in first["changes"]], [True, True, False, False])
        self.assertFalse(first["verified"])
        self.assertFalse(second["rule"]["verified"])
        self.assertEqual(second["rule"]["text"], "")
        self.assertEqual(sorted(u["kind"] for u in out["unverified"]),
                         ["change", "change", "rule"])

    def test_explicit_name_wins_and_internal_ids_are_refused(self):
        target = {"id": "R1", "rule": {"file": ".agents/rules/preserve-comments/RULE.md",
                                       "line": 2}, "paths": ["**/*.ts"], "change_kinds": []}
        repo, facts = self.setup_facts([target])
        out = verify(repo.path, facts, {"points": [], "warnings": [self.warning(name="mine")]})
        self.assertEqual(out["warnings"][0]["name"], "mine")
        for key in ("name", "says", "change"):
            with self.assertRaises(Exception) as ctx:
                verify(repo.path, facts, {"points": [], "warnings": [
                    self.warning(**{key: "see R1 here"})]})
            self.assertIn("R1", str(ctx.exception))
        ok = verify(repo.path, facts, {"points": [], "warnings": [
            self.warning(change="Renamed `R10` and CR1")]})
        self.assertEqual(len(ok["warnings"]), 1)

    def test_malformed_shapes_are_blocked_without_writing(self):
        repo, _ = self.setup_facts()
        good = {"title": "t", "files": []}
        warn = self.warning()
        cases = {
            "points": {"points": 3},
            "points[0]": {"points": ["x"]},
            "points[0].title": {"points": [{"files": []}]},
            "points[0].files": {"points": [dict(good, files="a")]},
            "points[0].table": {"points": [dict(good, table=[1])]},
            "points[0].table.rows[0]": {"points": [dict(
                good, table={"head": ["a"], "rows": [3]})]},
            "rest": {"points": [], "rest": 5},
            "rest.groups[0].kind": {"points": [], "rest": {"groups": [{"files": []}]}},
            "warnings[0].rule": {"points": [], "warnings": [dict(warn, rule="x")]},
            "warnings[0].says": {"points": [], "warnings": [{k: v for k, v in warn.items()
                                                            if k != "says"}]},
            "warnings[0].changes": {"points": [], "warnings": [dict(warn, changes=3)]},
            "comments[0]": {"points": [], "comments": [1]},
        }
        for needle, payload in cases.items():
            code, data = run_script(repo, "verify", stdin=json.dumps(payload))
            self.assertEqual(code, 2, needle)
            self.assertEqual(data["error"]["code"], "bad_input", needle)
            self.assertIn(needle, data["error"]["message"])
            self.assertFalse((repo.path / ".explain-changes/run/verified.json").exists())
        (repo.path / ".explain-changes/run/facts.json").write_text("[]")
        code, data = run_script(repo, "verify", stdin=json.dumps({"points": []}))
        self.assertEqual((code, data["error"]["code"]), (2, "bad_input"))

    def test_bad_json_is_blocked(self):
        repo, _ = self.setup_facts()
        for stdin in ("{nope", "", "[]", '{"points": 3}', "{}"):
            code, data = run_script(repo, "verify", stdin=stdin)
            self.assertEqual(code, 2, stdin)
            self.assertEqual(data["error"]["code"], "bad_input")

    def test_cli_writes_verified_json(self):
        repo, facts = self.setup_facts()
        interp = {"points": [self.point(["src/a.ts"])],
                  "comments": [{"file": "src/a.ts", "side": "new", "line": 5, "text": "x"},
                               {"file": "src/a.ts", "side": "new", "line": 50, "text": "x"}]}
        code, data = run_script(repo, "verify", stdin=json.dumps(interp))
        self.assertEqual(code, 0, data)
        self.assertEqual(data["path"], ".explain-changes/run/verified.json")
        self.assertEqual((data["unexplained_count"], data["dropped_comments"]), (2, 1))
        saved = json.loads((repo.path / data["path"]).read_text())
        self.assertEqual(len(saved["comments"]), 1)

    def test_missing_facts_is_blocked(self):
        repo = self.make_repo()
        repo.commit("x")
        code, data = run_script(repo, "verify", stdin=json.dumps({"points": []}))
        self.assertEqual(code, 2)
        self.assertEqual(data["error"]["code"], "bad_input")


if __name__ == "__main__":
    unittest.main()
