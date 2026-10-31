from __future__ import annotations


import teach_helpers  # noqa: F401
from teach_helpers import TempHome, run_script
from teach_me_lib import dossier


def init(url):
    return run_script("init", url, "--lang", "en")


class TestDiscard:
    def test_discard_moves_folder_and_cleans_up(self):
        with TempHome() as h:
            init("https://github.com/vercel/ai")
            init("https://pypi.org/project/requests")
            code, out = run_script("discard", "ai")
            assert code == 0, out
            assert out["ok"]
            assert out["id"] == "ai"
            moved = h.path / ".discarded"
            assert out["moved_to"].startswith(str(moved / "ai-")), out["moved_to"]
            assert (moved / out["moved_to"].rsplit("/", 1)[1] / "profile.md").is_file()
            assert not (h.path / "ai").exists()
            _, found = run_script("lookup", "https://github.com/vercel/ai")
            assert found["match"] == "new"
            _, listed = run_script("list")
            assert [d["id"] for d in listed["dossiers"]] == ["requests"]
            readme = (h.path / "README.md").read_text("utf-8")
            assert "github.com/vercel/ai" not in readme
            assert "pypi.org/project/requests" in readme
            assert (h.path / "requests" / "profile.md").is_file()
            assert list(h.path.rglob(".lock")) == []

    def test_refused_when_ready_or_syllabus(self):
        with TempHome() as h:
            init("https://github.com/vercel/ai")
            meta, _ = dossier.load("ai")
            meta["status"] = "ready"
            dossier.save("ai", meta)
            code, out = run_script("discard", "ai")
            assert (code, out["error"]["code"]) == (2, "not_discardable")
            meta["status"] = "investigating"
            meta["phases"] = {"syllabus": "2026-10-29T00:00:00Z"}
            dossier.save("ai", meta)
            code, out = run_script("discard", "ai")
            assert (code, out["error"]["code"]) == (2, "not_discardable")
            assert (h.path / "ai" / "profile.md").is_file()
            assert list(h.path.rglob(".lock")) == []

    def test_unknown_id(self):
        with TempHome() as h:
            code, out = run_script("discard", "missing")
            assert (code, out["error"]["code"]) == (2, "dossier_not_found")
            assert not (h.path / "missing").exists()
            assert not (h.path / ".discarded").exists()

    def test_busy_dossier_is_not_moved(self):
        with TempHome() as h:
            init("https://github.com/vercel/ai")
            (h.path / "ai" / ".lock").write_text("")
            code, out = run_script("discard", "ai")
            assert (code, out["error"]["code"]) == (2, "busy")
            assert (h.path / "ai" / "profile.md").is_file()

    def test_same_second_gets_distinct_folders(self, monkeypatch):
        with TempHome() as h:
            monkeypatch.setattr(dossier, "_utc_stamp", lambda *a, **k: "20261029T000000Z")
            moved = []
            for _ in range(3):
                dossier.init("https://github.com/vercel/ai", "en", "use", None)
                moved.append(dossier.discard("ai")["moved_to"])
            assert len(set(moved)) == 3
            assert moved[1].endswith("-2") and moved[2].endswith("-3")
            assert len(list((h.path / ".discarded").iterdir())) == 3
            assert list(h.path.rglob(".lock")) == []

