from __future__ import annotations

import json

import pytest

import teach_helpers  # noqa: F401
from teach_helpers import run_script
from teach_me_lib import docs, dossier, frontmatter, modes, store, topics
from teach_me_lib.errors import BlockedError

URL = "https://sdk.example.com/docs/generate"
KINDS = ["problem", "idea", "example", "predict", "internals", "pitfalls"]


def make(lang="en", site="https://sdk.example.com/docs"):
    code, out = run_script("init", site, "--lang", lang)
    assert code == 0, out
    did = out["id"]
    meta, _ = dossier.load(did)
    meta["version"] = {"label": "v1.0"}
    dossier.save(did, meta)
    n = meta["names"]
    base = store.dossier_dir(did)
    pages = base / n["sources_dir"] / n["docs_dir"]
    pages.mkdir(parents=True, exist_ok=True)
    (pages / docs._file_name(URL)).write_text(frontmatter.dump(
        {"teach_me": "page", "url": URL},
        "generateText returns a string.\n\nIt streams when asked.\n"), encoding="utf-8")
    cdir = base / n["sources_dir"] / n["code_dir"] / "v1.0"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "a.ts").write_text("line one\nline two\nline three\n", encoding="utf-8")
    return did, meta, base


def cite(quote="generateText returns a string"):
    return {"kind": "doc", "url": URL, "quote": quote}


def stopic(slug, title=None, depends_on=(), sources=None, part="use"):
    return {"slug": slug, "title": title or slug.title(), "objective": "obj " + slug,
            "why_here": "because " + slug, "part": part, "depends_on": list(depends_on),
            "sources": sources if sources is not None else [cite()]}


def blocks(**over):
    out = []
    for k in KINDS:
        claims = [{"text": "%s fact" % k, "kind": "fact", "support": "supported",
                   "sources": [cite()]}]
        out.append({"kind": k, "claims": claims})
    out[2]["code"] = "const x = 1;"
    out[2]["code_support"] = "supported"
    for k, v in over.items():
        for b in out:
            if b["kind"] == k:
                b.update(v)
    return out


def tdata(slug, **kw):
    d = {"slug": slug, "support_checked_in": "subagent", "blocks": blocks()}
    d.update(kw)
    return d


def sj(d):
    return json.dumps(d)


class TopicsBase:
    @pytest.fixture(autouse=True)
    def _topics_setup(self, home):
        self.home = home
        self.did, self.meta, self.base = make()
        self.n = self.meta["names"]

    def syl(self, *tps):
        return run_script("save-syllabus", self.did, stdin=sj({"topics": list(tps)}))

    def topic(self, d):
        return run_script("save-topic", self.did, stdin=sj(d))

    def tfiles(self):
        return sorted(p.name for p in (self.base / self.n["topics_dir"]).glob("*.md"))


class TestSyllabus(TopicsBase):
    def test_syllabus_numbering_ready_and_parts_done(self):
        code, out = self.syl(stopic("intro"), stopic("streams", depends_on=["intro"]))
        assert code == 0, out
        meta, body = frontmatter.parse((self.base / self.n["syllabus"]).read_text(encoding="utf-8"))
        assert meta["teach_me"] == "syllabus"
        assert [t["number"] for t in meta["topics"]] == [1, 2]
        assert meta["topics"][0]["sources"][0]["excerpt"] == "generateText returns a string"
        assert "[[01-intro]]" in body
        assert "[[02-streams]]" in body
        assert "because intro" in body
        prof, _ = dossier.load(self.did)
        assert prof["status"] == "ready"
        assert prof["parts_done"] == ["use"]
        assert "syllabus" in prof["phases"]
        self.syl(stopic("intro"))
        assert dossier.load(self.did)[0]["parts_done"] == ["use"]

    def test_depends_on_must_come_before(self):
        code, out = self.syl(stopic("a", depends_on=["b"]), stopic("b"))
        assert (code, out["error"]["code"]) == (2, "bad_input")
        code, out = self.syl(stopic("a", depends_on=["a"]))
        assert (code, out["error"]["code"]) == (2, "bad_input")

    def test_bad_slug_duplicate_and_empty(self):
        for tps in ([stopic("Bad_Slug")], [stopic("a"), stopic("a")], []):
            code, out = self.syl(*tps)
            assert (code, out["error"]["code"]) == (2, "bad_input")
        assert not (self.base / self.n["syllabus"]).exists()

    def test_internals_part_rejected_in_use_mode(self):
        code, out = self.syl(stopic("a", part="internals"))
        assert (code, out["error"]["code"]) == (2, "part_not_in_mode")

    def test_syllabus_with_unverified_source_rejected(self):
        code, out = self.syl(stopic("ok"), stopic("bad", sources=[cite("never said this")]))
        assert (code, out["error"]["code"]) == (2, "bad_input")
        assert "bad" in out["error"]["message"]
        assert "quote_not_found" in out["error"]["message"]
        assert not (self.base / self.n["syllabus"]).exists()
        code, out = self.syl(stopic("nosrc", sources=[]))
        assert (code, out["error"]["code"]) == (2, "bad_input")

    def test_resave_renumbers_and_renames_files(self):
        self.syl(stopic("a"), stopic("b", depends_on=["a"]))
        assert self.topic(tdata("b"))[0] == 0
        assert self.tfiles() == ["02-b.md"]
        exam = self.base / self.n["exams_dir"] / "02-b-attempt-1.md"
        exam.write_text("x", encoding="utf-8")
        code, out = self.syl(stopic("c"), stopic("b"), stopic("d", depends_on=["b"]))
        assert code == 0, out
        assert self.tfiles() == ["02-b.md"]
        self.syl(stopic("z"), stopic("a"), stopic("b", depends_on=["a"]), stopic("c"))
        assert self.tfiles() == ["03-b.md"]
        meta, body = frontmatter.parse((self.base / self.n["topics_dir"] / "03-b.md").read_text(encoding="utf-8"))
        assert meta["number"] == 3
        assert "# 03. B" in body
        assert "[[02-a]]" in body
        assert exam.exists()

    def test_resave_keeps_files_of_dropped_topics(self):
        self.syl(stopic("a"), stopic("b"))
        self.topic(tdata("b"))
        self.syl(stopic("a"))
        assert self.tfiles() == ["02-b.md"]

    def test_syllabus_two_parts_in_use_internals(self):
        run_script("set-mode", self.did, "use-internals")
        code, out = self.syl(stopic("a"), stopic("b"), stopic("c", part="internals"))
        assert code == 0, out
        meta, body = frontmatter.parse((self.base / self.n["syllabus"]).read_text(encoding="utf-8"))
        assert [t["part"] for t in meta["topics"]] == ["use", "use", "internals"]
        assert meta["topics"][2]["number"] == 3
        assert body.index("How to use it") < body.index("01. A")
        assert body.index("02. B") < body.index("How it is built")
        assert body.index("How it is built") < body.index("03. C")
        assert dossier.load(self.did)[0]["parts_done"] == ["use", "built_syllabus"]

    def test_syllabus_body_spanish_headings(self):
        did, _meta, base = make("es", "https://otro.example.org/docs")
        run_script("set-mode", did, "use-internals")
        code, out = run_script("save-syllabus", did, stdin=sj(
            {"topics": [stopic("a"), stopic("c", part="internals")]}))
        assert code == 0, out
        names = dossier.load(did)[0]["names"]
        _, body = frontmatter.parse((base / names["syllabus"]).read_text(encoding="utf-8"))
        assert "Cómo se usa" in body
        assert "Cómo está construida" in body

    def test_syllabus_internals_rejected_in_mode_use(self):
        code, out = self.syl(stopic("a"), stopic("c", part="internals"))
        assert (code, out["error"]["code"]) == (2, "part_not_in_mode")

    def test_syllabus_blocked_in_overview_modes(self):
        run_script("set-mode", self.did, "overview")
        code, out = self.syl(stopic("a"))
        assert (code, out["error"]["code"]) == (2, "part_not_in_mode")

    def test_syllabus_use_after_internals_rejected(self):
        run_script("set-mode", self.did, "use-internals")
        code, out = self.syl(stopic("c", part="internals"), stopic("a"))
        assert (code, out["error"]["code"]) == (2, "bad_input")
        assert "use topics come first" in out["error"]["message"]

    def test_syllabus_internals_without_public_code(self):
        run_script("set-mode", self.did, "use-internals")
        meta, _ = dossier.load(self.did)
        meta["public_code"] = False
        dossier.save(self.did, meta)
        code, out = self.syl(stopic("a"), stopic("c", part="internals"))
        assert (code, out["error"]["code"]) == (2, "no_public_code")

    def _inventory(self, layout):
        final = self.base / self.n["sources_dir"] / self.n["code_dir"] / "v1.0"
        (final / "_inventory.md").write_text(frontmatter.dump(
            {"teach_me": "index", "layout": layout, "files": [{"path": "a.ts"}]}, "# index\n"),
            encoding="utf-8")

    def test_syllabus_internals_blocks_monorepo_code(self):
        run_script("set-mode", self.did, "use-internals")
        self._inventory("monorepo")
        code, out = self.syl(stopic("a"), stopic("c", part="internals"))
        assert (code, out["error"]["code"]) == (2, "code_not_full")
        assert "--full" in out["error"]["message"]
        assert self.syl(stopic("a"))[0] == 0  # no internals topic sent: allowed
        self._inventory("full")
        assert self.syl(stopic("a"), stopic("c", part="internals"))[0] == 0

    def test_internals_syllabus_without_internals_topics_clears_built_syllabus(self):
        run_script("set-mode", self.did, "use-internals")
        assert self.syl(stopic("a"), stopic("c", part="internals"))[0] == 0
        assert dossier.load(self.did)[0]["parts_done"] == ["use", "built_syllabus"]
        assert self.syl(stopic("a"))[0] == 0
        meta, _ = dossier.load(self.did)
        assert meta["parts_done"] == ["use"]
        assert modes.missing_parts(meta) == ["built_syllabus"]

    def test_appending_internals_keeps_use_numbers_and_progress(self):
        self.syl(stopic("a"), stopic("b"), stopic("c"))
        assert self.topic(tdata("b"))[0] == 0
        prog = self.base / self.n["progress"]
        head = {"teach_me": "progress", "current": None, "last_session": None, "reviews": [],
                "topics": {"b": {"status": "passed", "best": 90, "asked": [], "outdated": False,
                                 "attempts": [{"attempt": 1, "average": 90, "passed": True,
                                               "date": "2026-01-01"}],
                                 "doubts": ["why?"]}}}
        prog.write_text(frontmatter.dump(head, "x"), encoding="utf-8")
        run_script("set-mode", self.did, "use-internals")
        code, out = self.syl(stopic("a"), stopic("b"), stopic("c"),
                             stopic("d", part="internals"), stopic("e", part="internals"))
        assert code == 0, out
        assert self.tfiles() == ["02-b.md"]
        code, shown = run_script("progress", self.did, "show")
        assert [(t["number"], t["slug"]) for t in shown["topics"]][:3] == \
                         [(1, "a"), (2, "b"), (3, "c")]
        assert shown["topics"][1]["status"] == "passed"
        t = frontmatter.parse(prog.read_text(encoding="utf-8"))[0]["topics"]["b"]
        assert (len(t["attempts"]), t["doubts"]) == (1, ["why?"])

    def test_resave_keeps_set_aside_topics(self):
        run_script("set-mode", self.did, "use-internals")
        self.syl(stopic("a"), stopic("c", part="internals"), )
        run_script("set-mode", self.did, "use")
        code, out = self.syl(stopic("a"), stopic("b"))
        assert code == 0, out
        meta, body = frontmatter.parse((self.base / self.n["syllabus"]).read_text(encoding="utf-8"))
        assert [(t["number"], t["slug"], t["part"]) for t in meta["topics"]] == \
                         [(1, "a", "use"), (2, "b", "use"), (3, "c", "internals")]
        assert "[[03-c]]" in body
        assert [t["slug"] for t in out["topics"]] == ["a", "b"]
        assert dossier.load(self.did)[0]["parts_done"] == ["use", "built_syllabus"]

    def test_save_topic_on_set_aside_topic_blocks(self):
        run_script("set-mode", self.did, "use-internals")
        self.syl(stopic("a"), stopic("c", part="internals"))
        run_script("set-mode", self.did, "use")
        code, out = self.topic(tdata("c"))
        assert (code, out["error"]["code"]) == (2, "part_not_in_mode")
        assert self.tfiles() == []
        assert self.topic(tdata("a"))[0] == 0


class TestTopic(TopicsBase):
    @pytest.fixture(autouse=True)
    def _topic_setup(self, _topics_setup):
        assert self.syl(stopic("intro"), stopic("streams", depends_on=["intro"]))[0] == 0

    def err(self, d, code_expected="bad_input"):
        code, out = self.topic(d)
        assert (code, out["error"]["code"]) == (2, code_expected), out
        assert self.tfiles() == []
        return out

    def test_topic_requires_six_blocks_in_order(self):
        b = blocks()
        self.err(tdata("intro", blocks=b[:5]))
        self.err(tdata("intro", blocks=[b[1], b[0]] + b[2:]))
        b2 = blocks()
        b2[0]["claims"] = []
        self.err(tdata("intro", blocks=b2))
        b3 = blocks()
        b3[0]["code"] = 5
        self.err(tdata("intro", blocks=b3))

    def test_topic_not_found_and_no_syllabus(self):
        self.err(tdata("nope"), "topic_not_found")
        code, out = self.topic(tdata("intro"))
        assert code == 0, out
        other, _, _ = make("en", "https://other.example.com/docs")
        code, out = run_script("save-topic", other, stdin=sj(tdata("intro")))
        assert (code, out["error"]["code"]) == (2, "bad_input")

    def test_topic_requires_support_checked_in(self):
        d = tdata("intro")
        del d["support_checked_in"]
        self.err(d, "support_not_checked")
        self.err(tdata("intro", support_checked_in="nobody"), "support_not_checked")
        b = blocks()
        del b[1]["claims"][0]["support"]
        out = self.err(tdata("intro", blocks=b), "support_not_checked")
        assert "idea" in out["error"]["message"]
        b = blocks()
        b[0]["claims"][0]["kind"] = "pedagogical"
        b[0]["claims"][0]["sources"] = []
        del b[0]["claims"][0]["support"]
        assert self.topic(tdata("intro", blocks=b))[0] == 0

    def test_topic_rejects_unsupported_claims(self):
        b = blocks()
        b[3]["claims"][0]["support"] = "unsupported"
        out = self.err(tdata("intro", blocks=b), "unsupported_claims")
        assert "predict" in out["error"]["message"]
        b = blocks()
        b[3]["claims"][0].update(kind="pedagogical", support="unsupported")
        self.err(tdata("intro", blocks=b), "unsupported_claims")

    def test_code_needs_support_verdict(self):
        b = blocks()
        del b[2]["code_support"]
        b[3]["code"] = "print(1)"
        out = self.err(tdata("intro", blocks=b), "support_not_checked")
        assert "example, predict" in out["error"]["message"]

    def test_code_unsupported_is_refused(self):
        b = blocks()
        b[2]["code_support"] = "unsupported"
        out = self.err(tdata("intro", blocks=b), "unsupported_claims")
        assert "example" in out["error"]["message"]

    def test_missing_verdicts_come_before_unsupported(self):
        b = blocks()
        b[2]["code_support"] = "unsupported"
        b[3]["code"] = "print(1)"
        self.err(tdata("intro", blocks=b), "support_not_checked")

    def test_code_supported_is_saved_with_verdict(self):
        code, out = self.topic(tdata("intro"))
        assert code == 0, out
        meta, _ = frontmatter.parse((self.base / self.n["topics_dir"] / "01-intro.md").read_text(encoding="utf-8"))
        ex = meta["blocks"][2]
        assert (ex["code"], ex["code_support"]) == ("const x = 1;", "supported")

    def test_code_support_ignored_without_code(self):
        b = blocks()
        b[0]["code_support"] = "unsupported"
        b[3]["code"] = ""
        code, out = self.topic(tdata("intro", blocks=b))
        assert code == 0, out
        meta, _ = frontmatter.parse((self.base / self.n["topics_dir"] / "01-intro.md").read_text(encoding="utf-8"))
        assert "code_support" not in meta["blocks"][0]
        assert "code_support" not in meta["blocks"][3]
        assert "code" not in meta["blocks"][3]

    def test_topic_rejects_unverified_citation(self):
        b = blocks()
        b[4]["claims"][0]["sources"] = [cite("made up sentence")]
        out = self.err(tdata("intro", blocks=b), "unverified_claims")
        assert "internals" in out["error"]["message"]
        assert "quote_not_found" in out["error"]["message"]
        b = blocks()
        b[4]["claims"][0]["sources"] = []
        self.err(tdata("intro", blocks=b), "unverified_claims")

    def test_topic_md_has_excerpts_and_wikilinks(self):
        b = blocks()
        b[2]["claims"].append({"text": "from code", "kind": "fact", "support": "supported",
                               "sources": [{"kind": "code", "path": "a.ts",
                                            "line_start": 1, "line_end": 2}]})
        code, out = self.topic(tdata("streams", blocks=b))
        assert code == 0, out
        meta, body = frontmatter.parse((self.base / self.n["topics_dir"] / "02-streams.md").read_text(encoding="utf-8"))
        assert meta["teach_me"] == "topic"
        assert (meta["number"], meta["slug"], meta["depends_on"]) == (2, "streams", ["intro"])
        assert meta["support_checked_in"] == "subagent"
        assert "saved_at" in meta
        assert [x["kind"] for x in meta["blocks"]] == KINDS
        assert meta["blocks"][0]["claims"][0]["sources"][0]["excerpt"] == \
                         "generateText returns a string"
        assert "# 02. Streams" in body
        assert "[[01-intro]]" in body
        assert "[[syllabus]]" in body
        assert "> generateText returns a string" in body
        assert URL in body
        assert "> line one\n> line two" in body
        assert "a.ts:1-2" in body
        assert "```\nconst x = 1;\n```" in body
        assert "## The problem" in body

    def test_topic_filename_in_dossier_language(self):
        did, meta, base = make("es", "https://otro.example.org/docs")
        n = meta["names"]
        run_script("save-syllabus", did, stdin=sj({"topics": [stopic("intro")]}))
        code, out = run_script("save-topic", did, stdin=sj(tdata("intro")))
        assert code == 0, out
        p = base / n["topics_dir"] / "01-intro.md"
        assert p.exists()
        assert n["topics_dir"] == "temas"
        _, body = frontmatter.parse(p.read_text(encoding="utf-8"))
        assert "## El problema" in body
        assert "[[temario]]" in body

    def test_resave_overwrites_and_show_topic(self):
        assert self.topic(tdata("intro"))[0] == 0
        b = blocks()
        b[0]["claims"][0]["text"] = "changed"
        assert self.topic(tdata("intro", blocks=b))[0] == 0
        assert self.tfiles() == ["01-intro.md"]
        code, out = run_script("show-topic", self.did, "intro")
        assert code == 0, out
        assert out["ok"]
        assert out["blocks"][0]["claims"][0]["text"] == "changed"
        code, out = run_script("show-topic", self.did, "streams")
        assert (code, out["error"]["code"]) == (2, "topic_not_found")
