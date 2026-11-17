from __future__ import annotations


import teach_helpers  # noqa: F401
from teach_me_lib import html2md


class TestHtml2Md:
    def test_headings_code_links_lists(self):
        html = (
            "<h1>Title</h1><p>Use <code>foo()</code> and see "
            "<a href='/x'>the guide</a>.</p><h2>Sub</h2>"
            "<ul><li>one</li><li>two</li></ul>"
            "<pre><code>a = 1\nb = 2</code></pre>"
            "<table><tr><th>k</th><th>v</th></tr><tr><td>a</td><td>1</td></tr></table>"
        )
        out = html2md.convert(html)
        assert "# Title" in out
        assert "## Sub" in out
        assert "Use `foo()` and see [the guide](/x)." in out
        assert "- one\n- two" in out
        assert "```\na = 1\nb = 2\n```" in out
        assert "| k | v |" in out
        assert "| a | 1 |" in out

    def test_blank_line_after_list(self):
        out = html2md.convert("<ul><li>a</li><li>b</li></ul>"
                              "<table><tr><th>k</th></tr><tr><td>1</td></tr></table><p>after</p>")
        assert "- b\n\n| k |" in out
        out = html2md.convert("<ul><li>a</li></ul><p>para</p>")
        assert "- a\n\npara" in out

    def test_drops_scripts_and_nav(self):
        html = (
            "<header>HEAD</header><nav>NAV<nav>inner</nav>after-inner</nav>"
            "<script>var x = '<p>bad</p>';</script><style>p{}</style>"
            "<p>Keep me</p><footer>FOOT</footer>"
        )
        out = html2md.convert(html)
        assert out.strip() == "Keep me"

    def test_malformed_html_and_blank_lines(self):
        out = html2md.convert("<p>a<p>b</div></span><h3>c<br><br><br><br><p>d")
        assert "a" in out
        assert "### c" in out
        assert "\n\n\n" not in out

