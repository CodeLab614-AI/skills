from __future__ import annotations

import json
import unittest

import helpers  # noqa: F401
from helpers import TempHome, run_script
from teach_me_lib import frontmatter, progress, store
from test_exams import ExamBase, exam, graded, questions
from test_topics import stopic, tdata


class ProgBase(ExamBase):
    def setUp(self):
        super().setUp()
        code, out = run_script("save-syllabus", self.did, stdin=json.dumps(
            {"topics": [stopic("alpha"), stopic("beta", depends_on=["alpha"]),
                        stopic("gamma", depends_on=["beta"])]}))
        assert code == 0, out

    def prog_cmd(self, *a, stdin=None):
        return run_script("progress", self.did, *a, stdin=stdin)

    def do_exam(self, slug, score):
        qs = questions()
        code, out = self.save(exam(graded(qs, score), slug=slug))
        self.assertEqual(code, 0, out)
        return out

    def statuses(self):
        code, out = self.prog_cmd("show")
        self.assertEqual(code, 0, out)
        return {t["slug"]: t["status"] for t in out["topics"]}


class TestProgress(ProgBase):
    def test_fail_then_continue_marks_pending(self):
        self.do_exam("alpha", 20)
        self.assertEqual(self.statuses()["alpha"], "pending")
        code, out = self.prog_cmd("show")
        self.assertEqual(out["pending"], ["alpha"])

    def test_fail_never_downgrades_passed(self):
        self.do_exam("alpha", 90)
        self.assertEqual(self.statuses()["alpha"], "passed")
        self.do_exam("alpha", 10)
        self.assertEqual(self.statuses()["alpha"], "passed")

    def test_skip_listed(self):
        code, out = self.prog_cmd("skip", "--topic", "beta")
        self.assertEqual(code, 0, out)
        self.assertTrue(out["changed"])
        code, out = self.prog_cmd("show")
        self.assertEqual(out["skipped"], ["beta"])
        self.assertEqual(self.statuses()["beta"], "skipped")
        body = (self.base / self.n["progress"]).read_text(encoding="utf-8")
        self.assertIn("Beta", body)

    def test_skip_keeps_passed(self):
        self.do_exam("alpha", 90)
        code, out = self.prog_cmd("skip", "--topic", "alpha")
        self.assertEqual(code, 0, out)
        self.assertFalse(out["changed"])
        self.assertEqual(self.statuses()["alpha"], "passed")

    def test_at_risk_when_prerequisite_pending(self):
        self.do_exam("alpha", 20)
        code, out = self.prog_cmd("start", "--topic", "beta")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["at_risk"], ["alpha"])
        self.assertEqual(out["status"], "in_progress")
        code, out = self.prog_cmd("show")
        self.assertEqual(out["current"], "beta")
        by = {t["slug"]: t for t in out["topics"]}
        self.assertEqual(by["beta"]["at_risk"], ["alpha"])
        self.assertEqual(by["gamma"]["at_risk"], [])
        self.assertEqual([t["number"] for t in out["topics"]], [1, 2, 3])

    def test_start_keeps_passed_and_unskips(self):
        self.do_exam("alpha", 90)
        self.prog_cmd("start", "--topic", "alpha")
        self.assertEqual(self.statuses()["alpha"], "passed")
        self.prog_cmd("skip", "--topic", "beta")
        self.prog_cmd("start", "--topic", "beta")
        self.assertEqual(self.statuses()["beta"], "in_progress")

    def test_progress_on_set_aside_topic_blocks(self):
        run_script("set-mode", self.did, "use-internals")
        run_script("save-syllabus", self.did, stdin=json.dumps(
            {"topics": [stopic("alpha"), stopic("core", part="internals")]}))
        run_script("set-mode", self.did, "use")
        for action in ("start", "skip", "doubt"):
            code, out = self.prog_cmd(action, "--topic", "core", stdin="why")
            self.assertEqual((code, out["error"]["code"]), (2, "part_not_in_mode"), action)
        self.assertEqual(self.prog_cmd("outdated", "--topic", "core")[0], 0)
        self.assertEqual(self.prog_cmd("start", "--topic", "alpha")[0], 0)

    def _internals_pending(self):
        """use-internals dossier: alpha (use) and core (internals, failed exam -> pending)."""
        run_script("set-mode", self.did, "use-internals")
        run_script("save-syllabus", self.did, stdin=json.dumps(
            {"topics": [stopic("alpha"), stopic("core", part="internals")]}))
        self.do_exam("core", 20)
        self.assertEqual(self.prog_cmd("show")[1]["pending"], ["core"])

    def test_set_aside_topics_are_not_pending(self):
        self._internals_pending()
        self.prog_cmd("skip", "--topic", "alpha")
        run_script("set-mode", self.did, "use")
        code, out = self.prog_cmd("show")
        self.assertEqual(code, 0, out)
        self.assertEqual([t["slug"] for t in out["topics"]], ["alpha"])
        self.assertEqual(out["pending"], [])
        self.assertEqual(out["skipped"], ["alpha"])
        self.assertEqual(out["set_aside"], ["core"])
        self.prog_cmd("touch")  # progress.md is rewritten on the next progress write
        self.assertEqual(self.prog()["topics"]["core"]["status"], "pending")
        self.assertEqual(len(self.prog()["topics"]["core"]["attempts"]), 1)
        body = (self.base / self.n["progress"]).read_text(encoding="utf-8")
        self.assertIn("Set aside", body)
        self.assertEqual(body.count("Core"), 1)

    def test_set_aside_does_not_trigger_needs_review(self):
        self._internals_pending()
        progress.touch(self.did, today="2026-01-01")
        self.assertTrue(progress.show(self.did, today="2026-01-02")["needs_review"])
        run_script("set-mode", self.did, "use")
        self.assertFalse(progress.show(self.did, today="2026-01-02")["needs_review"])
        self.assertFalse(progress.touch(self.did, today="2026-01-03")["needs_review"])

    def test_switching_back_restores_the_topics(self):
        self._internals_pending()
        run_script("set-mode", self.did, "use")
        run_script("set-mode", self.did, "use-internals")
        code, out = self.prog_cmd("show")
        self.assertEqual(out["pending"], ["core"])
        self.assertEqual(out["set_aside"], [])
        self.assertEqual(len(self.prog()["topics"]["core"]["attempts"]), 1)

    def test_needs_review_next_day(self):
        self.do_exam("alpha", 90)
        code, out = self.prog_cmd("touch")
        self.assertEqual(code, 0, out)
        self.assertFalse(out["needs_review"])
        self.assertEqual(self.prog()["last_session"], progress.today())
        self.assertFalse(progress.show(self.did)["needs_review"])
        self.assertTrue(progress.show(self.did, today="2999-01-01")["needs_review"])
        res = progress.touch(self.did, today="2999-01-01")
        self.assertTrue(res["needs_review"])
        self.assertEqual(res["previous_session"], progress.today())
        self.assertEqual(self.prog()["last_session"], "2999-01-01")

    def test_needs_review_requires_seen_topic(self):
        progress.touch(self.did, today="2026-01-01")
        self.assertFalse(progress.show(self.did, today="2026-01-02")["needs_review"])

    def test_progress_survives_new_syllabus_by_slug(self):
        self.do_exam("alpha", 90)
        self.do_exam("beta", 20)
        code, out = run_script("save-syllabus", self.did, stdin=json.dumps(
            {"topics": [stopic("zeta"), stopic("beta"), stopic("alpha")]}))
        self.assertEqual(code, 0, out)
        code, out = self.prog_cmd("show")
        self.assertEqual([t["slug"] for t in out["topics"]], ["zeta", "beta", "alpha"])
        st = self.statuses()
        self.assertEqual((st["alpha"], st["beta"], st["zeta"]), ("passed", "pending", "not_started"))
        code, out = run_script("save-syllabus", self.did, stdin=json.dumps(
            {"topics": [stopic("beta")]}))
        self.assertEqual(list(self.statuses()), ["beta"])
        self.assertEqual(self.prog()["topics"]["alpha"]["status"], "passed")

    def test_doubt_saved(self):
        code, out = self.prog_cmd("doubt", "--topic", "alpha", stdin="  why is it async?\n")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.prog()["topics"]["alpha"]["doubts"], ["why is it async?"])

    def test_doubt_too_long_rejected(self):
        code, out = self.prog_cmd("doubt", "--topic", "alpha", stdin="x" * 501)
        self.assertEqual((code, out["error"]["code"]), (2, "bad_input"))
        code, out = self.prog_cmd("doubt", "--topic", "alpha", stdin="   \n")
        self.assertEqual((code, out["error"]["code"]), (2, "bad_input"))
        code, out = self.prog_cmd("doubt", "--topic", "alpha", stdin="x" * 500)
        self.assertEqual(code, 0, out)

    def test_topic_required_and_validated(self):
        for action in ("start", "doubt", "skip", "outdated"):
            code, out = self.prog_cmd(action, stdin="hi")
            self.assertEqual((code, out["error"]["code"]), (2, "bad_input"), action)
            code, out = self.prog_cmd(action, "--topic", "nope", stdin="hi")
            self.assertEqual((code, out["error"]["code"]), (2, "topic_not_found"), action)

    def test_bad_action_and_no_syllabus(self):
        code, out = self.prog_cmd("explode")
        self.assertEqual((code, out["error"]["code"]), (2, "bad_input"))
        (self.base / self.n["syllabus"]).unlink()
        code, out = self.prog_cmd("show")
        self.assertEqual((code, out["error"]["code"]), (2, "bad_input"))

    def test_outdated_cleared_by_save_topic(self):
        code, out = self.prog_cmd("outdated", "--topic", "alpha")
        self.assertEqual(code, 0, out)
        code, out = self.prog_cmd("show")
        self.assertTrue({t["slug"]: t for t in out["topics"]}["alpha"]["outdated"])
        code, out = run_script("save-topic", self.did, stdin=json.dumps(tdata("alpha")))
        self.assertEqual(code, 0, out)
        code, out = self.prog_cmd("show")
        self.assertFalse({t["slug"]: t for t in out["topics"]}["alpha"]["outdated"])

    def test_show_is_read_only(self):
        code, out = self.prog_cmd("show")
        self.assertEqual(code, 0, out)
        self.assertFalse((self.base / self.n["progress"]).exists() and
                         "alpha" in self.prog()["topics"])
        self.assertEqual(out["mode"], "use")

    def test_body_table(self):
        self.do_exam("alpha", 90)
        body = (self.base / self.n["progress"]).read_text(encoding="utf-8")
        self.assertIn("| 1 | Alpha | passed |", body)
        self.assertIn("| Outdated |", body)


class TestProgressEs(ProgBase):
    lang = "es"

    def test_body_spanish(self):
        self.prog_cmd("skip", "--topic", "alpha")
        body = (self.base / self.n["progress"]).read_text(encoding="utf-8")
        self.assertIn("Saltados", body)
        self.assertIn("Desactualizado", body)


if __name__ == "__main__":
    unittest.main()
