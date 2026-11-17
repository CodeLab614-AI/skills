from __future__ import annotations

import re
from pathlib import Path

import teach_helpers  # noqa: F401
from teach_helpers import FixtureServer, TempHome, run_script
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


class TestDiscover:
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
            assert code == 0, out
            assert out["method"] == "llms_txt"
            assert out["page_count"] == 2
            assert len(out["fingerprint"]) == 64
            pages = read_pages(did)
            assert pages["teach_me"] == "index"
            assert [p["url"] for p in pages["pages"]] == \
                             [srv.url("/docs/intro"), srv.url("/docs/api")]
            assert all(p["state"] == "pending" for p in pages["pages"])
            meta, _ = dossier.load(did)
            assert meta["version"]["docs_fingerprint"] == out["fingerprint"]
            assert "docs_discover" in meta["phases"]

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
            assert code == 0, out
            assert out["method"] == "sitemap"
            assert out["page_count"] == 2

    def test_sitemap_with_doctype_is_ignored(self):
        xml = ('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]>'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>&a;</loc></url></urlset>')
        assert docs._sitemap_locs(xml) == ("", [])

    def test_links_fallback_only_same_prefix(self):
        html = ("<a href='/docs/a'>a</a><a href='/docs/b#frag'>b</a><a href='/blog/x'>x</a>"
                "<a href='/docsx/y'>y</a><a href='mailto:a@b.c'>m</a><a href='/docs/a?q=1'>dup</a>"
                "<a href='/docs/logo.png'>img</a>")
        routes = {"/docs": (200, "text/html", html.encode())}
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            code, out = run_script("discover-docs", did, srv.url("/docs"), env=srv.env())
            assert code == 0, out
            assert out["method"] == "links"
            got = sorted(p["url"] for p in read_pages(did)["pages"])
            assert got == sorted([srv.url("/docs"), srv.url("/docs/a"), srv.url("/docs/b")])

    def test_rediscover_merges_and_keeps_state(self):
        routes = {"/docs/llms.txt": (200, "text/plain", b"[A](/docs/a)\n")}
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            run_script("discover-docs", did, srv.url("/docs"), env=srv.env())
            srv.routes["/docs/a"] = page()
            run_script("fetch-docs", did, env=srv.env())
            srv.routes["/docs/llms.txt"] = (200, "text/plain", b"[A](/docs/a)\n[B](/docs/b)\n")
            code, out = run_script("discover-docs", did, srv.url("/docs"), env=srv.env())
            assert out["page_count"] == 2
            assert states(did) == {"a": "ok", "b": "pending"}

    def test_page_limit_recorded_in_coverage(self, monkeypatch):
        body = "\n".join("[p](/docs/p%d)" % i for i in range(5)).encode()
        routes = {"/docs/llms.txt": (200, "text/plain", body)}
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            with monkeypatch.context() as mp:
                mp.setattr(docs, "PAGE_LIMIT", 2)
                for key, value in srv.env().items():
                    mp.setenv(key, value)
                out = docs.discover(did, srv.url("/docs"))
            assert out["page_count"] == 2
            meta, _ = dossier.load(did)
            nd = meta["coverage"]["not_downloaded"]
            assert sorted(e["url"] for e in nd) == \
                             sorted(srv.url("/docs/p%d" % i) for i in (2, 3, 4))
            assert all(e["reason"] == "page_limit" for e in nd)

    def test_no_pages_found_when_docs_url_unreachable(self):
        with FixtureServer({}) as srv, TempHome():
            did = setup(srv)
            code, out = run_script("discover-docs", did, srv.url("/docs"), env=srv.env())
            assert code == 2, out
            assert not out["ok"]


def llms(srv, *paths):
    return {"/docs/llms.txt": (200, "text/plain", "\n".join("[x](%s)" % p for p in paths).encode())}


class TestFetch:
    def test_md_variant_used(self):
        routes = dict(llms(None, "/docs/a"), **{"/docs/a.md": md("# From md\n")})
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            run_script("discover-docs", did, srv.url("/docs"), env=srv.env())
            code, out = run_script("fetch-docs", did, env=srv.env())
            assert code == 0, out
            assert out["downloaded"] == 1
            path = docs.page_path(did, srv.url("/docs/a"))
            meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
            assert meta["teach_me"] == "page"
            assert meta["origin"] == "md"
            assert meta["url"] == srv.url("/docs/a")
            assert "fetched_at" in meta
            assert "# From md" in body
            assert "__docs__a.md" in path.name
            m, _ = dossier.load(did)
            assert "docs" in m["phases"]

    def test_md_variant_returning_html_is_ignored(self):
        routes = dict(llms(None, "/docs/a", "/docs/b"), **{
            "/docs/a.md": (200, "text/plain", b"<!DOCTYPE html><html><body>spa</body></html>"),
            "/docs/b.md": (200, "text/html", b"# looks like md"),
            "/docs/a": page("Real A"), "/docs/b": page("Real B")})
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            run_script("discover-docs", did, srv.url("/docs"), env=srv.env())
            code, out = run_script("fetch-docs", did, env=srv.env())
            assert out["downloaded"] == 2, out
            for name, title in (("a", "Real A"), ("b", "Real B")):
                meta, body = frontmatter.parse(
                    docs.page_path(did, srv.url("/docs/" + name)).read_text(encoding="utf-8"))
                assert meta["origin"] == "html"
                assert "# " + title in body

    def test_second_fetch_skips_downloaded(self):
        routes = dict(llms(None, "/docs/a", "/docs/b"), **{"/docs/a.md": md(), "/docs/b": page()})
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            run_script("discover-docs", did, srv.url("/docs"), env=srv.env())
            code, out = run_script("fetch-docs", did, env=srv.env())
            assert out["downloaded"] == 2
            before = len(srv.requests)
            code, out = run_script("fetch-docs", did, env=srv.env())
            assert (out["downloaded"], out["already"]) == (0, 2), out
            assert len(srv.requests) == before
            code, out = run_script("fetch-docs", did, "--url", srv.url("/docs/a"), env=srv.env())
            assert (out["downloaded"], out["already"]) == (0, 1), out
            assert len(srv.requests) == before

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
            assert code == 0, out
            assert (out["downloaded"], out["already"]) == (1, 0), out
            assert len(srv.requests) > before
            text = docs.page_path(did, srv.url("/docs/a")).read_text(encoding="utf-8")
            assert "New content" in text
            assert "Old" not in text
            assert states(did) == {"a": "ok", "b": "ok"}

    def test_refresh_without_url_is_bad_input(self):
        with FixtureServer({}) as srv, TempHome():
            did = setup(srv)
            code, out = run_script("fetch-docs", did, "--refresh", env=srv.env())
            assert code == 2
            assert out["error"]["code"] == "bad_input"
            assert "--url" in out["error"]["message"]

    def test_single_url_fetch_added_to_list(self):
        routes = {"/docs/extra": page("Extra")}
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            code, out = run_script("fetch-docs", did, "--url", srv.url("/docs/extra"), env=srv.env())
            assert code == 0, out
            assert out["downloaded"] == 1
            assert states(did) == {"extra": "ok"}
            assert docs.page_path(did, srv.url("/docs/extra")) is not None

    def test_failed_page_listed_not_fatal_and_retried(self):
        routes = dict(llms(None, "/docs/a", "/docs/gone"), **{"/docs/a": page()})
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            run_script("discover-docs", did, srv.url("/docs"), env=srv.env())
            code, out = run_script("fetch-docs", did, env=srv.env())
            assert code == 0, out
            assert out["downloaded"] == 1
            assert [f["url"] for f in out["failed"]] == [srv.url("/docs/gone")]
            assert out["failed"][0]["reason"]
            assert states(did) == {"a": "ok", "gone": "failed"}
            assert read_pages(did)["pages"][1]["reason"]
            assert docs.page_path(did, srv.url("/docs/gone")) is None
            srv.routes["/docs/gone"] = page("Back")
            code, out = run_script("fetch-docs", did, env=srv.env())
            assert (out["downloaded"], out["failed"]) == (1, []), out
            assert states(did) == {"a": "ok", "gone": "ok"}

    def test_fetch_without_list_needs_discover(self):
        with FixtureServer({}) as srv, TempHome():
            did = setup(srv)
            code, out = run_script("fetch-docs", did, env=srv.env())
            assert code == 2
            assert out["error"]["code"] == "bad_input"
            assert "discover-docs" in out["error"]["message"]

    def test_long_names_are_cut_and_unique(self):
        long_a = "/docs/" + "x" * 300 + "a"
        long_b = "/docs/" + "x" * 300 + "b"
        routes = dict(llms(None, long_a, long_b), **{long_a: page(), long_b: page()})
        with FixtureServer(routes) as srv, TempHome():
            did = setup(srv)
            run_script("discover-docs", did, srv.url("/docs"), env=srv.env())
            code, out = run_script("fetch-docs", did, env=srv.env())
            assert out["downloaded"] == 2, out
            pa = docs.page_path(did, srv.url(long_a))
            pb = docs.page_path(did, srv.url(long_b))
            assert pa != pb
            assert len(pa.name) <= 180

    def test_bad_dossier(self):
        with TempHome():
            code, out = run_script("fetch-docs", "nope")
            assert out["error"]["code"] == "dossier_not_found"


class TestFileName:
    def test_windows_safe_names(self):
        name = docs._file_name("http://127.0.0.1:50577/docs/a(b)/install?x=1&y='2';$!*")
        for ch in ':*?"<>|!$&\'();\\':
            assert ch not in name
        assert name.endswith(".md")
        assert "__docs__" in name


ROOT = Path(__file__).resolve().parents[2]


class TestUsageGuide:
    def test_readme_lists_teach_me_in_both_languages(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        en = text.split("### Skills")[1].split("### Install")[0]
        es = text.split("### Skills")[2].split("### Instalaci")[0]
        for section in (en, es):
            rows = [r for r in section.splitlines() if r.startswith("| `teach-me` |")]
            assert len(rows) == 1, section
            assert "(docs/teach-me.md)" in rows[0]

    def test_docs_links_resolve(self):
        doc = ROOT / "docs" / "teach-me.md"
        text = doc.read_text(encoding="utf-8")
        for link in re.findall(r"\]\(([^)#\s]+)", text):
            if re.match(r"[a-z]+:", link):
                continue
            assert (doc.parent / link).exists(), link
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        links = re.findall(r"\]\((docs/[^)#]*)", readme)
        assert "docs/teach-me.md" in links
        for link in links:
            assert (ROOT / link).is_file(), link
