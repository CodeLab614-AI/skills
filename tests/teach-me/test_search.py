from __future__ import annotations

import json
import unittest

import helpers  # noqa: F401
from helpers import TempHome, run_script
from teach_me_lib import frontmatter, search, store
from teach_me_lib.errors import BlockedError
from test_sources import make, put_code, put_page

URL = "https://sdk.example.com/docs/start"


def inventory(did, meta, files):
    n = meta["names"]
    p = store.dossier_dir(did) / n["sources_dir"] / n["code_dir"] / meta["version"]["label"]
    p.mkdir(parents=True, exist_ok=True)
    (p / "_inventory.md").write_text(frontmatter.dump(
        {"teach_me": "index", "files": [{"path": f, "lines": 1} for f in files]}, ""), encoding="utf-8")


class TokenizeTest(unittest.TestCase):
    def test_camel_case_split(self):
        self.assertEqual(search.tokenize("generateText"), ["generatetext", "generate", "text"])

    def test_snake_kebab_and_unicode(self):
        self.assertEqual(search.tokenize("max_tokens"), ["max", "tokens", "maxtokens"])
        self.assertEqual(search.tokenize("foo-bar baz"), ["foo", "bar", "foobar", "baz"])
        toks = search.tokenize("max_tokens")
        self.assertIn("max", toks)
        self.assertIn("tokens", toks)
        self.assertIn("maxtokens", toks)
        self.assertIn("instalación", search.tokenize("La Instalación"))
        self.assertIn("instalación", search.tokenize("instalación"))
        self.assertEqual(search.tokenize("HTTPServer2"), ["httpserver2", "http", "server", "2"])
        self.assertEqual(search.tokenize("!!"), [])


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.home = TempHome().__enter__()
        self.addCleanup(self.home.__exit__, None, None, None)
        self.did, self.meta, self.folder = make()

    def pages(self):
        put_page(self.did, self.meta, URL,
                 "Intro text about the sdk.\n\n# Start\n\n## Installation\n\nRun npm install sdk to "
                 "install and setup.\n\n```\n# not a heading\n```\n\n## Usage\n\nCall generateText.\n")

    def test_finds_install_section(self):
        self.pages()
        out = search.query(self.did, "install npm setup")
        top = out["results"][0]
        self.assertTrue(top["text"].startswith("## Installation"))
        self.assertEqual(top["citation"], {"kind": "doc", "url": URL, "heading": "Installation"})
        self.assertIsInstance(top["score"], float)
        self.assertNotIn("not a heading", [r["citation"].get("heading") for r in out["results"]])

    def test_preamble_chunk_and_fence(self):
        self.pages()
        out = search.query(self.did, "intro")
        self.assertEqual(out["results"][0]["citation"]["heading"], "")
        out = search.query(self.did, "heading")
        self.assertEqual(out["results"][0]["citation"]["heading"], "Installation")

    def test_code_window_citation_lines(self):
        text = "\n".join("line%d" % i for i in range(1, 121)) + "\nneedleword\n"
        put_code(self.did, self.meta, "src/a.py", text)
        inventory(self.did, self.meta, ["src/a.py"])
        out = search.query(self.did, "needleword")
        c = out["results"][0]["citation"]
        self.assertEqual(c, {"kind": "code", "path": "src/a.py", "line_start": 101, "line_end": 121})
        wins = [(x["citation"]["line_start"], x["citation"]["line_end"])
                for x in search.chunks(self.did) if x["citation"]["kind"] == "code"]
        self.assertEqual(wins, [(1, 60), (51, 110), (101, 121)])

    def test_short_code_file_one_window_and_inventory_only(self):
        put_code(self.did, self.meta, "a.py", "alpha\nbeta\n")
        put_code(self.did, self.meta, "b.py", "alpha secret\n")
        inventory(self.did, self.meta, ["a.py"])
        cs = [x for x in search.chunks(self.did) if x["citation"]["kind"] == "code"]
        self.assertEqual([x["citation"] for x in cs],
                         [{"kind": "code", "path": "a.py", "line_start": 1, "line_end": 2}])

    def test_partial_ignored(self):
        n = self.meta["names"]
        p = store.dossier_dir(self.did) / n["sources_dir"] / n["code_dir"] / "v9.partial"
        p.mkdir(parents=True)
        (p / "x.py").write_text("zzz\n")
        (p / "_inventory.md").write_text(frontmatter.dump({"teach_me": "index", "files": [{"path": "x.py", "lines": 1}]}, ""))
        self.assertEqual(search.query(self.did, "zzz")["results"], [])

    def test_k_and_text_limit(self):
        for i in range(8):
            put_page(self.did, self.meta, "https://sdk.example.com/p%d" % i, "# T\n\nword " + "x" * 2000)
        out = search.query(self.did, "word")
        self.assertEqual(len(out["results"]), 5)
        self.assertTrue(all(len(r["text"]) <= 1200 for r in out["results"]))
        self.assertEqual(len(search.query(self.did, "word", k=2)["results"]), 2)
        self.assertEqual(len(search.query(self.did, "word", k=50)["results"]), 8)
        for bad in (0, 51, True, "3"):
            with self.assertRaises(BlockedError) as cm:
                search.query(self.did, "word", k=bad)
            self.assertEqual(cm.exception.code, "bad_input")

    def test_no_results_is_ok(self):
        self.pages()
        self.assertEqual(search.query(self.did, "zebra"), {"ok": True, "results": []})

    def test_empty_query_and_unknown_dossier(self):
        with self.assertRaises(BlockedError) as cm:
            search.query(self.did, " !! ")
        self.assertEqual(cm.exception.code, "bad_input")
        with self.assertRaises(BlockedError) as cm:
            search.query("nope-id", "x")
        self.assertEqual(cm.exception.code, "dossier_not_found")

    def test_meta_files_not_searched(self):
        self.pages()
        d = store.dossier_dir(self.did)
        n = self.meta["names"]
        (d / n["meta_dir"]).mkdir(parents=True, exist_ok=True)
        (d / n["meta_dir"] / "npm.md").write_text(
            frontmatter.dump({"teach_me": "page", "url": "https://m"}, "metasecret\n"))
        pdir = d / n["sources_dir"] / n["docs_dir"]
        (pdir / "_pages.md").write_text(frontmatter.dump({"teach_me": "page", "url": "https://i"}, "indexsecret\n"))
        (pdir / "other.md").write_text(frontmatter.dump({"teach_me": "profile"}, "wrongtype\n"))
        for q in ("metasecret", "indexsecret", "wrongtype"):
            self.assertEqual(search.query(self.did, q)["results"], [], q)

    def test_cli(self):
        self.pages()
        code, out = run_script("search", self.did, "install npm", "--k", "1")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(out["results"]), 1)
        code, out = run_script("search", self.did, "zebra")
        self.assertEqual((code, out["results"]), (0, []))
        code, out = run_script("search", self.did, "x", "--k", "0")
        self.assertEqual((code, out["error"]["code"]), (2, "bad_input"))


if __name__ == "__main__":
    unittest.main()
