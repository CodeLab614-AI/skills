"""Tests for the offline guard in tests/offline/sitecustomize.py."""
from __future__ import annotations

import os
import socket
import subprocess
import sys

import pytest

CODE = "import socket; socket.getaddrinfo('example.com', 443)"


pytestmark = pytest.mark.skipif(
    os.environ.get("SKILLS_OFFLINE") != "1", reason="offline guard not active"
)


class TestOfflineGuard:
    def test_dns_blocked(self):
        with pytest.raises(OSError) as exc_info:
            socket.getaddrinfo("example.com", 443)
        assert "offline guard" in str(exc_info.value)

    def test_gethostbyname_family_blocked(self):
        for fn, arg in ((socket.gethostbyname, "example.com"),
                        (socket.gethostbyname_ex, "example.com"),
                        (socket.gethostbyaddr, "192.0.2.1")):
            with pytest.raises(OSError) as exc_info:
                fn(arg)
            assert "offline guard" in str(exc_info.value), fn.__name__
        assert socket.gethostbyname("localhost").startswith("127.")

    def test_public_connect_blocked(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(ConnectionRefusedError) as exc_info:
                s.connect(("192.0.2.1", 9))
            assert "offline guard" in str(exc_info.value)
        finally:
            s.close()

    def test_loopback_allowed(self):
        server = socket.create_server(("127.0.0.1", 0))
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            client.connect(server.getsockname())
            conn, _ = server.accept()
            conn.close()
        finally:
            client.close()
            server.close()

    def test_child_process_blocked(self):
        proc = subprocess.run([sys.executable, "-c", CODE],
                              capture_output=True)
        assert proc.returncode != 0
        assert "offline guard" in proc.stderr.decode("utf-8", "replace")

    def test_attempts_are_logged(self, tmp_path):
        log = tmp_path / "net.log"
        env = dict(os.environ, SKILLS_OFFLINE_LOG=str(log))
        subprocess.run([sys.executable, "-c", CODE], env=env,
                       capture_output=True)
        lines = log.read_text().splitlines()
        assert len(lines) == 1
        assert "example.com" in lines[0]
