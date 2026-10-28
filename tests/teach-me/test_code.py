from __future__ import annotations

import io
import os
import tarfile
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401
from helpers import FixtureServer, TempHome, run_script
from teach_me_lib import dossier, frontmatter, net, store
from teach_me_lib.errors import BlockedError


def tarball(entries):
    """entries: list of (name, kind, data/target). kind: file, dir, sym, hard, fifo."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, kind, payload in entries:
            info = tarfile.TarInfo(name)
            if kind == "dir":
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tf.addfile(info)
            elif kind == "sym":
                info.type = tarfile.SYMTYPE
                info.linkname = payload
                tf.addfile(info)
            elif kind == "hard":
                info.type = tarfile.LNKTYPE
                info.linkname = payload
                tf.addfile(info)
            elif kind == "fifo":
                info.type = tarfile.FIFOTYPE
                tf.addfile(info)
            else:
                data = payload if isinstance(payload, bytes) else payload.encode("utf-8")
                info.size = len(data)
                info.mode = 0o4755  # setuid bit must never be copied
                tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def route(body):
    return (200, "application/gzip", body)


def setup(srv, version=None):
    code, out = run_script("init", srv.url("/docs"), "--lang", "en", env=srv.env())
    assert code == 0, out
    did = out["id"]
    if version is not None:
        meta, _ = dossier.load(did)
        meta["version"] = version
        dossier.save(did, meta)
    return did


def code_root(did):
    meta, _ = dossier.load(did)
    return store.dossier_dir(did) / meta["names"]["sources_dir"] / meta["names"]["code_dir"]


def fetch(srv, did, ref="v1.0.0", repo="acme/lib"):
    return run_script("fetch-code", did, "--repo", repo, "--ref", ref, env=srv.env())


BASIC = [
    ("repo-x", "dir", None),
    ("repo-x/README.md", "file", "# Hi\n"),
    ("repo-x/src", "dir", None),
    ("repo-x/src/a.py", "file", "x = 1\ny = 2"),
    ("top.txt", "file", "ignored top-level file"),
]


class ExtractTests(unittest.TestCase):
    def test_extracts_and_strips_top_dir(self):
        routes = {"/acme/lib/tar.gz/v1.0.0": route(tarball(BASIC))}
        with FixtureServer(routes) as srv, TempHome() as home:
            did = setup(srv, {"kind": "package", "value": "1.0.0", "label": "lib_1.0.0"})
            code, out = fetch(srv, did)
            self.assertEqual(code, 0, out)
            dest = code_root(did) / "lib_1.0.0"
            self.assertEqual(out["path"], str(dest))
            self.assertEqual(out["files"], 2)
            self.assertEqual((dest / "README.md").read_text(), "# Hi\n")
            self.assertTrue((dest / "src" / "a.py").is_file())
            self.assertFalse((dest / "top.txt").exists())
            self.assertFalse((dest / "repo-x").exists())
            self.assertEqual((dest / "README.md").stat().st_mode & 0o7000, 0)
            self.assertFalse((code_root(did) / "lib_1.0.0.partial").exists())
            self.assertEqual([p for p in home.path.rglob("*") if ".tmp-code" in p.name], [])
            meta, _ = dossier.load(did)
            self.assertIn("code", meta["phases"])
            self.assertTrue(meta["public_code"])

    def test_label_falls_back_to_ref(self):
        routes = {"/acme/lib/tar.gz/ai@7.0.155": route(tarball(BASIC))}
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            code, out = fetch(srv, did, ref="ai@7.0.155")
            self.assertEqual(code, 0, out)
            self.assertTrue((code_root(did) / "ai_7.0.155" / "README.md").is_file())

    def test_label_used_is_stored_for_sources_and_search(self):
        from teach_me_lib import search, sources
        routes = {"/acme/lib/tar.gz/ai@7.0.155": route(tarball(BASIC))}
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            code, out = fetch(srv, did, ref="ai@7.0.155")
            self.assertEqual(code, 0, out)
            meta, _ = dossier.load(did)
            self.assertEqual(meta["version"]["label"], "ai_7.0.155")
            claims = [{"text": "x", "kind": "fact", "sources": [
                {"kind": "code", "path": "src/a.py", "line_start": 1, "line_end": 2}]}]
            resolved, unverified = sources.check_claims(did, claims)
            self.assertEqual(unverified, [])
            self.assertIn("x = 1", resolved[0]["sources"][0]["excerpt"])
            res = search.query(did, "x = 1")
            self.assertTrue(any(r["citation"].get("kind") == "code" for r in res["results"]))

    def test_not_found_is_fetch_failed(self):
        with FixtureServer({}) as srv, TempHome():
            did = setup(srv)
            code, out = fetch(srv, did, ref="nope")
            self.assertEqual(code, 2)
            self.assertEqual(out["error"]["code"], "fetch_failed")
            self.assertIn("nope", out["error"]["message"])
            self.assertEqual(list(code_root(did).iterdir()), [])

    def test_not_a_tarball_is_fetch_failed(self):
        routes = {"/acme/lib/tar.gz/v1": route(b"definitely not gzip")}
        with FixtureServer(routes) as srv, TempHome() as home:
            did = setup(srv)
            code, out = fetch(srv, did, ref="v1")
            self.assertEqual(code, 2)
            self.assertEqual(out["error"]["code"], "fetch_failed")
            self.assertEqual([p for p in home.path.rglob("*") if ".tmp-code" in p.name], [])
            self.assertEqual(list(code_root(did).iterdir()), [])

    def test_unsafe_entries_never_written(self):
        entries = [
            ("repo-x", "dir", None),
            ("repo-x/ok.txt", "file", "fine\n"),
            ("repo-x/../../evil.txt", "file", "evil"),
            ("/abs.txt", "file", "abs"),
            ("repo-x/back\\slash.txt", "file", "x"),
            ("C:/drive.txt", "file", "x"),
            ("repo-x/l", "sym", "/etc"),
            ("repo-x/h", "hard", "repo-x/ok.txt"),
            ("repo-x/pipe", "fifo", None),
        ]
        routes = {"/acme/lib/tar.gz/v1": route(tarball(entries))}
        with tempfile.TemporaryDirectory() as parent:
            parent = Path(parent).resolve()
            home_dir = parent / "a" / "b" / "home"
            home_dir.mkdir(parents=True)
            old = os.environ.get("TEACH_ME_HOME")
            os.environ["TEACH_ME_HOME"] = str(home_dir)
            try:
                with FixtureServer(routes) as srv:
                    did = setup(srv)
                    code, out = fetch(srv, did, ref="v1")
                    self.assertEqual(code, 0, out)
                    self.assertEqual(out["files"], 1)
                    names = [p.name for p in parent.rglob("*")]
                    for bad in ("evil.txt", "abs.txt", "l", "h", "pipe", "drive.txt"):
                        self.assertNotIn(bad, names)
                    self.assertFalse(any("slash" in n for n in names))
                    self.assertFalse(os.path.lexists("/abs.txt"))
                    self.assertFalse(any(p.is_symlink() for p in parent.rglob("*")))
                    meta, _ = dossier.load(did)
                    skipped = {e["path"]: e["reason"] for e in meta["coverage"]["skipped"]}
                    self.assertEqual(skipped["repo-x/../../evil.txt"], "unsafe_path")
                    self.assertEqual(skipped["/abs.txt"], "unsafe_path")
                    self.assertEqual(skipped["repo-x/back\\slash.txt"], "unsafe_path")
                    self.assertEqual(skipped["C:/drive.txt"], "unsafe_path")
                    self.assertEqual(skipped["l"], "link")
                    self.assertEqual(skipped["h"], "link")
                    self.assertEqual(skipped["repo-x/pipe"], "unsafe_path")
                    self.assertEqual(out["skipped_by_reason"], {"unsafe_path": 5, "link": 2})
            finally:
                if old is None:
                    os.environ.pop("TEACH_ME_HOME", None)
                else:
                    os.environ["TEACH_ME_HOME"] = old

    def test_binary_large_and_ignored_dirs_skipped(self):
        entries = [
            ("r", "dir", None),
            ("r/img.png", "file", b"\x89PNG\x00\x01"),
            ("r/big.txt", "file", "a" * (1024 * 1024 + 1)),
            ("r/exact.txt", "file", "a" * (1024 * 1024)),
            ("r/node_modules", "dir", None),
            ("r/node_modules/p/i.js", "file", "x"),
            ("r/node_modules/p/j.js", "file", "x"),
            ("r/build", "dir", None),
            ("r/src/vendor/v.js", "file", "x"),
            ("r/.git/config", "file", "x"),
            ("r/dist/o.js", "file", "x"),
            ("r/late_nul.bin", "file", b"a" * 9000 + b"\x00"),
            ("r/keep.js", "file", "ok"),
        ]
        routes = {"/acme/lib/tar.gz/v1": route(tarball(entries))}
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            code, out = fetch(srv, did, ref="v1")
            self.assertEqual(code, 0, out)
            self.assertEqual(out["skipped_by_reason"],
                             {"binary": 1, "too_large": 1, "ignored_dir": 5})
            dest = Path(out["path"])
            self.assertTrue((dest / "keep.js").is_file())
            self.assertTrue((dest / "exact.txt").is_file())
            self.assertTrue((dest / "late_nul.bin").is_file())  # NUL beyond 8 KB
            for gone in ("img.png", "big.txt", "node_modules", "src/vendor", ".git", "dist"):
                self.assertFalse((dest / gone).exists(), gone)
            meta, _ = dossier.load(did)
            skipped = {e["path"]: e["reason"] for e in meta["coverage"]["skipped"]}
            self.assertEqual(skipped["img.png"], "binary")
            self.assertEqual(skipped["big.txt"], "too_large")
            self.assertEqual(skipped["node_modules"], "ignored_dir")
            self.assertEqual(skipped["src/vendor"], "ignored_dir")
            self.assertEqual(skipped["build"], "ignored_dir")
            ignored = [e for e in meta["coverage"]["skipped"] if e["reason"] == "ignored_dir"]
            self.assertEqual(len(ignored), 5)
            self.assertNotIn("node_modules/p/i.js", skipped)

    def test_inventory_counts_lines(self):
        entries = [
            ("r", "dir", None),
            ("r/b.txt", "file", "one\ntwo\nthree\n"),
            ("r/a.txt", "file", "x\ny"),
            ("r/empty.txt", "file", ""),
        ]
        routes = {"/acme/lib/tar.gz/v1": route(tarball(entries))}
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            code, out = fetch(srv, did, ref="v1")
            self.assertEqual(code, 0, out)
            head, body = frontmatter.parse((Path(out["path"]) / "_inventory.md").read_text(encoding="utf-8"))
            self.assertEqual(head["teach_me"], "index")
            self.assertEqual(head["files"], [
                {"path": "a.txt", "lines": 2}, {"path": "b.txt", "lines": 3},
                {"path": "empty.txt", "lines": 0}])
            self.assertIn("a.txt", body)

    def test_second_fetch_does_not_download(self):
        routes = {"/acme/lib/tar.gz/v1": route(tarball(BASIC))}
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            code, first = fetch(srv, did, ref="v1")
            self.assertEqual(code, 0, first)
            count = len(srv.requests)
            self.assertEqual(count, 1)
            code, second = fetch(srv, did, ref="v1")
            self.assertEqual(code, 0, second)
            self.assertEqual(len(srv.requests), count)
            self.assertEqual(second["files"], first["files"])
            self.assertEqual(second["path"], first["path"])
            self.assertEqual(second["skipped_by_reason"], first["skipped_by_reason"])

    def test_stale_partial_is_replaced(self):
        routes = {"/acme/lib/tar.gz/v1": route(tarball(BASIC))}
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            stale = code_root(did) / "v1.partial"
            stale.mkdir()
            (stale / "junk.txt").write_text("junk")
            code, out = fetch(srv, did, ref="v1")
            self.assertEqual(code, 0, out)
            self.assertFalse(stale.exists())
            self.assertFalse((Path(out["path"]) / "junk.txt").exists())


class DownloadTests(unittest.TestCase):
    def test_download_streams_and_caps(self):
        routes = {"/f": (200, "application/octet-stream", b"x" * 5000)}
        with FixtureServer(routes) as srv, tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "f.bin"
            resp = net.download(srv.url("/f"), dest, 10000)
            self.assertEqual(resp.status, 200)
            self.assertEqual(dest.read_bytes(), b"x" * 5000)
            dest2 = Path(tmp) / "g.bin"
            with self.assertRaises(BlockedError) as ctx:
                net.download(srv.url("/f"), dest2, 100)
            self.assertEqual(ctx.exception.code, "too_large")
            self.assertFalse(dest2.exists())
            resp = net.download(srv.url("/missing"), dest2, 100)
            self.assertEqual(resp.status, 404)
            self.assertFalse(dest2.exists())

    def test_download_rejects_non_http(self):
        with self.assertRaises(BlockedError) as ctx:
            net.download("file:///etc/passwd", Path("/nonexistent/x"), 10)
        self.assertEqual(ctx.exception.code, "bad_input")


if __name__ == "__main__":
    unittest.main()
