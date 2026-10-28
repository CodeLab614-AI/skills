from __future__ import annotations

import unittest

from teach_me_lib import frontmatter


class FrontmatterTests(unittest.TestCase):
    def test_roundtrip_nested(self):
        meta = {
            "teach_me": "profile",
            "roots": [{"url": "https://x.io/docs", "nota": "línea1\nlínea2"},
                      {"url": "https://y.io", "nota": "ñandú — “comillas”"}],
            "lang": "es", "n": 3, "ok": True, "none": None,
        }
        text = frontmatter.dump(meta, "Cuerpo\n")
        for line in text.split("---\n")[1].splitlines():
            self.assertRegex(line, r"^[a-z_]+: ")
        got, body = frontmatter.parse(text)
        self.assertEqual(got, meta)
        self.assertEqual(body, "Cuerpo\n")

    def test_body_with_triple_dash_preserved(self):
        body = "uno\n---\ndos: 3\n---\nfin\n"
        got, out = frontmatter.parse(frontmatter.dump({"a": 1}, body))
        self.assertEqual(got, {"a": 1})
        self.assertEqual(out, body)

    def test_no_header(self):
        self.assertEqual(frontmatter.parse("hola\n"), ({}, "hola\n"))
        self.assertEqual(frontmatter.parse("---\nnunca cierra\n"), ({}, "---\nnunca cierra\n"))


if __name__ == "__main__":
    unittest.main()
