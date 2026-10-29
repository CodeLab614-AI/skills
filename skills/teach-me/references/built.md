# How it is built (mode 2; the same reading feeds mode 4)

Read this for the tour of "Know what it is and how it is built". It needs public code: without it (`public_code: false`) `save-built` blocks with `no_public_code`, and you never deduce how it is built from indirect signs. In mode 4 the same reading feeds the `internals` topics of the syllabus (lessons.md) instead of a tour.

## Read the internals first

In mode 2 `fetch-code <id> --repo <owner/name> --ref <ref>` saves the whole repository by itself. Only if `set-mode` reported `needs_full_code: true` (code already saved in the monorepo layout), run `python3 "<SKILL_DIR>/scripts/teach_me.py" fetch-code <id> --full` to upgrade it. Then read, with the file tools on the saved folder and `search` (never run anything): the manifest and entry point; the folder layout and main modules; how the pieces import each other; and the path that one or two typical uses from the docs take through the code. If docs and code disagree, the code wins and the discrepancy goes into the coverage. If the dossier already has the overview, the tour is written from what was already read, and the other way around.

## The four sections

1. `map`: the main pieces (packages, modules) and what each one does.
2. `connections`: how they connect: who calls whom, where data and control go.
3. `walkthrough`: what happens inside, step by step, in one or two typical uses taken from the documentation.
4. `design_decisions`: the decisions that the code or its documentation explains. If neither explains one, it is not stated.

Cite code (`{"kind": "code", "path": ..., "line_start": N, "line_end": M}`) in the claims: at least one citation of kind `code` in the whole tour, or `save-built` blocks with `no_code_citations`.

## Saving

`excerpts`, the support worker and the code check as in [sources.md](sources.md), then send to `python3 "<SKILL_DIR>/scripts/teach_me.py" save-built <id>` (stdin):

```
{"support_checked_in": "subagent",
 "sections": [
  {"kind": "map",              "claims": [...]},
  {"kind": "connections",      "claims": [...]},
  {"kind": "walkthrough",      "claims": [...], "code": "optional short excerpt", "code_support": "supported"},
  {"kind": "design_decisions", "claims": [...]}
 ]}
```

Exactly these four sections, in this order. Blocks: `no_code_citations`, `code_not_saved` (no code saved yet: run `fetch-code` first), `no_public_code`, `part_not_in_mode` (modes 1, 3 and 4), plus the support codes. `python3 "<SKILL_DIR>/scripts/teach_me.py" show-part <id> built` returns the saved tour (`part_not_saved` if none).

## Presenting it

In short parts, one section at a time, **pausing after each**, conversationally. No formal syllabus and no exam. Doubts go to the consult worker ([consult.md](consult.md)).

## New version

When `check-update` says `changed` in mode 2, regenerate the overview and the tour from the new downloads (`fetch-code <id> --repo <owner/name> --ref <ref>`, no `--full`).
