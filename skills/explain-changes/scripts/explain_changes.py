#!/usr/bin/env python3
"""explain-changes CLI: argparse and subcommand dispatch only."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from explain_changes_lib import detect as detect_mod  # noqa: E402
from explain_changes_lib import facts as facts_mod  # noqa: E402
from explain_changes_lib import gitcmd  # noqa: E402
from explain_changes_lib.ranges import RangeSpec  # noqa: E402
from explain_changes_lib.model import BlockedError  # noqa: E402
from explain_changes_lib.targets import load_targets  # noqa: E402
from explain_changes_lib import verify as verify_mod  # noqa: E402
from explain_changes_lib.bundle import bundle as bundle_mod  # noqa: E402
from explain_changes_lib import report as report_mod  # noqa: E402


def _setup_io() -> None:
    """JSON is always UTF-8, whatever the locale: lossy on output, strict on input."""
    for stream, errors in ((sys.stdout, "replace"), (sys.stdin, "strict")):
        try:
            stream.reconfigure(encoding="utf-8", errors=errors)
        except (AttributeError, ValueError, OSError):
            pass


def _read_stdin() -> str:
    try:
        return sys.stdin.read()
    except UnicodeDecodeError:
        raise BlockedError("bad_input", "Standard input is not valid UTF-8.")


def _emit(payload: dict, code: int = 0) -> int:
    try:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except (UnicodeError, ValueError):
        # Never let the output encoding break the answer: fall back to plain ASCII JSON.
        sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    return code


class JsonArgumentParser(argparse.ArgumentParser):
    """Turn argparse usage errors into the bad_input block (exit 2, JSON)."""

    def error(self, message):
        raise BlockedError("bad_input", message)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(prog="explain_changes")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("detect")
    p.add_argument("--no-fetch", action="store_true")

    p = sub.add_parser("facts")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--from", dest="from_ref")
    group.add_argument("--from-commit", dest="from_commit")
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
    p.add_argument("--labels-stdin", action="store_true")
    return parser


def find_repo(cwd: Path) -> Path:
    res = gitcmd.run_git(cwd, ["rev-parse", "--show-toplevel"], check=False)
    if res.code != 0:
        raise BlockedError("not_a_git_repo", "The current folder is not inside a Git repository.")
    return Path(res.out.decode("utf-8", errors="replace").strip())


def _range_spec(args) -> RangeSpec:
    return RangeSpec(
        from_ref=args.from_ref, commit=args.commit, from_commit=args.from_commit,
        include_uncommitted=args.include_uncommitted,
        exclude_merges=list(args.exclude_merge), include_merges=list(args.include_merge),
        exclude_authors=list(args.exclude_author))


def _read_targets(args):
    if not args.targets_stdin:
        return None
    return load_targets(_read_stdin())


def _read_labels(args):
    """``labels`` JSON object on stdin, only with --labels-stdin."""
    if not args.labels_stdin:
        return None
    raw = _read_stdin()
    if not raw.strip():
        return None
    try:
        labels = json.loads(raw)
    except ValueError:
        raise BlockedError("bad_input", "The labels on stdin are not valid JSON.")
    if not isinstance(labels, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in labels.items()):
        raise BlockedError("bad_input", "The labels must be a JSON object of strings.")
    return labels


def main(argv=None) -> int:
    _setup_io()
    try:
        args = build_parser().parse_args(argv)
        repo = find_repo(Path.cwd())
        if args.command == "detect":
            return _emit(detect_mod.detect(repo, fetch=not args.no_fetch))
        if args.command == "facts":
            return _emit(facts_mod.summary(facts_mod.collect_facts(
                repo, _range_spec(args), _read_targets(args), args.only_new)))
        if args.command == "bundle":
            return _emit(bundle_mod(repo, args.batch))
        if args.command == "verify":
            interp = verify_mod.parse_interpretation(_read_stdin())
            result = verify_mod.verify(repo, verify_mod.load_facts(repo), interp)
            return _emit(verify_mod.summary(verify_mod.write_verified(repo, result), result))
        return _emit(report_mod.write_report(repo, args.lang, _read_labels(args)))
    except BlockedError as exc:
        return _emit({"ok": False, "error": {"code": exc.code, "message": exc.message}}, 2)
    except Exception as exc:  # internal error
        try:
            message = str(exc)
        except Exception:
            message = exc.__class__.__name__
        return _emit({"ok": False, "error": {"code": "internal_error", "message": message}}, 1)


if __name__ == "__main__":
    sys.exit(main())
