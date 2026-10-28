from __future__ import annotations

import json
import unittest

import helpers  # noqa: F401
from helpers import FixtureServer, TempHome, run_script
from teach_me_lib import dossier, frontmatter


def js(obj):
    return (200, "application/json", json.dumps(obj).encode())


def npm_doc(version="7.0.155", lic="Apache-2.0"):
    return js({"dist-tags": {"latest": version}, "versions": {version: {"license": lic}}})


def gh_routes(spdx="Apache-2.0", tags=()):
    routes = {
        "/repos/vercel/ai": js({"full_name": "vercel/ai", "default_branch": "main", "size": 42,
                                "license": {"spdx_id": spdx}, "pushed_at": "2026-10-01T00:00:00Z"}),
        "/repos/vercel/ai/commits/main": js({"sha": "deadbeef"}),
    }
    for t in tags:
        routes["/repos/vercel/ai/git/ref/tags/" + t] = js({"ref": "refs/tags/" + t})
    return routes


def setup(srv):
    run_script("init", "https://github.com/vercel/ai", "--lang", "en", env=srv.env())


def fetch(srv, *extra):
    return run_script("fetch-meta", "ai", "--npm", "ai", "--repo", "vercel/ai", *extra, env=srv.env())


class MetaTests(unittest.TestCase):
    def test_npm_and_github_license_match(self):
        routes = dict(gh_routes(tags=["ai@7.0.155"]), **{"/ai": npm_doc()})
        with FixtureServer(routes) as srv, TempHome():
            setup(srv)
            code, out = fetch(srv)
            self.assertEqual(code, 0, out)
            self.assertEqual(out["package"]["latest"], "7.0.155")
            self.assertTrue(out["license"]["match"])
            self.assertEqual(out["tag"], "ai@7.0.155")
            self.assertEqual(out["repo"]["head_sha"], "deadbeef")
            meta, _ = dossier.load("ai")
            self.assertEqual(meta["version"]["label"], "ai_7.0.155")
            self.assertEqual(meta["version"]["kind"], "package")
            self.assertIn("meta", meta["phases"])

    def test_scoped_npm_name_is_url_encoded(self):
        routes = {"/@s%2Fp": npm_doc("1.0.0", {"type": "MIT"})}
        with FixtureServer(routes) as srv, TempHome():
            setup(srv)
            code, out = run_script("fetch-meta", "ai", "--npm", "@s/p", env=srv.env())
            self.assertEqual(code, 0, out)
            self.assertEqual(out["package"]["license"], "MIT")
            self.assertIsNone(out["license"]["match"])
            meta, _ = dossier.load("ai")
            self.assertEqual(meta["version"]["label"], "1.0.0")

    def test_pypi_and_snapshot(self):
        routes = dict(gh_routes(), **{"/pk/json": js({"info": {"version": "2.1", "license_expression": "MIT"}})})
        with FixtureServer(routes) as srv, TempHome():
            setup(srv)
            code, out = run_script("fetch-meta", "ai", "--pypi", "pk", env=srv.env())
            self.assertEqual((code, out["package"]["license"]), (0, "MIT"))
            code, out = run_script("fetch-meta", "ai", "--repo", "vercel/ai", env=srv.env())
            self.assertEqual(code, 0, out)
            meta, _ = dossier.load("ai")
            self.assertEqual(meta["version"]["kind"], "snapshot")
            self.assertEqual(meta["version"]["value"], "deadbeef")

    def test_license_mismatch_is_reported(self):
        routes = dict(gh_routes(spdx="NOASSERTION"), **{"/ai": npm_doc()})
        with FixtureServer(routes) as srv, TempHome():
            setup(srv)
            code, out = fetch(srv)
            self.assertEqual(code, 0, out)
            self.assertIs(out["license"]["match"], False)
            self.assertIn("license_mismatch", out["notices"])

    def test_find_tag_monorepo(self):
        from teach_me_lib import meta
        import os
        from unittest import mock
        with FixtureServer(gh_routes(tags=["ai@7.0.155"])) as srv:
            with mock.patch.dict(os.environ, srv.env()):
                self.assertEqual(meta.find_tag("vercel/ai", "ai", "7.0.155"), "ai@7.0.155")
                self.assertIsNone(meta.find_tag("vercel/ai", "ai", "9.9.9"))
            paths = [r["path"] for r in srv.requests[:1]]
            self.assertEqual(paths, ["/repos/vercel/ai/git/ref/tags/ai@7.0.155"])

    def test_tag_not_found_notice(self):
        routes = dict(gh_routes(), **{"/ai": npm_doc()})
        with FixtureServer(routes) as srv, TempHome():
            setup(srv)
            code, out = fetch(srv)
            self.assertEqual(code, 0, out)
            self.assertIsNone(out["tag"])
            self.assertIn("tag_not_found", out["notices"])
            meta, _ = dossier.load("ai")
            self.assertEqual(meta["version"]["label"], "deadbeef")

    def test_rate_limited_is_blocked(self):
        routes = {"/ai": npm_doc(), "/repos/vercel/ai": (403, "text/plain", b"limit")}
        with FixtureServer(routes) as srv, TempHome():
            setup(srv)
            code, out = fetch(srv)
            self.assertEqual(code, 2)
            self.assertEqual(out["error"]["code"], "github_rate_limited")
            self.assertIn("GITHUB_TOKEN", out["error"]["message"])

    def test_meta_saved_as_markdown(self):
        routes = dict(gh_routes(), **{"/ai": npm_doc()})
        with FixtureServer(routes) as srv, TempHome() as home:
            setup(srv)
            fetch(srv)
            meta, _ = dossier.load("ai")
            folder = home.path / "ai" / meta["names"]["sources_dir"] / meta["names"]["meta_dir"]
            self.assertEqual(sorted(p.name for p in folder.iterdir()),
                             ["github-commit.md", "github.md", "npm.md"])
            header, body = frontmatter.parse((folder / "npm.md").read_text(encoding="utf-8"))
            self.assertEqual(header["teach_me"], "meta")
            self.assertIn("/ai", header["url"])
            self.assertIn("fetched_at", header)
            self.assertIn("```json", body)
            inner = body.split("```json\n", 1)[1].rsplit("```", 1)[0]
            self.assertEqual(json.loads(inner)["dist-tags"]["latest"], "7.0.155")

    def test_fetch_meta_needs_dossier_and_source(self):
        with TempHome() as home:
            code, out = run_script("fetch-meta", "nope", "--npm", "x")
            self.assertEqual((code, out["error"]["code"]), (2, "dossier_not_found"))
            self.assertFalse((home.path / "nope").exists())
            run_script("init", "https://github.com/vercel/ai", "--lang", "en")
            code, out = run_script("fetch-meta", "ai")
            self.assertEqual((code, out["error"]["code"]), (2, "bad_input"))
            code, out = run_script("fetch-meta", "ai", "--npm", "a", "--pypi", "b")
            self.assertEqual((code, out["error"]["code"]), (2, "bad_input"))


class UpdateProfileTests(unittest.TestCase):
    def update(self, patch):
        return run_script("update-profile", "ai", stdin=json.dumps(patch))

    def test_update_profile_rejects_unknown_key(self):
        with TempHome():
            run_script("init", "https://github.com/vercel/ai", "--lang", "en")
            for patch in ({"colour": 1}, {"phase_done": "nap"}, {"coverage": {"x": []}},
                          {"public_code": "no"}, {"links": {"web": "not a url"}},
                          {"links": {"package": {"registry": "gem", "name": "a"}}}, []):
                code, out = self.update(patch)
                self.assertEqual((code, out["error"]["code"]), (2, "bad_input"), patch)
            meta, _ = dossier.load("ai")
            self.assertEqual(meta["links"], {})

    def test_links_become_roots(self):
        with TempHome():
            run_script("init", "https://github.com/vercel/ai", "--lang", "en")
            code, out = self.update({
                "name": "AI SDK", "one_liner": "Toolkit",
                "links": {"web": "https://ai-sdk.dev/", "docs": "https://ai-sdk.dev/docs/intro",
                          "repo": "vercel/ai", "package": {"registry": "npm", "name": "ai"}}})
            self.assertEqual(code, 0, out)
            meta, _ = dossier.load("ai")
            self.assertEqual(meta["roots"], ["github.com/vercel/ai", "ai-sdk.dev",
                                             "ai-sdk.dev/docs/intro", "npmjs.com/package/ai"])
            self.assertEqual(meta["name"], "AI SDK")
            self.assertEqual(meta["links"]["repo"], "https://github.com/vercel/ai")

    def test_no_public_code_marks_code_phase_done(self):
        with TempHome():
            run_script("init", "https://example.com/", "--lang", "en")
            code, out = run_script("update-profile", "example", stdin=json.dumps(
                {"public_code": False, "coverage": {"read": ["a"], "skipped": []}}))
            self.assertEqual(code, 0, out)
            meta, _ = dossier.load("example")
            self.assertIn("code", meta["phases"])
            self.assertIs(meta["public_code"], False)
            self.assertIn({"what": "code", "reason": "no_public_code"},
                          meta["coverage"]["not_downloaded"])
            self.assertEqual(meta["coverage"]["read"], ["a"])

    def test_phase_done_and_coverage_append(self):
        with TempHome():
            run_script("init", "https://github.com/vercel/ai", "--lang", "en")
            self.update({"coverage": {"read": ["a"]}, "phase_done": "docs"})
            self.update({"coverage": {"read": ["b"]}})
            meta, _ = dossier.load("ai")
            self.assertEqual(meta["coverage"]["read"], ["a", "b"])
            self.assertRegex(meta["phases"]["docs"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_unknown_dossier(self):
        with TempHome():
            code, out = run_script("update-profile", "nope", stdin="{}")
            self.assertEqual((code, out["error"]["code"]), (2, "dossier_not_found"))


if __name__ == "__main__":
    unittest.main()
