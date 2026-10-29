"""Data root, atomic writes and per-dossier locking."""
from __future__ import annotations

import contextlib
import os
import re
import tempfile
import time
from pathlib import Path

from .errors import BlockedError

STALE_LOCK_SECONDS = 10 * 60
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _not_writable(path) -> BlockedError:
    return BlockedError("not_writable", "Cannot write to this folder: %s" % path)


def home() -> Path:
    env = os.environ.get("TEACH_ME_HOME")
    root = Path(env) if env else Path.home() / ".teach-me"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise _not_writable(root)
    if not os.access(str(root), os.W_OK | os.X_OK):
        raise _not_writable(root)
    return root


def atomic_write(path: Path, text: str) -> None:
    path = Path(path)
    tmp_name = None
    try:
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".part")
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, str(path))
        tmp_name = None
    except OSError:
        raise _not_writable(path.parent)
    finally:
        if tmp_name is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)


def dossier_dir(dossier_id: str) -> Path:
    if not isinstance(dossier_id, str) or not _ID_RE.match(dossier_id):
        raise BlockedError(
            "bad_input", "The dossier id must match ^[a-z0-9][a-z0-9-]{0,63}$.")
    return home() / dossier_id


@contextlib.contextmanager
def locked(dossier_id: str):
    folder = dossier_dir(dossier_id)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise _not_writable(folder)
    lock = folder / ".lock"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    for attempt in (0, 1):
        try:
            os.close(os.open(str(lock), flags, 0o600))
            break
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except FileNotFoundError:
                continue
            if age < STALE_LOCK_SECONDS or attempt == 1:
                raise BlockedError(
                    "busy", "Another session is using this dossier. Try again shortly.")
            with contextlib.suppress(FileNotFoundError):
                lock.unlink()
        except OSError:
            raise _not_writable(folder)
    try:
        yield folder
    finally:
        with contextlib.suppress(OSError):
            lock.unlink()
