from __future__ import annotations

import json
import unittest

import helpers  # noqa: F401
from helpers import TempHome, run_script
from teach_me_lib import frontmatter, progress, store
from test_topics import cite, make, stopic

TYPES5 = ["multiple_choice", "open", "predict", "when_to_use", "open"]


def q(i, typ="open", **over):
    d = {"type": typ, "prompt": " ".join("w%d_%d" % (i, k) for k in range(6)),
         "reference": {"text": "generateText returns a string", "sources": [cite()]}}
    if typ == "multiple_choice":
        d["options"] = ["a", "b", "c", "d"]
        d["correct_option"] = 2
    if typ == "read_yourself":
        d["target"] = {"path": "a.ts", "symbol": "fn"}
    d.update(over)
    return d


def questions(types=None, start=0):
    return [q(start + i, t) for i, t in enumerate(types or TYPES5)]


def graded(qs, score=80):
    out = []
    for x in qs:
        g = dict(x, reference_support="supported", right="r", missing="m")
        if x["type"] == "multiple_choice":
            g.update(answer=2, score=100)
        else:
            g.update(answer="my answer", score=score)
        out.append(g)
    return out


def exam(qs, slug="alpha", **over):
    d = {"slug": slug, "graded_in": "subagent", "support_checked_in": "subagent",
         "questions": qs}
    d.update(over)
    return d


class ExamBase(unittest.TestCase):
    lang = "en"

    def setUp(self):
        self.home = TempHome().__enter__()
        self.addCleanup(self.home.__exit__, None, None, None)
        self.did, self.meta, self.base = make(self.lang)
        self.n = self.meta["names"]
        code, out = run_script("save-syllabus", self.did, stdin=json.dumps(
            {"topics": [stopic("alpha"), stopic("beta")]}))
        assert code == 0, out

    def check(self, qs, slug="alpha"):
        return run_script("exam-check", self.did, slug, stdin=json.dumps({"questions": qs}))

    def save(self, d):
        return run_script("save-exam", self.did, stdin=json.dumps(d))

    def review(self, d):
        return run_script("save-review", self.did, stdin=json.dumps(d))

    def prog(self):
        head, _ = frontmatter.parse((self.base / self.n["progress"]).read_text(encoding="utf-8"))
        return head


class TestSetAside(ExamBase):
    def setUp(self):
        super().setUp()
        run_script("set-mode", self.did, "use-internals")
        code, out = run_script("save-syllabus", self.did, stdin=json.dumps(
            {"topics": [stopic("alpha"), stopic("beta"), stopic("core", part="internals")]}))
        assert code == 0, out
        run_script("set-mode", self.did, "use")

    def test_exam_on_set_aside_topic_blocks(self):
        code, out = self.check(questions(), slug="core")
        self.assertEqual((code, out["error"]["code"]), (2, "part_not_in_mode"))
        code, out = self.save(exam(graded(questions()), slug="core"))
        self.assertEqual((code, out["error"]["code"]), (2, "part_not_in_mode"))
        self.assertEqual(self.check(questions(), slug="alpha")[0], 0)


class TestScoring(ExamBase):
    def test_score_50_is_incorrect_and_51_correct(self):
        qs = questions(["open"] * 5)
        g = graded(qs)
        g[0]["score"] = 50
        g[1]["score"] = 51
        code, out = self.save(exam(g))
        self.assertEqual(code, 0, out)
        self.assertEqual([x["correct"] for x in out["questions"]][:2], [False, True])

    def test_average_exactly_50_not_passed(self):
        g = graded(questions(["open"] * 5), score=50)
        code, out = self.save(exam(g))
        self.assertEqual(code, 0, out)
        self.assertEqual(out["average"], 50.0)
        self.assertFalse(out["passed"])
        self.assertEqual(self.prog()["topics"]["alpha"]["status"], "pending")

    def test_skipped_read_yourself_excluded_from_average(self):
        qs = questions(["open", "open", "open", "open", "read_yourself"])
        g = graded(qs, score=80)
        g[4] = dict(g[4], skipped=True)
        for k in ("score", "answer", "right", "missing"):
            g[4].pop(k)
        code, out = self.save(exam(g))
        self.assertEqual(code, 0, out)
        self.assertEqual(out["average"], 80.0)
        self.assertTrue(out["passed"])

    def test_skip_only_on_read_yourself(self):
        g = graded(questions(["open"] * 5))
        g[0]["skipped"] = True
        code, out = self.save(exam(g))
        self.assertEqual((code, out["error"]["code"]), (2, "bad_input"))

    def test_two_read_yourself_rejected(self):
        qs = questions(["open", "open", "open", "read_yourself", "read_yourself"])
        code, out = self.save(exam(graded(qs)))
        self.assertEqual((code, out["error"]["code"]), (2, "bad_input"))
        code, out = self.check(qs)
        self.assertEqual((code, out["error"]["code"]), (2, "bad_input"))

    def test_question_count_bounds(self):
        for n, ok in ((4, False), (5, True), (8, True), (9, False)):
            qs = questions(["open"] * n)
            code, out = self.check(qs)
            self.assertEqual(code == 0, ok, (n, out))
            code, out = self.save(exam(graded(qs)))
            self.assertEqual(code == 0, ok, (n, out))
            if not ok:
                self.assertEqual(out["error"]["code"], "bad_input")

    def test_multiple_choice_score_must_match_answer(self):
        g = graded(questions())
        g[0]["answer"] = 1  # wrong option but score 100
        code, out = self.save(exam(g))
        self.assertEqual((code, out["error"]["code"]), (2, "score_mismatch"))
        g[0]["score"] = 0
        code, out = self.save(exam(g))
        self.assertEqual(code, 0, out)
        self.assertFalse(out["questions"][0]["correct"])

    def test_shape_rules(self):
        bad = [q(0, "multiple_choice", options=["a", "b", "c"]),
               q(0, "multiple_choice", correct_option=4),
               q(0, "read_yourself", target={"symbol": "x"}),
               q(0, "open", prompt=" "),
               q(0, "open", reference={"text": "t", "sources": []})]
        for item in bad:
            code, out = self.check([item] + questions(start=10)[1:])
            self.assertEqual((code, out["error"]["code"]), (2, "bad_input"), item)

    def test_topic_not_found(self):
        code, out = self.check(questions(), "nope")
        self.assertEqual((code, out["error"]["code"]), (2, "topic_not_found"))

    def test_graded_in_and_support_checked_in(self):
        g = graded(questions())
        code, out = self.save(exam(g, graded_in="me"))
        self.assertEqual((code, out["error"]["code"]), (2, "bad_input"))
        code, out = self.save(exam(g, support_checked_in="me"))
        self.assertEqual((code, out["error"]["code"]), (2, "support_not_checked"))


class TestReferences(ExamBase):
    def test_reference_unsupported_rejected(self):
        g = graded(questions())
        g[1]["reference_support"] = "unsupported"
        code, out = self.save(exam(g))
        self.assertEqual((code, out["error"]["code"]), (2, "unsupported_claims"))
        self.assertIn("1", out["error"]["message"])
        g[1].pop("reference_support")
        code, out = self.save(exam(g))
        self.assertEqual((code, out["error"]["code"]), (2, "support_not_checked"))

    def test_unverified_reference_rejected(self):
        g = graded(questions())
        g[2]["reference"]["sources"] = [cite("this text is not in the page")]
        code, out = self.save(exam(g))
        self.assertEqual((code, out["error"]["code"]), (2, "unverified_claims"))
        self.assertEqual(list(self.base.glob("exams/*")), [])

    def test_check_returns_excerpts(self):
        qs = questions()
        qs[1]["reference"]["sources"] = [cite("nonexistent words here")]
        code, out = self.check(qs)
        self.assertEqual(code, 0, out)
        self.assertTrue(out["references"][0]["verified"])
        self.assertIn("generateText returns a string", out["references"][0]["excerpts"][0])
        self.assertFalse(out["references"][1]["verified"])
        self.assertTrue(out["references"][1]["errors"])


class TestRepetition(ExamBase):
    def test_repeated_exact_after_normalization(self):
        qs = questions()
        self.assertEqual(self.save(exam(graded(qs)))[0], 0)
        again = questions(start=40)
        again[0]["prompt"] = "  **" + qs[0]["prompt"].upper() + "**  "
        code, out = self.check(again)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["repeated"], [0])

    def test_repeated_by_jaccard(self):
        qs = questions()
        qs[0]["prompt"] = "¿Qué devuelve generateText en finalStep?"
        self.assertEqual(self.save(exam(graded(qs)))[0], 0)
        new = questions(start=20)
        new[0]["prompt"] = "¿Qué devuelve generateText dentro de finalStep?"
        new[1]["prompt"] = "¿Qué devuelve streamText al terminar el flujo?"
        code, out = self.check(new)
        self.assertEqual(out["repeated"], [0])

    def test_repeated_within_batch(self):
        qs = questions()
        qs[3]["prompt"] = qs[1]["prompt"]
        code, out = self.check(qs)
        self.assertEqual(out["repeated"], [3])

    def test_same_mix_as_last(self):
        code, out = self.check(questions())
        self.assertFalse(out["same_mix_as_last"])
        self.assertEqual(self.save(exam(graded(questions())))[0], 0)
        code, out = self.check(questions(start=30))
        self.assertTrue(out["same_mix_as_last"])
        code, out = self.check(questions(["open"] * 5, start=30))
        self.assertFalse(out["same_mix_as_last"])
        code, out = self.check(questions(start=30), "beta")
        self.assertFalse(out["same_mix_as_last"])


class TestFiles(ExamBase):
    def test_attempt_numbering(self):
        for k in (1, 2):
            code, out = self.save(exam(graded(questions(start=k * 10))))
            self.assertEqual((code, out["attempt"]), (0, k), out)
        code, out = self.save(exam(graded(questions(start=50)), slug="beta"))
        self.assertEqual(out["attempt"], 1)
        names = sorted(p.name for p in (self.base / self.n["exams_dir"]).iterdir())
        self.assertEqual(names, ["01-alpha-attempt-1.md", "01-alpha-attempt-2.md",
                                 "02-beta-attempt-1.md"])
        self.assertEqual([a["attempt"] for a in self.prog()["topics"]["alpha"]["attempts"]], [1, 2])

    def test_report_md_has_checkmarks_and_percentages(self):
        g = graded(questions())
        g[1]["score"] = 30
        code, out = self.save(exam(g))
        with open(out["report_path"], encoding="utf-8") as fh:
            text = fh.read()
        head, body = frontmatter.parse(text)
        self.assertEqual(head["teach_me"], "exam")
        self.assertEqual(head["slug"], "alpha")
        self.assertIn("✅", body)
        self.assertIn("❌", body)
        self.assertIn("30%", body)
        self.assertIn("generateText returns a string", body)  # literal excerpt
        self.assertIn("Passed", body)
        self.assertIn("Correct answer", body)


class TestSpanish(ExamBase):
    lang = "es"

    def test_names_and_labels(self):
        code, out = self.save(exam(graded(questions())))
        self.assertEqual(code, 0, out)
        self.assertTrue(out["report_path"].endswith("examenes/01-alpha-intento-1.md"))
        with open(out["report_path"], encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("Aprobado", text)
        self.assertIn("Respuesta correcta", text)


class TestReview(ExamBase):
    def test_review_does_not_change_topic_status(self):
        g = graded(questions(["open"] * 5), score=40)
        self.assertEqual(self.save(exam(g))[0], 0)
        before = self.prog()["topics"]["alpha"]
        self.assertEqual((before["status"], before["best"]), ("pending", 40.0))
        rq = [dict(x, slug="alpha") for x in graded(questions(["open", "open"], start=70), 95)]
        code, out = self.review({"graded_in": "subagent", "support_checked_in": "subagent",
                                 "questions": rq})
        self.assertEqual(code, 0, out)
        self.assertEqual(out["average"], 95.0)
        self.assertEqual(out["questions"], [{"slug": "alpha", "correct": True, "score": 95}] * 2)
        after = self.prog()
        self.assertEqual(after["topics"]["alpha"], before)
        self.assertEqual(len(after["reviews"]), 1)
        self.assertEqual(after["reviews"][0]["questions"][0]["slug"], "alpha")
        self.assertEqual(len(list((self.base / self.n["exams_dir"]).iterdir())), 1)

    def test_review_declarations(self):
        rq = [dict(x, slug="alpha") for x in graded(questions(["open", "open"], start=70))]
        code, out = self.review({"questions": rq})
        self.assertEqual((code, out["error"]["code"]), (2, "bad_input"))
        code, out = self.review({"graded_in": "subagent", "support_checked_in": "x",
                                 "questions": rq})
        self.assertEqual((code, out["error"]["code"]), (2, "support_not_checked"))
        code, out = self.review({"graded_in": "same_conversation",
                                 "support_checked_in": "subagent", "questions": rq})
        self.assertEqual(code, 0, out)
        r = self.prog()["reviews"][0]
        self.assertEqual((r["graded_in"], r["support_checked_in"]), ("same_conversation", "subagent"))

    def test_review_bounds_and_slug(self):
        mk = lambda n, slug="alpha": {"graded_in": "subagent", "support_checked_in": "subagent",
                                      "questions": [dict(x, slug=slug) for x in graded(
            questions(["open"] * n, start=80))]}
        for n, ok in ((1, False), (2, True), (3, True), (4, False)):
            code, out = self.review(mk(n))
            self.assertEqual(code == 0, ok, (n, out))
        code, out = self.review(mk(2, "nope"))
        self.assertEqual((code, out["error"]["code"]), (2, "topic_not_found"))

    def test_record_exam_helpers(self):
        self.assertEqual(progress.asked(self.did, "alpha"), [])
        self.assertEqual(self.save(exam(graded(questions(["open"] * 5), 90)))[0], 0)
        self.assertEqual(self.save(exam(graded(questions(["open"] * 5, start=9), 10)))[0], 0)
        t = self.prog()["topics"]["alpha"]
        self.assertEqual((t["status"], t["best"]), ("passed", 90.0))
        self.assertEqual(len(progress.asked(self.did, "alpha")), 10)
        self.assertEqual(self.prog()["teach_me"], "progress")


if __name__ == "__main__":
    unittest.main()
