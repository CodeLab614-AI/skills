from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

import teach_helpers  # noqa: F401  (sets sys.path)
from teach_helpers import run_script
import teach_me


class TestCli:
    def test_unknown_command_is_bad_input(self):
        code, data = run_script("nope")
        assert code == 2
        assert not data["ok"]
        assert data["error"]["code"] == "bad_input"

    def test_internal_error_is_exit_1(self, monkeypatch):
        def boom(args):
            raise RuntimeError("kaput")

        monkeypatch.setitem(teach_me.COMMANDS, "boom", (lambda p: None, boom))
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = teach_me.main(["boom"])
        assert code == 1
        data = json.loads(buf.getvalue())
        assert data["error"]["code"] == "internal_error"
        assert "kaput" in data["error"]["message"]

    def test_blocked_error_is_exit_2(self, monkeypatch):
        from teach_me_lib.errors import BlockedError

        def blocked(args):
            raise BlockedError("busy", "later")

        buf = io.StringIO()
        monkeypatch.setitem(teach_me.COMMANDS, "b", (lambda p: None, blocked))
        with redirect_stdout(buf):
            code = teach_me.main(["b"])
        assert code == 2
        assert json.loads(buf.getvalue())["error"] == {"code": "busy", "message": "later"}

