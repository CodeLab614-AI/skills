from __future__ import annotations

import json

import pytest

import teach_helpers  # noqa: F401
from teach_helpers import run_script
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


class ExamBase:
    lang = "en"

    @pytest.fixture(autouse=True)
    def _exam_setup(self, home):
        self.home = home
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
    @pytest.fixture(autouse=True)
    def _set_aside_setup(self, _exam_setup):
        run_script("set-mode", self.did, "use-internals")
        code, out = run_script("save-syllabus", self.did, stdin=json.dumps(
            {"topics": [stopic("alpha"), stopic("beta"), stopic("core", part="internals")]}))
        assert code == 0, out
        run_script("set-mode", self.did, "use")

    def test_exam_on_set_aside_topic_blocks(self):
        code, out = self.check(questions(), slug="core")
        assert (code, out["error"]["code"]) == (2, "part_not_in_mode")
        code, out = self.save(exam(graded(questions()), slug="core"))
        assert (code, out["error"]["code"]) == (2, "part_not_in_mode")
        assert self.check(questions(), slug="alpha")[0] == 0


class TestScoring(ExamBase):
    def test_score_50_is_incorrect_and_51_correct(self):
        qs = questions(["open"] * 5)
        g = graded(qs)
        g[0]["score"] = 50
        g[1]["score"] = 51
        code, out = self.save(exam(g))
        assert code == 0, out
        assert [x["correct"] for x in out["questions"]][:2] == [False, True]

    def test_average_exactly_50_not_passed(self):
        g = graded(questions(["open"] * 5), score=50)
        code, out = self.save(exam(g))
        assert code == 0, out
        assert out["average"] == 50.0
        assert not out["passed"]
        assert self.prog()["topics"]["alpha"]["status"] == "pending"

    def test_skipped_read_yourself_excluded_from_average(self):
        qs = questions(["open", "open", "open", "open", "read_yourself"])
        g = graded(qs, score=80)
        g[4] = dict(g[4], skipped=True)
        for k in ("score", "answer", "right", "missing"):
            g[4].pop(k)
        code, out = self.save(exam(g))
        assert code == 0, out
        assert out["average"] == 80.0
        assert out["passed"]

    def test_skip_only_on_read_yourself(self):
        g = graded(questions(["open"] * 5))
        g[0]["skipped"] = True
        code, out = self.save(exam(g))
        assert (code, out["error"]["code"]) == (2, "bad_input")

    def test_two_read_yourself_rejected(self):
        qs = questions(["open", "open", "open", "read_yourself", "read_yourself"])
        code, out = self.save(exam(graded(qs)))
        assert (code, out["error"]["code"]) == (2, "bad_input")
        code, out = self.check(qs)
        assert (code, out["error"]["code"]) == (2, "bad_input")

    def test_question_count_bounds(self):
        for n, ok in ((4, False), (5, True), (8, True), (9, False)):
            qs = questions(["open"] * n)
            code, out = self.check(qs)
            assert (code == 0) == ok, (n, out)
            code, out = self.save(exam(graded(qs)))
            assert (code == 0) == ok, (n, out)
            if not ok:
                assert out["error"]["code"] == "bad_input"

    def test_multiple_choice_score_must_match_answer(self):
        g = graded(questions())
        g[0]["answer"] = 1  # wrong option but score 100
        code, out = self.save(exam(g))
        assert (code, out["error"]["code"]) == (2, "score_mismatch")
        g[0]["score"] = 0
        code, out = self.save(exam(g))
        assert code == 0, out
        assert not out["questions"][0]["correct"]

    def test_shape_rules(self):
        bad = [q(0, "multiple_choice", options=["a", "b", "c"]),
               q(0, "multiple_choice", correct_option=4),
               q(0, "read_yourself", target={"symbol": "x"}),
               q(0, "open", prompt=" "),
               q(0, "open", reference={"text": "t", "sources": []})]
        for item in bad:
            code, out = self.check([item] + questions(start=10)[1:])
            assert (code, out["error"]["code"]) == (2, "bad_input"), item

    def test_topic_not_found(self):
        code, out = self.check(questions(), "nope")
        assert (code, out["error"]["code"]) == (2, "topic_not_found")

    def test_graded_in_and_support_checked_in(self):
        g = graded(questions())
        code, out = self.save(exam(g, graded_in="me"))
        assert (code, out["error"]["code"]) == (2, "bad_input")
        code, out = self.save(exam(g, support_checked_in="me"))
        assert (code, out["error"]["code"]) == (2, "support_not_checked")


class TestReferences(ExamBase):
    def test_reference_unsupported_rejected(self):
        g = graded(questions())
        g[1]["reference_support"] = "unsupported"
        code, out = self.save(exam(g))
        assert (code, out["error"]["code"]) == (2, "unsupported_claims")
        assert "1" in out["error"]["message"]
        g[1].pop("reference_support")
        code, out = self.save(exam(g))
        assert (code, out["error"]["code"]) == (2, "support_not_checked")

    def test_unverified_reference_rejected(self):
        g = graded(questions())
        g[2]["reference"]["sources"] = [cite("this text is not in the page")]
        code, out = self.save(exam(g))
        assert (code, out["error"]["code"]) == (2, "unverified_claims")
        assert list(self.base.glob("exams/*")) == []

    def test_check_returns_excerpts(self):
        qs = questions()
        qs[1]["reference"]["sources"] = [cite("nonexistent words here")]
        code, out = self.check(qs)
        assert code == 0, out
        assert out["references"][0]["verified"]
        assert "generateText returns a string" in out["references"][0]["excerpts"][0]
        assert not out["references"][1]["verified"]
        assert out["references"][1]["errors"]


class TestRepetition(ExamBase):
    def test_repeated_exact_after_normalization(self):
        qs = questions()
        assert self.save(exam(graded(qs)))[0] == 0
        again = questions(start=40)
        again[0]["prompt"] = "  **" + qs[0]["prompt"].upper() + "**  "
        code, out = self.check(again)
        assert code == 0, out
        assert out["repeated"] == [0]

    def test_repeated_by_jaccard(self):
        qs = questions()
        qs[0]["prompt"] = "¿Qué devuelve generateText en finalStep?"
        assert self.save(exam(graded(qs)))[0] == 0
        new = questions(start=20)
        new[0]["prompt"] = "¿Qué devuelve generateText dentro de finalStep?"
        new[1]["prompt"] = "¿Qué devuelve streamText al terminar el flujo?"
        code, out = self.check(new)
        assert out["repeated"] == [0]

    def test_repeated_within_batch(self):
        qs = questions()
        qs[3]["prompt"] = qs[1]["prompt"]
        code, out = self.check(qs)
        assert out["repeated"] == [3]

    def test_same_mix_as_last(self):
        code, out = self.check(questions())
        assert not out["same_mix_as_last"]
        assert self.save(exam(graded(questions())))[0] == 0
        code, out = self.check(questions(start=30))
        assert out["same_mix_as_last"]
        code, out = self.check(questions(["open"] * 5, start=30))
        assert not out["same_mix_as_last"]
        code, out = self.check(questions(start=30), "beta")
        assert not out["same_mix_as_last"]


class TestFiles(ExamBase):
    def test_attempt_numbering(self):
        for k in (1, 2):
            code, out = self.save(exam(graded(questions(start=k * 10))))
            assert (code, out["attempt"]) == (0, k), out
        code, out = self.save(exam(graded(questions(start=50)), slug="beta"))
        assert out["attempt"] == 1
        names = sorted(p.name for p in (self.base / self.n["exams_dir"]).iterdir())
        assert names == ["01-alpha-attempt-1.md", "01-alpha-attempt-2.md",
                                 "02-beta-attempt-1.md"]
        assert [a["attempt"] for a in self.prog()["topics"]["alpha"]["attempts"]] == [1, 2]

    def test_report_md_has_checkmarks_and_percentages(self):
        g = graded(questions())
        g[1]["score"] = 30
        code, out = self.save(exam(g))
        with open(out["report_path"], encoding="utf-8") as fh:
            text = fh.read()
        head, body = frontmatter.parse(text)
        assert head["teach_me"] == "exam"
        assert head["slug"] == "alpha"
        assert "✅" in body
        assert "❌" in body
        assert "30%" in body
        assert "generateText returns a string" in body  # literal excerpt
        assert "Passed" in body
        assert "Correct answer" in body


class TestSpanish(ExamBase):
    lang = "es"

    def test_names_and_labels(self):
        code, out = self.save(exam(graded(questions())))
        assert code == 0, out
        assert out["report_path"].endswith("examenes/01-alpha-intento-1.md")
        with open(out["report_path"], encoding="utf-8") as fh:
            text = fh.read()
        assert "Aprobado" in text
        assert "Respuesta correcta" in text


class TestReview(ExamBase):
    def test_review_does_not_change_topic_status(self):
        g = graded(questions(["open"] * 5), score=40)
        assert self.save(exam(g))[0] == 0
        before = self.prog()["topics"]["alpha"]
        assert (before["status"], before["best"]) == ("pending", 40.0)
        rq = [dict(x, slug="alpha") for x in graded(questions(["open", "open"], start=70), 95)]
        code, out = self.review({"graded_in": "subagent", "support_checked_in": "subagent",
                                 "questions": rq})
        assert code == 0, out
        assert out["average"] == 95.0
        assert out["questions"] == [{"slug": "alpha", "correct": True, "score": 95}] * 2
        after = self.prog()
        assert after["topics"]["alpha"] == before
        assert len(after["reviews"]) == 1
        assert after["reviews"][0]["questions"][0]["slug"] == "alpha"
        assert len(list((self.base / self.n["exams_dir"]).iterdir())) == 1

    def test_review_declarations(self):
        rq = [dict(x, slug="alpha") for x in graded(questions(["open", "open"], start=70))]
        code, out = self.review({"questions": rq})
        assert (code, out["error"]["code"]) == (2, "bad_input")
        code, out = self.review({"graded_in": "subagent", "support_checked_in": "x",
                                 "questions": rq})
        assert (code, out["error"]["code"]) == (2, "support_not_checked")
        code, out = self.review({"graded_in": "same_conversation",
                                 "support_checked_in": "subagent", "questions": rq})
        assert code == 0, out
        r = self.prog()["reviews"][0]
        assert (r["graded_in"], r["support_checked_in"]) == ("same_conversation", "subagent")

    def test_review_bounds_and_slug(self):
        mk = lambda n, slug="alpha": {"graded_in": "subagent", "support_checked_in": "subagent",
                                      "questions": [dict(x, slug=slug) for x in graded(
            questions(["open"] * n, start=80))]}
        for n, ok in ((1, False), (2, True), (3, True), (4, False)):
            code, out = self.review(mk(n))
            assert (code == 0) == ok, (n, out)
        code, out = self.review(mk(2, "nope"))
        assert (code, out["error"]["code"]) == (2, "topic_not_found")

    def test_record_exam_helpers(self):
        assert progress.asked(self.did, "alpha") == []
        assert self.save(exam(graded(questions(["open"] * 5), 90)))[0] == 0
        assert self.save(exam(graded(questions(["open"] * 5, start=9), 10)))[0] == 0
        t = self.prog()["topics"]["alpha"]
        assert (t["status"], t["best"]) == ("passed", 90.0)
        assert len(progress.asked(self.did, "alpha")) == 10
        assert self.prog()["teach_me"] == "progress"
