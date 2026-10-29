from __future__ import annotations

import unittest
from unittest import mock

import helpers  # noqa: F401
from helpers import TempHome, run_script
from teach_me_lib import dossier


def init(url):
    return run_script("init", url, "--lang", "en")


class DiscardTests(unittest.TestCase):
    def test_discard_moves_folder_and_cleans_up(self):
        with TempHome() as h:
            init("https://github.com/vercel/ai")
            init("https://pypi.org/project/requests")
            code, out = run_script("discard", "ai")
            self.assertEqual(code, 0, out)
            self.assertTrue(out["ok"])
            self.assertEqual(out["id"], "ai")
            moved = h.path / ".discarded"
            self.assertTrue(out["moved_to"].startswith(str(moved / "ai-")), out["moved_to"])
            self.assertTrue((moved / out["moved_to"].rsplit("/", 1)[1] / "profile.md").is_file())
            self.assertFalse((h.path / "ai").exists())
            _, found = run_script("lookup", "https://github.com/vercel/ai")
            self.assertEqual(found["match"], "new")
            _, listed = run_script("list")
            self.assertEqual([d["id"] for d in listed["dossiers"]], ["requests"])
            readme = (h.path / "README.md").read_text("utf-8")
            self.assertNotIn("github.com/vercel/ai", readme)
            self.assertIn("pypi.org/project/requests", readme)
            self.assertTrue((h.path / "requests" / "profile.md").is_file())
            self.assertEqual(list(h.path.rglob(".lock")), [])

    def test_refused_when_ready_or_syllabus(self):
        with TempHome() as h:
            init("https://github.com/vercel/ai")
            meta, _ = dossier.load("ai")
            meta["status"] = "ready"
            dossier.save("ai", meta)
            code, out = run_script("discard", "ai")
            self.assertEqual((code, out["error"]["code"]), (2, "not_discardable"))
            meta["status"] = "investigating"
            meta["phases"] = {"syllabus": "2026-10-29T00:00:00Z"}
            dossier.save("ai", meta)
            code, out = run_script("discard", "ai")
            self.assertEqual((code, out["error"]["code"]), (2, "not_discardable"))
            self.assertTrue((h.path / "ai" / "profile.md").is_file())
            self.assertEqual(list(h.path.rglob(".lock")), [])

    def test_unknown_id(self):
        with TempHome() as h:
            code, out = run_script("discard", "missing")
            self.assertEqual((code, out["error"]["code"]), (2, "dossier_not_found"))
            self.assertFalse((h.path / "missing").exists())
            self.assertFalse((h.path / ".discarded").exists())

    def test_busy_dossier_is_not_moved(self):
        with TempHome() as h:
            init("https://github.com/vercel/ai")
            (h.path / "ai" / ".lock").write_text("")
            code, out = run_script("discard", "ai")
            self.assertEqual((code, out["error"]["code"]), (2, "busy"))
            self.assertTrue((h.path / "ai" / "profile.md").is_file())

    def test_same_second_gets_distinct_folders(self):
        with TempHome() as h:
            with mock.patch("teach_me_lib.dossier._utc_stamp", return_value="20261029T000000Z"):
                moved = []
                for _ in range(3):
                    dossier.init("https://github.com/vercel/ai", "en", "use", None)
                    moved.append(dossier.discard("ai")["moved_to"])
            self.assertEqual(len(set(moved)), 3)
            self.assertTrue(moved[1].endswith("-2") and moved[2].endswith("-3"))
            self.assertEqual(len(list((h.path / ".discarded").iterdir())), 3)
            self.assertEqual(list(h.path.rglob(".lock")), [])


if __name__ == "__main__":
    unittest.main()
