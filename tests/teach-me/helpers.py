"""Test helpers: temporary TEACH_ME_HOME and a script runner."""
from __future__ import annotations

import json
import os
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
