"""Tests for diff parsing, intraline changes and fingerprints."""
from __future__ import annotations

import os
import unittest

from helpers import RepoTestCase

from explain_changes_lib import diffparse


def by_path(changes):
    return {c.path: c for c in changes}


class DiffParseTests(RepoTestCase):
    def test_single_char_change(self):
        repo = self.make_repo()
        repo.write("a.ts", "const a = 1\n")
        base = repo.commit("base")
        repo.write("a.ts", "const a = 2\n")
        head = repo.commit("change")
        (fc,) = diffparse.diff_files(repo.path, base, head)
        self.assertEqual(len(fc.hunks), 1)
        self.assertEqual(fc.hunks[0].intraline, [
            {"line": 1, "col_start": 11, "col_end": 11, "before": "1", "after": "2"}])
        self.assertEqual(fc.hunks[0].removed, ["const a = 1"])
        self.assertEqual(fc.hunks[0].added, ["const a = 2"])
        self.assertEqual(fc.hunks[0].id, "h-" + fc.hunks[0].fingerprint[:12])
        self.assertEqual(fc.to_json()["hunks"], [fc.hunks[0].id])
        self.assertEqual(fc.to_json()["class"], "logic")

    def test_intraline_conventions(self):
        self.assertEqual(diffparse.intraline("abc", "abXc"), [(3, 3, "", "X")])
        self.assertEqual(diffparse.intraline("abXc", "abc"), [(3, 2, "X", "")])
        self.assertEqual(diffparse.intraline("x" * 2001, "y" * 2001), [])

    def test_statuses(self):
        repo = self.make_repo()
        repo.write("mod.txt", "one\ntwo\n")
        repo.write("del.txt", "gone\n")
        repo.write("same.txt", "x\ny\nz\nw\nv\nu\nt\ns\n")
        repo.write("chg.txt", "alpha\nbeta\ngamma\ndelta\nepsilon\nzeta\neta\ntheta\n")
        repo.write("mode.sh", "echo\n")
        repo.write("bin.dat", b"\x00\x01\x02old")
        repo.write("sub/f", "f\n")
        base = repo.commit("base")
        repo.write("mod.txt", "one\nTWO\n")
        os.remove(repo.path / "del.txt")
        repo.write("new.txt", "new\n")
        repo.git("mv", "same.txt", "same2.txt")
        repo.git("mv", "chg.txt", "chg2.txt")
        repo.write("chg2.txt", "alpha\nbeta\ngamma\ndelta\nepsilon\nzeta\neta\nTHETA\n")
        os.chmod(repo.path / "mode.sh", 0o755)
        repo.write("bin.dat", b"\x00\x01\x02new")
        repo.git("add", "-A")
        repo.git("update-index", "--add", "--cacheinfo", f"160000,{base},subm")
        repo.git("commit", "-q", "-m", "c2")
        head = repo.git("rev-parse", "HEAD")
        files = by_path(diffparse.diff_files(repo.path, base, head))
        self.assertEqual(files["new.txt"].status, "added")
        self.assertEqual(files["del.txt"].status, "deleted")
        self.assertEqual(files["mod.txt"].status, "modified")
        self.assertEqual(files["same2.txt"].status, "renamed")
        self.assertEqual(files["same2.txt"].similarity, 100)
        self.assertEqual(files["same2.txt"].old_path, "same.txt")
        self.assertEqual(files["same2.txt"].hunks, [])
        self.assertEqual(files["chg2.txt"].status, "renamed")
        self.assertTrue(files["chg2.txt"].hunks)
        self.assertEqual(files["mode.sh"].old_mode, "100644")
        self.assertEqual(files["mode.sh"].new_mode, "100755")
        b = files["bin.dat"]
        self.assertTrue(b.binary)
        self.assertEqual(b.hunks, [])
        self.assertTrue(b.old_blob and b.new_blob and b.old_blob != b.new_blob)
        self.assertEqual(files["subm"].status, "submodule")
        self.assertEqual(files["subm"].submodule, {"old": None, "new": base})
        # untracked
        repo.write("u/new file.txt", "l1\nl2")
        repo.write(".explain-changes/run/x.json", "{}")
        un = diffparse.untracked_files(repo.path)
        self.assertEqual([u.path for u in un], ["u/new file.txt"])
        self.assertEqual(un[0].status, "untracked")
        self.assertEqual(un[0].additions, 2)
        self.assertEqual(un[0].hunks[0].added, ["l1", "l2"])
        self.assertEqual(un[0].hunks[0].new_start, 1)

    def test_worktree_diff(self):
        repo = self.make_repo()
        repo.write("a.txt", "1\n2\n")
        base = repo.commit("base")
        repo.write("a.txt", "1\n2\n3\n")
        (fc,) = diffparse.diff_files(repo.path, base, None)
        self.assertEqual(fc.hunks[0].added, ["3"])
        self.assertEqual(fc.hunks[0].new_start, 3)
        self.assertTrue(fc.new_blob)

    def test_paths_with_spaces_unicode_and_quotes(self):
        repo = self.make_repo()
        names = ['a b/ñandú "x".ts', "line\nbreak.txt", "tab\there.txt"]
        for n in names:
            repo.write(n, "v1\n")
        base = repo.commit("base")
        for n in names:
            repo.write(n, "v2\n")
        head = repo.commit("c")
        files = by_path(diffparse.diff_files(repo.path, base, head))
        self.assertEqual(set(files), set(names))
        for n in names:
            self.assertEqual(files[n].hunks[0].added, ["v2"])
            self.assertEqual(files[n].hunks[0].file, n)
        repo.write("new\nname ü.txt", "x\n")
        self.assertEqual([u.path for u in diffparse.untracked_files(repo.path)],
                         ["new\nname ü.txt"])

    def test_crlf_and_no_newline_at_eof(self):
        repo = self.make_repo()
        repo.write("crlf.txt", "a\nb\n")
        repo.write("nonl.txt", "a\nb")
        repo.write("real.txt", "a\nb\n")
        base = repo.commit("base")
        repo.write("crlf.txt", "a\r\nb\r\n")
        repo.write("nonl.txt", "a\nb\nc\n")
        repo.write("real.txt", "a\r\nB\r\n")
        head = repo.commit("c")
        files = by_path(diffparse.diff_files(repo.path, base, head))
        self.assertTrue(files["crlf.txt"].eol_only)
        self.assertFalse(files["real.txt"].eol_only)
        self.assertFalse(files["nonl.txt"].eol_only)
        # stored text keeps the CR
        self.assertEqual(files["crlf.txt"].hunks[0].added, ["a\r", "b\r"])
        h = files["nonl.txt"].hunks[0]
        self.assertEqual(h.new_start, 2)
        self.assertEqual(h.removed, ["b"])
        self.assertEqual(h.added, ["b", "c"])
        for f in files.values():
            for hk in f.hunks:
                for line in hk.added + hk.removed:
                    self.assertNotIn("No newline", line)
        # marker on the new side only
        repo.write("nonl.txt", "a\nb\nc")
        head2 = repo.commit("d")
        (fc,) = diffparse.diff_files(repo.path, head, head2)
        self.assertEqual(fc.hunks[0].removed, ["c"])
        self.assertEqual(fc.hunks[0].added, ["c"])

    def test_non_utf8(self):
        repo = self.make_repo()
        repo.write("l.txt", "caf\xe9\n".encode("latin-1"))
        base = repo.commit("base")
        repo.write("l.txt", "caf\xe9 au lait\n".encode("latin-1"))
        head = repo.commit("c")
        (fc,) = diffparse.diff_files(repo.path, base, head)
        self.assertTrue(fc.encoding_issue)
        self.assertEqual(fc.hunks[0].removed, ["caf�"])

    def test_too_large(self):
        repo = self.make_repo()
        repo.write("big.txt", "x" * 100 + "\n")
        repo.write("many.txt", "")
        base = repo.commit("base")
        repo.write("big.txt", ("y" * 99 + "\n") * 22000)
        repo.write("many.txt", "z\n" * 20001)
        head = repo.commit("c")
        files = by_path(diffparse.diff_files(repo.path, base, head))
        self.assertTrue(files["big.txt"].too_large)
        self.assertEqual(files["big.txt"].hunks, [])
        self.assertEqual(files["big.txt"].additions, 22000)
        self.assertTrue(files["many.txt"].too_large)
        self.assertEqual(files["many.txt"].hunks, [])
        repo.write("small.txt", "a\n")
        self.assertFalse(by_path(diffparse.diff_files(repo.path, head, None)).get(
            "small.txt", diffparse.FileChange("small.txt", "added")).too_large)

    def test_fingerprint_stable(self):
        repo = self.make_repo()
        repo.write("a.txt", "x\n")
        repo.write("b.txt", "x\n")
        base = repo.commit("base")
        repo.write("a.txt", "y\n")
        c1 = repo.commit("c1")
        repo.write("b.txt", "y\n")
        c2 = repo.commit("c2")
        (a,) = diffparse.diff_files(repo.path, base, c1)
        (b,) = diffparse.diff_files(repo.path, c1, c2)
        self.assertNotEqual(a.hunks[0].fingerprint, b.hunks[0].fingerprint)
        repo.git("checkout", "-q", "-b", "other", base)
        repo.write("a.txt", "y\n")
        other = repo.commit("same change, other commit")
        self.assertNotEqual(other, c1)
        (a2,) = diffparse.diff_files(repo.path, base, other)
        self.assertEqual(a2.hunks[0].fingerprint, a.hunks[0].fingerprint)
        self.assertEqual(
            diffparse.fingerprint("a.txt", ["x"], ["y"]), a.hunks[0].fingerprint)

    def test_parse_hunks_counts_and_markers(self):
        patch = (b"diff --git a/f b/f\nindex 1..2 100644\n--- a/f\n+++ b/f\n"
                 b"@@ -3 +3,2 @@ head\n-+++ not header\n+a\n+b\n"
                 b"\\ No newline at end of file\n@@ -9,0 +10 @@\n+z\n")
        hs = diffparse.parse_hunks("f", patch)
        self.assertEqual(len(hs), 2)
        self.assertEqual((hs[0].old_start, hs[0].old_lines, hs[0].new_lines), (3, 1, 2))
        self.assertEqual(hs[0].removed, ["+++ not header"])
        self.assertEqual(hs[1].added, ["z"])


if __name__ == "__main__":
    unittest.main()
