from __future__ import annotations

import json
import unittest

import helpers  # noqa: F401
from helpers import TempHome, run_script
from teach_me_lib import docs, dossier, frontmatter, sources, store
from teach_me_lib.errors import BlockedError

URL = "https://sdk.example.com/docs/generate"


def make(version=None):
    code, out = run_script("init", "https://sdk.example.com/docs", "--lang", "en")
    assert code == 0, out
    did = out["id"]
    meta, _ = dossier.load(did)
    meta["version"] = version or {"label": "v1.0"}
    dossier.save(did, meta)
    return did, meta, store.dossier_dir(did)


def put_page(did, meta, url, body):
    d = store.dossier_dir(did) / meta["names"]["sources_dir"] / meta["names"]["docs_dir"]
    d.mkdir(parents=True, exist_ok=True)
    (d / docs._file_name(url)).write_text(
        frontmatter.dump({"teach_me": "page", "url": url}, body), encoding="utf-8")


def put_code(did, meta, rel, text):
    n = meta["names"]
    p = store.dossier_dir(did) / n["sources_dir"] / n["code_dir"] / meta["version"]["label"] / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def fact(*cites):
    return {"text": "x", "kind": "fact", "sources": list(cites)}


def doc(quote, url=URL):
    return {"kind": "doc", "url": url, "quote": quote}


def code(path, a, b):
    return {"kind": "code", "path": path, "line_start": a, "line_end": b}


class SourcesTest(unittest.TestCase):
    def setUp(self):
        self.home = TempHome().__enter__()
        self.addCleanup(self.home.__exit__, None, None, None)
        self.did, self.meta, _ = make()

    def one(self, claim):
        out = sources.resolve(self.did, [claim])[0]
        return out

    def test_normalize(self):
        self.assertEqual(sources.normalize("  A\n\n**B** [link](http://x) `c`_d_ # E "), "a b link cd e")

    def test_doc_quote_found_after_normalization(self):
        put_page(self.did, self.meta, URL, "# Title\n\nUse `generateText`  returns a\nstring.\n")
        out = self.one(fact(doc("generateText **returns**")))
        self.assertTrue(out["verified"])
        self.assertEqual(out["sources"][0]["excerpt"], "`generateText`  returns")

    def test_excerpt_is_literal_with_links(self):
        put_page(self.did, self.meta, URL, "See the [Foo Bar](http://a/b) guide now.")
        out = self.one(fact(doc("foo bar guide")))
        self.assertEqual(out["sources"][0]["excerpt"], "[Foo Bar](http://a/b) guide")

    def test_front_matter_not_searched(self):
        put_page(self.did, self.meta, URL, "body only")
        out = self.one(fact(doc("page")))
        self.assertEqual(out["sources"][0]["error"], "quote_not_found")

    def test_doc_quote_missing_is_unverified(self):
        put_page(self.did, self.meta, URL, "hello")
        out = self.one(fact(doc("nope")))
        self.assertFalse(out["verified"])
        self.assertEqual(out["sources"][0]["error"], "quote_not_found")

    def test_doc_page_not_downloaded(self):
        out = self.one(fact(doc("x")))
        self.assertFalse(out["verified"])
        self.assertEqual(out["sources"][0]["error"], "page_not_downloaded")

    def test_code_lines_extracted(self):
        put_code(self.did, self.meta, "src/a.py", "one\ntwo\nthree\n")
        out = self.one(fact(code("src/a.py", 2, 3)))
        self.assertTrue(out["verified"])
        self.assertEqual(out["sources"][0]["excerpt"], "two\nthree")

    def test_code_line_out_of_range(self):
        put_code(self.did, self.meta, "a.py", "one\ntwo\n")
        for a, b in ((0, 1), (2, 1), (1, 3)):
            out = self.one(fact(code("a.py", a, b)))
            self.assertEqual(out["sources"][0]["error"], "line_out_of_range", (a, b))

    def test_code_more_than_40_lines(self):
        put_code(self.did, self.meta, "a.py", "\n".join("l%d" % i for i in range(60)))
        self.assertEqual(self.one(fact(code("a.py", 1, 41)))["sources"][0]["error"], "too_many_lines")
        self.assertTrue(self.one(fact(code("a.py", 1, 40)))["verified"])

    def test_code_path_traversal_rejected(self):
        put_code(self.did, self.meta, "a.py", "x\n")
        secret = store.dossier_dir(self.did) / "secret.txt"
        secret.write_text("s\n")
        for p in ("../../secret.txt", "../v1.0/a.py", "/etc/passwd", str(secret), "missing.py", "."):
            out = self.one(fact(code(p, 1, 1)))
            self.assertEqual(out["sources"][0]["error"], "file_not_found", p)

    def test_fact_without_sources_unverified(self):
        out = self.one({"text": "x", "kind": "fact", "sources": []})
        self.assertFalse(out["verified"])
        self.assertEqual(out["error"], "no_sources")

    def test_pedagogical_without_sources_ok(self):
        out = self.one({"text": "now we see", "kind": "pedagogical"})
        self.assertTrue(out["verified"])
        self.assertNotIn("error", out)

    def test_pedagogical_with_bad_source_unverified(self):
        out = self.one({"text": "t", "kind": "pedagogical", "sources": [doc("x")]})
        self.assertFalse(out["verified"])

    def test_bad_shape(self):
        bad = [
            "nope", [1], [{"kind": "fact"}], [{"text": "t", "kind": "other"}],
            [{"text": "t", "kind": "fact", "sources": [{"kind": "x"}]}],
            [fact(doc(""))], [fact(doc("a" * 501))],
            [fact({"kind": "code", "path": "a", "line_start": "1", "line_end": 2})],
            [fact({"kind": "code", "path": "a", "line_start": True, "line_end": 2})],
        ]
        for claims in bad:
            with self.assertRaises(BlockedError) as cm:
                sources.resolve(self.did, claims)
            self.assertEqual(cm.exception.code, "bad_input")

    def test_unknown_dossier(self):
        with self.assertRaises(BlockedError) as cm:
            sources.resolve("nope-id", [])
        self.assertEqual(cm.exception.code, "dossier_not_found")

    def test_cli(self):
        put_page(self.did, self.meta, URL, "alpha beta")
        claims = [fact(doc("alpha")), fact(doc("zzz"))]
        code_, out = run_script("excerpts", self.did, stdin=json.dumps({"claims": claims}))
        self.assertEqual(code_, 0, out)
        self.assertEqual(out["unverified"], [1])
        self.assertTrue(out["claims"][0]["verified"])
        code_, out = run_script("excerpts", self.did, stdin=json.dumps({"claims": "x"}))
        self.assertEqual((code_, out["error"]["code"]), (2, "bad_input"))


if __name__ == "__main__":
    unittest.main()
