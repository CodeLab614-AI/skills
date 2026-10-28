#!/usr/bin/env python3
"""teach-me CLI: argparse and subcommand dispatch only."""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from teach_me_lib import code, docs, dossier, meta, sources  # noqa: E402
from teach_me_lib.errors import BlockedError  # noqa: E402

# name -> (configure(subparser), handler(args) -> dict). Later tasks add entries.
COMMANDS: dict = {}


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


def _read_stdin_json():
    raw = _read_stdin()
    try:
        return json.loads(raw)
    except ValueError:
        raise BlockedError("bad_input", "Standard input is not valid JSON.")


def _cmd_lookup(args) -> dict:
    return dossier.lookup(args.url)


def _cmd_list(args) -> dict:
    return {"ok": True, "dossiers": dossier.list_all()}


def _cmd_init(args) -> dict:
    custom = _read_stdin_json() if args.names_stdin else None
    return dossier.init(args.url, args.lang, args.mode, custom)


def _cmd_add_root(args) -> dict:
    return dossier.add_root(args.id, args.url)


def _cmd_fetch_meta(args) -> dict:
    return meta.fetch_meta(args.id, args.npm, args.pypi, args.repo)


def _cmd_update_profile(args) -> dict:
    return dossier.update_profile(args.id, _read_stdin_json())


def _cmd_discover_docs(args) -> dict:
    return docs.discover(args.id, args.docs_url)


def _cmd_fetch_docs(args) -> dict:
    return docs.fetch(args.id, args.url)


def _cmd_fetch_code(args) -> dict:
    return code.fetch(args.id, args.repo, args.ref)


def _cmd_excerpts(args) -> dict:
    data = _read_stdin_json()
    if not isinstance(data, dict) or "claims" not in data:
        raise BlockedError("bad_input", "Standard input must be an object with a claims list.")
    claims, unverified = sources.check_claims(args.id, data["claims"])
    return {"ok": True, "claims": claims, "unverified": unverified}


def _emit(payload: dict, code: int = 0) -> int:
    try:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except (UnicodeError, ValueError):
        sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    return code


class JsonArgumentParser(argparse.ArgumentParser):
    """Turn argparse usage errors into the bad_input block (exit 2, JSON)."""

    def error(self, message):
        raise BlockedError("bad_input", message)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(prog="teach_me")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (configure, _handler) in COMMANDS.items():
        configure(sub.add_parser(name))
    return parser


def _register() -> None:
    COMMANDS["lookup"] = (lambda p: p.add_argument("url"), _cmd_lookup)
    COMMANDS["list"] = (lambda p: None, _cmd_list)

    def cfg_init(p):
        p.add_argument("url")
        p.add_argument("--lang", required=True)
        p.add_argument("--mode", choices=dossier.MODES, default="use")
        p.add_argument("--names-stdin", action="store_true")

    def cfg_add_root(p):
        p.add_argument("id")
        p.add_argument("url")

    def cfg_fetch_meta(p):
        p.add_argument("id")
        p.add_argument("--npm")
        p.add_argument("--pypi")
        p.add_argument("--repo")

    def cfg_discover_docs(p):
        p.add_argument("id")
        p.add_argument("docs_url")

    def cfg_fetch_docs(p):
        p.add_argument("id")
        p.add_argument("--url")

    def cfg_fetch_code(p):
        p.add_argument("id")
        p.add_argument("--repo", required=True)
        p.add_argument("--ref", required=True)

    COMMANDS["excerpts"] = (lambda p: p.add_argument("id"), _cmd_excerpts)
    COMMANDS["fetch-code"] = (cfg_fetch_code, _cmd_fetch_code)
    COMMANDS["discover-docs"] = (cfg_discover_docs, _cmd_discover_docs)
    COMMANDS["fetch-docs"] = (cfg_fetch_docs, _cmd_fetch_docs)
    COMMANDS["fetch-meta"] = (cfg_fetch_meta, _cmd_fetch_meta)
    COMMANDS["update-profile"] = (lambda p: p.add_argument("id"), _cmd_update_profile)
    COMMANDS["init"] = (cfg_init, _cmd_init)
    COMMANDS["add-root"] = (cfg_add_root, _cmd_add_root)


def main(argv=None) -> int:
    _setup_io()
    try:
        args = build_parser().parse_args(argv)
        return _emit(COMMANDS[args.command][1](args))
    except BlockedError as exc:
        return _emit({"ok": False, "error": {"code": exc.code, "message": exc.message}}, 2)
    except Exception as exc:  # internal error
        try:
            message = str(exc)
        except Exception:
            message = exc.__class__.__name__
        return _emit({"ok": False, "error": {"code": "internal_error", "message": message}}, 1)


_register()

if __name__ == "__main__":
    sys.exit(main())
