#!/usr/bin/env python3
"""explain-changes CLI: argparse and subcommand dispatch only."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from explain_changes_lib import gitcmd  # noqa: E402
from explain_changes_lib.model import BlockedError  # noqa: E402


def _emit(payload: dict, code: int = 0) -> int:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return code


def _not_implemented(name: str) -> int:
    return _emit({"ok": False, "error": {
        "code": "not_implemented", "message": f"{name} is not implemented yet"}}, 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="explain_changes")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("detect")
    p.add_argument("--no-fetch", action="store_true")

    p = sub.add_parser("facts")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--from", dest="from_ref")
    group.add_argument("--commit")
    p.add_argument("--include-uncommitted", action="store_true")
    p.add_argument("--exclude-merge", action="append", default=[])
    p.add_argument("--exclude-author", action="append", default=[])
    p.add_argument("--include-merge", action="append", default=[])
    p.add_argument("--targets-stdin", action="store_true")
    p.add_argument("--only-new", action="store_true")

    p = sub.add_parser("bundle")
    p.add_argument("--batch", type=int, required=True)

    sub.add_parser("verify")

    p = sub.add_parser("report")
    p.add_argument("--lang", required=True)
    return parser


def find_repo(cwd: Path) -> Path:
    res = gitcmd.run_git(cwd, ["rev-parse", "--show-toplevel"], check=False)
    if res.code != 0:
        raise BlockedError("not_a_git_repo", "The current folder is not inside a Git repository.")
    return Path(res.out.decode("utf-8", errors="replace").strip())


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        find_repo(Path.cwd())
        return _not_implemented(args.command)
    except BlockedError as exc:
        return _emit({"ok": False, "error": {"code": exc.code, "message": exc.message}}, 2)
    except Exception as exc:  # internal error
        return _emit({"ok": False, "error": {"code": "internal_error", "message": str(exc)}}, 1)


if __name__ == "__main__":
    sys.exit(main())
