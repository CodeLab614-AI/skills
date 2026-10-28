from __future__ import annotations

import unittest
from unittest import mock

import helpers  # noqa: F401
from helpers import FixtureServer, TempHome, run_script
from teach_me_lib import dossier, docs, frontmatter, store


def page(title="T"):
    return (200, "text/html; charset=utf-8", ("<html><body><h1>%s</h1><p>body</p></body></html>" % title).encode())


def md(text="# Hi\n"):
    return (200, "text/markdown", text.encode())


def setup(srv):
    code, out = run_script("init", srv.url("/docs"), "--lang", "en", env=srv.env())
    assert code == 0, out
    return out["id"]


def read_pages(dossier_id):
    meta, _ = dossier.load(dossier_id)
    path = store.dossier_dir(dossier_id) / meta["names"]["sources_dir"] / meta["names"]["docs_dir"] / "_pages.md"
    return frontmatter.parse(path.read_text(encoding="utf-8"))[0]


def states(dossier_id):
    return {p["url"].rsplit("/", 1)[-1]: p["state"] for p in read_pages(dossier_id)["pages"]}


class DiscoverTests(unittest.TestCase):
    def test_llms_txt_preferred(self):
        routes = {
            "/docs/llms.txt": (200, "text/plain", b"# Docs\n- [Intro](/docs/intro.md)\n- [Api](http://x/y)\n"
                               b"https://other.example/docs/z\n- [Rel](api)\n"),
            "/llms.txt": (200, "text/plain", b"nothing"),
            "/sitemap.xml": (404, "text/plain", b""),
        }
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            code, out = run_script("discover-docs", did, srv.url("/docs"), env=srv.env())
            self.assertEqual(code, 0, out)
            self.assertEqual(out["method"], "llms_txt")
            self.assertEqual(out["page_count"], 2)
            self.assertEqual(len(out["fingerprint"]), 64)
            pages = read_pages(did)
            self.assertEqual(pages["teach_me"], "index")
            self.assertEqual([p["url"] for p in pages["pages"]],
                             [srv.url("/docs/intro"), srv.url("/docs/api")])
            self.assertTrue(all(p["state"] == "pending" for p in pages["pages"]))
            meta, _ = dossier.load(did)
            self.assertEqual(meta["version"]["docs_fingerprint"], out["fingerprint"])
            self.assertIn("docs_discover", meta["phases"])

    def test_sitemap_index_followed(self):
        idx = ('<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               '<sitemap><loc>%s</loc></sitemap></sitemapindex>')
        sm = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
              '<url><loc>%s</loc></url><url><loc>%s</loc></url><url><loc>%s</loc></url></urlset>')
        with FixtureServer({}) as srv, TempHome():
            srv.routes["/sitemap.xml"] = (200, "application/xml", (idx % srv.url("/sm1.xml")).encode())
            srv.routes["/sm1.xml"] = (200, "application/xml", (sm % (
                srv.url("/docs/a"), srv.url("/docs/b"), srv.url("/blog/c"))).encode())
            did = setup(srv)
            code, out = run_script("discover-docs", did, srv.url("/docs"), env=srv.env())
            self.assertEqual(code, 0, out)
            self.assertEqual(out["method"], "sitemap")
            self.assertEqual(out["page_count"], 2)

    def test_links_fallback_only_same_prefix(self):
        html = ("<a href='/docs/a'>a</a><a href='/docs/b#frag'>b</a><a href='/blog/x'>x</a>"
                "<a href='/docsx/y'>y</a><a href='mailto:a@b.c'>m</a><a href='/docs/a?q=1'>dup</a>"
                "<a href='/docs/logo.png'>img</a>")
        routes = {"/docs": (200, "text/html", html.encode())}
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            code, out = run_script("discover-docs", did, srv.url("/docs"), env=srv.env())
            self.assertEqual(code, 0, out)
            self.assertEqual(out["method"], "links")
            got = sorted(p["url"] for p in read_pages(did)["pages"])
            self.assertEqual(got, sorted([srv.url("/docs"), srv.url("/docs/a"), srv.url("/docs/b")]))

    def test_rediscover_merges_and_keeps_state(self):
        routes = {"/docs/llms.txt": (200, "text/plain", b"[A](/docs/a)\n")}
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            run_script("discover-docs", did, srv.url("/docs"), env=srv.env())
            srv.routes["/docs/a"] = page()
            run_script("fetch-docs", did, env=srv.env())
            srv.routes["/docs/llms.txt"] = (200, "text/plain", b"[A](/docs/a)\n[B](/docs/b)\n")
            code, out = run_script("discover-docs", did, srv.url("/docs"), env=srv.env())
            self.assertEqual(out["page_count"], 2)
            self.assertEqual(states(did), {"a": "ok", "b": "pending"})

    def test_page_limit_recorded_in_coverage(self):
        body = "\n".join("[p](/docs/p%d)" % i for i in range(5)).encode()
        routes = {"/docs/llms.txt": (200, "text/plain", body)}
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            with mock.patch.object(docs, "PAGE_LIMIT", 2), \
                    mock.patch.dict("os.environ", srv.env()):
                out = docs.discover(did, srv.url("/docs"))
            self.assertEqual(out["page_count"], 2)
            meta, _ = dossier.load(did)
            nd = meta["coverage"]["not_downloaded"]
            self.assertEqual(sorted(e["url"] for e in nd),
                             sorted(srv.url("/docs/p%d" % i) for i in (2, 3, 4)))
            self.assertTrue(all(e["reason"] == "page_limit" for e in nd))

    def test_no_pages_found_when_docs_url_unreachable(self):
        with FixtureServer({}) as srv, TempHome():
            did = setup(srv)
            code, out = run_script("discover-docs", did, srv.url("/docs"), env=srv.env())
            self.assertEqual(code, 2, out)
            self.assertFalse(out["ok"])


def llms(srv, *paths):
    return {"/docs/llms.txt": (200, "text/plain", "\n".join("[x](%s)" % p for p in paths).encode())}


class FetchTests(unittest.TestCase):
    def test_md_variant_used(self):
        routes = dict(llms(None, "/docs/a"), **{"/docs/a.md": md("# From md\n")})
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            run_script("discover-docs", did, srv.url("/docs"), env=srv.env())
            code, out = run_script("fetch-docs", did, env=srv.env())
            self.assertEqual(code, 0, out)
            self.assertEqual(out["downloaded"], 1)
            path = docs.page_path(did, srv.url("/docs/a"))
            meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
            self.assertEqual(meta["teach_me"], "page")
            self.assertEqual(meta["origin"], "md")
            self.assertEqual(meta["url"], srv.url("/docs/a"))
            self.assertIn("fetched_at", meta)
            self.assertIn("# From md", body)
            self.assertIn("__docs__a.md", path.name)
            m, _ = dossier.load(did)
            self.assertIn("docs", m["phases"])

    def test_md_variant_returning_html_is_ignored(self):
        routes = dict(llms(None, "/docs/a", "/docs/b"), **{
            "/docs/a.md": (200, "text/plain", b"<!DOCTYPE html><html><body>spa</body></html>"),
            "/docs/b.md": (200, "text/html", b"# looks like md"),
            "/docs/a": page("Real A"), "/docs/b": page("Real B")})
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            run_script("discover-docs", did, srv.url("/docs"), env=srv.env())
            code, out = run_script("fetch-docs", did, env=srv.env())
            self.assertEqual(out["downloaded"], 2, out)
            for name, title in (("a", "Real A"), ("b", "Real B")):
                meta, body = frontmatter.parse(
                    docs.page_path(did, srv.url("/docs/" + name)).read_text(encoding="utf-8"))
                self.assertEqual(meta["origin"], "html")
                self.assertIn("# " + title, body)

    def test_second_fetch_skips_downloaded(self):
        routes = dict(llms(None, "/docs/a", "/docs/b"), **{"/docs/a.md": md(), "/docs/b": page()})
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            run_script("discover-docs", did, srv.url("/docs"), env=srv.env())
            code, out = run_script("fetch-docs", did, env=srv.env())
            self.assertEqual(out["downloaded"], 2)
            before = len(srv.requests)
            code, out = run_script("fetch-docs", did, env=srv.env())
            self.assertEqual((out["downloaded"], out["already"]), (0, 2), out)
            self.assertEqual(len(srv.requests), before)
            code, out = run_script("fetch-docs", did, "--url", srv.url("/docs/a"), env=srv.env())
            self.assertEqual((out["downloaded"], out["already"]), (0, 1), out)
            self.assertEqual(len(srv.requests), before)

    def test_refresh_redownloads_one_ok_page(self):
        routes = dict(llms(None, "/docs/a", "/docs/b"), **{"/docs/a.md": md("# Old\n"), "/docs/b": page("B")})
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            run_script("discover-docs", did, srv.url("/docs"), env=srv.env())
            run_script("fetch-docs", did, env=srv.env())
            srv.routes["/docs/a.md"] = md("# New content\n")
            before = len(srv.requests)
            code, out = run_script("fetch-docs", did, "--url", srv.url("/docs/a"), "--refresh",
                                   env=srv.env())
            self.assertEqual(code, 0, out)
            self.assertEqual((out["downloaded"], out["already"]), (1, 0), out)
            self.assertGreater(len(srv.requests), before)
            text = docs.page_path(did, srv.url("/docs/a")).read_text(encoding="utf-8")
            self.assertIn("New content", text)
            self.assertNotIn("Old", text)
            self.assertEqual(states(did), {"a": "ok", "b": "ok"})

    def test_refresh_without_url_is_bad_input(self):
        with FixtureServer({}) as srv, TempHome():
            did = setup(srv)
            code, out = run_script("fetch-docs", did, "--refresh", env=srv.env())
            self.assertEqual(code, 2)
            self.assertEqual(out["error"]["code"], "bad_input")
            self.assertIn("--url", out["error"]["message"])

    def test_single_url_fetch_added_to_list(self):
        routes = {"/docs/extra": page("Extra")}
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            code, out = run_script("fetch-docs", did, "--url", srv.url("/docs/extra"), env=srv.env())
            self.assertEqual(code, 0, out)
            self.assertEqual(out["downloaded"], 1)
            self.assertEqual(states(did), {"extra": "ok"})
            self.assertIsNotNone(docs.page_path(did, srv.url("/docs/extra")))

    def test_failed_page_listed_not_fatal_and_retried(self):
        routes = dict(llms(None, "/docs/a", "/docs/gone"), **{"/docs/a": page()})
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            run_script("discover-docs", did, srv.url("/docs"), env=srv.env())
            code, out = run_script("fetch-docs", did, env=srv.env())
            self.assertEqual(code, 0, out)
            self.assertEqual(out["downloaded"], 1)
            self.assertEqual([f["url"] for f in out["failed"]], [srv.url("/docs/gone")])
            self.assertTrue(out["failed"][0]["reason"])
            self.assertEqual(states(did), {"a": "ok", "gone": "failed"})
            self.assertTrue(read_pages(did)["pages"][1]["reason"])
            self.assertIsNone(docs.page_path(did, srv.url("/docs/gone")))
            srv.routes["/docs/gone"] = page("Back")
            code, out = run_script("fetch-docs", did, env=srv.env())
            self.assertEqual((out["downloaded"], out["failed"]), (1, []), out)
            self.assertEqual(states(did), {"a": "ok", "gone": "ok"})

    def test_fetch_without_list_needs_discover(self):
        with FixtureServer({}) as srv, TempHome():
            did = setup(srv)
            code, out = run_script("fetch-docs", did, env=srv.env())
            self.assertEqual(code, 2)
            self.assertEqual(out["error"]["code"], "bad_input")
            self.assertIn("discover-docs", out["error"]["message"])

    def test_long_names_are_cut_and_unique(self):
        long_a = "/docs/" + "x" * 300 + "a"
        long_b = "/docs/" + "x" * 300 + "b"
        routes = dict(llms(None, long_a, long_b), **{long_a: page(), long_b: page()})
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            run_script("discover-docs", did, srv.url("/docs"), env=srv.env())
            code, out = run_script("fetch-docs", did, env=srv.env())
            self.assertEqual(out["downloaded"], 2, out)
            pa = docs.page_path(did, srv.url(long_a))
            pb = docs.page_path(did, srv.url(long_b))
            self.assertNotEqual(pa, pb)
            self.assertLessEqual(len(pa.name), 180)

    def test_bad_dossier(self):
        with TempHome():
            code, out = run_script("fetch-docs", "nope")
            self.assertEqual(out["error"]["code"], "dossier_not_found")


if __name__ == "__main__":
    unittest.main()
