from __future__ import annotations

import json

import teach_helpers  # noqa: F401
from teach_helpers import FixtureServer, TempHome, run_script
from teach_me_lib import net
from teach_me_lib.errors import BlockedError
import pytest


def code_of(fn, *a):
    try:
        fn(*a)
    except BlockedError as exc:
        return exc.code
    return None


class TestNet:
    def test_too_large(self):
        with FixtureServer({"/big": (200, "text/plain", b"x" * 100)}) as srv:
            assert code_of(net.get, srv.url("/big"), 50) == "too_large"
            assert len(net.get(srv.url("/big"), 100).body) == 100

    def test_404_is_not_an_error(self):
        with FixtureServer({}) as srv:
            resp = net.get(srv.url("/nope"), 1000)
            assert resp.status == 404
            assert resp.final_url == srv.url("/nope")

    def test_rejects_file_scheme(self):
        assert code_of(net.get, "file:///etc/passwd", 10) == "bad_input"
        assert code_of(net.get, "ftp://example.com/x", 10) == "bad_input"

    def test_5xx_and_network_failure_are_fetch_failed(self):
        with FixtureServer({"/boom": (503, "text/plain", b"x")}) as srv:
            assert code_of(net.get, srv.url("/boom"), 10) == "fetch_failed"
            dead = srv.url("/x")
        assert code_of(net.get, dead, 10) == "fetch_failed"

    def test_github_rate_limit_mentions_token(self, monkeypatch):
        with FixtureServer({"/limit": (403, "text/plain", b"slow down")}) as srv:
            with monkeypatch.context() as mp:
                for key, value in srv.env().items():
                    mp.setenv(key, value)
                with pytest.raises(BlockedError) as cm:
                    net.get(srv.url("/limit"), 10)
            assert cm.value.code == "github_rate_limited"
            assert "GITHUB_TOKEN" in cm.value.message
            # not GitHub: a 403 is just a response
            with monkeypatch.context() as mp:
                mp.setenv("TEACH_ME_GITHUB_API", "http://127.0.0.1:1")
                assert net.get(srv.url("/limit"), 10).status == 403

    def test_redirect_drops_token_on_other_host(self, monkeypatch):
        with FixtureServer({"/final": (200, "text/plain", b"ok")}) as target:
            # 'localhost' is a different host name than 127.0.0.1
            other = target.url("/final").replace("127.0.0.1", "localhost")
            with FixtureServer({"/go": (302, "text/plain", b"", {"Location": other})}) as gh:
                env = dict(gh.env(), GITHUB_TOKEN="secret")
                with monkeypatch.context() as mp:
                    for key, value in env.items():
                        mp.setenv(key, value)
                    resp = net.get(gh.url("/go"), 100)
                assert resp.body == b"ok"
                assert resp.final_url == other
                assert gh.requests[0]["headers"].get("Authorization") == "Bearer secret"
                assert "Authorization" not in target.requests[0]["headers"]

    def test_token_only_sent_to_github(self):
        npm = json.dumps({"name": "pkg", "version": "1.0.0", "license": "MIT"}).encode()
        repo = json.dumps({"full_name": "o/r", "default_branch": "main",
                           "license": {"spdx_id": "MIT"}}).encode()
        routes = {"/pkg/latest": (200, "application/json", npm),
                  "/repos/o/r": (200, "application/json", repo),
                  "/repos/o/r/commits/main": (200, "application/json", b'{"sha":"abc123"}')}
        with FixtureServer(routes) as srv, FixtureServer(routes) as gh, TempHome() as home:
            env = dict(gh.env(), GITHUB_TOKEN="secret", TEACH_ME_NPM_REGISTRY=srv.url(""))
            run_script("init", "https://github.com/o/r", "--lang", "en", env=env)
            code, out = run_script("fetch-meta", "r", "--npm", "pkg", "--repo", "o/r", env=env)
            assert code == 0, out
            assert srv.requests
            for req in srv.requests:
                assert "Authorization" not in req["headers"]
            assert gh.requests
            for req in gh.requests:
                assert req["headers"].get("Authorization") == "Bearer secret"
                assert req["headers"].get("User-Agent") == "teach-me-skill"
            assert "secret" not in json.dumps(out)
            for path in home.path.rglob("*"):
                if path.is_file():
                    assert "secret" not in path.read_text(encoding="utf-8"), str(path)

