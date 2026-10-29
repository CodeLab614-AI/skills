from __future__ import annotations

import hashlib
import json
import unittest

import helpers  # noqa: F401
from helpers import FixtureServer, TempHome, run_script


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


class SearchPackagesTests(unittest.TestCase):
    def test_search_npm_returns_candidates_and_saves_raw(self):
        with FixtureServer({"/-/v1/search": js(SEARCH)}) as srv, TempHome() as home:
            setup(srv)
            code, out = run_script("search-packages", "ai", "--npm", "ai sdk", env=srv.env())
            self.assertEqual(code, 0, out)
            self.assertEqual(out["registry"], "npm")
            res = out["results"]
            self.assertEqual([r["name"] for r in res], ["alpha", "@s/beta", "gamma", "delta"])
            self.assertEqual(res[0]["repository"], "https://github.com/Acme/alpha")
            self.assertEqual(res[0]["npm_url"], "https://www.npmjs.com/package/alpha")
            self.assertEqual(res[1]["repository"], "https://github.com/acme/beta")
            self.assertEqual(res[1]["npm_url"], "https://www.npmjs.com/package/@s/beta")
            self.assertEqual(res[2]["repository"], "https://gitlab.com/o/gamma")
            self.assertIsNone(res[3]["repository"])
            self.assertIsNone(res[3]["description"])
            digest = hashlib.sha256("ai sdk".encode("utf-8")).hexdigest()[:8]
            found = list(home.path.rglob("search-npm-%s.md" % digest))
            self.assertEqual(len(found), 1)
            self.assertIn("alpha", found[0].read_text(encoding="utf-8"))

    def test_search_npm_size_out_of_range(self):
        with FixtureServer({"/-/v1/search": js(SEARCH)}) as srv, TempHome():
            setup(srv)
            for size in ("0", "21"):
                code, out = run_script("search-packages", "ai", "--npm", "x", "--size", size,
                                       env=srv.env())
                self.assertEqual((code, out["error"]["code"]), (2, "bad_input"))

    def test_search_pypi_is_not_available(self):
        with FixtureServer({}) as srv, TempHome():
            setup(srv)
            before = len(srv.requests)
            code, out = run_script("search-packages", "ai", "--pypi", "x", env=srv.env())
            self.assertEqual((code, out["error"]["code"]), (2, "search_not_available"))
            self.assertIn("PyPI has no search API", out["error"]["message"])
            self.assertEqual(len(srv.requests), before)

    def test_bad_input_and_missing_dossier(self):
        with FixtureServer({"/-/v1/search": js(SEARCH)}) as srv, TempHome():
            setup(srv)
            for args in (["ai"], ["ai", "--npm", "a", "--pypi", "b"], ["ai", "--npm", "  "]):
                code, out = run_script("search-packages", *args, env=srv.env())
                self.assertEqual((code, out["error"]["code"]), (2, "bad_input"), args)
            code, out = run_script("search-packages", "nope", "--npm", "x", env=srv.env())
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
