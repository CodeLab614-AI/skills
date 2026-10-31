from __future__ import annotations

import json

import pytest

import teach_helpers  # noqa: F401
from teach_helpers import run_script
from teach_me_lib import frontmatter, progress, store
from test_exams import ExamBase, exam, graded, questions
from test_topics import stopic, tdata


class ProgBase(ExamBase):
    @pytest.fixture(autouse=True)
    def _prog_setup(self, _exam_setup):
        code, out = run_script("save-syllabus", self.did, stdin=json.dumps(
            {"topics": [stopic("alpha"), stopic("beta", depends_on=["alpha"]),
                        stopic("gamma", depends_on=["beta"])]}))
        assert code == 0, out

    def prog_cmd(self, *a, stdin=None):
        return run_script("progress", self.did, *a, stdin=stdin)

    def do_exam(self, slug, score):
        qs = questions()
        code, out = self.save(exam(graded(qs, score), slug=slug))
        assert code == 0, out
        return out

    def statuses(self):
        code, out = self.prog_cmd("show")
        assert code == 0, out
        return {t["slug"]: t["status"] for t in out["topics"]}


class TestProgress(ProgBase):
    def test_fail_then_continue_marks_pending(self):
        self.do_exam("alpha", 20)
        assert self.statuses()["alpha"] == "pending"
        code, out = self.prog_cmd("show")
        assert out["pending"] == ["alpha"]

    def test_fail_never_downgrades_passed(self):
        self.do_exam("alpha", 90)
        assert self.statuses()["alpha"] == "passed"
        self.do_exam("alpha", 10)
        assert self.statuses()["alpha"] == "passed"

    def test_skip_listed(self):
        code, out = self.prog_cmd("skip", "--topic", "beta")
        assert code == 0, out
        assert out["changed"]
        code, out = self.prog_cmd("show")
        assert out["skipped"] == ["beta"]
        assert self.statuses()["beta"] == "skipped"
        body = (self.base / self.n["progress"]).read_text(encoding="utf-8")
        assert "Beta" in body

    def test_skip_keeps_passed(self):
        self.do_exam("alpha", 90)
        code, out = self.prog_cmd("skip", "--topic", "alpha")
        assert code == 0, out
        assert not out["changed"]
        assert self.statuses()["alpha"] == "passed"

    def test_at_risk_when_prerequisite_pending(self):
        self.do_exam("alpha", 20)
        code, out = self.prog_cmd("start", "--topic", "beta")
        assert code == 0, out
        assert out["at_risk"] == ["alpha"]
        assert out["status"] == "in_progress"
        code, out = self.prog_cmd("show")
        assert out["current"] == "beta"
        by = {t["slug"]: t for t in out["topics"]}
        assert by["beta"]["at_risk"] == ["alpha"]
        assert by["gamma"]["at_risk"] == []
        assert [t["number"] for t in out["topics"]] == [1, 2, 3]

    def test_start_keeps_passed_and_unskips(self):
        self.do_exam("alpha", 90)
        self.prog_cmd("start", "--topic", "alpha")
        assert self.statuses()["alpha"] == "passed"
        self.prog_cmd("skip", "--topic", "beta")
        self.prog_cmd("start", "--topic", "beta")
        assert self.statuses()["beta"] == "in_progress"

    def test_progress_on_set_aside_topic_blocks(self):
        run_script("set-mode", self.did, "use-internals")
        run_script("save-syllabus", self.did, stdin=json.dumps(
            {"topics": [stopic("alpha"), stopic("core", part="internals")]}))
        run_script("set-mode", self.did, "use")
        for action in ("start", "skip", "doubt"):
            code, out = self.prog_cmd(action, "--topic", "core", stdin="why")
            assert (code, out["error"]["code"]) == (2, "part_not_in_mode"), action
        assert self.prog_cmd("outdated", "--topic", "core")[0] == 0
        assert self.prog_cmd("start", "--topic", "alpha")[0] == 0

    def _internals_pending(self):
        """use-internals dossier: alpha (use) and core (internals, failed exam -> pending)."""
        run_script("set-mode", self.did, "use-internals")
        run_script("save-syllabus", self.did, stdin=json.dumps(
            {"topics": [stopic("alpha"), stopic("core", part="internals")]}))
        self.do_exam("core", 20)
        assert self.prog_cmd("show")[1]["pending"] == ["core"]

    def test_set_aside_topics_are_not_pending(self):
        self._internals_pending()
        self.prog_cmd("skip", "--topic", "alpha")
        run_script("set-mode", self.did, "use")
        code, out = self.prog_cmd("show")
        assert code == 0, out
        assert [t["slug"] for t in out["topics"]] == ["alpha"]
        assert out["pending"] == []
        assert out["skipped"] == ["alpha"]
        assert out["set_aside"] == ["core"]
        self.prog_cmd("touch")  # progress.md is rewritten on the next progress write
        assert self.prog()["topics"]["core"]["status"] == "pending"
        assert len(self.prog()["topics"]["core"]["attempts"]) == 1
        body = (self.base / self.n["progress"]).read_text(encoding="utf-8")
        assert "Set aside" in body
        assert body.count("Core") == 1

    def test_set_aside_does_not_trigger_needs_review(self):
        self._internals_pending()
        progress.touch(self.did, today="2026-01-01")
        assert progress.show(self.did, today="2026-01-02")["needs_review"]
        run_script("set-mode", self.did, "use")
        assert not progress.show(self.did, today="2026-01-02")["needs_review"]
        assert not progress.touch(self.did, today="2026-01-03")["needs_review"]

    def test_switching_back_restores_the_topics(self):
        self._internals_pending()
        run_script("set-mode", self.did, "use")
        run_script("set-mode", self.did, "use-internals")
        code, out = self.prog_cmd("show")
        assert out["pending"] == ["core"]
        assert out["set_aside"] == []
        assert len(self.prog()["topics"]["core"]["attempts"]) == 1

    def test_needs_review_next_day(self):
        self.do_exam("alpha", 90)
        code, out = self.prog_cmd("touch")
        assert code == 0, out
        assert not out["needs_review"]
        assert self.prog()["last_session"] == progress.today()
        assert not progress.show(self.did)["needs_review"]
        assert progress.show(self.did, today="2999-01-01")["needs_review"]
        res = progress.touch(self.did, today="2999-01-01")
        assert res["needs_review"]
        assert res["previous_session"] == progress.today()
        assert self.prog()["last_session"] == "2999-01-01"

    def test_needs_review_requires_seen_topic(self):
        progress.touch(self.did, today="2026-01-01")
        assert not progress.show(self.did, today="2026-01-02")["needs_review"]

    def test_progress_survives_new_syllabus_by_slug(self):
        self.do_exam("alpha", 90)
        self.do_exam("beta", 20)
        code, out = run_script("save-syllabus", self.did, stdin=json.dumps(
            {"topics": [stopic("zeta"), stopic("beta"), stopic("alpha")]}))
        assert code == 0, out
        code, out = self.prog_cmd("show")
        assert [t["slug"] for t in out["topics"]] == ["zeta", "beta", "alpha"]
        st = self.statuses()
        assert (st["alpha"], st["beta"], st["zeta"]) == ("passed", "pending", "not_started")
        code, out = run_script("save-syllabus", self.did, stdin=json.dumps(
            {"topics": [stopic("beta")]}))
        assert list(self.statuses()) == ["beta"]
        assert self.prog()["topics"]["alpha"]["status"] == "passed"

    def test_doubt_saved(self):
        code, out = self.prog_cmd("doubt", "--topic", "alpha", stdin="  why is it async?\n")
        assert code == 0, out
        assert self.prog()["topics"]["alpha"]["doubts"] == ["why is it async?"]

    def test_doubt_too_long_rejected(self):
        code, out = self.prog_cmd("doubt", "--topic", "alpha", stdin="x" * 501)
        assert (code, out["error"]["code"]) == (2, "bad_input")
        code, out = self.prog_cmd("doubt", "--topic", "alpha", stdin="   \n")
        assert (code, out["error"]["code"]) == (2, "bad_input")
        code, out = self.prog_cmd("doubt", "--topic", "alpha", stdin="x" * 500)
        assert code == 0, out

    def test_topic_required_and_validated(self):
        for action in ("start", "doubt", "skip", "outdated"):
            code, out = self.prog_cmd(action, stdin="hi")
            assert (code, out["error"]["code"]) == (2, "bad_input"), action
            code, out = self.prog_cmd(action, "--topic", "nope", stdin="hi")
            assert (code, out["error"]["code"]) == (2, "topic_not_found"), action

    def test_bad_action_and_no_syllabus(self):
        code, out = self.prog_cmd("explode")
        assert (code, out["error"]["code"]) == (2, "bad_input")
        (self.base / self.n["syllabus"]).unlink()
        code, out = self.prog_cmd("show")
        assert (code, out["error"]["code"]) == (2, "bad_input")

    def test_outdated_cleared_by_save_topic(self):
        code, out = self.prog_cmd("outdated", "--topic", "alpha")
        assert code == 0, out
        code, out = self.prog_cmd("show")
        assert {t["slug"]: t for t in out["topics"]}["alpha"]["outdated"]
        code, out = run_script("save-topic", self.did, stdin=json.dumps(tdata("alpha")))
        assert code == 0, out
        code, out = self.prog_cmd("show")
        assert not {t["slug"]: t for t in out["topics"]}["alpha"]["outdated"]

    def test_show_is_read_only(self):
        code, out = self.prog_cmd("show")
        assert code == 0, out
        assert not ((self.base / self.n["progress"]).exists() and
                         "alpha" in self.prog()["topics"])
        assert out["mode"] == "use"

    def test_body_table(self):
        self.do_exam("alpha", 90)
        body = (self.base / self.n["progress"]).read_text(encoding="utf-8")
        assert "| 1 | Alpha | passed |" in body
        assert "| Outdated |" in body


class TestProgressEs(ProgBase):
    lang = "es"

    def test_body_spanish(self):
        self.prog_cmd("skip", "--topic", "alpha")
        body = (self.base / self.n["progress"]).read_text(encoding="utf-8")
        assert "Saltados" in body
        assert "Desactualizado" in body
