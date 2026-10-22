"""Run Git with a safe, read-only-friendly environment."""
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

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


def _env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in STRIPPED_ENV}
    env.update(SAFE_ENV)
    return env


def run_git(repo: Path, args: List[str], check: bool = True, timeout: int = 60,
            stdin: Optional[bytes] = None) -> GitResult:
    env = _env()
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


def blob_heads(repo: Path, shas: List[str], limit: int, timeout: int = 120) -> Dict[str, bytes]:
    """First ``limit`` bytes of each blob through ONE ``git cat-file --batch``.

    The rest of every blob is read and discarded in chunks, so memory stays bounded.
    Missing objects are left out; any failure returns what was read so far."""
    shas = list(dict.fromkeys(shas))
    heads: Dict[str, bytes] = {}
    if not shas:
        return heads
    try:
        proc = subprocess.Popen(
            ["git", *SAFE_OPTS, "cat-file", "--batch"], cwd=str(repo), env=_env(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return heads

    def feed() -> None:
        try:
            proc.stdin.write(("\n".join(shas) + "\n").encode("ascii"))
            proc.stdin.close()
        except (OSError, ValueError):
            pass

    feeder = threading.Thread(target=feed, daemon=True)
    feeder.start()
    timer = threading.Timer(timeout, proc.kill)
    timer.start()
    try:
        for _ in shas:
            header = proc.stdout.readline().split()
            if len(header) != 3 or not header[2].isdigit():
                continue  # "<sha> missing"
            size, name = int(header[2]), header[0].decode("ascii", "replace")
            data = proc.stdout.read(min(size, limit))
            remaining = size - len(data)
            while remaining > 0:
                chunk = proc.stdout.read(min(remaining, 1 << 16))
                if not chunk:
                    return heads
                remaining -= len(chunk)
            proc.stdout.read(1)  # the newline after the content
            heads[name] = data
    except (OSError, ValueError):
        pass
    finally:
        timer.cancel()
        try:
            proc.kill()
        except OSError:
            pass
        proc.wait()
        feeder.join(1)
        for pipe in (proc.stdin, proc.stdout):
            try:
                pipe.close()
            except OSError:
                pass
    return heads


def git_text(repo: Path, args: List[str], **kw) -> str:
    res = run_git(repo, args, **kw)
    text = res.out.decode("utf-8", errors="replace")
    return text[:-1] if text.endswith("\n") else text
