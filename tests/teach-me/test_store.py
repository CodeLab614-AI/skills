from __future__ import annotations

import os
import time
import unittest

from helpers import TempHome
from teach_me_lib import store
from teach_me_lib.errors import BlockedError


class StoreTests(unittest.TestCase):
    def test_atomic_write_leaves_no_temp_files(self):
        with TempHome() as h:
            target = h.path / "a" / "x.md"
            target.parent.mkdir()
            store.atomic_write(target, "hola\n")
            store.atomic_write(target, "adiós\n")
            self.assertEqual(target.read_text(encoding="utf-8"), "adiós\n")
            self.assertEqual([p.name for p in target.parent.iterdir()], ["x.md"])

    def test_dossier_dir_rejects_traversal(self):
        with TempHome():
            for bad in ["../x", "a/b", "", "-a", "A", "a" * 65, "a b", ".."]:
                with self.assertRaises(BlockedError) as cm:
                    store.dossier_dir(bad)
                self.assertEqual(cm.exception.code, "bad_input")
            self.assertEqual(store.dossier_dir("ai-sdk").name, "ai-sdk")

    def test_lock_busy_then_stale(self):
        with TempHome() as h:
            with store.locked("lib"):
                with self.assertRaises(BlockedError) as cm:
                    with store.locked("lib"):
                        pass
                self.assertEqual(cm.exception.code, "busy")
            self.assertFalse((h.path / "lib" / ".lock").exists())
            lock = h.path / "lib" / ".lock"
            lock.write_text("")
            old = time.time() - 11 * 60
            os.utime(lock, (old, old))
            with store.locked("lib"):
                self.assertTrue(lock.exists())
            self.assertFalse(lock.exists())

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root ignores chmod")
    def test_not_writable(self):
        with TempHome() as h:
            os.chmod(h.path, 0o500)
            with self.assertRaises(BlockedError) as cm:
                store.home()
            self.assertEqual(cm.exception.code, "not_writable")
            self.assertIn(str(h.path), cm.exception.message)

    def test_home_created_when_missing(self):
        with TempHome() as h:
            sub = h.path / "new"
            os.environ["TEACH_ME_HOME"] = str(sub)
            self.assertEqual(store.home(), sub)
            self.assertTrue(sub.is_dir())


if __name__ == "__main__":
    unittest.main()
