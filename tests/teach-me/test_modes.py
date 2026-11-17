from __future__ import annotations


import teach_helpers  # noqa: F401
from teach_helpers import TempHome, run_script
from teach_me_lib import code, dossier, frontmatter, modes, store

MODES = ("overview", "overview-internals", "use", "use-internals")


def make(url="https://lib.example.com/docs", lang="en", mode="use", **fields):
    code_, out = run_script("init", url, "--lang", lang, "--mode", mode)
    assert code_ == 0, out
    did = out["id"]
    meta, _ = dossier.load(did)
    meta.update(fields)
    dossier.save(did, meta)
    return did


class TestModes:
    def test_init_accepts_every_mode(self):
        with TempHome():
            for mode in MODES:
                code_, out = run_script("init", "https://%s.example.com/x" % mode, "--lang", "en",
                                        "--mode", mode)
                assert code_ == 0, out
                assert out["mode"] == mode
                assert dossier.load(out["id"])[0]["mode"] == mode

    def test_profile_body_labels_every_mode_and_pieces(self):
        with TempHome():
            for lang, word in (("es", "Piezas"), ("en", "Pieces")):
                for mode in MODES:
                    did = make("https://%s-%s.example.com/x" % (lang, mode), lang, mode)
                    path = dossier._profile_path(store.dossier_dir(did))
                    _, body = frontmatter.parse(path.read_text(encoding="utf-8"))
                    assert dossier._MODE_LABELS[lang][mode] in body
                    assert word in body

    def test_set_mode_reports_missing_and_set_aside(self):
        with TempHome():
            did = make(parts_done=["use"])
            code_, out = run_script("set-mode", did, "use-internals")
            assert code_ == 0, out
            assert (out["mode"], out["previous_mode"]) == ("use-internals", "use")
            assert out["missing_parts"] == ["built_syllabus"]
            assert out["set_aside_parts"] == []
            assert not out["needs_full_code"]
            code_, out = run_script("set-mode", did, "overview")
            assert out["missing_parts"] == ["overview"]
            assert out["set_aside_parts"] == ["use"]
            assert dossier.load(did)[0]["parts_done"] == ["use"]
            assert dossier.load(did)[0]["mode"] == "overview"

    def test_set_mode_refreshes_the_progress_set_aside_list(self):
        with TempHome():
            did = make(mode="use-internals")
            topic = {"slug": "core", "title": "Core", "objective": "o", "why_here": "w",
                     "part": "internals", "depends_on": [], "sources": []}
            meta, _ = dossier.load(did)
            folder = store.dossier_dir(did)
            store.atomic_write(folder / meta["names"]["syllabus"], frontmatter.dump(
                {"teach_me": "syllabus", "topics": [dict(topic, number=1)]}, "# s\n"))
            code_, out = run_script("set-mode", did, "use")
            assert code_ == 0, out
            body = (folder / meta["names"]["progress"]).read_text(encoding="utf-8")
            assert "Set aside" in body
            assert "Core" in body

    def test_set_mode_blocks_without_public_code(self):
        with TempHome():
            did = make(public_code=False)
            for mode in ("overview-internals", "use-internals"):
                code_, out = run_script("set-mode", did, mode)
                assert (code_, out["error"]["code"]) == (2, "no_public_code")
            for mode in ("overview", "use"):
                assert run_script("set-mode", did, mode)[0] == 0

    def test_unknown_public_code_does_not_block(self):
        with TempHome():
            did = make()
            assert run_script("set-mode", did, "use-internals")[0] == 0

    def test_set_mode_unknown_mode_and_dossier(self):
        with TempHome():
            did = make()
            code_, out = run_script("set-mode", did, "bogus")
            assert (code_, out["error"]["code"]) == (2, "bad_input")
            code_, out = run_script("set-mode", "nope", "use")
            assert (code_, out["error"]["code"]) == (2, "dossier_not_found")

    def test_needs_full_code_reads_inventory_layout(self):
        with TempHome():
            did = make(version={"label": "v1"})
            meta, _ = dossier.load(did)
            n = meta["names"]
            final = store.dossier_dir(did) / n["sources_dir"] / n["code_dir"] / "v1"
            final.mkdir(parents=True)
            code._write_inventory(final, [], {}, {"layout": "monorepo", "package_dir": "packages/a"}, [])
            assert run_script("set-mode", did, "use-internals")[1]["needs_full_code"]
            assert not run_script("set-mode", did, "use")[1]["needs_full_code"]

    def test_lookup_existing_lists_missing_parts(self):
        with TempHome():
            did = make(mode="use-internals", parts_done=["use"])
            _, found = run_script("lookup", "https://lib.example.com/docs")
            assert (found["match"], found["mode"]) == ("existing", "use-internals")
            _, listed = run_script("list")
            row = [d for d in listed["dossiers"] if d["id"] == did][0]
            assert row["parts_done"] == ["use"]
            assert row["missing_parts"] == ["built_syllabus"]

    def test_pure_helpers(self):
        assert modes.missing_parts({"mode": "overview-internals", "parts_done": ["built_tour"]}) == \
                         ["overview"]
        assert modes.syllabus_parts("use-internals") == ("use", "internals")
        assert [m for m in MODES if modes.needs_public_code(m)] == \
                         ["overview-internals", "use-internals"]

