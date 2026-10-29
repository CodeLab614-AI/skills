"""Support verdicts and citations shared by every saved file: topics, overview, tour (spec 6).

A block is `{"kind": str, "claims": [claim, ...]}` and may carry `code` with its
`code_support`. Nothing here writes; callers save what `resolve_blocks` returns.
"""
from __future__ import annotations

import re

from . import sources
from .errors import BlockedError


def check_blocks(data: dict, blocks: list) -> None:
    if data.get("support_checked_in") not in ("subagent", "same_conversation"):
        raise BlockedError("support_not_checked",
                           "support_checked_in must be 'subagent' or 'same_conversation'.")
    missing, unsupported, code_missing, code_bad = [], [], [], []
    for block in blocks:
        for j, claim in enumerate(block["claims"]):
            where = "%s[%d]" % (block["kind"], j)
            verdict = claim.get("support")
            if verdict is None:
                if claim["kind"] == "fact":
                    missing.append(where)
            elif verdict != "supported":
                unsupported.append(where)
        if block.get("code"):
            verdict = block.get("code_support")
            if verdict is None:
                code_missing.append(block["kind"])
            elif verdict != "supported":
                code_bad.append(block["kind"])
    if missing or code_missing:
        parts = []
        if missing:
            parts.append("Fact claims without a support verdict: %s." % ", ".join(missing))
        if code_missing:
            parts.append("Code blocks without a support verdict: %s." % ", ".join(code_missing))
        raise BlockedError("support_not_checked", " ".join(parts))
    if unsupported or code_bad:
        parts = []
        if unsupported:
            parts.append("Unsupported or invalid verdicts, fix or remove: %s." % ", ".join(unsupported))
        if code_bad:
            parts.append("Code blocks unsupported or with an invalid verdict, fix or remove: %s."
                         % ", ".join(code_bad))
        raise BlockedError("unsupported_claims", " ".join(parts))


def resolve_blocks(dossier_id: str, blocks: list) -> list:
    """Resolve every claim's citations; return the resolved claims, one list per block.

    Raises unverified_claims naming each `kind[j] (errors)` that did not resolve.
    """
    flat = [c for b in blocks for c in b["claims"]]
    resolved, bad = sources.check_claims(dossier_id, flat)
    if bad:
        where, k = [], 0
        for b in blocks:
            for j in range(len(b["claims"])):
                if k in bad:
                    errs = sorted({c["error"] for c in resolved[k]["sources"] if "error" in c}
                                  | ({resolved[k]["error"]} if "error" in resolved[k] else set()))
                    where.append("%s[%d] (%s)" % (b["kind"], j, ", ".join(errs) or "unverified"))
                k += 1
        raise BlockedError("unverified_claims",
                           "Citations not verified, fix or remove: %s." % "; ".join(where))
    out, k = [], 0
    for b in blocks:
        out.append(resolved[k:k + len(b["claims"])])
        k += len(b["claims"])
    return out


def source_line(cite: dict) -> str:
    if cite["kind"] == "doc":
        return cite["url"]
    return "%s:%d-%d" % (cite["path"], cite["line_start"], cite["line_end"])


def quote(text: str) -> str:
    return "\n".join("> " + ln if ln else ">" for ln in text.split("\n"))


def fence(code: str) -> str:
    longest = max([len(m) for m in re.findall(r"`+", code)] + [2])
    ticks = "`" * (longest + 1)
    return "%s\n%s\n%s" % (ticks, code.rstrip("\n"), ticks)


def render_claims(claims: list) -> list:
    """Lines for resolved claims: text, quoted excerpt, `— source`, blank line after each."""
    lines: list = []
    for claim in claims:
        lines += [claim["text"], ""]
        for cite in claim.get("sources", []):
            lines += [quote(cite["excerpt"]), ">", quote("— " + source_line(cite)), ""]
    return lines
