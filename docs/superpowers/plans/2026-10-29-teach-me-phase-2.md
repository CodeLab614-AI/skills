# teach-me fase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the three missing modes work — 1 «Saber qué es» (`overview`), 2 «Saber qué es y cómo está construida» (`overview-internals`) and 4 «Estudiar cómo se usa y cómo está construida» (`use-internals`) — plus changing mode on an existing dossier, on top of the phase 1 skill that is in `main`.

**Architecture:** The modes are combinations of pieces (`overview`, `use`, `built_tour`, `built_syllabus`) recorded in the profile (`mode`, `parts_done`). A new `modes.py` owns that table; new subcommands save the overview report (`save-overview`), the internals tour (`save-built`), find and verify competitors (`search-packages`, `fetch-competitor`) and switch modes (`set-mode`). The syllabus learns a second part (`internals`), progress hides the topics of pieces that are not in the current mode, and `fetch-code` saves the whole repository in the modes that explain how it is built. Everything reuses the phase 1 claim/citation/support pipeline.

**Tech Stack:** Python 3.9+, standard library only; `unittest`; the existing `tests/teach-me/helpers.py` (`TempHome`, `run_script`, `FixtureServer`).

**Spec:** `docs/superpowers/specs/2026-10-28-teach-me-design.md` (version 5). Sections that this plan implements: §1 (mode table), §8 (all of it), §7.1 «Qué código se guarda», §7.2 (two-part syllabus), §11 (overview regenerated on a new version), §12 (`search-packages`, `save-overview`), §13 «Fase 2».

## Global Constraints

- Python 3.9 or newer, standard library only. No `pip install`. Tests never touch the real network (use `FixtureServer` and the `TEACH_ME_*` base URL variables).
- Every subcommand prints one JSON object; exit 0 ok, exit 2 expected block `{"ok": false, "error": {"code", "message"}}`, exit 1 internal error.
- Only the script writes under `~/.teach-me/` (`TEACH_ME_HOME` in tests); every write is atomic and under the dossier lock (`store.locked`).
- Mode ids, in order 1 to 4: `overview`, `overview-internals`, `use`, `use-internals`.
- «Cómo está construida» only with public code: never deduced, no reverse engineering (§8.5).
- Every fact saved in a file carries citations that `sources.check_claims` resolves, plus a `support: "supported"` verdict; every block with code carries `code_support: "supported"`. Same codes as phase 1: `support_not_checked`, `unsupported_claims`, `unverified_claims`.
- `SKILL.md` and JSON keys in English; saved files and their labels in the dossier language (`es` and `en` built in).
- Phase 2 has **no embeddings and no database** (spec §2, §13).
- One commit per task, Conventional Commits `feat(teach-me): …` / `docs(teach-me): …`, no AI attribution lines, no push.

## Review Focus

1. Switching `use` → `use-internals` on a dossier with progress: the syllabus is re-sent with the internals part appended; every `use` topic keeps its number, status, attempts and doubts (test in Task 7).
2. Switching `use-internals` → `use`: the internals topics stop counting as pending or at risk and are listed as `set_aside`, and their files stay on disk (test in Task 8).
3. A dossier with `public_code: false` asked for mode 2 or 4: `set-mode` blocks with `no_public_code`, and so do `save-built` and an internals syllabus (tests in Tasks 1, 6 and 7).
4. A competitor README cited as a doc quote resolves with `excerpts`, because the page is stored under the same file name rule as any doc page (test in Task 4).
5. A monorepo dossier saved in mode `use` that moves to an internals mode: `fetch-code --full` adds the missing files without touching the saved ones, the inventory becomes `layout: "full"` with no `not_saved`, and `search` then finds internal code (test in Task 9).

---

### Task 1: Modes, `init` with every mode and `set-mode`

**Files:**
- Create: `skills/teach-me/scripts/teach_me_lib/modes.py`
- Modify: `skills/teach-me/scripts/teach_me_lib/dossier.py` (`init`, `_existing_info`, `list_all`, `_profile_body`)
- Modify: `skills/teach-me/scripts/teach_me.py` (register `set-mode`)
- Test: `tests/teach-me/test_modes.py`; update `tests/teach-me/test_lookup.py` (the test that expects `mode_not_available` for the other modes)

**Interfaces:**
- Produces, in `modes.py`:
  - `PARTS = {"overview": ("overview",), "overview-internals": ("overview", "built_tour"), "use": ("use",), "use-internals": ("use", "built_syllabus")}`
  - `SYLLABUS_PARTS = {"overview": (), "overview-internals": (), "use": ("use",), "use-internals": ("use", "internals")}`
  - `parts_for(mode: str) -> tuple`, `syllabus_parts(mode: str) -> tuple`, `needs_public_code(mode: str) -> bool` (true for the two internals modes), `needs_full_code(mode: str) -> bool` (same two)
  - `missing_parts(meta: dict) -> list` — `parts_for(meta["mode"])` minus `meta["parts_done"]`, in table order
  - `set_mode(dossier_id: str, mode: str) -> dict` → `{"ok", "id", "mode", "previous_mode", "missing_parts", "set_aside_parts", "needs_full_code"}`; `set_aside_parts` = parts done that the new mode does not use; `needs_full_code` = `needs_full_code(mode)` and the saved code inventory has `layout == "monorepo"` (Task 9 reads the same inventory)
- `init(..., mode)` accepts the four ids; `_existing_info` and `list_all` add `parts_done` and `missing_parts`.

- [ ] **Step 1: Write the failing tests** in `test_modes.py`:
  - `test_init_accepts_every_mode`: `init <url> --lang es --mode overview` (and the other three) exits 0 and the profile has that `mode`.
  - `test_set_mode_reports_missing_and_set_aside`: a dossier with `mode: use`, `parts_done: ["use"]`; `set-mode <id> use-internals` → `missing_parts == ["built_syllabus"]`, `set_aside_parts == []`; then `set-mode <id> overview` → `missing_parts == ["overview"]`, `set_aside_parts == ["use"]`, and `parts_done` is still `["use"]`.
  - `test_set_mode_blocks_without_public_code`: profile with `public_code: false`; `set-mode <id> overview-internals` and `use-internals` exit 2 with `no_public_code`; `overview` and `use` exit 0.
  - `test_set_mode_unknown_mode`: exit 2, `bad_input`.
  - `test_lookup_existing_lists_missing_parts`: `lookup` on an existing dossier returns `mode`, and `list` returns `parts_done` and `missing_parts` per dossier.
- [ ] **Step 2: Run** `python3 -m unittest discover -s tests/teach-me -p test_modes.py -v` — expected FAIL (`modes` missing, `mode_not_available`).
- [ ] **Step 3: Implement** `modes.py`, the `init` change (remove `mode_not_available`), `set-mode <id> <mode>` (positional mode, under the dossier lock, writes only `mode`) and the profile body line «Modo / Mode» + «Piezas / Pieces». `public_code: null` (not known yet) does not block.
- [ ] **Step 4: Run** the new file and the whole suite `python3 -m unittest discover -s tests/teach-me -v` — expected PASS.
- [ ] **Step 5: Commit** `feat(teach-me): every mode at init and set-mode with missing and set-aside pieces`

### Task 2: Activity in `fetch-meta` (last release of the exact tag, last commit)

**Files:**
- Modify: `skills/teach-me/scripts/teach_me_lib/meta.py`
- Test: `tests/teach-me/test_meta.py`

**Interfaces:**
- Produces: `meta.release_date(slug: str, tag: "str | None") -> "tuple[str | None, str | None]"` → `(iso_date, source)` with `source` in `"release"`, `"tag_commit"`, `"latest_release"` or `None`.
  Order: with a tag, `GET /repos/{slug}/releases/tags/{tag}` → `published_at` (`"release"`); on 404, the date of the tag's commit (`git/ref/tags/{tag}` → its commit → `committer.date`, `"tag_commit"`); without a tag, `GET /repos/{slug}/releases/latest` (`"latest_release"`); otherwise `(None, None)`.
- `fetch_meta` output and the profile gain `activity: {"last_release_at", "release_source", "last_commit_at"}`; `last_commit_at` is `commit.committer.date` of the head commit it already downloads. Task 4 reuses `release_date`.

- [ ] **Step 1: Write the failing tests:** `test_activity_uses_the_release_of_the_exact_tag` (fixture: `releases/tags/ai@7.0.156` with `published_at: "2026-10-29T10:00:00Z"` while `releases/latest` answers another package's release → `last_release_at == "2026-10-29T10:00:00Z"`, `release_source == "release"`); `test_activity_falls_back_to_the_tag_commit_date`; `test_activity_without_tag_uses_latest_release`; `test_activity_last_commit_at_is_the_head_commit_date`.
- [ ] **Step 2: Run** `python3 -m unittest discover -s tests/teach-me -p test_meta.py -v` — expected FAIL.
- [ ] **Step 3: Implement** `release_date` and the `activity` field (stored in the profile under the lock, like `license`). A 404 is not an error here; other failures follow the phase 1 rules (`github_rate_limited`, `fetch_failed`).
- [ ] **Step 4: Run** the file and the whole suite — expected PASS.
- [ ] **Step 5: Commit** `feat(teach-me): record the last release of the exact tag and the last commit in fetch-meta`

### Task 3: `search-packages` (npm only)

**Files:**
- Create: `skills/teach-me/scripts/teach_me_lib/competitors.py`
- Modify: `skills/teach-me/scripts/teach_me.py`
- Test: `tests/teach-me/test_competitors.py`

**Interfaces:**
- Produces: `competitors.search_packages(dossier_id: str, registry: str, text: str, size: int = 10) -> dict` → `{"ok", "registry": "npm", "results": [{"name", "version", "description", "repository", "npm_url"}]}`; `size` 1 to 20.
- CLI: `search-packages <id> --npm "<text>" [--size N]` and `--pypi "<text>"`.
- npm: `GET {npm base}/-/v1/search?text=<text>&size=<n>`; the raw response is saved as `<meta_dir>/search-npm-<first 8 hex of sha256(text)>.md` with `meta._meta_markdown`. `repository` is `links.repository` normalised to `https://github.com/<owner>/<name>` when it is GitHub, else the raw value or `null`.
- PyPI: block `search_not_available` with the message «PyPI has no search API; find candidates in the docs, the README or with the agent's web search.» (verified 2026-10-29: XML-RPC search answers «PyPI no longer supports 'pip search'»).

- [ ] **Step 1: Write the failing tests:** `test_search_npm_returns_candidates_and_saves_raw` (fixture route `/-/v1/search` → 2 objects; result names and repositories match; the meta file exists); `test_search_npm_size_out_of_range` (`--size 0` and `21` → `bad_input`); `test_search_pypi_is_not_available`.
- [ ] **Step 2: Run** `python3 -m unittest discover -s tests/teach-me -p test_competitors.py -v` — expected FAIL.
- [ ] **Step 3: Implement** as specified (network outside the lock; the meta write under it).
- [ ] **Step 4: Run** the file and the whole suite — expected PASS.
- [ ] **Step 5: Commit** `feat(teach-me): search npm for competitor candidates`

### Task 4: `fetch-competitor` (light verification and README)

**Files:**
- Modify: `skills/teach-me/scripts/teach_me_lib/competitors.py`, `skills/teach-me/scripts/teach_me_lib/docs.py`
- Modify: `skills/teach-me/scripts/teach_me.py`
- Test: `tests/teach-me/test_competitors.py`

**Interfaces:**
- Produces in `docs.py`: `store_page(dossier_id: str, url: str, markdown: str, origin: str) -> Path` — writes one page exactly as `fetch-docs` does (same `_file_name`, same header with `url`, `fetched_at`, `origin`), so `page_path` and `excerpts` find it. Must be called under the dossier lock. Refactor the page write in `_flush` to use it.
- Produces in `competitors.py`: `fetch_competitor(dossier_id: str, repo: str, npm: "str | None", pypi: "str | None") -> dict` → the stored entry plus `{"ok", "notices"}`.
  Entry, stored in the profile under `competitors[<owner/name lowercase>]`: `{"repo", "url", "package": {"registry", "name"} | null, "latest", "license": {"registry", "repo", "match"}, "activity": {"last_release_at", "release_source", "last_commit_at"}, "readme_url", "fetched_at"}`.
  Data: GitHub repo (`NOASSERTION` → `null`, as in phase 1), head commit date, package latest and license via `meta.registry_package` when `--npm`/`--pypi` is given, tag via `meta.find_tag`, `meta.release_date`; README via `GET /repos/{slug}/readme` → `download_url` → `net.get(url, 1 MiB)` → `docs.store_page(id, download_url, text, "md")`. No README → `readme_url: null` and notice `no_readme`.
- CLI: `fetch-competitor <id> --repo <owner/name> [--npm <name> | --pypi <name>]`. `--repo` is required (spec §8.1: without a GitHub repository a competitor is not verified). Re-running for the same repo replaces its entry.

- [ ] **Step 1: Write the failing tests:** `test_fetch_competitor_stores_entry_and_readme` (fixtures for repo, commit, readme with `download_url` on the fixture server, npm `/latest`, tag, release; the entry has license, latest, activity and `readme_url`); `test_competitor_readme_quote_resolves_with_excerpts` (a `doc` citation with `url = readme_url` and a quote from the README → `verified: true`); `test_fetch_competitor_without_readme` (`notices == ["no_readme"]`); `test_fetch_competitor_requires_repo` (CLI without `--repo` → exit 2 `bad_input`).
- [ ] **Step 2: Run** the file — expected FAIL.
- [ ] **Step 3: Implement** `store_page`, the `_flush` refactor and `fetch_competitor` (network first, then one locked write of the page, the meta files `competitor-<owner>__<name>-*.md` and the profile).
- [ ] **Step 4: Run** the file, `test_docs.py` and the whole suite — expected PASS.
- [ ] **Step 5: Commit** `feat(teach-me): verify competitors lightly and keep their README as a citable page`

### Task 5: Shared support check, `save-overview` and `show-part`

**Files:**
- Create: `skills/teach-me/scripts/teach_me_lib/support.py`, `skills/teach-me/scripts/teach_me_lib/overview.py`
- Modify: `skills/teach-me/scripts/teach_me_lib/topics.py` (use `support.py`), `skills/teach-me/scripts/teach_me.py`
- Test: `tests/teach-me/test_overview.py`; `tests/teach-me/test_topics.py` must keep passing unchanged

**Interfaces:**
- Produces in `support.py` (moved from `topics._check_support`, same behaviour and error codes): `check_blocks(data: dict, blocks: list) -> None` — `support_checked_in` in `("subagent", "same_conversation")`, every fact claim with `support`, every block with `code` with `code_support`. Also `render_claims(claims: list) -> list` (the lines `_topic_body` writes today: text, quoted excerpt, `— source`).
- Produces in `overview.py`: `SECTIONS = ("what", "use_cases", "works_with", "example", "competitors")`; `save_overview(dossier_id: str, data: dict) -> dict` → `{"ok", "id", "path", "claims", "competitors"}`; `show_part(dossier_id: str, part: str) -> dict` for `part` in `("overview", "built")` (block `part_not_saved` when the file does not exist).
- stdin of `save-overview`:
  `{"sections": [{"kind": "what", "claims": [...]}, {"kind": "use_cases", "claims": [...]}, {"kind": "works_with", "claims": [...]}, {"kind": "example", "claims": [...], "code": "...", "code_support": "supported"}, {"kind": "competitors", "rows": [{"competitor": "<owner/name>", "one_liner": <claim>, "difference": <claim>}]}], "support_checked_in": "subagent"}`
  Rules: exactly these five sections in this order; the first four need at least one claim; `rows` has 0 to 5 items; each `competitor` must exist in `profile.competitors` (else `competitor_not_fetched`); `one_liner` and `difference` are `fact` claims with sources and `support`. The mode must contain the `overview` piece (else `part_not_in_mode`).
- The file `names["overview"]` (header `teach_me: overview`) has six headings, labels per language — es: «Qué es y qué hace», «Para qué sirve», «Con qué se usa», «Cómo se ve usarlo», «Competidores directos», «Cobertura»; en: «What it is and what it does», «What it is for», «What it is used with», «What using it looks like», «Direct competitors», «Coverage». The competitors table columns (name linked to `url`, what it does, licence, latest version, last release, last commit, difference) take licence, version and dates **from `profile.competitors`, never from the AI**; the excerpts of `one_liner` and `difference` go below the table. «Cobertura» is written by the script from `profile.coverage` and the docs page list (`ok` / not downloaded counts).
- On save: `parts_done` gains `overview`, `phases.overview` is set, `status` becomes `ready`.

- [ ] **Step 1: Write the failing tests:** `test_save_overview_writes_six_sections_in_es` (fixture dossier with one doc page, one competitor entry; headings in order; licence and version in the table come from the profile even if the claim text says otherwise); `test_save_overview_rejects_unknown_competitor`; `test_save_overview_rejects_more_than_five_rows`; `test_save_overview_needs_support_and_code_support` (missing `support` → `support_not_checked`; `code_support: "unsupported"` → `unsupported_claims`); `test_save_overview_blocks_in_mode_use` (`part_not_in_mode`); `test_save_overview_marks_part_done_and_ready`; `test_show_part_overview_and_missing`.
- [ ] **Step 2: Run** `python3 -m unittest discover -s tests/teach-me -p test_overview.py -v` — expected FAIL.
- [ ] **Step 3: Implement** `support.py` (move, do not duplicate), then `overview.py` and the two subcommands.
- [ ] **Step 4: Run** `test_overview.py`, `test_topics.py` and the whole suite — expected PASS.
- [ ] **Step 5: Commit** `feat(teach-me): save the overview report with verified competitors`

### Task 6: `save-built` (the internals tour of mode 2)

**Files:**
- Create: `skills/teach-me/scripts/teach_me_lib/built.py`
- Modify: `skills/teach-me/scripts/teach_me.py`
- Test: `tests/teach-me/test_built.py`

**Interfaces:**
- Consumes: `support.check_blocks`, `support.render_claims`, `sources.check_claims`, `modes.parts_for`.
- Produces: `built.SECTIONS = ("map", "connections", "walkthrough", "design_decisions")`; `save_built(dossier_id: str, data: dict) -> dict` → `{"ok", "id", "path", "claims"}`.
- stdin: `{"sections": [{"kind": "map", "claims": [...]}, {"kind": "connections", "claims": [...]}, {"kind": "walkthrough", "claims": [...], "code": "..."?, "code_support": ...}, {"kind": "design_decisions", "claims": [...]}], "support_checked_in": "..."}` — four sections in this order, each with at least one claim.
- Blocks: mode without `built_tour` → `part_not_in_mode`; `public_code` false → `no_public_code`; no saved code for the version → `code_not_saved`; no `code` citation anywhere in the document → `no_code_citations` (the tour is about the code, spec §8.4).
- File `names["built"]`, header `teach_me: built`; headings es «Mapa de las piezas», «Cómo se conectan», «Qué pasa por dentro», «Decisiones de diseño»; en «Map of the pieces», «How they connect», «What happens inside», «Design decisions». On save `parts_done` gains `built_tour`.

- [ ] **Step 1: Write the failing tests:** `test_save_built_writes_four_sections`; `test_save_built_requires_a_code_citation`; `test_save_built_blocks_without_public_code`; `test_save_built_blocks_without_saved_code`; `test_save_built_blocks_in_mode_overview`; `test_show_part_built`.
- [ ] **Step 2: Run** `python3 -m unittest discover -s tests/teach-me -p test_built.py -v` — expected FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the file and the whole suite — expected PASS.
- [ ] **Step 5: Commit** `feat(teach-me): save the how-it-is-built tour with code citations`

### Task 7: Two-part syllabus (`use` then `internals`) and set-aside guards

**Files:**
- Modify: `skills/teach-me/scripts/teach_me_lib/topics.py`, `skills/teach-me/scripts/teach_me_lib/exams.py`
- Test: `tests/teach-me/test_topics.py`, `tests/teach-me/test_exams.py`

**Interfaces:**
- Consumes: `modes.syllabus_parts`.
- `save-syllabus` accepts topics with `part` in `modes.syllabus_parts(meta["mode"])` (else `part_not_in_mode`); every `use` topic comes before every `internals` topic (else `bad_input` «use topics come first»); an `internals` topic with `public_code: false` → `no_public_code`. `parts_done` gains `use` and, when there is at least one `internals` topic, `built_syllabus`. The syllabus body shows the two parts under two headings (es «Cómo se usa» / «Cómo está construida», en «How to use it» / «How it is built»).
- `save-topic`, `exam-check`, `save-exam` and `progress start|doubt|skip` on a topic whose part is not in the current mode → `part_not_in_mode` (the topic is set aside).

- [ ] **Step 1: Write the failing tests:** `test_syllabus_two_parts_in_use_internals`; `test_syllabus_internals_rejected_in_mode_use`; `test_syllabus_use_after_internals_rejected`; `test_syllabus_internals_without_public_code`; `test_appending_internals_keeps_use_numbers_and_progress` (Review Focus 1: a `use` dossier with a passed topic 2; `set-mode use-internals`; re-save the same use topics plus two internals topics → topic 2 keeps number, status `passed`, attempts and doubts); `test_save_topic_on_set_aside_topic_blocks`; `test_exam_on_set_aside_topic_blocks`.
- [ ] **Step 2: Run** `test_topics.py` and `test_exams.py` — expected FAIL on the new tests.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** both files and the whole suite — expected PASS.
- [ ] **Step 5: Commit** `feat(teach-me): a second syllabus part for how it is built, and set-aside topics`

### Task 8: Progress hides set-aside topics

**Files:**
- Modify: `skills/teach-me/scripts/teach_me_lib/progress.py`
- Test: `tests/teach-me/test_progress.py`

**Interfaces:**
- `progress show` / `touch` count only topics whose `part` is in `modes.syllabus_parts(meta["mode"])`: `pending`, `skipped`, `at_risk` and `needs_review` ignore the others. The payload gains `set_aside: [slugs]`. `avance.md` adds a «Apartados» / «Set aside» list. Nothing is deleted from the progress header.

- [ ] **Step 1: Write the failing tests:** `test_set_aside_topics_are_not_pending` (Review Focus 2: `use-internals` dossier with a pending internals topic; `set-mode use` → not in `pending`, listed in `set_aside`; the topic file still exists); `test_set_aside_does_not_trigger_needs_review`; `test_switching_back_restores_the_topics` (`set-mode use-internals` again → it is pending again with its attempts).
- [ ] **Step 2: Run** `python3 -m unittest discover -s tests/teach-me -p test_progress.py -v` — expected FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the file and the whole suite — expected PASS.
- [ ] **Step 5: Commit** `feat(teach-me): keep set-aside topics out of the pending lists`

### Task 9: Code scope by mode and `fetch-code --full`

**Files:**
- Modify: `skills/teach-me/scripts/teach_me_lib/code.py`, `skills/teach-me/scripts/teach_me.py`
- Test: `tests/teach-me/test_code.py`

**Interfaces:**
- Consumes: `modes.needs_full_code(mode)`.
- `fetch-code --repo --ref` in an internals mode saves the whole repository (no monorepo selection; only the phase 1 safety rules) and writes the inventory with `layout: "full"`. In `overview` and `use` it keeps the phase 1 monorepo selection. The output and `_done` accept `layout` in `("single", "monorepo", "full")`.
- New `fetch-code <id> --full`: needs saved code for the current version (else the phase 1 `_NO_CODE` block); reuses `repo` and `ref` from the inventory; if the layout is already `single` or `full` it returns `{"ok": true, "added": 0, "already": true}` without downloading; otherwise it downloads once and extracts everything with `only_new=True` (saved files untouched), then rewrites the inventory with every file, no `not_saved` and `layout: "full"`, and clears the `not_saved` entries from the profile coverage. Output `{"ok", "added", "files", "layout": "full"}`. `--full` and `--path` together → `bad_input`.

- [ ] **Step 1: Write the failing tests:** `test_internals_mode_saves_the_whole_monorepo`; `test_full_adds_the_rest_without_touching_saved_files` (Review Focus 5: a saved file modified on disk keeps its content after `--full`; inventory `layout == "full"`; `not_saved` empty; `search` finds a token that exists only in a non-package folder); `test_full_on_single_layout_does_nothing`; `test_full_without_saved_code_blocks`; `test_full_and_path_together_rejected`.
- [ ] **Step 2: Run** `python3 -m unittest discover -s tests/teach-me -p test_code.py -v` — expected FAIL on the new tests.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the file and the whole suite — expected PASS.
- [ ] **Step 5: Commit** `feat(teach-me): save the whole repository in the internals modes and fetch-code --full`

### Task 10: `SKILL.md`, references, guide and README

**Files:**
- Modify: `skills/teach-me/SKILL.md`, `skills/teach-me/references/research.md`, `skills/teach-me/references/lessons.md`, `docs/teach-me.md`, `README.md` (the `teach-me` row, both languages)
- Create: `skills/teach-me/references/overview.md`, `skills/teach-me/references/built.md`
- Test: `tests/teach-me/test_skill_md.py`

**Content (decided here):**
- §1 of `SKILL.md`: the four options with no «coming soon»; mode ids 1 to 4 = `overview`, `overview-internals`, `use`, `use-internals`.
- Existing dossier (spec §8.3): say what exists (mode, pieces done, current topic), ask the mode with the same four options, run `set-mode`, then do only `missing_parts`; if `needs_full_code`, run `fetch-code <id> --full`. Moving to fewer pieces deletes nothing (`set_aside_parts`).
- Without public code (spec §8.5): in modes 2 and 4 say at the start that «how it is built» cannot be explained and offer 2 → 1 and 4 → 3 (`set-mode`); never deduce from indirect signs.
- `references/research.md`: a «Light research» section for modes 1 and 2 — `fetch-meta` (with activity), `discover-docs`, then `fetch-docs --url` only for the entry pages (introduction, getting started, installation, concepts, comparisons); the rest is declared as not downloaded; code: README, examples, exports and manifest (in mode 2, `fetch-code` saves the whole repository).
- `references/overview.md`: competitors (3 to 5; candidates from the docs and README, `search-packages --npm`, and the agent's web search; PyPI has no search; each one verified with `fetch-competitor`; none from memory; not verified → not listed), the `save-overview` payload, presenting the report in short parts with a pause after each, doubts through the consult worker, no verdict («te sirve / no te sirve» is the person's call), and «regenerate the report» when `check-update` says `changed` in modes 1 and 2.
- `references/built.md`: the four sections of spec §8.4, read the internal modules first, at least one code citation, `save-built`, presented in short parts with pauses, no syllabus and no exam.
- `references/lessons.md`: the second syllabus part (`internals`) after the `use` part in mode 4, with its prerequisites.
- `test_skill_md.py`: assert no «coming soon» in `SKILL.md`; assert it names `set-mode`, `save-overview`, `save-built`, `search-packages`, `fetch-competitor` and `fetch-code <id> --full`; assert both new reference files exist and are linked from `SKILL.md`.

- [ ] **Step 1: Update the test** as above — run `python3 -m unittest discover -s tests/teach-me -p test_skill_md.py -v` — expected FAIL.
- [ ] **Step 2: Write** the documents.
- [ ] **Step 3: Run** the file and the whole suite — expected PASS.
- [ ] **Step 4: Commit** `docs(teach-me): document the four modes and changing mode`

### Task 11: Final verification (no commit)

- [ ] **Step 1:** `python3 -m unittest discover -s tests/teach-me -v` and `python3 -m unittest discover -s tests/explain-changes -v` on Python 3.9 and on the newest Python available — expected all OK.
- [ ] **Step 2: Real network run**, with `TEACH_ME_HOME` pointing to a temporary folder (never `~/.teach-me`), deleted at the end:
  1. `init https://ai-sdk.dev/docs --lang es --mode overview`; `fetch-meta --npm ai --repo vercel/ai` (report `activity`); `update-profile` with the links; `discover-docs https://ai-sdk.dev/docs`; `fetch-docs --url` for the introduction page; `fetch-code` with the tag.
  2. `search-packages --npm "llm ai sdk typescript"`; `fetch-competitor --repo langchain-ai/langchainjs --npm langchain`; `excerpts` with one quote from its README (must verify).
  3. `set-mode use-internals` → `needs_full_code: true`; `fetch-code --full` (report files and size); `search` for a symbol of an internal module.
  4. `set-mode overview-internals` on a dossier with `public_code: false` → `no_public_code`.
- [ ] **Step 3:** Report the commits, the test results and what stayed unverified (at least: the full conversation with a real agent in modes 1, 2 and 4).
