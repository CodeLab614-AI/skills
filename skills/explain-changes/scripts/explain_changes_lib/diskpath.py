"""Git paths are UTF-8 bytes; the filesystem layer may not be (LC_ALL=C gives ascii).

``on_disk`` turns a path decoded from Git into the str Python's filesystem calls
accept under any locale; ``from_disk`` turns a path read from the disk back into
the Git form. Both are the identity when the filesystem encoding is UTF-8."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Union


def fs_str(text: str) -> str:
    """``text`` (Git form) as the str the OS layer will encode back to the same bytes."""
    return os.fsdecode(text.encode("utf-8", "surrogateescape"))


def on_disk(repo: Union[str, Path], rel: str) -> Path:
    return Path(repo) / fs_str(rel)


def from_disk(path: str) -> str:
    return os.fsencode(path).decode("utf-8", "surrogateescape")
