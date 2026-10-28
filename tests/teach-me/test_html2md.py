from __future__ import annotations

import unittest

import helpers  # noqa: F401
from teach_me_lib import html2md


class Html2MdTests(unittest.TestCase):
    def test_headings_code_links_lists(self):
        html = (
            "<h1>Title</h1><p>Use <code>foo()</code> and see "
            "<a href='/x'>the guide</a>.</p><h2>Sub</h2>"
            "<ul><li>one</li><li>two</li></ul>"
            "<pre><code>a = 1\nb = 2</code></pre>"
            "<table><tr><th>k</th><th>v</th></tr><tr><td>a</td><td>1</td></tr></table>"
        )
        out = html2md.convert(html)
        self.assertIn("# Title", out)
        self.assertIn("## Sub", out)
        self.assertIn("Use `foo()` and see [the guide](/x).", out)
        self.assertIn("- one\n- two", out)
        self.assertIn("```\na = 1\nb = 2\n```", out)
        self.assertIn("| k | v |", out)
        self.assertIn("| a | 1 |", out)

    def test_blank_line_after_list(self):
        out = html2md.convert("<ul><li>a</li><li>b</li></ul>"
                              "<table><tr><th>k</th></tr><tr><td>1</td></tr></table><p>after</p>")
        self.assertIn("- b\n\n| k |", out)
        out = html2md.convert("<ul><li>a</li></ul><p>para</p>")
        self.assertIn("- a\n\npara", out)

    def test_drops_scripts_and_nav(self):
        html = (
            "<header>HEAD</header><nav>NAV<nav>inner</nav>after-inner</nav>"
            "<script>var x = '<p>bad</p>';</script><style>p{}</style>"
            "<p>Keep me</p><footer>FOOT</footer>"
        )
        out = html2md.convert(html)
        self.assertEqual(out.strip(), "Keep me")

    def test_malformed_html_and_blank_lines(self):
        out = html2md.convert("<p>a<p>b</div></span><h3>c<br><br><br><br><p>d")
        self.assertIn("a", out)
        self.assertIn("### c", out)
        self.assertNotIn("\n\n\n", out)


if __name__ == "__main__":
    unittest.main()
