from __future__ import annotations


from teach_me_lib import frontmatter
import re


class TestFrontmatter:
    def test_roundtrip_nested(self):
        meta = {
            "teach_me": "profile",
            "roots": [{"url": "https://x.io/docs", "nota": "línea1\nlínea2"},
                      {"url": "https://y.io", "nota": "ñandú — “comillas”"}],
            "lang": "es", "n": 3, "ok": True, "none": None,
        }
        text = frontmatter.dump(meta, "Cuerpo\n")
        for line in text.split("---\n")[1].splitlines():
            assert re.search(r"^[a-z_]+: ", line)
        got, body = frontmatter.parse(text)
        assert got == meta
        assert body == "Cuerpo\n"

    def test_body_with_triple_dash_preserved(self):
        body = "uno\n---\ndos: 3\n---\nfin\n"
        got, out = frontmatter.parse(frontmatter.dump({"a": 1}, body))
        assert got == {"a": 1}
        assert out == body

    def test_no_header(self):
        assert frontmatter.parse("hola\n") == ({}, "hola\n")
        assert frontmatter.parse("---\nnunca cierra\n") == ({}, "---\nnunca cierra\n")

