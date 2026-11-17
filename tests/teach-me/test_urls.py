from __future__ import annotations


import teach_helpers  # noqa: F401  (sets sys.path)
from teach_me_lib import urls
from teach_me_lib.errors import BlockedError
import pytest


class TestUrls:
    def test_normalize_variants_are_equal(self):
        variants = [
            "https://ai-sdk.dev/docs",
            "http://www.AI-SDK.dev/docs/",
            "https://ai-sdk.dev:443/docs?x=1#top",
            "HTTPS://Ai-Sdk.Dev/docs///",
        ]
        results = {urls.normalize(v) for v in variants}
        assert results == {"ai-sdk.dev/docs"}

    def test_normalize_keeps_non_default_port(self):
        assert urls.normalize("http://127.0.0.1:8080/a/") == "127.0.0.1:8080/a"
        assert urls.normalize("https://example.com") == "example.com"

    def test_root_for_github_any_subpath(self):
        for u in ("https://github.com/vercel/ai", "https://github.com/vercel/ai.git",
                  "https://www.github.com/vercel/ai/tree/main/packages/ai?x=1",
                  "https://github.com/vercel/ai/issues/12"):
            assert urls.root_for(u) == "github.com/vercel/ai"

    def test_root_for_npm_scoped(self):
        assert urls.root_for("https://www.npmjs.com/package/@ai-sdk/openai/v/1.0.0") == \
                         "npmjs.com/package/@ai-sdk/openai"
        assert urls.root_for("https://npmjs.com/package/ai?activeTab=readme") == \
                         "npmjs.com/package/ai"

    def test_root_for_pypi(self):
        assert urls.root_for("https://pypi.org/project/requests/2.0/") == \
                         "pypi.org/project/requests"

    def test_root_for_shared_host(self):
        assert urls.root_for("https://user.github.io/lib/guide/intro") == \
                         "user.github.io/lib"
        assert urls.root_for("https://proj.vercel.app/docs/x") == "proj.vercel.app/docs"
        assert urls.root_for("https://ai-sdk.dev/docs/intro/") == "ai-sdk.dev/docs/intro"

    def test_matches_respects_segments(self):
        assert urls.matches("ai-sdk.dev/docs", "ai-sdk.dev/docs")
        assert urls.matches("ai-sdk.dev/docs/intro", "ai-sdk.dev/docs")
        assert not urls.matches("ai-sdk.dev/docsxyz", "ai-sdk.dev/docs")
        assert not urls.matches("ai-sdk.dev", "ai-sdk.dev/docs")

    def test_rejects_non_http(self):
        for bad in ("file:///etc/passwd", "SDK de Vercel", "ftp://x.com/a", "", "https://"):
            with pytest.raises(BlockedError) as ctx:
                urls.normalize(bad)
            assert ctx.value.code == "bad_input"
            assert "not_a_url" in ctx.value.message

