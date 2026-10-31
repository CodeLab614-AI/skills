from __future__ import annotations

import hashlib
import json

import teach_helpers  # noqa: F401
from teach_helpers import FixtureServer, TempHome, run_script
from teach_me_lib import dossier


def js(obj):
    return (200, "application/json", json.dumps(obj).encode())


SEARCH = {"objects": [
    {"package": {"name": "alpha", "version": "1.2.0", "description": "First",
                 "links": {"npm": "https://www.npmjs.com/package/alpha",
                           "repository": "git+https://github.com/Acme/alpha.git"}}},
    {"package": {"name": "@s/beta", "version": "0.4.1",
                 "links": {"repository": "https://github.com/acme/beta/tree/main/packages/x"}}},
    {"package": {"name": "gamma", "version": "3.0.0", "description": "Third",
                 "links": {"repository": "https://gitlab.com/o/gamma"}}},
    {"package": {"name": "delta", "version": "1.0.0"}},
], "total": 4}


def setup(srv):
    run_script("init", "https://github.com/vercel/ai", "--lang", "en", env=srv.env())


class TestSearchPackages:
    def test_search_npm_returns_candidates_and_saves_raw(self):
        with FixtureServer({"/-/v1/search": js(SEARCH)}) as srv, TempHome() as home:
            setup(srv)
            code, out = run_script("search-packages", "ai", "--npm", "ai sdk", env=srv.env())
            assert code == 0, out
            assert out["registry"] == "npm"
            res = out["results"]
            assert [r["name"] for r in res] == ["alpha", "@s/beta", "gamma", "delta"]
            assert res[0]["repository"] == "https://github.com/Acme/alpha"
            assert res[0]["npm_url"] == "https://www.npmjs.com/package/alpha"
            assert res[1]["repository"] == "https://github.com/acme/beta"
            assert res[1]["npm_url"] == "https://www.npmjs.com/package/@s/beta"
            assert res[2]["repository"] == "https://gitlab.com/o/gamma"
            assert res[3]["repository"] is None
            assert res[3]["description"] is None
            digest = hashlib.sha256("ai sdk".encode("utf-8")).hexdigest()[:8]
            found = list(home.path.rglob("search-npm-%s.md" % digest))
            assert len(found) == 1
            assert "alpha" in found[0].read_text(encoding="utf-8")

    def test_search_npm_size_out_of_range(self):
        with FixtureServer({"/-/v1/search": js(SEARCH)}) as srv, TempHome():
            setup(srv)
            for size in ("0", "21"):
                code, out = run_script("search-packages", "ai", "--npm", "x", "--size", size,
                                       env=srv.env())
                assert (code, out["error"]["code"]) == (2, "bad_input")

    def test_search_pypi_is_not_available(self):
        with FixtureServer({}) as srv, TempHome():
            setup(srv)
            before = len(srv.requests)
            code, out = run_script("search-packages", "ai", "--pypi", "x", env=srv.env())
            assert (code, out["error"]["code"]) == (2, "search_not_available")
            assert "PyPI has no search API" in out["error"]["message"]
            assert len(srv.requests) == before

    def test_bad_input_and_missing_dossier(self):
        with FixtureServer({"/-/v1/search": js(SEARCH)}) as srv, TempHome():
            setup(srv)
            for args in (["ai"], ["ai", "--npm", "a", "--pypi", "b"], ["ai", "--npm", "  "]):
                code, out = run_script("search-packages", *args, env=srv.env())
                assert (code, out["error"]["code"]) == (2, "bad_input"), args
            code, out = run_script("search-packages", "nope", "--npm", "x", env=srv.env())
            assert code == 2


README = "# Widget\n\nWidget renders charts in the browser.\n"


def comp_routes(readme=True, spdx="MIT", npm_lic="MIT"):
    routes = {
        "/repos/Acme/Widget": js({"full_name": "Acme/Widget", "default_branch": "main",
                                  "license": {"spdx_id": spdx}}),
        "/repos/Acme/Widget/commits/main": js({"sha": "abc", "commit": {
            "committer": {"date": "2026-10-20T00:00:00Z"}}}),
        "/widget/latest": js({"name": "widget", "version": "2.1.0", "license": npm_lic}),
        "/repos/Acme/Widget/git/ref/tags/v2.1.0": js({"ref": "refs/tags/v2.1.0"}),
        "/repos/Acme/Widget/releases/tags/v2.1.0": js({"published_at": "2026-09-01T00:00:00Z"}),
    }
    return routes


def with_readme(srv_holder, routes):
    routes["/repos/Acme/Widget/readme"] = lambda path: js(
        {"download_url": srv_holder["srv"].url("/raw/Acme/Widget/main/README.md")})
    routes["/raw/Acme/Widget/main/README.md"] = (200, "text/plain", README.encode())


class TestFetchCompetitor:
    def run_it(self, routes, holder, *extra):
        return run_script("fetch-competitor", "ai", "--repo", "Acme/Widget", *extra,
                          env=holder["srv"].env())

    def test_fetch_competitor_stores_entry_and_readme(self):
        holder = {}
        routes = comp_routes()
        with_readme(holder, routes)
        with FixtureServer(routes) as srv, TempHome() as home:
            holder["srv"] = srv
            setup(srv)
            code, out = self.run_it(routes, holder, "--npm", "widget")
            assert code == 0, out
            assert out["notices"] == []
            assert out["repo"] == "acme/widget"
            assert out["url"] == "https://github.com/Acme/Widget"
            assert out["package"] == {"registry": "npm", "name": "widget"}
            assert out["latest"] == "2.1.0"
            assert out["license"] == {"registry": "MIT", "repo": "MIT", "match": True}
            assert out["activity"] == {
                "last_release_at": "2026-09-01T00:00:00Z", "release_source": "release",
                "last_commit_at": "2026-10-20T00:00:00Z"}
            assert out["readme_url"].endswith("/raw/Acme/Widget/main/README.md")
            profile, _ = dossier.load("ai")
            stored = profile["competitors"]["acme/widget"]
            assert stored["latest"] == "2.1.0"
            assert stored["readme_url"] == out["readme_url"]
            assert len(list(home.path.rglob("competitor-acme__widget-*.md"))) == 4
            pages = list(home.path.rglob("_pages.md"))
            assert pages == []
            # re-running replaces the entry
            code, again = self.run_it(routes, holder, "--npm", "widget")
            assert code == 0, again
            profile, _ = dossier.load("ai")
            assert list(profile["competitors"]) == ["acme/widget"]

    def test_competitor_readme_quote_resolves_with_excerpts(self):
        holder = {}
        routes = comp_routes()
        with_readme(holder, routes)
        with FixtureServer(routes) as srv, TempHome():
            holder["srv"] = srv
            setup(srv)
            code, out = self.run_it(routes, holder, "--npm", "widget")
            assert code == 0, out
            claims = [{"text": "It renders charts", "kind": "fact", "sources": [
                {"kind": "doc", "url": out["readme_url"], "quote": "renders charts in the browser"}]}]
            code, res = run_script("excerpts", "ai", stdin=json.dumps({"claims": claims}))
            assert code == 0, res
            assert res["claims"][0]["verified"], res

    def test_fetch_competitor_without_readme(self):
        holder = {}
        routes = comp_routes(spdx="NOASSERTION")
        with FixtureServer(routes) as srv, TempHome():
            holder["srv"] = srv
            setup(srv)
            code, out = self.run_it(routes, holder)
            assert code == 0, out
            assert out["notices"] == ["no_readme"]
            assert out["readme_url"] is None
            assert out["package"] is None
            assert out["latest"] is None
            assert out["license"] == {"registry": None, "repo": None, "match": None}

    def test_readme_download_failure_keeps_the_verified_data(self):
        holder = {}
        routes = comp_routes()
        with_readme(holder, routes)
        routes["/raw/Acme/Widget/main/README.md"] = (500, "text/plain", b"boom")
        with FixtureServer(routes) as srv, TempHome():
            holder["srv"] = srv
            setup(srv)
            code, out = self.run_it(routes, holder, "--npm", "widget")
            assert code == 0, out
            assert out["notices"] == ["no_readme"]
            assert out["readme_url"] is None
            profile, _ = dossier.load("ai")
            stored = profile["competitors"]["acme/widget"]
            assert stored["latest"] == "2.1.0"
            assert stored["readme_url"] is None

    def test_refetch_removes_stale_meta_files(self):
        holder = {}
        routes = comp_routes()
        with_readme(holder, routes)
        with FixtureServer(routes) as srv, TempHome() as home:
            holder["srv"] = srv
            setup(srv)
            assert self.run_it(routes, holder, "--npm", "widget")[0] == 0
            assert len(list(home.path.rglob("competitor-acme__widget-*.md"))) == 4
            assert self.run_it(routes, holder)[0] == 0
            names = sorted(p.name for p in home.path.rglob("competitor-acme__widget-*.md"))
            assert len(names) == 3, names
            assert not [n for n in names if "npm" in n]

    def test_license_mismatch_notice(self):
        holder = {}
        routes = comp_routes(npm_lic="GPL-3.0")
        with_readme(holder, routes)
        with FixtureServer(routes) as srv, TempHome():
            holder["srv"] = srv
            setup(srv)
            code, out = self.run_it(routes, holder, "--npm", "widget")
            assert code == 0, out
            assert out["notices"] == ["license_mismatch"]

    def test_missing_repo_is_fetch_failed(self):
        with FixtureServer({}) as srv, TempHome():
            setup(srv)
            code, out = run_script("fetch-competitor", "ai", "--repo", "Acme/Widget",
                                   env=srv.env())
            assert (code, out["error"]["code"]) == (2, "fetch_failed")

    def test_fetch_competitor_requires_repo(self):
        with FixtureServer({}) as srv, TempHome():
            setup(srv)
            code, out = run_script("fetch-competitor", "ai", env=srv.env())
            assert (code, out["error"]["code"]) == (2, "bad_input")

    def test_npm_and_pypi_together_is_bad_input(self):
        with FixtureServer({}) as srv, TempHome():
            setup(srv)
            code, out = run_script("fetch-competitor", "ai", "--repo", "Acme/Widget",
                                   "--npm", "a", "--pypi", "b", env=srv.env())
            assert (code, out["error"]["code"]) == (2, "bad_input")
