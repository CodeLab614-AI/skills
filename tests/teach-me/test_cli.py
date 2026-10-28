from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

import helpers  # noqa: F401  (sets sys.path)
from helpers import run_script
import teach_me


class CliTests(unittest.TestCase):
    def test_unknown_command_is_bad_input(self):
        code, data = run_script("nope")
        self.assertEqual(code, 2)
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"]["code"], "bad_input")

    def test_internal_error_is_exit_1(self):
        def boom(args):
            raise RuntimeError("kaput")

        table = {"boom": (lambda p: None, boom)}
        buf = io.StringIO()
        with mock.patch.dict(teach_me.COMMANDS, table), redirect_stdout(buf):
            code = teach_me.main(["boom"])
        self.assertEqual(code, 1)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["error"]["code"], "internal_error")
        self.assertIn("kaput", data["error"]["message"])

    def test_blocked_error_is_exit_2(self):
        from teach_me_lib.errors import BlockedError

        def blocked(args):
            raise BlockedError("busy", "later")

        buf = io.StringIO()
        with mock.patch.dict(teach_me.COMMANDS, {"b": (lambda p: None, blocked)}), \
                redirect_stdout(buf):
            code = teach_me.main(["b"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(buf.getvalue())["error"],
                         {"code": "busy", "message": "later"})


if __name__ == "__main__":
    unittest.main()
