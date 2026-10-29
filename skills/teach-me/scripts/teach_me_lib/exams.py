"""Exams and reviews: shape, repetition and references are checked and scored by the script."""
from __future__ import annotations

import string
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import dossier, frontmatter, modes, progress, sources, store
from .errors import BlockedError

TYPES = ("multiple_choice", "open", "predict", "when_to_use", "read_yourself")
_JACCARD = 0.8
_PUNCT = string.punctuation + "¿¡«»“”‘’…"

_LABELS = {
    "es": {"title": "Examen", "attempt": "Intento", "right": "Qué acertaste",
           "missing": "Qué faltó", "answer": "Respuesta correcta", "source": "Fuente",
           "average": "Nota", "passed": "Aprobado", "failed": "No aprobado",
           "skipped": "Saltada", "none": "(nada)"},
    "en": {"title": "Exam", "attempt": "Attempt", "right": "What you got right",
           "missing": "What was missing", "answer": "Correct answer", "source": "Source",
           "average": "Score", "passed": "Passed", "failed": "Not passed",
           "skipped": "Skipped", "none": "(nothing)"},
}


def _bad(message: str) -> BlockedError:
    return BlockedError("bad_input", message)


def _lab(meta: dict, key: str) -> str:
    return _LABELS.get(meta.get("lang"), _LABELS["en"])[key]


def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _words(prompt: str) -> set:
    """Words for the Jaccard test: tokens of the normalized prompt, punctuation stripped,
    keeping only those of 3 or more characters (drops en, de, a, of, to...)."""
    return {w for w in (t.strip(_PUNCT) for t in sources.normalize(prompt).split())
            if len(w) >= 3}


def _similar(a: str, b: str) -> bool:
    if sources.normalize(a) == sources.normalize(b):
        return True
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) >= _JACCARD


# --- shape --------------------------------------------------------------------------

def _validate_question(q, tag: str) -> None:
    if not isinstance(q, dict):
        raise _bad("%s must be an object." % tag)
    if q.get("type") not in TYPES:
        raise _bad("%s: type must be one of %s." % (tag, ", ".join(TYPES)))
    if not isinstance(q.get("prompt"), str) or not q["prompt"].strip():
        raise _bad("%s needs a non-empty prompt." % tag)
    if q["type"] == "multiple_choice":
        opts = q.get("options")
        if not isinstance(opts, list) or len(opts) != 4 or any(not isinstance(o, str) for o in opts):
            raise _bad("%s: multiple_choice needs exactly 4 string options." % tag)
        co = q.get("correct_option")
        if not isinstance(co, int) or isinstance(co, bool) or not 0 <= co <= 3:
            raise _bad("%s: multiple_choice needs correct_option 0-3." % tag)
    if q["type"] == "read_yourself":
        target = q.get("target")
        if not isinstance(target, dict) \
                or not any(isinstance(target.get(k), str) and target[k] for k in ("url", "path")) \
                or not isinstance(target.get("symbol"), str) or not target["symbol"]:
            raise _bad("%s: read_yourself needs target with url or path, plus symbol." % tag)
    ref = q.get("reference")
    if not isinstance(ref, dict) or not isinstance(ref.get("text"), str) or not ref["text"].strip():
        raise _bad("%s needs a reference with non-empty text." % tag)
    if not isinstance(ref.get("sources"), list) or not ref["sources"]:
        raise _bad("%s: the reference needs at least one source." % tag)


def _validate_exam_shape(questions) -> None:
    if not isinstance(questions, list):
        raise _bad("questions must be a list.")
    if not 5 <= len(questions) <= 8:
        raise _bad("An exam has 5 to 8 questions, got %d." % len(questions))
    for i, q in enumerate(questions):
        _validate_question(q, "question %d" % i)
    if sum(1 for q in questions if q["type"] == "read_yourself") > 1:
        raise _bad("At most one read_yourself question per exam.")


def _syllabus(folder: Path, meta: dict) -> list:
    head, _ = _read(folder / meta["names"]["syllabus"])
    if head.get("teach_me") != "syllabus" or not isinstance(head.get("topics"), list):
        raise _bad("This dossier has no syllabus yet; save it first.")
    return head["topics"]


def _read(path: Path) -> "tuple[dict, str]":
    try:
        return frontmatter.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {}, ""


def _entry(syllabus: list, slug) -> dict:
    found = next((t for t in syllabus if t.get("slug") == slug), None)
    if found is None:
        raise BlockedError("topic_not_found", "The syllabus has no topic %r." % (slug,))
    return found


def _exam_files(folder: Path, meta: dict, slug: str) -> list:
    """(attempt, header) of saved exams of the topic, found by header slug."""
    out = []
    edir = folder / meta["names"]["exams_dir"]
    if edir.is_dir():
        for path in sorted(edir.glob("*.md")):
            head, _ = _read(path)
            if head.get("teach_me") == "exam" and head.get("slug") == slug:
                out.append((head.get("attempt") if isinstance(head.get("attempt"), int) else 0,
                            head))
    return out


def _claims(questions: list) -> list:
    return [{"text": q["reference"]["text"], "kind": "fact", "sources": q["reference"]["sources"]}
            for q in questions]


# --- exam-check ---------------------------------------------------------------------

def check(dossier_id: str, slug: str, questions) -> dict:
    dossier.require(dossier_id)
    folder = store.dossier_dir(dossier_id)
    meta, _ = dossier.load(dossier_id)
    modes.require_in_mode(meta, _entry(_syllabus(folder, meta), slug))
    _validate_exam_shape(questions)
    previous = progress.asked(dossier_id, slug)
    repeated = []
    for i, q in enumerate(questions):
        if any(_similar(q["prompt"], p) for p in previous) \
                or any(_similar(q["prompt"], questions[j]["prompt"]) for j in range(i)):
            repeated.append(i)
    last = max(_exam_files(folder, meta, slug), key=lambda t: t[0], default=None)
    same_mix = last is not None and Counter(q["type"] for q in questions) == Counter(
        q.get("type") for q in last[1].get("questions") or [])
    resolved, _bad_idx = sources.check_claims(dossier_id, _claims(questions))
    refs = []
    for i, claim in enumerate(resolved):
        refs.append({"index": i, "verified": claim["verified"],
                     "excerpts": [c["excerpt"] for c in claim["sources"] if "excerpt" in c],
                     "errors": [c["error"] for c in claim["sources"] if "error" in c]
                     + ([claim["error"]] if "error" in claim else [])})
    return {"ok": True, "repeated": repeated, "same_mix_as_last": same_mix, "references": refs}


# --- grading ------------------------------------------------------------------------

def _validate_graded(questions: list, review: bool) -> None:
    unsupported, missing = [], []
    for i, q in enumerate(questions):
        verdict = q.get("reference_support")
        if verdict is None:
            missing.append(i)
        elif verdict != "supported":
            unsupported.append(i)
    if missing:
        raise BlockedError("support_not_checked",
                           "Questions without reference_support: %s." % missing)
    if unsupported:
        raise BlockedError("unsupported_claims",
                           "Unsupported references, regenerate these questions: %s." % unsupported)


def _validate_grades(questions: list) -> None:
    for i, q in enumerate(questions):
        tag = "question %d" % i
        if q.get("skipped") is True:
            if q["type"] != "read_yourself":
                raise _bad("%s: only a read_yourself question can be skipped." % tag)
            continue
        if "skipped" in q and q["skipped"] not in (False, None):
            raise _bad("%s: skipped must be true or absent." % tag)
        if not _num(q.get("score")) or not 0 <= q["score"] <= 100:
            raise _bad("%s needs a numeric score from 0 to 100." % tag)
        for key in ("right", "missing"):
            if not isinstance(q.get(key), str):
                raise _bad("%s needs a string %s." % (tag, key))
        if q["type"] == "multiple_choice":
            ans = q.get("answer")
            if not isinstance(ans, int) or isinstance(ans, bool):
                raise _bad("%s: answer must be an option index." % tag)
            if q["score"] != (100 if ans == q["correct_option"] else 0):
                raise BlockedError("score_mismatch",
                                   "%s: score must be 100 if answer equals correct_option, else 0." % tag)
        elif not isinstance(q.get("answer"), str):
            raise _bad("%s needs a string answer." % tag)


def _verify_references(dossier_id: str, questions: list) -> list:
    resolved, bad = sources.check_claims(dossier_id, _claims(questions))
    if bad:
        raise BlockedError("unverified_claims",
                           "References not verified, fix or remove questions: %s." % bad)
    return resolved


def _grade(questions: list, resolved: list) -> "tuple[list, float]":
    out, scores = [], []
    for q, claim in zip(questions, resolved):
        item = dict(q)
        item["reference"] = {"text": q["reference"]["text"], "sources": claim["sources"]}
        if q.get("skipped") is True:
            item["skipped"] = True
            item["correct"] = False
        else:
            item.pop("skipped", None)
            item["correct"] = q["score"] > 50
            scores.append(q["score"])
        out.append(item)
    average = round(sum(scores) / len(scores), 1) if scores else 0.0
    return out, average


def _check_common(data, count_ok, review: bool) -> list:
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        raise _bad("Send an object with a questions list.")
    questions = data["questions"]
    if not count_ok(len(questions)):
        raise _bad("A %s has %s questions, got %d." % (
            "review" if review else "exam", "2 to 3" if review else "5 to 8", len(questions)))
    for i, q in enumerate(questions):
        _validate_question(q, "question %d" % i)
        if review and (not isinstance(q.get("slug"), str) or not q["slug"]):
            raise _bad("question %d needs a slug." % i)
    if not review:
        if sum(1 for q in questions if q["type"] == "read_yourself") > 1:
            raise _bad("At most one read_yourself question per exam.")
    if data.get("graded_in") not in ("subagent", "same_conversation"):
        raise _bad("graded_in must be 'subagent' or 'same_conversation'.")
    if data.get("support_checked_in") not in ("subagent", "same_conversation"):
        raise BlockedError("support_not_checked",
                           "support_checked_in must be 'subagent' or 'same_conversation'.")
    _validate_graded(questions, review)
    _validate_grades(questions)
    return questions


def _labels_body(meta: dict, head: dict) -> str:
    lines = ["# %s %02d — %s, %s %d" % (_lab(meta, "title"), head["number"], head["slug"],
                                         _lab(meta, "attempt"), head["attempt"]), ""]
    for i, q in enumerate(head["questions"], start=1):
        if q.get("skipped"):
            mark, pct = "⏭", _lab(meta, "skipped")
        else:
            mark, pct = ("✅" if q["correct"] else "❌"), "%g%%" % q["score"]
        lines += ["## %d. %s %s — %s" % (i, mark, q["prompt"], pct), ""]
        if not q.get("skipped"):
            lines += ["**%s:** %s" % (_lab(meta, "right"), q["right"] or _lab(meta, "none")),
                      "**%s:** %s" % (_lab(meta, "missing"), q["missing"] or _lab(meta, "none")), ""]
        if q["type"] == "multiple_choice":
            lines += ["**%s:** %s" % (_lab(meta, "answer"), q["options"][q["correct_option"]]), ""]
        else:
            lines += ["**%s:** %s" % (_lab(meta, "answer"), q["reference"]["text"]), ""]
        for cite in q["reference"]["sources"]:
            where = cite["url"] if cite["kind"] == "doc" else "%s:%d-%d" % (
                cite["path"], cite["line_start"], cite["line_end"])
            lines += ["\n".join("> " + ln if ln else ">" for ln in cite["excerpt"].split("\n")),
                      ">", "> — %s: %s" % (_lab(meta, "source"), where), ""]
    lines.append("**%s: %g%% — %s**" % (_lab(meta, "average"), head["average"],
                                         _lab(meta, "passed" if head["passed"] else "failed")))
    return "\n".join(lines) + "\n"


# --- save-exam ----------------------------------------------------------------------

def save(dossier_id: str, data) -> dict:
    questions = _check_common(data, lambda n: 5 <= n <= 8, False)
    if "slug" not in data or not isinstance(data["slug"], str):
        raise _bad("Send the topic slug.")
    dossier.require(dossier_id)
    with store.locked(dossier_id) as folder:
        meta, _ = dossier.load(dossier_id)
        entry = _entry(_syllabus(folder, meta), data["slug"])
        modes.require_in_mode(meta, entry)
        resolved = _verify_references(dossier_id, questions)
        graded, average = _grade(questions, resolved)
        passed = average > 50
        attempt = 1 + len(_exam_files(folder, meta, data["slug"]))
        head = {"teach_me": "exam", "slug": entry["slug"], "number": entry["number"],
                "attempt": attempt, "graded_in": data["graded_in"],
                "support_checked_in": data["support_checked_in"],
                "date": datetime.now().strftime("%Y-%m-%d"), "average": average,
                "passed": passed, "questions": graded}
        edir = folder / meta["names"]["exams_dir"]
        edir.mkdir(parents=True, exist_ok=True)
        path = edir / ("%02d-%s-%s-%d.md" % (entry["number"], entry["slug"],
                                              meta["names"]["attempt"], attempt))
        store.atomic_write(path, frontmatter.dump(head, _labels_body(meta, head)))
        progress.record_exam(dossier_id, entry["slug"], attempt, average, passed,
                             [q["prompt"] for q in questions])
    return {"ok": True, "attempt": attempt, "average": average, "passed": passed,
            "questions": [{"correct": q["correct"], "score": q.get("score")} for q in graded],
            "report_path": str(path)}


# --- save-review --------------------------------------------------------------------

def save_review(dossier_id: str, data) -> dict:
    questions = _check_common(data, lambda n: 2 <= n <= 3, True)
    dossier.require(dossier_id)
    with store.locked(dossier_id) as folder:
        meta, _ = dossier.load(dossier_id)
        syllabus = _syllabus(folder, meta)
        for q in questions:
            _entry(syllabus, q["slug"])
        resolved = _verify_references(dossier_id, questions)
        graded, average = _grade(questions, resolved)
        progress.record_review(dossier_id, {
            "date": progress.today(), "average": average, "graded_in": data["graded_in"],
            "support_checked_in": data["support_checked_in"],
            "questions": [{"slug": q["slug"], "type": q["type"], "prompt": q["prompt"],
                           "score": q.get("score"), "correct": q["correct"]} for q in graded]})
    return {"ok": True, "average": average,
            "questions": [{"slug": q["slug"], "correct": q["correct"], "score": q.get("score")}
                          for q in graded]}
