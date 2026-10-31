# pytest migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every test in `tests/` runs on pytest and is written in pytest style (plain `assert`, fixtures, `pytest.raises`, `pytest.mark`). No `unittest` remains anywhere in `tests/`.

**Architecture:** One `pytest.ini` at the repo root with `--import-mode=importlib`, so test files with the same name in different folders (`test_docs.py`, `test_skill_md.py`) do not clash. The helper modules get unique names (`explain_helpers.py`, `teach_helpers.py`) and are put on the path through `pythonpath`. Shared setup moves to one `conftest.py` per suite as fixtures. A final guard test fails if `unittest` style comes back.

**Tech Stack:** pytest 8.4.2 (MIT, https://github.com/pytest-dev/pytest), the last line that supports Python 3.9. pytest 9 needs Python 3.10 or newer. unittest2pytest 0.5 (GPLv3+, https://github.com/pytest-dev/unittest2pytest) is used only locally, through `uvx`, to rewrite `self.assertX` calls. It is never added to the repo.

**Spec:** request from the person on 2026-10-31: «quiero que todo se cambie a pytest». It builds on the branch `ci/hardening` (plan `2026-10-31-ci-hardening.md`).

## Global Constraints

- Branch `ci/hardening` (not pushed yet). One commit per task, English conventional messages, **no AI attribution lines**, never push.
- Change nothing under `skills/`. The skills stay stdlib only; pytest is a test-only dependency.
- Python 3.9 compatible (`from __future__ import annotations` stays, no `match`, no runtime `X | Y`).
- **No test is lost or weakened.** For every converted file, the set of test method names stays identical (class renames are allowed). Every assertion keeps its exact meaning: same values, same messages where they matter. The only allowed change in test count is a `subTest` loop that becomes `@pytest.mark.parametrize`.
- Baseline collected counts today: `tests/security` 27, `tests/explain-changes` 214, `tests/teach-me` 319.
- After a task, the files it converted contain no `unittest`, no `self.assert`, no `setUp`/`tearDown` and no `addCleanup`.

### Conversion rules (all conversion tasks)

1. First run `uvx unittest2pytest==0.5 -w -n <files>` on the task's files to rewrite `self.assertX(...)`. Then review every rewritten line by hand. The tool is not trusted blindly: check `assertRaises`, `assertRegex`, `assertAlmostEqual` and asserts with a `msg`.
2. Classes: `class FooTests(unittest.TestCase)` becomes `class TestFoo:`, with no base class and the same method names. A base class that only shares setup must NOT start with `Test` (for example `ExamsBase`), so pytest does not collect it twice.
3. `setUp`, `addCleanup` and `super().setUp()` become fixtures: an autouse fixture on the class (`@pytest.fixture(autouse=True)`) that stores on `self`, or explicit fixture arguments. Cleanup goes in `yield` fixtures. Inherited setup becomes an inherited autouse fixture with a distinct name.
4. `mock.patch.dict(os.environ, …)` becomes `monkeypatch.setenv/delenv`. `mock.patch` and `mock.patch.object` become `monkeypatch.setattr`. `mock.Mock` becomes a tiny local stub class. `unittest.mock` is not used at all.
5. `@unittest.skipIf/skipUnless` become `@pytest.mark.skipif`. `self.subTest` becomes `@pytest.mark.parametrize`. `self.fail` becomes `pytest.fail`. `assertRaises` with `cm.exception` becomes `pytest.raises(...) as exc_info` with `exc_info.value`.
6. `if __name__ == "__main__": unittest.main()` blocks are deleted.

### Verification each conversion task runs (copy the exact counts into the report)

- `python3 -m pytest <suite> -q`: all pass, and the collected count equals the baseline.
- `uv run --python 3.9 --with pytest==8.4.2 python -m pytest <suite> -q`: all pass.
- The same suite offline: `SKILLS_OFFLINE=1 PYTHONPATH=$PWD/tests/offline SKILLS_OFFLINE_LOG=<tmp>/net.log python3 -m pytest <suite> -q` passes, and `<tmp>/net.log` does not exist or is empty. `tests/security` is the exception: run it with `SKILLS_OFFLINE_LOG=` empty.
- `grep -nE "unittest|self\.assert|setUp|tearDown|addCleanup" <converted files>`: no output.

## Review Focus

- **Duplicate file names across suites.** `test_docs.py` and `test_skill_md.py` exist in two suites. They must both be collected in a single `pytest tests` run. Task 1 proves this with `python3 -m pytest tests -q` → 560 passed.
- **Offline guard during pip install in CI.** The job sets `SKILLS_OFFLINE=1` at job level, so `pip install` would be blocked. Task 1 turns the guard off for the install step only.
- **Setup inheritance.** `super().setUp()` chains in `test_exams.py`, `test_topics.py` and `test_progress.py` must keep their order. The parent's setup runs first.
- **unittest2pytest mistakes.** `assertRaises` used as a context manager with `cm.exception`, `assertRegex` (it must become `re.search`), and `assertTrue(x, msg)` (the message must not be lost where it carried meaning).
- **Environment leaks between tests.** `monkeypatch` undoes changes per test. Anything a test changed by hand (for example `os.environ[...] = …`) must go through `monkeypatch` or a `yield` fixture.

---

### Task 1: pytest infrastructure (tests still unittest-style, all run on pytest)

**Files:**
- Create: `pytest.ini`, `.github/test-requirements.in`, `.github/test-requirements.txt`
- Rename: `tests/explain-changes/helpers.py` to `tests/explain-changes/explain_helpers.py`, and `tests/teach-me/helpers.py` to `tests/teach-me/teach_helpers.py` (with `git mv`). Update every `import helpers` / `from helpers import …` in those suites.
- Modify: `.github/workflows/test.yml`, `.gitignore` (add `.pytest_cache/`), `tests/explain-changes/test_docs.py` (only if a contract regex needs the new job id)

- [ ] **Step 1:** Create `pytest.ini`:
  ```ini
  [pytest]
  minversion = 8.4
  testpaths = tests
  addopts = --import-mode=importlib -ra --strict-markers --strict-config
  pythonpath = tests/explain-changes tests/teach-me tests/security
  xfail_strict = true
  ```
- [ ] **Step 2:** Rename the helpers and update the imports.
- [ ] **Step 3:** Run `python3 -m pytest tests -q` → `560 passed`. Run each suite alone → 27 / 214 / 319. Run on 3.9 with `uv run --python 3.9 --with pytest==8.4.2 python -m pytest tests -q` → 560 passed.
- [ ] **Step 4:** Create `.github/test-requirements.in` containing `pytest==8.4.2`. Generate the `.txt` with `uv pip compile --universal --generate-hashes --python-version 3.9 .github/test-requirements.in -o .github/test-requirements.txt`.
- [ ] **Step 5: CI.**
  - Rename job `unittest` to `tests`.
  - After setup-python, add step `Install pytest (hash-pinned)`: `python3 -m pip install --require-hashes --no-deps -r .github/test-requirements.txt`, with step `env: SKILLS_OFFLINE: "0"`.
  - Replace the three unittest steps with:
    - `Run security guardrails`: `python3 -m pytest tests/security -v`, keeping `SKILLS_OFFLINE_LOG: ""`;
    - `Run explain-changes tests`: `python3 -m pytest tests/explain-changes -v`;
    - `Run teach-me tests`: `python3 -m pytest tests/teach-me -v`.
  - Everything else stays.
  - Check with `actionlint` and `uvx zizmor==1.31.1 .github` (0 findings), and run `python3 -m pytest tests/explain-changes/test_docs.py`, whose workflow contract must pass.
- [ ] **Step 6:** Verify the hashed install in a throwaway Python 3.9 venv under the scratchpad, then run pytest from it on `tests/security` → OK. Delete the venv.
- [ ] **Step 7: Commit:** `git commit -m "test: run all suites with pytest"`

### Task 2: convert `tests/security` (test_guardrails.py, test_offline_guard.py)

- Interfaces: `guardrails.py` stays as it is. The `FakeRepo.make` helper becomes a `fake_repo` fixture returning a callable `make(files: dict) -> Path`, built on `tmp_path`.
- `test_offline_guard.py`: the class skip becomes `pytestmark = pytest.mark.skipif(os.environ.get("SKILLS_OFFLINE") != "1", reason="offline guard not active")`.
- [ ] Convert following the rules. Verify as described above (27 collected; offline run with the guard: 27 passed; without the vars: 6 skipped).
- [ ] Commit: `git commit -m "test(security): convert to pytest style"`

### Task 3: explain-changes, part A (conftest + 10 files)

**Files:** create `tests/explain-changes/conftest.py`. Convert `test_workspace.py`, `test_end_to_end.py`, `test_gitcmd.py`, `test_docs.py`, `test_skill_md.py`, `test_rules.py`, `test_replacements.py`, `test_detect_repo.py`, `test_mechanical.py` and `test_verify.py`.

- Interfaces (produced, used by Task 4): in `conftest.py`, fixture `make_repo` returns a callable `make_repo(branch: str = "main") -> TempRepo`; every repo it creates is cleaned up at teardown. `RepoTestCase` stays in `explain_helpers.py` until Task 8 because part B still uses it.
- [ ] Convert, verify (the explain-changes suite stays at 214 collected and passing, files from both parts included), and commit: `git commit -m "test(explain-changes): convert part A to pytest style"`

### Task 4: explain-changes, part B (8 files)

Convert `test_robustness.py`, `test_state.py`, `test_report_html.py`, `test_diffparse.py`, `test_targets_batches.py`, `test_detect_commits.py`, `test_ranges.py` and `test_report.py`, using `make_repo` from Task 3.
- [ ] Convert, verify (214), and commit: `git commit -m "test(explain-changes): convert part B to pytest style"`

### Task 5: teach-me, part A (conftest + 15 files)

**Files:** create `tests/teach-me/conftest.py`. Convert `test_frontmatter.py`, `test_names.py`, `test_cli.py`, `test_html2md.py`, `test_urls.py`, `test_store.py`, `test_config.py`, `test_discard.py`, `test_skill_md.py`, `test_net.py`, `test_update.py`, `test_modes.py`, `test_search.py`, `test_built.py` and `test_sources.py`.

- Interfaces (used by Tasks 6–7): in `conftest.py`, fixture `home` yields an active `TempHome` (TEACH_ME_HOME set, then restored), This fixture replaces the `setUp`/`addCleanup` uses of `TempHome`. `FixtureServer` gets different routes in each test, so it stays an inline `with FixtureServer(routes) as srv:` block, which is valid pytest style, and so do the existing inline `with TempHome() [as h]:` blocks. `TempHome`, `FixtureServer` and `run_script` stay in `teach_helpers.py`.
- [ ] Convert, verify (the teach-me suite stays at 319), and commit: `git commit -m "test(teach-me): convert part A to pytest style"`

### Task 6: teach-me, part B (6 files)

Convert `test_overview.py`, `test_competitors.py`, `test_progress.py`, `test_lookup.py`, `test_docs.py` and `test_exams.py`. Keep the setup order in `test_exams.py` and `test_progress.py`, which inherit setup today.
- [ ] Convert, verify (319), and commit: `git commit -m "test(teach-me): convert part B to pytest style"`

### Task 7: teach-me, part C (3 files)

Convert `test_meta.py`, `test_topics.py` (inherited setup) and `test_code.py` (828 lines).
- [ ] Convert, verify (319), and commit: `git commit -m "test(teach-me): convert part C to pytest style"`

### Task 8: lock it in

**Files:** modify `tests/explain-changes/explain_helpers.py` (remove `RepoTestCase` and `import unittest`). Create `tests/security/test_pytest_style.py`.

- [ ] Add `test_no_unittest_in_tests`. It scans every `tests/**/*.py` with `ast` and the raw text, and fails on:
  - an `import unittest` / `from unittest import …`;
  - a class inheriting `TestCase`;
  - a `self.assert…` call;
  - a method named `setUp` or `tearDown`.
  It reports `path:line`. Before removing `RepoTestCase` it fails on `explain_helpers.py`; after, it passes.
- [ ] Full verification on 3.14 and 3.9, normal and offline: 560 + the new test. Then Bandit, zizmor and actionlint.
- [ ] Commit: `git commit -m "test: forbid unittest style in the test suites"`

## After the last task (orchestrator)

- Per file, compare the test method names against `5ee741b` with an AST script: they must be identical, apart from documented parametrize expansions.
- Hand-over: push, PR, then branch protection with the checks `tests (ubuntu-24.04, 3.9)`, `tests (ubuntu-latest, 3.13)`, `tests (macos-latest, 3.13)` and `security-scan`.
