from __future__ import annotations

import json
import unittest

import helpers  # noqa: F401
from helpers import FixtureServer, TempHome, run_script
from teach_me_lib import dossier, frontmatter, store


def js(obj):
    return (200, "application/json", json.dumps(obj).encode())


def npm_doc(version):
    return js({"name": "ai", "version": version, "license": "MIT"})


def gh(sha="aaa", tags=()):
    routes = {"/repos/vercel/ai": js({"full_name": "vercel/ai", "default_branch": "main"}),
              "/repos/vercel/ai/commits/main": js({"sha": sha})}
    for t in tags:
        routes["/repos/vercel/ai/git/ref/tags/" + t] = js({"ref": t})
    return routes


def prepare(srv, version, links):
    code, out = run_script("init", "https://github.com/vercel/ai", "--lang", "en", env=srv.env())
    assert code == 0, out
    did = out["id"]
    meta, _ = dossier.load(did)
    meta["version"] = version
    meta["links"] = links
    dossier.save(did, meta)
    return did


def pkg_version(value="1.0.0"):
    return {"kind": "package", "value": value, "tag": None, "sha": "aaa", "label": value,
            "docs_fingerprint": None, "other_packages": {"other": "3.0.0"}}


PKG_LINKS = {"package": {"registry": "npm", "name": "ai"}, "repo": "https://github.com/vercel/ai"}


class UpdateTests(unittest.TestCase):
    def test_package_unchanged(self):
        with FixtureServer(dict(gh(), **{"/ai/latest": npm_doc("1.0.0")})) as srv, TempHome():
            did = prepare(srv, pkg_version(), PKG_LINKS)
            code, out = run_script("check-update", did, env=srv.env())
            self.assertEqual(code, 0, out)
            self.assertEqual(out, {"ok": True, "changed": False, "kind": "package",
                                   "from": "1.0.0", "to": "1.0.0", "new_tag": None})

    def test_package_new_version_with_tag(self):
        routes = dict(gh(tags=["ai@2.0.0"]), **{"/ai/latest": npm_doc("2.0.0")})
        with FixtureServer(routes) as srv, TempHome():
            did = prepare(srv, pkg_version(), PKG_LINKS)
            before = dossier.load(did)[0]
            code, out = run_script("check-update", did, env=srv.env())
            self.assertEqual(code, 0, out)
            self.assertEqual((out["changed"], out["from"], out["to"], out["new_tag"]),
                             (True, "1.0.0", "2.0.0", "ai@2.0.0"))
            self.assertEqual(dossier.load(did)[0], before)

    def test_monorepo_other_packages_ignored(self):
        # "other" is stored at 3.0.0 and must never be queried; only "ai" is.
        with FixtureServer(dict(gh(), **{"/ai/latest": npm_doc("1.0.0")})) as srv, TempHome():
            did = prepare(srv, pkg_version(), PKG_LINKS)
            code, out = run_script("check-update", did, env=srv.env())
            self.assertEqual((code, out["changed"]), (0, False))
            self.assertNotIn("/other", [r["path"] for r in srv.requests])

    def test_no_version_is_bad_input(self):
        with FixtureServer({}) as srv, TempHome():
            did = prepare(srv, {}, {})
            code, out = run_script("check-update", did, env=srv.env())
            self.assertEqual((code, out["error"]["code"]), (2, "bad_input"))
            self.assertIn("fetch-meta", out["error"]["message"])

    def test_rate_limit_propagates(self):
        routes = {"/repos/vercel/ai": (403, "text/plain", b"limit")}
        with FixtureServer(routes) as srv, TempHome():
            did = prepare(srv, {"kind": "snapshot", "value": "aaa", "sha": "aaa",
                                "docs_fingerprint": None}, {"repo": "https://github.com/vercel/ai"})
            code, out = run_script("check-update", did, env=srv.env())
            self.assertEqual((code, out["error"]["code"]), (2, "github_rate_limited"))

    def test_snapshot_docs_fingerprint_changed(self):
        llms = [b"# Docs\n- [Intro](/docs/intro.md)\n"]
        routes = dict(gh("aaa"), **{
            "/docs/llms.txt": lambda p: (200, "text/plain", llms[0]),
            "/docs/intro.md": (200, "text/markdown", b"# Hi\n"),
        })
        with FixtureServer(routes) as srv, TempHome():
            links = {"repo": "https://github.com/vercel/ai", "docs": srv.url("/docs")}
            did = prepare(srv, {"kind": "snapshot", "value": "aaa", "tag": None, "sha": "aaa",
                                "label": "aaa", "docs_fingerprint": None, "other_packages": {}}, links)
            code, out = run_script("discover-docs", did, srv.url("/docs"), env=srv.env())
            self.assertEqual(code, 0, out)
            meta, _ = dossier.load(did)
            pages = (store.dossier_dir(did) / meta["names"]["sources_dir"] /
                     meta["names"]["docs_dir"] / "_pages.md")
            raw_before = pages.read_bytes()
            code, out = run_script("check-update", did, env=srv.env())
            self.assertEqual(code, 0, out)
            self.assertFalse(out["changed"])
            llms[0] = b"# Docs\n- [Intro](/docs/intro.md)\n- [New](/docs/new.md)\n"
            code, out = run_script("check-update", did, env=srv.env())
            self.assertEqual(code, 0, out)
            self.assertEqual((out["changed"], out["code_changed"], out["docs_changed"], out["kind"]),
                             (True, False, True, "snapshot"))
            self.assertEqual((out["from"], out["to"], out["new_tag"]), ("aaa", "aaa", None))
            self.assertEqual(pages.read_bytes(), raw_before)

    def test_snapshot_code_changed(self):
        with FixtureServer(gh("bbb")) as srv, TempHome():
            did = prepare(srv, {"kind": "snapshot", "value": "aaa", "sha": "aaa",
                                "docs_fingerprint": None}, {"repo": "https://github.com/vercel/ai"})
            code, out = run_script("check-update", did, env=srv.env())
            self.assertEqual((code, out["changed"], out["code_changed"], out["docs_changed"],
                              out["from"], out["to"]), (0, True, True, False, "aaa", "bbb"))
