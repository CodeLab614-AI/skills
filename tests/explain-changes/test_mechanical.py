"""Tests for the deterministic mechanical classification."""
from __future__ import annotations

import json
import unittest

from helpers import RepoTestCase, run_script
from explain_changes_lib import mechanical
from explain_changes_lib.model import Hunk

FACTS = ".explain-changes/run/facts.json"


def _facts(repo, *args):
    code, data = run_script(repo, "facts", *args)
    assert code == 0, data
    return json.loads((repo.path / FACTS).read_text(encoding="utf-8"))


def _file(facts, path):
    return next(f for f in facts["files"] if f["path"] == path)


class MechanicalTests(RepoTestCase):
    def _base(self, files):
        repo = self.make_repo("main")
        for p, t in files.items():
            repo.write(p, t)
        repo.commit("init")
        repo.checkout("feature", create=True)
        return repo

    def test_lockfile(self):
        repo = self._base({"package-lock.json": "{}\n", "a.ts": "1\n"})
        repo.write("package-lock.json", '{"a":1}\n')
        facts = _facts(repo, "--from", "main", "--include-uncommitted")
        f = _file(facts, "package-lock.json")
        self.assertEqual((f["class"], f["mechanical_kind"]), ("mechanical", "lockfile"))
        self.assertTrue(all(h["class"] == "mechanical" for h in facts["hunks"]))
        self.assertGreater(facts["totals"]["mechanical_lines"], 0)
        self.assertEqual(facts["totals"]["logic_lines"], 0)

    def test_generated_by_attr_header_and_path(self):
        repo = self._base({
            ".gitattributes": "gen.txt linguist-generated\n",
            "gen.txt": "x\n", "hdr.py": "# @generated\nx = 1\n",
            "dist/app.js": "a\n", "m.min.js": "a\n", "plain.py": "a\n",
        })
        repo.write("gen.txt", "y\n")
        repo.write("hdr.py", "# @generated\nx = 2\n")
        repo.write("dist/app.js", "b\n")
        repo.write("m.min.js", "b\n")
        repo.write("plain.py", "b\n")
        repo.commit("change")
        facts = _facts(repo, "--from", "main")
        for p in ("gen.txt", "hdr.py", "dist/app.js", "m.min.js"):
            f = _file(facts, p)
            self.assertEqual((f["class"], f["mechanical_kind"]), ("mechanical", "generated"), p)
        self.assertEqual(_file(facts, "plain.py")["class"], "logic")

    def test_whitespace_only(self):
        repo = self._base({"a.ts": "if (x) {\n    y();\n}\n"})
        repo.write("a.ts", "if (x) {\n        y();\n}\n")
        repo.commit("indent")
        f = _file(_facts(repo, "--from", "main"), "a.ts")
        self.assertEqual((f["class"], f["mechanical_kind"]), ("mechanical", "whitespace"))

    def test_python_reindent_is_logic(self):
        repo = self._base({"a.py": "if x:\n    y()\n"})
        repo.write("a.py", "if x:\n        y()\n")
        repo.commit("indent")
        self.assertEqual(_file(_facts(repo, "--from", "main"), "a.py")["class"], "logic")

    def test_python_intraline_spacing_is_mechanical(self):
        repo = self._base({"a.py": "x=1\n"})
        repo.write("a.py", "x = 1\n")
        repo.commit("space")
        f = _file(_facts(repo, "--from", "main"), "a.py")
        self.assertEqual((f["class"], f["mechanical_kind"]), ("mechanical", "whitespace"))

    def test_line_join_is_logic(self):
        repo = self._base({"a.ts": "// disabled\nrun()\n"})
        repo.write("a.ts", "// disabledrun()\n")
        repo.commit("join")
        self.assertEqual(_file(_facts(repo, "--from", "main"), "a.ts")["class"], "logic")

    def test_blank_line_change_is_mechanical(self):
        repo = self._base({"a.ts": "a()\nb()\n"})
        repo.write("a.ts", "a()\n\nb()\n")
        repo.commit("blank")
        self.assertEqual(_file(_facts(repo, "--from", "main"), "a.ts")["class"], "mechanical")

    def test_build_out_generated_dirs_are_logic_dist_is_generated(self):
        repo = self._base({"src/build/compile.ts": "a\n", "lib/generated/handwritten.py": "a\n",
                           "packages/ui/dist/index.js": "a\n"})
        for p in ("src/build/compile.ts", "lib/generated/handwritten.py", "packages/ui/dist/index.js"):
            repo.write(p, "b\n")
        repo.commit("edit")
        facts = _facts(repo, "--from", "main")
        self.assertEqual(_file(facts, "src/build/compile.ts")["class"], "logic")
        self.assertEqual(_file(facts, "lib/generated/handwritten.py")["class"], "logic")
        self.assertEqual(_file(facts, "packages/ui/dist/index.js")["mechanical_kind"], "generated")

    def test_move_with_mode_change_is_logic(self):
        repo = self._base({"old.sh": "a\nb\nc\nd\n"})
        repo.git("mv", "old.sh", "new.sh")
        (repo.path / "new.sh").chmod(0o755)
        repo.commit("move+chmod")
        f = _file(_facts(repo, "--from", "main"), "new.sh")
        self.assertEqual(f["status"], "renamed")
        self.assertEqual(f["class"], "logic")

    def test_eol_only_without_hunks_stays_logic(self):
        repo = self._base({"a.ts": "a\nb\n"})
        repo.write("a.ts", "a\r\nb\r\n")
        repo.commit("crlf")
        f = _file(_facts(repo, "--from", "main"), "a.ts")
        self.assertTrue(f["eol_only"])
        self.assertEqual(f["class"], "logic")

    def test_whitespace_plus_char_is_logic(self):
        repo = self._base({"a.py": "if x:\n    y()\n"})
        repo.write("a.py", "if x:\n        z()\n")
        repo.commit("indent+edit")
        facts = _facts(repo, "--from", "main")
        self.assertEqual(_file(facts, "a.py")["class"], "logic")
        self.assertEqual(facts["hunks"][0]["class"], "logic")

    def test_pure_move(self):
        repo = self._base({"old.py": "a\nb\nc\nd\n"})
        repo.git("mv", "old.py", "new.py")
        repo.commit("move")
        f = _file(_facts(repo, "--from", "main"), "new.py")
        self.assertEqual((f["class"], f["mechanical_kind"]), ("mechanical", "move"))

    def test_rename_with_edit_is_logic(self):
        repo = self._base({"old.py": "a\nb\nc\nd\ne\nf\n"})
        repo.git("mv", "old.py", "new.py")
        repo.write("new.py", "a\nb\nc\nd\ne\nF!\n")
        repo.commit("move+edit")
        f = _file(_facts(repo, "--from", "main"), "new.py")
        self.assertEqual(f["class"], "logic")

    def test_binary_stays_logic(self):
        repo = self._base({"img.bin": b"\0\1\2"})
        repo.write("img.bin", b"\0\1\3")
        repo.commit("bin")
        self.assertEqual(_file(_facts(repo, "--from", "main"), "img.bin")["class"], "logic")

    def test_unit_helpers(self):
        self.assertTrue(mechanical.is_lockfile("sub/dir/Cargo.lock"))
        self.assertFalse(mechanical.is_lockfile("Cargo.toml"))
        mk = lambda r, a: Hunk("f", 1, len(r), 1, len(a), r, a)
        self.assertTrue(mechanical.is_whitespace_only(mk(["a  b"], ["a b"])))
        self.assertFalse(mechanical.is_whitespace_only(mk(["a"], ["b"])))
        self.assertFalse(mechanical.is_whitespace_only(mk([], [])))


if __name__ == "__main__":
    unittest.main()
