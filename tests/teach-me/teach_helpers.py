"""Test helpers: temporary TEACH_ME_HOME and a script runner."""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "teach-me" / "scripts"
SCRIPT = SCRIPTS / "teach_me.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


class TempHome:
    """A temporary data root; sets TEACH_ME_HOME while active."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name).resolve()
        self._old = None

    def __enter__(self) -> "TempHome":
        self._old = os.environ.get("TEACH_ME_HOME")
        os.environ["TEACH_ME_HOME"] = str(self.path)
        return self

    def __exit__(self, *exc) -> None:
        if self._old is None:
            os.environ.pop("TEACH_ME_HOME", None)
        else:
            os.environ["TEACH_ME_HOME"] = self._old
        self.cleanup()

    def cleanup(self) -> None:
        for p in [self.path, *self.path.rglob("*")]:
            try:
                os.chmod(p, 0o700)
            except OSError:
                pass
        self._tmp.cleanup()


def run_script(*args: str, stdin: str | None = None,
               env: dict | None = None) -> tuple[int, dict]:
    full_env = dict(os.environ)
    full_env.update(env or {})
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args], env=full_env,
        input=stdin.encode("utf-8") if stdin is not None else None,
        stdin=None if stdin is not None else subprocess.DEVNULL,
        capture_output=True,
    )
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    try:
        data = json.loads(out) if out else {}
    except ValueError:
        data = {"raw": out, "stderr": proc.stderr.decode("utf-8", errors="replace")}
    return proc.returncode, data


class FixtureServer:
    """Local HTTP server. routes: path -> (status, content_type, body) or a
    callable(path) -> (status, content_type, body[, extra_headers]). Query strings are
    ignored for matching; unknown paths answer 404. Use as a context manager."""

    def __init__(self, routes: dict) -> None:
        self.routes = routes
        self.requests: list = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                path = urlsplit(self.path).path
                outer.requests.append({"path": path, "headers": dict(self.headers.items())})
                route = outer.routes.get(path) or outer.routes.get(unquote(path))
                extra = {}
                if route is None:
                    status, ctype, body = 404, "text/plain", b"not found"
                else:
                    if callable(route):
                        route = route(path)
                    status, ctype, body = route[:3]
                    extra = route[3] if len(route) > 3 else {}
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in extra.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "FixtureServer":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def url(self, path: str = "/") -> str:
        return "http://127.0.0.1:%d%s" % (self._server.server_address[1], path)

    def env(self) -> dict:
        base = self.url("")
        return {"TEACH_ME_NPM_REGISTRY": base, "TEACH_ME_PYPI_BASE": base,
                "TEACH_ME_GITHUB_API": base, "TEACH_ME_CODELOAD": base}
