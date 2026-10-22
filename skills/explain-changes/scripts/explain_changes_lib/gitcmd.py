"""Run Git with a safe, read-only-friendly environment."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List, NamedTuple, Optional

SAFE_ENV = {
    "GIT_OPTIONAL_LOCKS": "0",
    "LC_ALL": "C",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_PAGER": "cat",
}
# Variables that would redirect Git away from the repo (e.g. inside a hook).
STRIPPED_ENV = (
    "GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR",
)
SAFE_OPTS = ["-c", "core.quotepath=off", "-c", "color.ui=never", "--no-pager"]


class GitResult(NamedTuple):
    code: int
    out: bytes
    err: str


class GitError(Exception):
    def __init__(self, args: List[str], code: int, err: str) -> None:
        super().__init__(f"git {' '.join(args)} failed ({code}): {err.strip()}")
        self.args_list = list(args)
        self.code = code
        self.err = err


def run_git(repo: Path, args: List[str], check: bool = True, timeout: int = 60,
            stdin: Optional[bytes] = None) -> GitResult:
    env = {k: v for k, v in os.environ.items() if k not in STRIPPED_ENV}
    env.update(SAFE_ENV)
    try:
        proc = subprocess.run(
            ["git", *SAFE_OPTS, *args], cwd=str(repo), env=env, input=stdin,
            stdin=None if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        if check:
            raise GitError(args, -1, "timeout")
        return GitResult(-1, b"", "timeout")
    result = GitResult(proc.returncode, proc.stdout,
                       proc.stderr.decode("utf-8", errors="replace"))
    if check and result.code != 0:
        raise GitError(args, result.code, result.err)
    return result


def git_text(repo: Path, args: List[str], **kw) -> str:
    res = run_git(repo, args, **kw)
    text = res.out.decode("utf-8", errors="replace")
    return text[:-1] if text.endswith("\n") else text
