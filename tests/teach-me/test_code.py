from __future__ import annotations

import io
import json
import os
import random
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


def set_package(did, registry, name):
    code, out = run_script("update-profile", did,
                           stdin=json.dumps({"links": {"package": {"registry": registry, "name": name}}}),
                           env=None)
    assert code == 0, out


def head_of(out):
    head, _ = frontmatter.parse((Path(out["path"]) / "_inventory.md").read_text(encoding="utf-8"))
    return head


def not_saved(meta):
    return sorted(e["path"] for e in meta["coverage"]["skipped"] if e["reason"] == "not_saved")


NPM_MONO = [
    ("m", "dir", None),
    ("m/README.md", "file", "# root\n"),
    ("m/LICENSE", "file", "MIT\n"),
    ("m/CHANGELOG.md", "file", "# log\n"),
    ("m/package.json", "file", json.dumps({"name": "mono", "private": True})),
    ("m/tsconfig.json", "file", "{}"),
    ("m/turbo.json", "file", "{}"),
    ("m/packages/ai/package.json", "file", json.dumps({"name": "ai"})),
    ("m/packages/ai/src/index.ts", "file", "export const a = 1;\n"),
    ("m/packages/ai/node_modules/x/i.js", "file", "x"),
    ("m/packages/openai/package.json", "file", json.dumps({"name": "@ai-sdk/openai"})),
    ("m/packages/openai/src/index.ts", "file", "export const o = 1;\n"),
    ("m/examples/next-openai/app/page.tsx", "file", "import { x } from '@ai-sdk/react';\n"),
    ("m/examples/ai-core/src/a.ts", "file", "import { generateText } from 'ai';\n"),
    ("m/examples/ai-core/src/b.ts", "file", "import { rsc } from \"ai/rsc\";\n"),
    ("m/examples/ai-core/src/c.ts", "file", "import { y } from '@ai-sdk/openai';\n"),
    ("m/examples/ai-core/src/d.js", "file", "const a = require('ai');\n"),
    ("m/examples/ai-core/src/e.js", "file", "const a = await import('ai/test');\n"),
    ("m/examples/ai-core/src/f.ts", "file", "import { z } from 'ai-other';\n"),
    ("m/examples/ai-core/src/g.ts", "file", "import 'ai';\n"),
    ("m/examples/ai-core/src/sub/h.ts", "file", "const t = 1;\n"),
]


def mono_setup(srv, entries=NPM_MONO, registry="npm", name="ai"):
    did = setup(srv, {"kind": "package", "value": "1.0.0", "label": "lib_1.0.0"})
    set_package(did, registry, name)
    return did


class MonorepoTests(unittest.TestCase):
    def run_mono(self, entries=NPM_MONO, registry="npm", name="ai", ref="v1"):
        routes = {"/acme/lib/tar.gz/" + ref: route(tarball(entries))}
        srv = FixtureServer(routes)
        return srv

    def test_single_package_extracts_everything(self):
        entries = [("r", "dir", None),
                   ("r/package.json", "file", json.dumps({"name": "ai"})),
                   ("r/src/a.ts", "file", "x\n"),
                   ("r/packages/other/o.ts", "file", "y\n")]
        with self.run_mono(entries) as srv, TempHome():
            did = mono_setup(srv)
            code, out = fetch(srv, did, ref="v1")
            self.assertEqual(code, 0, out)
            self.assertEqual(out["layout"], "single")
            self.assertNotIn("package_dir", out)
            self.assertNotIn("notices", out)
            self.assertEqual(out["files"], 3)
            self.assertNotIn("not_saved", out["skipped_by_reason"])
            head = head_of(out)
            self.assertEqual((head["repo"], head["ref"], head["layout"]), ("acme/lib", "v1", "single"))
            self.assertNotIn("package_dir", head)

    def test_no_links_package_extracts_everything(self):
        with self.run_mono() as srv, TempHome():
            did = setup(srv, {"kind": "package", "value": "1.0.0", "label": "lib_1.0.0"})
            code, out = fetch(srv, did, ref="v1")
            self.assertEqual(code, 0, out)
            self.assertEqual(out["layout"], "single")
            self.assertNotIn("notices", out)
            self.assertTrue((Path(out["path"]) / "tsconfig.json").is_file())
            self.assertTrue((Path(out["path"]) / "packages" / "openai" / "src" / "index.ts").is_file())

    def test_package_without_manifest_adds_notice(self):
        with self.run_mono() as srv, TempHome():
            did = mono_setup(srv, name="nope")
            code, out = fetch(srv, did, ref="v1")
            self.assertEqual(code, 0, out)
            self.assertEqual(out["layout"], "single")
            self.assertEqual(out["notices"], ["package_dir_not_found"])
            self.assertTrue((Path(out["path"]) / "tsconfig.json").is_file())

    def test_manifest_inside_examples_or_ignored_dirs_is_ignored(self):
        entries = [("r", "dir", None),
                   ("r/examples/x/package.json", "file", json.dumps({"name": "ai"})),
                   ("r/node_modules/ai/package.json", "file", json.dumps({"name": "ai"})),
                   ("r/a.txt", "file", "a")]
        with self.run_mono(entries) as srv, TempHome():
            did = mono_setup(srv)
            code, out = fetch(srv, did, ref="v1")
            self.assertEqual(code, 0, out)
            self.assertEqual(out["notices"], ["package_dir_not_found"])
            self.assertEqual(out["layout"], "single")

    def test_npm_monorepo_keeps_only_the_package(self):
        with self.run_mono() as srv, TempHome():
            did = mono_setup(srv)
            code, out = fetch(srv, did, ref="v1")
            self.assertEqual(code, 0, out)
            self.assertEqual((out["layout"], out["package_dir"]), ("monorepo", "packages/ai"))
            dest = Path(out["path"])
            for kept in ("README.md", "LICENSE", "CHANGELOG.md", "package.json",
                         "packages/ai/package.json", "packages/ai/src/index.ts",
                         "examples/ai-core/src/a.ts", "examples/ai-core/src/b.ts",
                         "examples/ai-core/src/d.js", "examples/ai-core/src/e.js",
                         "examples/ai-core/src/g.ts"):
                self.assertTrue((dest / kept).is_file(), kept)
            for gone in ("tsconfig.json", "turbo.json", "packages/openai", "examples/next-openai",
                         "examples/ai-core/src/c.ts", "examples/ai-core/src/f.ts",
                         "examples/ai-core/src/sub", "packages/ai/node_modules"):
                self.assertFalse((dest / gone).exists(), gone)
            meta, _ = dossier.load(did)
            self.assertEqual(not_saved(meta), [
                "examples/ai-core/src", "examples/ai-core/src/sub",
                "examples/next-openai", "packages/openai",
                "tsconfig.json", "turbo.json"])
            self.assertEqual(out["skipped_by_reason"], {"not_saved": 6, "ignored_dir": 1})
            ignored = [e["path"] for e in meta["coverage"]["skipped"] if e["reason"] == "ignored_dir"]
            self.assertEqual(ignored, ["packages/ai/node_modules"])
            head = head_of(out)
            self.assertEqual((head["repo"], head["ref"], head["layout"], head["package_dir"]),
                             ("acme/lib", "v1", "monorepo", "packages/ai"))
            self.assertEqual(sorted(e["path"] for e in head["skipped"]), not_saved(meta))
            self.assertTrue(all(e["reason"] == "not_saved" for e in head["skipped"]))
            self.assertEqual(head["skipped_by_reason"], out["skipped_by_reason"])
            # resume keeps the new keys
            code, again = fetch(srv, did, ref="v1")
            self.assertEqual(again["layout"], "monorepo")
            self.assertEqual(again["package_dir"], "packages/ai")
            self.assertEqual(len(srv.requests), 1)

    def test_shallowest_manifest_wins(self):
        entries = [("r", "dir", None),
                   ("r/a/b/c/package.json", "file", json.dumps({"name": "ai"})),
                   ("r/z/package.json", "file", json.dumps({"name": "ai"})),
                   ("r/a/package.json", "file", json.dumps({"name": "ai"})),
                   ("r/a/k.ts", "file", "k")]
        with self.run_mono(entries) as srv, TempHome():
            did = mono_setup(srv)
            code, out = fetch(srv, did, ref="v1")
            self.assertEqual(out["package_dir"], "a")

    def test_examples_cap_is_first_by_path_regardless_of_tar_order(self):
        names = ["m/examples/e%03d.ts" % i for i in range(305)]
        order = list(range(305))
        random.Random(7).shuffle(order)
        entries = [("m", "dir", None), ("m/packages/ai/package.json", "file", json.dumps({"name": "ai"}))]
        entries += [(names[i], "file", "import 'ai';\n") for i in order]
        with self.run_mono(entries) as srv, TempHome():
            did = mono_setup(srv)
            code, out = fetch(srv, did, ref="v1")
            self.assertEqual(code, 0, out)
            dest = Path(out["path"])
            saved = sorted(p.name for p in (dest / "examples").iterdir())
            self.assertEqual(saved, ["e%03d.ts" % i for i in range(300)])
            self.assertEqual(out["files"], 301)
            meta, _ = dossier.load(did)
            # one entry per folder: examples
            self.assertEqual(not_saved(meta), ["examples"])

    def _saved_examples(self, out):
        dest = Path(out["path"])
        return sorted(str(p.relative_to(dest)) for p in (dest / "examples").rglob("*") if p.is_file())

    def _example_entries(self, paths, order_seed):
        entries = [("m", "dir", None), ("m/packages/ai/package.json", "file", json.dumps({"name": "ai"}))]
        entries += [("m/" + p, "file", body) for p, body in paths]
        head, tail = entries[:2], entries[2:]
        random.Random(order_seed).shuffle(tail)
        return head + tail

    def _round_robin_files(self):
        groups = {"": ["examples/x%d.ts" % i for i in range(3)],
                  "a": ["examples/a/f%03d.ts" % i for i in range(200)],
                  "b": ["examples/b/sub/f%03d.ts" % i for i in range(150)],
                  "c": ["examples/c/f%d.ts" % i for i in range(2)]}
        return [(p, "import 'ai';\n") for g in groups.values() for p in g], groups

    def test_examples_spread_round_robin_across_folders(self):
        files, groups = self._round_robin_files()
        expected = []
        keys = sorted(groups)
        for depth in range(200):
            for k in keys:
                if depth < len(groups[k]):
                    expected.append(sorted(groups[k])[depth])
        expected = sorted(expected[:300])
        self.assertEqual(len(expected), 300)
        with self.run_mono(self._example_entries(files, 11)) as srv, TempHome():
            did = mono_setup(srv)
            code, out = fetch(srv, did, ref="v1")
            self.assertEqual(code, 0, out)
            saved = self._saved_examples(out)
            self.assertEqual(len(saved), 300)
            self.assertEqual(saved, expected)
            for p in groups["c"] + groups[""]:
                self.assertIn(p, saved)

    def test_examples_same_set_in_two_tar_orders(self):
        files, _ = self._round_robin_files()
        results = []
        for seed in (1, 2):
            with self.run_mono(self._example_entries(files, seed)) as srv, TempHome():
                did = mono_setup(srv)
                code, out = fetch(srv, did, ref="v1")
                self.assertEqual(code, 0, out)
                results.append(self._saved_examples(out))
        self.assertEqual(results[0], results[1])

    def test_examples_fewer_than_cap_are_all_saved(self):
        files = [("examples/a/f%d.ts" % i, "import 'ai';\n") for i in range(40)]
        files += [("examples/b/g%d.ts" % i, "import 'ai';\n") for i in range(7)]
        files += [("examples/top.ts", "import 'ai';\n")]
        with self.run_mono(self._example_entries(files, 3)) as srv, TempHome():
            did = mono_setup(srv)
            code, out = fetch(srv, did, ref="v1")
            self.assertEqual(code, 0, out)
            self.assertEqual(self._saved_examples(out), sorted(p for p, _ in files))

    def test_examples_not_importing_are_never_picked(self):
        files = [("examples/a/f%03d.ts" % i, "import 'ai';\n") for i in range(300)]
        files += [("examples/b/f%03d.ts" % i, "import 'ai';\n") for i in range(10)]
        files += [("examples/b/nope.ts", "const t = 1;\n"), ("examples/z/nope.ts", "const t = 1;\n")]
        with self.run_mono(self._example_entries(files, 5)) as srv, TempHome():
            did = mono_setup(srv)
            code, out = fetch(srv, did, ref="v1")
            self.assertEqual(code, 0, out)
            saved = self._saved_examples(out)
            self.assertEqual(len(saved), 300)
            self.assertNotIn("examples/b/nope.ts", saved)
            self.assertNotIn("examples/z/nope.ts", saved)
            self.assertEqual(sum(1 for p in saved if p.startswith("examples/b/")), 10)

    def test_pypi_monorepo(self):
        entries = [
            ("m", "dir", None),
            ("m/README.md", "file", "r"),
            ("m/pyproject.toml", "file", '[tool.x]\nname = "root"\n'),
            ("m/libs/my_lib/pyproject.toml", "file",
             '[build-system]\nrequires = []\n\n[project]\nname = "My_Lib"  # c\nversion = "1"\n'),
            ("m/libs/my_lib/my_lib/__init__.py", "file", "x = 1\n"),
            ("m/libs/other/pyproject.toml", "file", '[project]\nname = "other"\n'),
            ("m/libs/other/o.py", "file", "o = 1\n"),
            ("m/examples/a.py", "file", "from my_lib import x\n"),
            ("m/examples/b.py", "file", "import my_lib.sub\n"),
            ("m/examples/c.py", "file", "from my_lib_extra import x\n"),
            ("m/examples/d.py", "file", "import other\n"),
        ]
        with self.run_mono(entries) as srv, TempHome():
            did = mono_setup(srv, registry="pypi", name="my-lib")
            code, out = fetch(srv, did, ref="v1")
            self.assertEqual(code, 0, out)
            self.assertEqual((out["layout"], out["package_dir"]), ("monorepo", "libs/my_lib"))
            dest = Path(out["path"])
            for kept in ("README.md", "pyproject.toml", "libs/my_lib/my_lib/__init__.py",
                         "examples/a.py", "examples/b.py"):
                self.assertTrue((dest / kept).is_file(), kept)
            self.assertFalse((dest / "libs/other").exists())
            self.assertFalse((dest / "examples/c.py").exists())
            meta, _ = dossier.load(did)
            self.assertEqual(not_saved(meta), ["examples", "libs/other"])

    def test_poetry_name_matches(self):
        entries = [("m", "dir", None),
                   ("m/sub/pyproject.toml", "file", "[tool.poetry]\nname = 'a.b_c'\n"),
                   ("m/sub/x.py", "file", "x"), ("m/other.py", "file", "y")]
        with self.run_mono(entries) as srv, TempHome():
            did = mono_setup(srv, registry="pypi", name="A-B-C")
            code, out = fetch(srv, did, ref="v1")
            self.assertEqual(out["package_dir"], "sub")
            self.assertFalse((Path(out["path"]) / "other.py").exists())


class FetchPathTests(unittest.TestCase):
    def fetched(self, srv, entries=NPM_MONO):
        did = mono_setup(srv)
        code, out = fetch(srv, did, ref="v1")
        self.assertEqual(code, 0, out)
        return did, out

    def test_path_adds_folder_and_updates_inventory_and_coverage(self):
        from teach_me_lib import search
        entries = NPM_MONO + [("m/packages/openai/src/zzuniquemarker.ts", "file", "export const zzuniquemarker = 1;\n")]
        with FixtureServer({"/acme/lib/tar.gz/v1": route(tarball(entries))}) as srv, TempHome():
            did, out = self.fetched(srv, entries)
            self.assertIn("packages/openai", not_saved(dossier.load(did)[0]))
            code, res = run_script("fetch-code", did, "--path", "packages/openai", env=srv.env())
            self.assertEqual(code, 0, res)
            self.assertEqual(res["files"], 3)
            self.assertEqual(res["saved_path"], "packages/openai")
            self.assertEqual(res["path"], out["path"])
            self.assertEqual(len(srv.requests), 2)
            dest = Path(out["path"])
            self.assertTrue((dest / "packages/openai/src/index.ts").is_file())
            head = head_of(out)
            paths = [f["path"] for f in head["files"]]
            self.assertEqual(paths, sorted(paths))
            self.assertIn("packages/openai/src/index.ts", paths)
            self.assertIn("packages/ai/src/index.ts", paths)
            self.assertNotIn("packages/openai", [e["path"] for e in head["skipped"]])
            self.assertEqual(head["skipped_by_reason"]["not_saved"], 5)
            self.assertEqual(res["skipped_by_reason"], head["skipped_by_reason"])
            self.assertEqual((head["repo"], head["ref"], head["layout"], head["package_dir"]),
                             ("acme/lib", "v1", "monorepo", "packages/ai"))
            self.assertNotIn("packages/openai", not_saved(dossier.load(did)[0]))
            self.assertIn("tsconfig.json", not_saved(dossier.load(did)[0]))
            found = search.query(did, "zzuniquemarker")
            self.assertTrue(any(r["citation"].get("path") == "packages/openai/src/zzuniquemarker.ts"
                                for r in found["results"]))
            # a second call adds nothing new and leaves files alone
            code, again = run_script("fetch-code", did, "--path", "packages/openai", env=srv.env())
            self.assertEqual(code, 0, again)
            self.assertEqual(again["files"], 0)

    def test_single_file_inside_not_saved_folder_keeps_folder_entry(self):
        with FixtureServer({"/acme/lib/tar.gz/v1": route(tarball(NPM_MONO))}) as srv, TempHome():
            did, out = self.fetched(srv)
            code, res = run_script("fetch-code", did, "--path", "packages/openai/src/index.ts",
                                   env=srv.env())
            self.assertEqual(code, 0, res)
            self.assertEqual(res["files"], 1)
            dest = Path(out["path"])
            self.assertTrue((dest / "packages/openai/src/index.ts").is_file())
            self.assertFalse((dest / "packages/openai/package.json").exists())
            self.assertIn("packages/openai", not_saved(dossier.load(did)[0]))
            self.assertIn("packages/openai", [e["path"] for e in head_of(out)["skipped"]])

    def test_root_file_entry_removed(self):
        with FixtureServer({"/acme/lib/tar.gz/v1": route(tarball(NPM_MONO))}) as srv, TempHome():
            did, out = self.fetched(srv)
            code, res = run_script("fetch-code", did, "--path", "tsconfig.json", env=srv.env())
            self.assertEqual(code, 0, res)
            self.assertNotIn("tsconfig.json", not_saved(dossier.load(did)[0]))
            self.assertIn("turbo.json", not_saved(dossier.load(did)[0]))

    def test_path_not_found(self):
        with FixtureServer({"/acme/lib/tar.gz/v1": route(tarball(NPM_MONO))}) as srv, TempHome():
            did, out = self.fetched(srv)
            code, res = run_script("fetch-code", did, "--path", "packages/nothing", env=srv.env())
            self.assertEqual(code, 2)
            self.assertEqual(res["error"]["code"], "path_not_found")

    def test_bad_paths(self):
        with FixtureServer({"/acme/lib/tar.gz/v1": route(tarball(NPM_MONO))}) as srv, TempHome():
            did, out = self.fetched(srv)
            n = len(srv.requests)
            for bad in ("../x", "/etc", "a\\b", "a/../b", "", "."):
                code, res = run_script("fetch-code", did, "--path", bad, env=srv.env())
                self.assertEqual(code, 2, bad)
                self.assertEqual(res["error"]["code"], "bad_input", bad)
            self.assertEqual(len(srv.requests), n)

    def test_without_repo_ref_and_without_path_is_bad_input(self):
        with FixtureServer({}) as srv, TempHome():
            did = setup(srv)
            code, res = run_script("fetch-code", did, env=srv.env())
            self.assertEqual(code, 2)
            self.assertEqual(res["error"]["code"], "bad_input")
            code, res = run_script("fetch-code", did, "--repo", "acme/lib", env=srv.env())
            self.assertEqual(res["error"]["code"], "bad_input")

    def test_path_without_inventory_repo_ref_is_bad_input_then_accepts_flags(self):
        with FixtureServer({"/acme/lib/tar.gz/v1": route(tarball(BASIC))}) as srv, TempHome():
            did = setup(srv, {"kind": "package", "value": "1.0.0", "label": "lib_1.0.0"})
            code, res = run_script("fetch-code", did, "--path", "src", env=srv.env())
            self.assertEqual(code, 2)
            self.assertEqual(res["error"]["code"], "bad_input")
            self.assertIn("--repo", res["error"]["message"])
            # old inventory without repo/ref
            code, out = fetch(srv, did, ref="v1")
            inv = Path(out["path"]) / "_inventory.md"
            head, body = frontmatter.parse(inv.read_text(encoding="utf-8"))
            for k in ("repo", "ref", "layout"):
                head.pop(k, None)
            inv.write_text(frontmatter.dump(head, body), encoding="utf-8")
            code, res = run_script("fetch-code", did, "--path", "src", env=srv.env())
            self.assertEqual(res["error"]["code"], "bad_input")
            code, res = run_script("fetch-code", did, "--path", "src", "--repo", "acme/lib",
                                   "--ref", "v1", env=srv.env())
            self.assertEqual(code, 0, res)
            self.assertEqual(res["files"], 0)
            self.assertEqual(frontmatter.parse(inv.read_text(encoding="utf-8"))[0]["repo"], "acme/lib")

    def test_path_without_any_inventory_is_bad_input(self):
        with FixtureServer({"/acme/lib/tar.gz/v1": route(tarball(BASIC))}) as srv, TempHome():
            did = setup(srv, {"kind": "package", "value": "1.0.0", "label": "lib_1.0.0"})
            before = dossier.load(did)[0]
            code, res = run_script("fetch-code", did, "--path", "src", "--repo", "acme/lib",
                                   "--ref", "v1", env=srv.env())
            self.assertEqual(code, 2)
            self.assertEqual(res["error"]["code"], "bad_input")
            self.assertIn("fetch-code", res["error"]["message"])
            self.assertEqual(list(code_root(did).iterdir()), [])
            after = dossier.load(did)[0]
            self.assertEqual(after.get("phases"), before.get("phases"))
            self.assertEqual(len(srv.requests), 0)

    def test_safety_holds_for_path(self):
        entries = NPM_MONO + [
            ("m/packages/openai/link", "sym", "/etc"),
            ("m/packages/openai/hard", "hard", "m/packages/openai/package.json"),
            ("m/packages/openai/../../evil.txt", "file", "evil"),
            ("m/packages/openai/node_modules/n.js", "file", "x"),
            ("m/packages/openai/bin.dat", "file", b"a\x00b"),
        ]
        with FixtureServer({"/acme/lib/tar.gz/v1": route(tarball(entries))}) as srv, TempHome() as home:
            did, out = self.fetched(srv, entries)
            code, res = run_script("fetch-code", did, "--path", "packages/openai", env=srv.env())
            self.assertEqual(code, 0, res)
            dest = Path(out["path"])
            for gone in ("link", "hard", "node_modules", "bin.dat"):
                self.assertFalse((dest / "packages/openai" / gone).exists(), gone)
            self.assertFalse((dest / "evil.txt").exists())
            self.assertFalse(any(p.name == "evil.txt" for p in home.path.rglob("*")))
            self.assertFalse(any(p.is_symlink() for p in home.path.rglob("*")))
            reasons = {e["path"]: e["reason"] for e in dossier.load(did)[0]["coverage"]["skipped"]
                       if e["reason"] != "not_saved"}
            self.assertEqual(reasons["packages/openai/link"], "link")
            self.assertEqual(reasons["packages/openai/bin.dat"], "binary")
            self.assertEqual(reasons["packages/openai/node_modules"], "ignored_dir")


FULL_ENTRIES = NPM_MONO + [
    ("m/tools/zzfullonly.ts", "file", "export const zzfullonlytoken = 1;\n"),
    ("m/tools/blob.bin", "file", b"a\x00b"),
]


class FullTests(unittest.TestCase):
    def mode(self, did, mode):
        code, res = run_script("set-mode", did, mode)
        self.assertEqual(code, 0, res)

    def light(self, srv, entries=FULL_ENTRIES):
        did = mono_setup(srv)
        self.mode(did, "use")
        code, out = fetch(srv, did, ref="v1")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["layout"], "monorepo")
        return did, out

    def test_internals_mode_saves_the_whole_monorepo(self):
        with FixtureServer({"/acme/lib/tar.gz/v1": route(tarball(FULL_ENTRIES))}) as srv, TempHome():
            did = mono_setup(srv)
            self.mode(did, "overview-internals")
            code, out = fetch(srv, did, ref="v1")
            self.assertEqual(code, 0, out)
            self.assertEqual(out["layout"], "full")
            self.assertNotIn("package_dir", out)
            dest = Path(out["path"])
            self.assertTrue((dest / "packages/openai/src/index.ts").is_file())
            self.assertTrue((dest / "tools/zzfullonly.ts").is_file())
            self.assertFalse((dest / "tools/blob.bin").exists())
            head = head_of(out)
            self.assertEqual(head["layout"], "full")
            self.assertEqual(head["skipped"], [])
            self.assertEqual(not_saved(dossier.load(did)[0]), [])
            self.assertIn("binary", out["skipped_by_reason"])
            code, again = fetch(srv, did, ref="v1")
            self.assertEqual(again["layout"], "full")
            self.assertEqual(len(srv.requests), 1)

    def test_full_adds_the_rest_without_touching_saved_files(self):
        from teach_me_lib import search
        with FixtureServer({"/acme/lib/tar.gz/v1": route(tarball(FULL_ENTRIES))}) as srv, TempHome():
            did, out = self.light(srv)
            dest = Path(out["path"])
            self.assertFalse((dest / "tools").exists())
            mine = dest / "packages/ai/src/index.ts"
            mine.write_text("// edited on disk\n", encoding="utf-8")
            self.mode(did, "use-internals")
            code, res = run_script("fetch-code", did, "--full", env=srv.env())
            self.assertEqual(code, 0, res)
            self.assertEqual(res["layout"], "full")
            self.assertGreater(res["added"], 0)
            self.assertEqual(mine.read_text(encoding="utf-8"), "// edited on disk\n")
            self.assertTrue((dest / "tools/zzfullonly.ts").is_file())
            head = head_of(out)
            self.assertEqual(head["layout"], "full")
            self.assertEqual(head["skipped"], [])
            self.assertNotIn("not_saved", head["skipped_by_reason"])
            self.assertNotIn("package_dir", head)
            self.assertEqual((head["repo"], head["ref"]), ("acme/lib", "v1"))
            self.assertEqual(res["files"], len(head["files"]))
            self.assertEqual(not_saved(dossier.load(did)[0]), [])
            found = search.query(did, "zzfullonlytoken")
            self.assertTrue(any(r["citation"].get("path") == "tools/zzfullonly.ts" for r in found["results"]))
            code, again = run_script("fetch-code", did, "--full", env=srv.env())
            self.assertEqual(again, {"ok": True, "added": 0, "already": True})

    def test_full_on_single_layout_does_nothing(self):
        with FixtureServer({"/acme/lib/tar.gz/v1": route(tarball(BASIC))}) as srv, TempHome():
            did = setup(srv, {"kind": "package", "value": "1.0.0", "label": "lib_1.0.0"})
            code, out = fetch(srv, did, ref="v1")
            self.assertEqual(out["layout"], "single")
            code, res = run_script("fetch-code", did, "--full", env=srv.env())
            self.assertEqual(code, 0, res)
            self.assertEqual(res, {"ok": True, "added": 0, "already": True})
            self.assertEqual(len(srv.requests), 1)

    def test_full_without_saved_code_blocks(self):
        with FixtureServer({}) as srv, TempHome():
            did = setup(srv, {"kind": "package", "value": "1.0.0", "label": "lib_1.0.0"})
            code, res = run_script("fetch-code", did, "--full", env=srv.env())
            self.assertEqual(code, 2)
            self.assertEqual(res["error"]["code"], "bad_input")
            self.assertIn("fetch-code", res["error"]["message"])
            self.assertEqual(len(srv.requests), 0)

    def test_full_and_path_together_rejected(self):
        with FixtureServer({}) as srv, TempHome():
            did = setup(srv)
            code, res = run_script("fetch-code", did, "--full", "--path", "src", env=srv.env())
            self.assertEqual(code, 2)
            self.assertEqual(res["error"]["code"], "bad_input")


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
