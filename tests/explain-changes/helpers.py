"""Test helpers: temporary git repos and a script runner."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "explain-changes" / "scripts"
SCRIPT = SCRIPTS / "explain_changes.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


class TempRepo:
    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name).resolve()

    def init(self, branch: str = "main") -> "TempRepo":
        self.git("init", "-q", "-b", branch)
        self.git("config", "user.email", "me@x.io")
        self.git("config", "user.name", "Me")
        self.git("config", "commit.gpgsign", "false")
        return self

    def write(self, path: str, text) -> Path:
        target = self.path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            target.write_bytes(text)
        else:
            target.write_bytes(text.encode("utf-8"))
        return target

    def git(self, *args: str, env: dict | None = None) -> str:
        full_env = dict(os.environ)
        full_env.update(env or {})
        proc = subprocess.run(
            ["git", *args], cwd=self.path, env=full_env,
            capture_output=True, check=True,
        )
        return proc.stdout.decode("utf-8", errors="replace").rstrip("\n")

    def commit(self, msg: str, email: str = "me@x.io") -> str:
        self.git("add", "-A")
        env = {
            "GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_EMAIL": email,
            "GIT_AUTHOR_NAME": "Me", "GIT_COMMITTER_NAME": "Me",
        }
        self.git("commit", "-q", "--allow-empty", "-m", msg, env=env)
        return self.git("rev-parse", "HEAD")

    def checkout(self, branch: str, create: bool = False) -> None:
        if create:
            self.git("checkout", "-q", "-b", branch)
        else:
            self.git("checkout", "-q", branch)

    def merge(self, branch: str, no_ff: bool = True) -> None:
        args = ["merge", "-q", "-m", f"merge {branch}"]
        if no_ff:
            args.append("--no-ff")
        self.git(*args, branch)

    def cleanup(self) -> None:
        self._tmp.cleanup()


class RepoTestCase(unittest.TestCase):
    def make_repo(self, branch: str = "main") -> TempRepo:
        repo = TempRepo().init(branch)
        self.addCleanup(repo.cleanup)
        return repo


def run_script(repo, *args: str, stdin: str | None = None,
               env: dict | None = None) -> tuple[int, dict]:
    path = repo.path if hasattr(repo, "path") else Path(repo)
    full_env = dict(os.environ)
    full_env.update(env or {})
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args], cwd=path, env=full_env,
        input=stdin.encode("utf-8") if stdin is not None else None,
        capture_output=True,
    )
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    try:
        data = json.loads(out) if out else {}
    except ValueError:
        data = {"raw": out, "stderr": proc.stderr.decode("utf-8", errors="replace")}
    return proc.returncode, data
