"""Tests for diff parsing, intraline changes and fingerprints."""
from __future__ import annotations

import os


from explain_changes_lib import diffparse


def by_path(changes):
    return {c.path: c for c in changes}


class TestDiffParse:
    def test_single_char_change(self, make_repo):
        repo = make_repo()
        repo.write("a.ts", "const a = 1\n")
        base = repo.commit("base")
        repo.write("a.ts", "const a = 2\n")
        head = repo.commit("change")
        (fc,) = diffparse.diff_files(repo.path, base, head)
        assert len(fc.hunks) == 1
        assert fc.hunks[0].intraline == [
            {"line": 1, "col_start": 11, "col_end": 11, "before": "1", "after": "2"}]
        assert fc.hunks[0].removed == ["const a = 1"]
        assert fc.hunks[0].added == ["const a = 2"]
        assert fc.hunks[0].id == "h-" + fc.hunks[0].fingerprint[:12]
        assert fc.to_json()["hunks"] == [fc.hunks[0].id]
        assert fc.to_json()["class"] == "logic"

    def test_intraline_conventions(self):
        assert diffparse.intraline("abc", "abXc") == [(3, 3, "", "X")]
        assert diffparse.intraline("abXc", "abc") == [(3, 2, "X", "")]
        assert diffparse.intraline("x" * 2001, "y" * 2001) == []

    def test_statuses(self, make_repo):
        repo = make_repo()
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
        assert files["new.txt"].status == "added"
        assert files["del.txt"].status == "deleted"
        assert files["mod.txt"].status == "modified"
        assert files["same2.txt"].status == "renamed"
        assert files["same2.txt"].similarity == 100
        assert files["same2.txt"].old_path == "same.txt"
        assert files["same2.txt"].hunks == []
        assert files["chg2.txt"].status == "renamed"
        assert files["chg2.txt"].hunks
        assert files["mode.sh"].old_mode == "100644"
        assert files["mode.sh"].new_mode == "100755"
        b = files["bin.dat"]
        assert b.binary
        assert b.hunks == []
        assert b.old_blob and b.new_blob and b.old_blob != b.new_blob
        assert files["subm"].status == "submodule"
        assert files["subm"].submodule == {"old": None, "new": base}
        # untracked
        repo.write("u/new file.txt", "l1\nl2")
        repo.write(".explain-changes/run/x.json", "{}")
        un = diffparse.untracked_files(repo.path)
        assert [u.path for u in un] == ["u/new file.txt"]
        assert un[0].status == "untracked"
        assert un[0].additions == 2
        assert un[0].hunks[0].added == ["l1", "l2"]
        assert un[0].hunks[0].new_start == 1

    def test_worktree_diff(self, make_repo):
        repo = make_repo()
        repo.write("a.txt", "1\n2\n")
        base = repo.commit("base")
        repo.write("a.txt", "1\n2\n3\n")
        (fc,) = diffparse.diff_files(repo.path, base, None)
        assert fc.hunks[0].added == ["3"]
        assert fc.hunks[0].new_start == 3
        assert fc.new_blob

    def test_paths_with_spaces_unicode_and_quotes(self, make_repo):
        repo = make_repo()
        names = ['a b/ñandú "x".ts', "line\nbreak.txt", "tab\there.txt"]
        for n in names:
            repo.write(n, "v1\n")
        base = repo.commit("base")
        for n in names:
            repo.write(n, "v2\n")
        head = repo.commit("c")
        files = by_path(diffparse.diff_files(repo.path, base, head))
        assert set(files) == set(names)
        for n in names:
            assert files[n].hunks[0].added == ["v2"]
            assert files[n].hunks[0].file == n
        repo.write("new\nname ü.txt", "x\n")
        assert [u.path for u in diffparse.untracked_files(repo.path)] == \
                         ["new\nname ü.txt"]

    def test_crlf_and_no_newline_at_eof(self, make_repo):
        repo = make_repo()
        repo.write("crlf.txt", "a\nb\n")
        repo.write("nonl.txt", "a\nb")
        repo.write("real.txt", "a\nb\n")
        base = repo.commit("base")
        repo.write("crlf.txt", "a\r\nb\r\n")
        repo.write("nonl.txt", "a\nb\nc\n")
        repo.write("real.txt", "a\r\nB\r\n")
        head = repo.commit("c")
        files = by_path(diffparse.diff_files(repo.path, base, head))
        assert files["crlf.txt"].eol_only
        assert not files["real.txt"].eol_only
        assert not files["nonl.txt"].eol_only
        # stored text keeps the CR
        assert files["crlf.txt"].hunks[0].added == ["a\r", "b\r"]
        h = files["nonl.txt"].hunks[0]
        assert h.new_start == 2
        assert h.removed == ["b"]
        assert h.added == ["b", "c"]
        for f in files.values():
            for hk in f.hunks:
                for line in hk.added + hk.removed:
                    assert "No newline" not in line
        # marker on the new side only
        repo.write("nonl.txt", "a\nb\nc")
        head2 = repo.commit("d")
        (fc,) = diffparse.diff_files(repo.path, head, head2)
        assert fc.hunks[0].removed == ["c"]
        assert fc.hunks[0].added == ["c"]

    def test_non_utf8(self, make_repo):
        repo = make_repo()
        repo.write("l.txt", "caf\xe9\n".encode("latin-1"))
        base = repo.commit("base")
        repo.write("l.txt", "caf\xe9 au lait\n".encode("latin-1"))
        head = repo.commit("c")
        (fc,) = diffparse.diff_files(repo.path, base, head)
        assert fc.encoding_issue
        assert fc.hunks[0].removed == ["caf�"]

    def test_too_large(self, make_repo):
        repo = make_repo()
        repo.write("big.txt", "x" * 100 + "\n")
        repo.write("many.txt", "")
        base = repo.commit("base")
        repo.write("big.txt", ("y" * 99 + "\n") * 22000)
        repo.write("many.txt", "z\n" * 20001)
        head = repo.commit("c")
        files = by_path(diffparse.diff_files(repo.path, base, head))
        assert files["big.txt"].too_large
        assert files["big.txt"].hunks == []
        assert files["big.txt"].additions == 22000
        assert files["many.txt"].too_large
        assert files["many.txt"].hunks == []
        repo.write("small.txt", "a\n")
        repo.write("small.txt", "a\nb\n")
        repo.git("add", "small.txt")
        files = by_path(diffparse.diff_files(repo.path, head, None))
        assert "small.txt" in files
        assert not files["small.txt"].too_large
        assert files["small.txt"].hunks

    def test_blob_over_2mb_with_few_lines_is_too_large(self, make_repo):
        repo = make_repo()
        repo.write("long.txt", "x\n")
        base = repo.commit("base")
        repo.write("long.txt", "y" * (2 * 1024 * 1024 + 10) + "\n")
        head = repo.commit("c")
        (fc,) = diffparse.diff_files(repo.path, base, head)
        assert fc.additions == 1
        assert fc.too_large
        assert fc.hunks == []

    def test_untracked_over_2mb_not_read(self, make_repo):
        repo = make_repo()
        repo.write("seed.txt", "s\n")
        repo.commit("base")
        repo.write("huge.txt", "z" * (2 * 1024 * 1024 + 1))
        repo.write("hugebin.dat", b"\0" + b"z" * (2 * 1024 * 1024 + 1))
        files = by_path(diffparse.untracked_files(repo.path))
        assert files["huge.txt"].too_large
        assert files["huge.txt"].hunks == []
        assert not files["huge.txt"].binary
        assert files["hugebin.dat"].too_large
        assert files["hugebin.dat"].binary

    def test_duplicate_changes_get_unique_ids(self, make_repo):
        repo = make_repo()
        body = "foo\nkeep1\nkeep2\nfoo\nkeep3\nkeep4\nfoo\n"
        repo.write("d.txt", body)
        base = repo.commit("base")
        repo.write("d.txt", body.replace("foo", "bar"))
        head = repo.commit("c")
        (fc,) = diffparse.diff_files(repo.path, base, head)
        assert len(fc.hunks) == 3
        ids = [h.id for h in fc.hunks]
        assert len(set(ids)) == 3
        assert len({h.fingerprint for h in fc.hunks}) == 1
        base_id = "h-" + fc.hunks[0].fingerprint[:12]
        assert ids == [base_id, base_id + "-2", base_id + "-3"]
        assert fc.to_json()["hunks"] == ids

    def test_fingerprint_stable(self, make_repo):
        repo = make_repo()
        repo.write("a.txt", "x\n")
        repo.write("b.txt", "x\n")
        base = repo.commit("base")
        repo.write("a.txt", "y\n")
        c1 = repo.commit("c1")
        repo.write("b.txt", "y\n")
        c2 = repo.commit("c2")
        (a,) = diffparse.diff_files(repo.path, base, c1)
        (b,) = diffparse.diff_files(repo.path, c1, c2)
        assert a.hunks[0].fingerprint != b.hunks[0].fingerprint
        repo.git("checkout", "-q", "-b", "other", base)
        repo.write("a.txt", "y\n")
        other = repo.commit("same change, other commit")
        assert other != c1
        (a2,) = diffparse.diff_files(repo.path, base, other)
        assert a2.hunks[0].fingerprint == a.hunks[0].fingerprint
        from explain_changes_lib.model import hunk_fingerprint
        assert hunk_fingerprint("a.txt", ["x"], ["y"]) == a.hunks[0].fingerprint

    def test_parse_hunks_counts_and_markers(self):
        patch = (b"diff --git a/f b/f\nindex 1..2 100644\n--- a/f\n+++ b/f\n"
                 b"@@ -3 +3,2 @@ head\n-+++ not header\n+a\n+b\n"
                 b"\\ No newline at end of file\n@@ -9,0 +10 @@\n+z\n")
        hs = diffparse.parse_hunks("f", patch)
        assert len(hs) == 2
        assert (hs[0].old_start, hs[0].old_lines, hs[0].new_lines) == (3, 1, 2)
        assert hs[0].removed == ["+++ not header"]
        assert hs[1].added == ["z"]

