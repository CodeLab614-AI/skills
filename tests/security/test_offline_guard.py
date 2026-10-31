"""Tests for the offline guard in tests/offline/sitecustomize.py."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CODE = "import socket; socket.getaddrinfo('example.com', 443)"


@unittest.skipUnless(os.environ.get("SKILLS_OFFLINE") == "1",
                     "offline guard not active")
class OfflineGuardTests(unittest.TestCase):
    def test_dns_blocked(self):
        with self.assertRaises(OSError) as ctx:
            socket.getaddrinfo("example.com", 443)
        self.assertIn("offline guard", str(ctx.exception))

    def test_gethostbyname_family_blocked(self):
        for fn, arg in ((socket.gethostbyname, "example.com"),
                        (socket.gethostbyname_ex, "example.com"),
                        (socket.gethostbyaddr, "192.0.2.1")):
            with self.subTest(fn=fn.__name__):
                with self.assertRaises(OSError) as ctx:
                    fn(arg)
                self.assertIn("offline guard", str(ctx.exception))
        self.assertTrue(socket.gethostbyname("localhost").startswith("127."))

    def test_public_connect_blocked(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(s.close)
        with self.assertRaises(ConnectionRefusedError) as ctx:
            s.connect(("192.0.2.1", 9))
        self.assertIn("offline guard", str(ctx.exception))

    def test_loopback_allowed(self):
        server = socket.create_server(("127.0.0.1", 0))
        self.addCleanup(server.close)
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(client.close)
        client.connect(server.getsockname())
        conn, _ = server.accept()
        conn.close()

    def test_child_process_blocked(self):
        proc = subprocess.run([sys.executable, "-c", CODE],
                              capture_output=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("offline guard", proc.stderr.decode("utf-8", "replace"))

    def test_attempts_are_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "net.log"
            env = dict(os.environ, SKILLS_OFFLINE_LOG=str(log))
            subprocess.run([sys.executable, "-c", CODE], env=env,
                           capture_output=True)
            lines = log.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("example.com", lines[0])


if __name__ == "__main__":
    unittest.main()
