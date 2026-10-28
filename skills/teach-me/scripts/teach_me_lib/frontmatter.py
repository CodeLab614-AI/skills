"""Minimal front matter: one `key: <one-line JSON>` per key (JSON is valid YAML)."""
from __future__ import annotations

import json

_FENCE = "---"


def dump(meta: dict, body: str) -> str:
    lines = [_FENCE]
    for key, value in meta.items():
        lines.append("%s: %s" % (key, json.dumps(value, ensure_ascii=False)))
    lines.append(_FENCE)
    return "\n".join(lines) + "\n" + body


def parse(text: str) -> "tuple[dict, str]":
    lines = text.split("\n")
    if not lines or lines[0].rstrip("\r") != _FENCE:
        return {}, text
    meta: dict = {}
    for i in range(1, len(lines)):
        line = lines[i].rstrip("\r")
        if line == _FENCE:
            return meta, "\n".join(lines[i + 1:])
        key, sep, raw = line.partition(": ")
        if not sep:
            if line.endswith(":") and line[:-1]:
                key, raw = line[:-1], "null"
            else:
                return {}, text
        try:
            meta[key] = json.loads(raw)
        except ValueError:
            return {}, text
    return {}, text
