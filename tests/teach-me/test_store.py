from __future__ import annotations

import os
import time

from teach_helpers import TempHome
from teach_me_lib import store
from teach_me_lib.errors import BlockedError
import pytest


class TestStore:
    def test_atomic_write_leaves_no_temp_files(self):
        with TempHome() as h:
            target = h.path / "a" / "x.md"
            target.parent.mkdir()
            store.atomic_write(target, "hola\n")
            store.atomic_write(target, "adiós\n")
            assert target.read_text(encoding="utf-8") == "adiós\n"
            assert [p.name for p in target.parent.iterdir()] == ["x.md"]

    def test_dossier_dir_rejects_traversal(self):
        with TempHome():
            for bad in ["../x", "a/b", "", "-a", "A", "a" * 65, "a b", ".."]:
                with pytest.raises(BlockedError) as cm:
                    store.dossier_dir(bad)
                assert cm.value.code == "bad_input"
            assert store.dossier_dir("ai-sdk").name == "ai-sdk"

    def test_lock_busy_then_stale(self):
        with TempHome() as h:
            with store.locked("lib"):
                with pytest.raises(BlockedError) as cm:
                    with store.locked("lib"):
                        pass
                assert cm.value.code == "busy"
            assert not (h.path / "lib" / ".lock").exists()
            lock = h.path / "lib" / ".lock"
            lock.write_text("")
            old = time.time() - 11 * 60
            os.utime(lock, (old, old))
            with store.locked("lib"):
                assert lock.exists()
            assert not lock.exists()

    @pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                        reason="root ignores chmod")
    def test_not_writable(self):
        with TempHome() as h:
            os.chmod(h.path, 0o500)
            with pytest.raises(BlockedError) as cm:
                store.home()
            assert cm.value.code == "not_writable"
            assert str(h.path) in cm.value.message

    def test_home_created_when_missing(self):
        with TempHome() as h:
            sub = h.path / "new"
            os.environ["TEACH_ME_HOME"] = str(sub)
            assert store.home() == sub
            assert sub.is_dir()

