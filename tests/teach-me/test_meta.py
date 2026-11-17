from __future__ import annotations

import json
import re

import teach_helpers  # noqa: F401
from teach_helpers import FixtureServer, TempHome, run_script
from teach_me_lib import dossier, frontmatter


def js(obj):
    return (200, "application/json", json.dumps(obj).encode())


def npm_doc(version="7.0.155", lic="Apache-2.0"):
    return js({"name": "ai", "version": version, "license": lic,
               "repository": {"type": "git", "url": "git+https://github.com/vercel/ai.git"}})


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


class TestMeta:
    def test_npm_and_github_license_match(self):
        routes = dict(gh_routes(tags=["ai@7.0.155"]), **{"/ai/latest": npm_doc()})
        with FixtureServer(routes) as srv, TempHome():
            setup(srv)
            code, out = fetch(srv)
            assert code == 0, out
            assert out["package"]["latest"] == "7.0.155"
            assert out["license"]["match"]
            assert out["tag"] == "ai@7.0.155"
            assert out["repo"]["head_sha"] == "deadbeef"
            meta, _ = dossier.load("ai")
            assert meta["version"]["label"] == "ai_7.0.155"
            assert meta["version"]["kind"] == "package"
            assert "meta" in meta["phases"]

    def test_huge_full_packument_is_not_requested(self):
        big = {"dist-tags": {"latest": "0.0.1"}, "versions": {}, "pad": "x" * (5 * 1024 * 1024 + 10)}
        routes = {"/ai": js(big), "/ai/latest": npm_doc("7.0.155")}
        with FixtureServer(routes) as srv, TempHome():
            run_script("init", "https://github.com/vercel/ai", "--lang", "en", env=srv.env())
            code, out = run_script("fetch-meta", "ai", "--npm", "ai", env=srv.env())
            assert code == 0, out
            assert out["package"]["latest"] == "7.0.155"
            assert out["package"]["license"] == "Apache-2.0"

    def test_scoped_npm_name_is_url_encoded(self):
        routes = {"/@s%2Fp/latest": npm_doc("1.0.0", {"type": "MIT"})}
        with FixtureServer(routes) as srv, TempHome():
            setup(srv)
            code, out = run_script("fetch-meta", "ai", "--npm", "@s/p", env=srv.env())
            assert code == 0, out
            assert out["package"]["license"] == "MIT"
            assert out["license"]["match"] is None
            meta, _ = dossier.load("ai")
            assert meta["version"]["label"] == "1.0.0"

    def test_pypi_and_snapshot(self):
        routes = dict(gh_routes(), **{"/pk/json": js({"info": {"version": "2.1", "license_expression": "MIT"}})})
        with FixtureServer(routes) as srv, TempHome():
            setup(srv)
            code, out = run_script("fetch-meta", "ai", "--pypi", "pk", env=srv.env())
            assert (code, out["package"]["license"]) == (0, "MIT")
            code, out = run_script("fetch-meta", "ai", "--repo", "vercel/ai", env=srv.env())
            assert code == 0, out
            meta, _ = dossier.load("ai")
            assert meta["version"]["kind"] == "snapshot"
            assert meta["version"]["value"] == "deadbeef"

    def test_license_mismatch_is_reported(self):
        routes = dict(gh_routes(spdx="MIT"), **{"/ai/latest": npm_doc()})
        with FixtureServer(routes) as srv, TempHome():
            setup(srv)
            code, out = fetch(srv)
            assert code == 0, out
            assert out["license"]["match"] is False
            assert "license_mismatch" in out["notices"]

    def test_noassertion_license_is_unknown(self):
        routes = dict(gh_routes(spdx="NOASSERTION"), **{"/ai/latest": npm_doc()})
        with FixtureServer(routes) as srv, TempHome():
            setup(srv)
            code, out = fetch(srv)
            assert code == 0, out
            assert out["repo"]["license_spdx"] is None
            assert out["license"] == \
                             {"registry": "Apache-2.0", "repo": None, "match": None}
            assert "license_mismatch" not in out["notices"]
            meta, _ = dossier.load("ai")
            assert meta["license"]["repo"] is None

    def test_find_tag_monorepo(self, monkeypatch):
        from teach_me_lib import meta
        with FixtureServer(gh_routes(tags=["ai@7.0.155"])) as srv:
            with monkeypatch.context() as mp:
                for key, value in srv.env().items():
                    mp.setenv(key, value)
                assert meta.find_tag("vercel/ai", "ai", "7.0.155") == "ai@7.0.155"
                assert meta.find_tag("vercel/ai", "ai", "9.9.9") is None
            paths = [r["path"] for r in srv.requests[:1]]
            assert paths == ["/repos/vercel/ai/git/ref/tags/ai@7.0.155"]

    def test_tag_not_found_notice(self):
        routes = dict(gh_routes(), **{"/ai/latest": npm_doc()})
        with FixtureServer(routes) as srv, TempHome():
            setup(srv)
            code, out = fetch(srv)
            assert code == 0, out
            assert out["tag"] is None
            assert "tag_not_found" in out["notices"]
            meta, _ = dossier.load("ai")
            assert meta["version"]["label"] == "deadbeef"

    def test_rate_limited_is_blocked(self):
        routes = {"/ai/latest": npm_doc(), "/repos/vercel/ai": (403, "text/plain", b"limit")}
        with FixtureServer(routes) as srv, TempHome():
            setup(srv)
            code, out = fetch(srv)
            assert code == 2
            assert out["error"]["code"] == "github_rate_limited"
            assert "GITHUB_TOKEN" in out["error"]["message"]

    def test_meta_saved_as_markdown(self):
        routes = dict(gh_routes(), **{"/ai/latest": npm_doc()})
        with FixtureServer(routes) as srv, TempHome() as home:
            setup(srv)
            fetch(srv)
            meta, _ = dossier.load("ai")
            folder = home.path / "ai" / meta["names"]["sources_dir"] / meta["names"]["meta_dir"]
            assert sorted(p.name for p in folder.iterdir()) == \
                             ["github-commit.md", "github.md", "npm.md"]
            header, body = frontmatter.parse((folder / "npm.md").read_text(encoding="utf-8"))
            assert header["teach_me"] == "meta"
            assert "/ai" in header["url"]
            assert "fetched_at" in header
            assert "```json" in body
            inner = body.split("```json\n", 1)[1].rsplit("```", 1)[0]
            assert json.loads(inner)["version"] == "7.0.155"

    def test_fetch_meta_needs_dossier_and_source(self):
        with TempHome() as home:
            code, out = run_script("fetch-meta", "nope", "--npm", "x")
            assert (code, out["error"]["code"]) == (2, "dossier_not_found")
            assert not (home.path / "nope").exists()
            run_script("init", "https://github.com/vercel/ai", "--lang", "en")
            code, out = run_script("fetch-meta", "ai")
            assert (code, out["error"]["code"]) == (2, "bad_input")
            code, out = run_script("fetch-meta", "ai", "--npm", "a", "--pypi", "b")
            assert (code, out["error"]["code"]) == (2, "bad_input")


def head_commit(date="2026-10-28T08:00:00Z"):
    return js({"sha": "deadbeef", "commit": {"committer": {"date": date}}})


class TestActivity:
    def routes(self, **extra):
        routes = gh_routes(tags=["ai@7.0.155"])
        routes["/repos/vercel/ai/commits/main"] = head_commit()
        routes["/ai/latest"] = npm_doc()
        routes.update(extra)
        return routes

    def test_activity_uses_the_release_of_the_exact_tag(self):
        routes = self.routes(**{
            "/repos/vercel/ai/releases/tags/ai@7.0.155": js({"published_at": "2026-10-29T10:00:00Z"}),
            "/repos/vercel/ai/releases/latest": js({"published_at": "2020-01-01T00:00:00Z"})})
        with FixtureServer(routes) as srv, TempHome():
            setup(srv)
            code, out = fetch(srv)
            assert code == 0, out
            assert out["activity"]["last_release_at"] == "2026-10-29T10:00:00Z"
            assert out["activity"]["release_source"] == "release"
            meta, _ = dossier.load("ai")
            assert meta["activity"] == out["activity"]
            paths = [r["path"] for r in srv.requests]
            assert "/repos/vercel/ai/releases/latest" not in paths

    def test_activity_falls_back_to_the_tag_commit_date(self):
        routes = self.routes(**{
            "/repos/vercel/ai/git/ref/tags/ai@7.0.155": js(
                {"object": {"type": "commit", "sha": "c0ffee"}}),
            "/repos/vercel/ai/commits/c0ffee": head_commit("2026-09-01T00:00:00Z")})
        with FixtureServer(routes) as srv, TempHome():
            setup(srv)
            code, out = fetch(srv)
            assert code == 0, out
            assert out["activity"]["last_release_at"] == "2026-09-01T00:00:00Z"
            assert out["activity"]["release_source"] == "tag_commit"

    def test_annotated_tag_is_followed_to_its_commit(self):
        routes = self.routes(**{
            "/repos/vercel/ai/git/ref/tags/ai@7.0.155": js(
                {"object": {"type": "tag", "sha": "a1a1"}}),
            "/repos/vercel/ai/git/tags/a1a1": js({"object": {"type": "commit", "sha": "c0ffee"}}),
            "/repos/vercel/ai/commits/c0ffee": head_commit("2026-08-01T00:00:00Z")})
        with FixtureServer(routes) as srv, TempHome():
            setup(srv)
            code, out = fetch(srv)
            assert code == 0, out
            assert out["activity"]["last_release_at"] == "2026-08-01T00:00:00Z"
            assert out["activity"]["release_source"] == "tag_commit"

    def test_no_release_and_no_commit_leaves_the_date_empty(self):
        with FixtureServer(self.routes()) as srv, TempHome():
            setup(srv)
            code, out = fetch(srv)
            assert code == 0, out
            assert out["activity"]["last_release_at"] is None
            assert out["activity"]["release_source"] is None

    def test_activity_without_tag_uses_latest_release(self):
        routes = dict(gh_routes(), **{
            "/repos/vercel/ai/commits/main": head_commit(),
            "/repos/vercel/ai/releases/latest": js({"published_at": "2026-07-01T00:00:00Z"})})
        with FixtureServer(routes) as srv, TempHome():
            setup(srv)
            code, out = run_script("fetch-meta", "ai", "--repo", "vercel/ai", env=srv.env())
            assert code == 0, out
            assert out["activity"]["last_release_at"] == "2026-07-01T00:00:00Z"
            assert out["activity"]["release_source"] == "latest_release"

    def test_activity_last_commit_at_is_the_head_commit_date(self):
        with FixtureServer(self.routes()) as srv, TempHome():
            setup(srv)
            code, out = fetch(srv)
            assert code == 0, out
            assert out["activity"]["last_commit_at"] == "2026-10-28T08:00:00Z"

    def test_release_date_quotes_the_tag(self, monkeypatch):
        from teach_me_lib import meta
        routes = {"/repos/o/r/releases/tags/@s/p@1.0": js({"published_at": "2026-01-01T00:00:00Z"})}
        with FixtureServer(routes) as srv:
            with monkeypatch.context() as mp:
                for key, value in srv.env().items():
                    mp.setenv(key, value)
                assert meta.release_date("o/r", "@s/p@1.0") == \
                                 ("2026-01-01T00:00:00Z", "release")
                assert meta.release_date("o/r", None) == (None, None)

    def test_release_rate_limit_is_blocked(self):
        routes = self.routes(**{
            "/repos/vercel/ai/releases/tags/ai@7.0.155": (403, "text/plain", b"limit")})
        with FixtureServer(routes) as srv, TempHome():
            setup(srv)
            code, out = fetch(srv)
            assert code == 2
            assert out["error"]["code"] == "github_rate_limited"

    def test_no_repo_no_activity(self):
        with FixtureServer({"/ai/latest": npm_doc()}) as srv, TempHome():
            setup(srv)
            code, out = run_script("fetch-meta", "ai", "--npm", "ai", env=srv.env())
            assert code == 0, out
            assert "activity" not in out
            meta, _ = dossier.load("ai")
            assert "activity" not in meta


class TestUpdateProfile:
    def update(self, patch):
        return run_script("update-profile", "ai", stdin=json.dumps(patch))

    def test_update_profile_rejects_unknown_key(self):
        with TempHome():
            run_script("init", "https://github.com/vercel/ai", "--lang", "en")
            for patch in ({"colour": 1}, {"phase_done": "nap"}, {"coverage": {"x": []}},
                          {"public_code": "no"}, {"links": {"web": "not a url"}},
                          {"links": {"package": {"registry": "gem", "name": "a"}}}, []):
                code, out = self.update(patch)
                assert (code, out["error"]["code"]) == (2, "bad_input"), patch
            meta, _ = dossier.load("ai")
            assert meta["links"] == {}

    def test_links_become_roots(self):
        with TempHome():
            run_script("init", "https://github.com/vercel/ai", "--lang", "en")
            code, out = self.update({
                "name": "AI SDK", "one_liner": "Toolkit",
                "links": {"web": "https://ai-sdk.dev/", "docs": "https://ai-sdk.dev/docs/intro",
                          "repo": "vercel/ai", "package": {"registry": "npm", "name": "ai"}}})
            assert code == 0, out
            meta, _ = dossier.load("ai")
            assert meta["roots"] == ["github.com/vercel/ai", "ai-sdk.dev",
                                             "ai-sdk.dev/docs/intro", "npmjs.com/package/ai"]
            assert meta["name"] == "AI SDK"
            assert meta["links"]["repo"] == "https://github.com/vercel/ai"

    def test_no_public_code_marks_code_phase_done(self):
        with TempHome():
            run_script("init", "https://example.com/", "--lang", "en")
            code, out = run_script("update-profile", "example", stdin=json.dumps(
                {"public_code": False, "coverage": {"read": ["a"], "skipped": []}}))
            assert code == 0, out
            meta, _ = dossier.load("example")
            assert "code" in meta["phases"]
            assert meta["public_code"] is False
            assert {"what": "code", "reason": "no_public_code"} in \
                          meta["coverage"]["not_downloaded"]
            assert meta["coverage"]["read"] == ["a"]

    def test_phase_done_and_coverage_append(self):
        with TempHome():
            run_script("init", "https://github.com/vercel/ai", "--lang", "en")
            self.update({"coverage": {"read": ["a"]}, "phase_done": "docs"})
            self.update({"coverage": {"read": ["b"]}})
            meta, _ = dossier.load("ai")
            assert meta["coverage"]["read"] == ["a", "b"]
            assert re.search(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", meta["phases"]["docs"])

    def test_unknown_dossier(self):
        with TempHome():
            code, out = run_script("update-profile", "nope", stdin="{}")
            assert (code, out["error"]["code"]) == (2, "dossier_not_found")


class TestSameRepo:
    def _two(self, srv):
        run_script("init", "https://github.com/vercel/ai", "--lang", "en", env=srv.env())
        run_script("init", "https://www.npmjs.com/package/@ai-sdk/openai", "--lang", "en", env=srv.env())

    def test_same_repo_as_lists_other_dossiers(self):
        routes = dict(gh_routes(), **{"/@ai-sdk%2Fopenai/latest": npm_doc("1.0.0")})
        with FixtureServer(routes) as srv, TempHome():
            self._two(srv)
            code, out = run_script("fetch-meta", "ai-sdk-openai", "--npm", "@ai-sdk/openai",
                                   "--repo", "vercel/ai", env=srv.env())
            assert code == 0, out
            assert [c["id"] for c in out["same_repo_as"]] == ["ai"]
            assert set(out["same_repo_as"][0]) == {"id", "name", "roots"}
            assert "github.com/vercel/ai" in out["same_repo_as"][0]["roots"]
            assert dossier.load("ai-sdk-openai")[0]["phases"].keys() == {"meta"}

    def test_no_other_dossier_no_key(self):
        with FixtureServer(gh_routes()) as srv, TempHome():
            run_script("init", "https://www.npmjs.com/package/@ai-sdk/openai", "--lang", "en", env=srv.env())
            code, out = run_script("fetch-meta", "ai-sdk-openai", "--repo", "vercel/ai", env=srv.env())
            assert code == 0, out
            assert "same_repo_as" not in out

    def test_not_investigating_no_key(self):
        with FixtureServer(gh_routes()) as srv, TempHome():
            self._two(srv)
            meta, _ = dossier.load("ai-sdk-openai")
            meta["status"] = "ready"
            dossier.save("ai-sdk-openai", meta)
            code, out = run_script("fetch-meta", "ai-sdk-openai", "--repo", "vercel/ai", env=srv.env())
            assert code == 0, out
            assert "same_repo_as" not in out
