from __future__ import annotations

import json
import unittest

from helpers import RepoTestCase, run_script


def lines(n, prefix="l"):
    return "".join("%s%d\n" % (prefix, i) for i in range(1, n + 1))


class VerifyTests(RepoTestCase):
    def setup_facts(self):
        repo = self.make_repo()
        repo.write("AGENTS.md", "# rules\n" * 10)
        repo.write("src/a.ts", lines(60))
        repo.write("src/b.ts", lines(5))
        repo.commit("base")
        repo.checkout("feat", create=True)
        a = lines(60).replace("l5\n", "L5\n").replace("l30\n", "L30\n").replace("l55\n", "L55\n")
        repo.write("src/a.ts", a)
        repo.commit("change")
        code, data = run_script(repo, "facts", "--from", "main")
        self.assertEqual(code, 0, data)
        facts = json.loads((repo.path / ".explain-changes/run/facts.json").read_text())
        return repo, facts

    def interp(self, locations, rules=None):
        return {"interpreted_in": "subagent", "rules": rules or [],
                "groups": [{"id": "g1", "name": "G", "what": "w", "order": 1,
                            "locations": locations}]}

    def test_valid_and_invented_citations(self):
        repo, facts = self.setup_facts()
        self.assertEqual([r["path"] for r in facts["rule_files"]], ["AGENTS.md"])
        loc = lambda s, e, f="src/a.ts": {"file": f, "start": s, "end": e, "side": "new"}
        rule = {"rule": {"file": "AGENTS.md", "line": 99}, "status": "complies",
                "changes": [{"file": "src/a.ts", "line": 5, "side": "new"}], "note": ""}
        ok_rule = {"rule": {"file": "AGENTS.md", "line": 3}, "status": "complies",
                   "changes": [{"file": "src/a.ts", "line": 999, "side": "new"}],
                   "note": ""}
        interp = self.interp([loc(5, 5), loc(999, 999), loc(9, 4)], [rule, ok_rule])
        from explain_changes_lib.verify import verify
        out = verify(repo.path, facts, interp)
        locs = out["groups"][0]["locations"]
        self.assertEqual([l["verified"] for l in locs], [True, False, False])
        self.assertEqual(len(out["unverified"]), 4)
        self.assertEqual(sorted(u["kind"] for u in out["unverified"]),
                         ["change", "location", "location", "rule"])
        self.assertFalse(out["rules"][0]["verified"])
        self.assertTrue(out["rules"][1]["verified"])
        self.assertTrue(out["rules"][0]["changes"][0]["verified"])
        self.assertFalse(out["rules"][1]["changes"][0]["verified"])

    def test_unverified_location_covers_nothing(self):
        repo, facts = self.setup_facts()
        logic = [h for h in facts["hunks"] if h["class"] == "logic"]
        from explain_changes_lib.verify import verify
        out = verify(repo.path, facts, self.interp(
            [{"file": "src/a.ts", "start": 999, "end": 999, "side": "new"}]))
        self.assertEqual(out["groups"][0]["hunk_ids"], [])
        ung = [g for g in out["groups"] if g["id"] == "ungrouped"][0]
        self.assertEqual(ung["hunk_ids"], [h["id"] for h in logic])

    def test_sides_are_tied_to_paths(self):
        repo = self.make_repo()
        repo.write("old/x.ts", lines(20))
        repo.commit("base")
        repo.checkout("feat", create=True)
        (repo.path / "new").mkdir()
        repo.git("mv", "old/x.ts", "new/x.ts")
        repo.write("new/x.ts", lines(20).replace("l10\n", "L10\n"))
        repo.commit("mv+edit")
        code, data = run_script(repo, "facts", "--from", "main")
        self.assertEqual(code, 0, data)
        facts = json.loads((repo.path / ".explain-changes/run/facts.json").read_text())
        self.assertEqual(facts["files"][0]["old_path"], "old/x.ts")
        from explain_changes_lib.verify import verify
        loc = lambda f, side: {"file": f, "start": 10, "end": 10, "side": side}
        out = verify(repo.path, facts, self.interp([
            loc("old/x.ts", "old"), loc("old/x.ts", "new"),
            loc("new/x.ts", "new"), loc("new/x.ts", "old")]))
        self.assertEqual([l["verified"] for l in out["groups"][0]["locations"]],
                         [True, False, True, False])

    def test_malformed_shapes_are_blocked_without_writing(self):
        repo, _ = self.setup_facts()
        good = {"id": "g", "name": "n", "what": "w", "order": 1, "locations": []}
        cases = {
            "groups[0].locations": {"groups": [dict(good, locations=5)]},
            "groups[0].locations[0]": {"groups": [dict(good, locations=[3])]},
            "groups[0].id": {"groups": [{"locations": []}]},
            "groups[0]": {"groups": ["x"]},
            "rules[0]": {"groups": [], "rules": ["x"]},
            "rules[0].rule": {"groups": [], "rules": [{"rule": "x", "changes": []}]},
            "rules[0].changes": {"groups": [], "rules": [{"rule": {}, "changes": 3}]},
            "rules[0].changes[0]": {"groups": [], "rules": [{"rule": {}, "changes": [1]}]},
            "reserved": {"groups": [dict(good, id="ungrouped")]},
        }
        for needle, payload in cases.items():
            code, data = run_script(repo, "verify", stdin=json.dumps(payload))
            self.assertEqual(code, 2, needle)
            self.assertEqual(data["error"]["code"], "bad_input", needle)
            self.assertIn(needle, data["error"]["message"])
            self.assertFalse((repo.path / ".explain-changes/run/verified.json").exists())
        (repo.path / ".explain-changes/run/facts.json").write_text("[]")
        code, data = run_script(repo, "verify", stdin=json.dumps({"groups": []}))
        self.assertEqual((code, data["error"]["code"]), (2, "bad_input"))

    def test_ungrouped_logic_hunks_are_added(self):
        repo, facts = self.setup_facts()
        logic = [h for h in facts["hunks"] if h["class"] == "logic"]
        self.assertEqual(len(logic), 3)
        from explain_changes_lib.verify import verify
        locs = [{"file": "src/a.ts", "start": h["new_start"], "end": h["new_start"],
                 "side": "new"} for h in logic[:2]]
        out = verify(repo.path, facts, self.interp(locs))
        g = [x for x in out["groups"] if x["id"] == "ungrouped"]
        self.assertEqual(len(g), 1)
        self.assertEqual(g[0]["hunk_ids"], [logic[2]["id"]])
        self.assertEqual(g[0]["order"], 999)
        self.assertIsNone(g[0]["name"])
        self.assertEqual(sorted(out["groups"][0]["hunk_ids"]),
                         sorted(h["id"] for h in logic[:2]))
        # fully covered: no ungrouped group
        locs = [{"file": "src/a.ts", "start": 1, "end": 60, "side": "new"}]
        out = verify(repo.path, facts, self.interp(locs))
        self.assertFalse([x for x in out["groups"] if x["id"] == "ungrouped"])

    def test_hunkless_logic_files_and_old_side(self):
        repo = self.make_repo()
        repo.write("old/x.ts", lines(20))
        repo.write("src/b.ts", lines(5))
        repo.commit("base")
        repo.checkout("feat", create=True)
        repo.write("img/logo.bin", b"\x00\x01\x02binary")
        repo.write("src/b.ts", "l1\n")
        repo.commit("mv")
        code, data = run_script(repo, "facts", "--from", "main")
        self.assertEqual(code, 0, data)
        facts = json.loads((repo.path / ".explain-changes/run/facts.json").read_text())
        from explain_changes_lib.verify import verify
        out = verify(repo.path, facts, self.interp(
            [{"file": "src/b.ts", "start": 2, "end": 5, "side": "old"}]))
        self.assertTrue(out["groups"][0]["locations"][0]["verified"])
        ung = [g for g in out["groups"] if g["id"] == "ungrouped"]
        hunkless = [f["path"] for f in facts["files"]
                    if f["class"] == "logic" and not f["hunks"]]
        self.assertEqual(hunkless, ["img/logo.bin"])
        if hunkless:
            self.assertEqual(ung[0]["files"], hunkless)
            out2 = verify(repo.path, facts, self.interp(
                [{"file": hunkless[0], "start": 1, "end": 1, "side": "new"}]))
            ung2 = [g for g in out2["groups"] if g["id"] == "ungrouped"]
            self.assertTrue(not ung2 or hunkless[0] not in ung2[0]["files"])

    def test_bad_json_is_blocked(self):
        repo, _ = self.setup_facts()
        for stdin in ("{nope", "", "[]", '{"groups": 3}'):
            code, data = run_script(repo, "verify", stdin=stdin)
            self.assertEqual(code, 2, stdin)
            self.assertEqual(data["error"]["code"], "bad_input")

    def test_cli_writes_verified_json(self):
        repo, facts = self.setup_facts()
        h = [h for h in facts["hunks"] if h["class"] == "logic"][0]
        interp = self.interp([{"file": "src/a.ts", "start": h["new_start"],
                               "end": h["new_start"], "side": "new"}])
        code, data = run_script(repo, "verify", stdin=json.dumps(interp))
        self.assertEqual(code, 0, data)
        self.assertEqual(data["ok"], True)
        self.assertEqual(data["path"], ".explain-changes/run/verified.json")
        self.assertEqual(data["ungrouped_count"], 2)
        saved = json.loads((repo.path / data["path"]).read_text())
        self.assertIn("unverified", saved)

    def test_missing_facts_is_blocked(self):
        repo = self.make_repo()
        repo.commit("x")
        code, data = run_script(repo, "verify", stdin=json.dumps(self.interp([])))
        self.assertEqual(code, 2)
        self.assertEqual(data["error"]["code"], "bad_input")


if __name__ == "__main__":
    unittest.main()
