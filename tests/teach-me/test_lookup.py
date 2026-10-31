from __future__ import annotations

import json

import teach_helpers  # noqa: F401  (sets sys.path)
from teach_helpers import TempHome, run_script
from teach_me_lib import dossier, frontmatter


def init(url, lang="en", *extra, stdin=None):
    return run_script("init", url, "--lang", lang, "--mode", "use", *extra, stdin=stdin)


class TestLookup:
    def test_new_then_existing_with_other_spelling(self):
        with TempHome():
            code, data = run_script("lookup", "https://ai-sdk.dev/docs")
            assert (code, data["match"], data["normalized"]) == (0, "new", "ai-sdk.dev/docs")
            code, made = init("https://ai-sdk.dev/docs")
            assert code == 0
            assert made["id"] == "ai-sdk-docs"
            code, data = run_script("lookup", "http://www.AI-SDK.dev/docs/intro/?q=1#x")
            assert data["match"] == "existing"
            assert data["id"] == "ai-sdk-docs"

    def test_status_investigating_after_init(self):
        with TempHome():
            init("https://github.com/vercel/ai")
            _, data = run_script("lookup", "https://github.com/vercel/ai/issues/3")
            assert data["status"] == "investigating"
            assert data["mode"] == "use"
            assert data["id"] == "ai"

    def test_same_host_other_path_is_ambiguous(self):
        with TempHome():
            init("https://ai-sdk.dev/docs")
            _, data = run_script("lookup", "https://ai-sdk.dev/blog")
            assert data["match"] == "ambiguous"
            assert [c["id"] for c in data["candidates"]] == ["ai-sdk-docs"]
            assert data["candidates"][0]["roots"] == ["ai-sdk.dev/docs"]

    def test_longest_root_wins(self):
        with TempHome():
            init("https://example.com/docs")
            init("https://other.org/x")
            run_script("add-root", "other-x", "https://example.com/docs/advanced")
            _, data = run_script("lookup", "https://example.com/docs/advanced/x")
            assert (data["match"], data["id"]) == ("existing", "other-x")
            _, data = run_script("lookup", "https://example.com/docs/basics")
            assert data["id"] == "example-docs"

    def test_tie_between_two_dossiers_is_ambiguous(self):
        with TempHome():
            init("https://a.dev/one")
            init("https://b.dev/two")
            run_script("add-root", "b-two", "https://a.dev/one")
            _, data = run_script("lookup", "https://a.dev/one/page")
            assert data["match"] == "ambiguous"
            assert sorted(c["id"] for c in data["candidates"]) == ["a-one", "b-two"]

    def test_monorepo_other_npm_package_is_new(self):
        with TempHome():
            init("https://www.npmjs.com/package/ai")
            _, data = run_script("lookup", "https://npmjs.com/package/@ai-sdk/openai")
            assert data["match"] == "new"

    def test_github_same_owner_ambiguous_other_owner_new(self):
        with TempHome():
            init("https://github.com/vercel/ai")
            _, data = run_script("lookup", "https://github.com/Vercel/next.js")
            assert data["match"] == "ambiguous"
            assert data["candidates"][0]["id"] == "ai"
            _, data = run_script("lookup", "https://github.com/other/ai")
            assert data["match"] == "new"
            _, data = run_script("lookup", "https://github.com")
            assert data["match"] == "new"

    def test_npm_same_scope_ambiguous_other_scope_new(self):
        with TempHome():
            init("https://www.npmjs.com/package/@ai-sdk/openai")
            _, data = run_script("lookup", "https://npmjs.com/package/@ai-sdk/anthropic")
            assert data["match"] == "ambiguous"
            assert data["candidates"][0]["id"] == "ai-sdk-openai"
            _, data = run_script("lookup", "https://npmjs.com/package/@other/anthropic")
            assert data["match"] == "new"
            _, data = run_script("lookup", "https://npmjs.com/package/left-pad")
            assert data["match"] == "new"

    def test_npm_unscoped_vs_unscoped_is_new(self):
        with TempHome():
            init("https://www.npmjs.com/package/ai")
            _, data = run_script("lookup", "https://npmjs.com/package/zod")
            assert data["match"] == "new"

    def test_pypi_other_project_is_new(self):
        with TempHome():
            init("https://pypi.org/project/requests")
            _, data = run_script("lookup", "https://pypi.org/project/httpx")
            assert data["match"] == "new"

    def test_shared_host_unit_is_host_plus_first_segment(self):
        with TempHome():
            init("https://user.github.io/lib")
            _, data = run_script("lookup", "https://user.github.io/other")
            assert data["match"] == "new"
            _, data = run_script("lookup", "https://user.github.io/lib/guide")
            assert data["match"] == "existing"

    def test_add_root_then_existing(self):
        with TempHome():
            init("https://www.npmjs.com/package/ai")
            _, data = run_script("lookup", "https://npmjs.com/package/@ai-sdk/openai")
            assert data["match"] == "new"
            code, res = run_script("add-root", "ai", "https://npmjs.com/package/@ai-sdk/openai")
            assert code == 0
            assert "npmjs.com/package/@ai-sdk/openai" in res["roots"]
            _, data = run_script("lookup", "https://npmjs.com/package/@ai-sdk/openai/v/2")
            assert (data["match"], data["id"]) == ("existing", "ai")
            code, res = run_script("add-root", "ai", "https://npmjs.com/package/@ai-sdk/openai")
            assert res["roots"].count("npmjs.com/package/@ai-sdk/openai") == 1

    def test_add_root_unknown_id_creates_no_folder(self):
        with TempHome() as h:
            code, res = run_script("add-root", "missing", "https://x.dev")
            assert (code, res["error"]["code"]) == (2, "dossier_not_found")
            assert not (h.path / "missing").exists()

    def test_registry_lookup_is_case_insensitive(self):
        with TempHome():
            init("https://github.com/vercel/ai")
            _, data = run_script("lookup", "https://github.com/Vercel/AI/tree/main")
            assert (data["match"], data["id"]) == ("existing", "ai")
            init("https://pypi.org/project/requests")
            _, data = run_script("lookup", "https://pypi.org/project/Requests/2.0")
            assert (data["match"], data["id"]) == ("existing", "requests")

    def test_readme_shows_version_value(self):
        with TempHome() as h:
            init("https://ai-sdk.dev/docs")
            meta, _ = dossier.load("ai-sdk-docs")
            meta["version"] = {"kind": "package", "value": "4.2.1", "label": "v4"}
            dossier.save("ai-sdk-docs", meta)
            assert "4.2.1" in (h.path / "README.md").read_text("utf-8")

    def test_init_is_idempotent(self):
        with TempHome():
            code, a = init("https://github.com/vercel/ai", "es")
            assert a["created"]
            code, b = init("https://github.com/vercel/ai/tree/main", "en")
            assert code == 0
            assert not b["created"]
            assert (b["id"], b["lang"]) == ("ai", "es")
            assert len(dossier.list_all()) == 1

    def test_init_ambiguous_blocks(self):
        with TempHome():
            init("https://ai-sdk.dev/docs")
            code, data = init("https://ai-sdk.dev/blog")
            assert (code, data["error"]["code"]) == (2, "ambiguous_url")

    def test_id_collision_gets_suffix(self):
        with TempHome():
            _, data = init("https://github.com/a/ai")
            assert data["id"] == "ai"
            _, data = init("https://pypi.org/project/ai")
            assert data["id"] == "ai-2"
            _, data = init("https://www.npmjs.com/package/ai")
            assert data["id"] == "ai-3"

    def test_scoped_npm_id(self):
        with TempHome():
            _, data = init("https://www.npmjs.com/package/@ai-sdk/openai")
            assert data["id"] == "ai-sdk-openai"

    def test_files_named_in_dossier_language(self):
        with TempHome() as h:
            init("https://ai-sdk.dev/docs", "es")
            base = h.path / "ai-sdk-docs"
            assert (base / "ficha.md").is_file()
            assert (base / "temas").is_dir()
            assert (base / "fuentes" / "docs").is_dir()
            init("https://other.dev/lib", "en")
            base = h.path / "other-lib"
            assert (base / "profile.md").is_file()
            assert (base / "topics").is_dir()
            assert (base / "sources" / "docs").is_dir()

    def test_profile_header_fields(self):
        with TempHome() as h:
            init("https://ai-sdk.dev/docs", "en")
            meta, body = frontmatter.parse((h.path / "ai-sdk-docs" / "profile.md").read_text("utf-8"))
            assert meta["teach_me"] == "profile"
            assert meta["parts_done"] == []
            assert meta["public_code"] is None
            assert meta["phases"] == {}
            assert meta["coverage"] == {"read": [], "skipped": [], "not_downloaded": []}
            assert meta["input_url"] == "https://ai-sdk.dev/docs"
            assert meta["roots"] == ["ai-sdk.dev/docs"]
            assert "ai-sdk.dev/docs" in body

    def test_found_by_header_not_by_filename(self):
        names = {
            "profile": "fiche.md", "overview": "quoi.md", "built": "construit.md",
            "syllabus": "programme.md", "progress": "avancement.md", "topics_dir": "sujets",
            "exams_dir": "examens", "sources_dir": "sources", "docs_dir": "docs",
            "code_dir": "code", "meta_dir": "meta", "attempt": "essai",
        }
        with TempHome() as h:
            code, data = run_script("init", "https://lib.example.fr/doc", "--lang", "fr",
                                    "--mode", "use", "--names-stdin", stdin=json.dumps(names))
            assert code == 0
            assert (h.path / data["id"] / "fiche.md").is_file()
            code, listed = run_script("list")
            assert [d["id"] for d in listed["dossiers"]] == [data["id"]]
            assert listed["dossiers"][0]["status"] == "investigating"
            _, found = run_script("lookup", "https://lib.example.fr/doc/x")
            assert found["match"] == "existing"

    def test_unknown_language_requires_names(self):
        with TempHome():
            code, data = init("https://lib.example.fr/doc", "fr")
            assert (code, data["error"]["code"]) == (2, "names_required")

    def test_bogus_mode_and_bad_lookup_input(self):
        with TempHome():
            code, data = run_script("init", "https://a.dev/x", "--lang", "en", "--mode", "bogus")
            assert (code, data["error"]["code"]) == (2, "bad_input")
            code, data = run_script("lookup", "SDK de Vercel")
            assert (code, data["error"]["code"]) == (2, "bad_input")

    def test_readme_index_regenerated(self):
        with TempHome() as h:
            init("https://ai-sdk.dev/docs", "es")
            init("https://pypi.org/project/requests", "en")
            text = (h.path / "README.md").read_text("utf-8")
            meta, body = frontmatter.parse(text)
            assert meta["teach_me"] == "index"
            assert "ai-sdk.dev/docs" in body
            assert "pypi.org/project/requests" in body
            assert "Investigando" in body
            assert "Investigating" in body
            run_script("add-root", "ai-sdk-docs", "https://ai-sdk.dev/blog")
            assert "ai-sdk.dev/blog" in (h.path / "README.md").read_text("utf-8")

    def test_save_and_load_roundtrip_without_lock(self):
        with TempHome():
            init("https://ai-sdk.dev/docs")
            meta, _ = dossier.load("ai-sdk-docs")
            meta["status"] = "ready"
            dossier.save("ai-sdk-docs", meta)
            assert dossier.load("ai-sdk-docs")[0]["status"] == "ready"
