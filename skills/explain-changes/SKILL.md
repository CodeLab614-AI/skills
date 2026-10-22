---
name: explain-changes
description: Explains the changes on the current Git branch group by group (what they do, which project rules they touch, what is mechanical) and writes a report. Use only when the user explicitly invokes /explain-changes; never start it on your own.
disable-model-invocation: true
---

# explain-changes

You guide the user through the changes of their branch. A bundled script gathers the facts; you interpret them and talk to the user. The skill is **read-only**: it never edits the user's code, never commits, never runs tests, lint or typecheck, and never suggests improvements.

Speak to the user in the language of the conversation (questions, walkthrough, report). This file and the script's JSON keys are in English.

## 0. Before anything

1. Check Python: run `python3 --version`. On Windows, if `python3` is missing, try `python --version` and use `python` everywhere below. It must be 3.9 or newer. If Python is missing or older, tell the user in plain words that this skill needs Python 3.9+ and stop.
2. Resolve `SKILL_DIR` from the location of this SKILL.md (its folder). Every call has this exact shape:

   `python3 "<SKILL_DIR>/scripts/explain_changes.py" <subcommand> [flags]`

3. Every subcommand prints one JSON object. Exit code 0 is fine. Exit code 2 is an expected block: `{"ok": false, "error": {"code", "message"}}`. Exit code 1 is an internal error: tell the user it failed, show the message, and stop.
4. You never write files. The script writes only inside `.explain-changes/`. When a subcommand needs JSON on stdin, pass it with a quoted heredoc, and only when the matching flag is given (no flag, no stdin):

   ```
   python3 "<SKILL_DIR>/scripts/explain_changes.py" verify <<'EOF'
   { ... }
   EOF
   ```

## 1. Detect

Run `python3 "<SKILL_DIR>/scripts/explain_changes.py" detect` (add `--no-fetch` if the user is offline or asks for no network access). On exit 2, explain the code in plain language and stop. Do not try to fix the repo:

| code | tell the user |
|---|---|
| `not_a_git_repo` | this folder is not inside a Git repository |
| `rebase_in_progress` | a rebase is running; finish or abort it, then run again |
| `merge_in_progress` | a merge is running; finish or abort it, then run again |
| `unresolved_conflicts` | there are files with unresolved conflicts; resolve them first |
| `shallow_no_merge_base` | the clone is shallow and the base is not reachable; they can deepen the clone themselves (never deepen it for them) |
| `no_base_branch` | no base branch (origin/HEAD, main, master, develop) was found |
| `not_excluded` | `.explain-changes/` could not be excluded from Git, so nothing is written |
| `bad_input` | the call was malformed; show the message |

Show each entry of `notices` in one plain sentence, translated. Codes: `fetch_failed` (working from the local base), `no_merge_base`, `author_check_skipped` (no `user.email`, so nobody is treated as foreign), `no_own_commits`, `history_rewritten` (new work detected by content), `auto_answered`.

## 2. Questions

Ask **only** the entries of `questions`, in order. Never invent others. In Claude Code use a selection menu; in other agents use a numbered list. Translate the option ids into short labels in the user's language, mark the `recommended` one, and use `params` (`commits`, `emails`) to fill in details:

- `scope`: `merge_commit` (review the commit that merged the branch), `only_new` (only what is new since the last review), `whole_branch`, `from_commit` / `other_commit` (user picks a commit), `uncommitted_only`.
- `foreign_merges`: leave out (`exclude`) or include merged branches that are not the user's.
- `other_authors`: leave out or include commits by other authors.

Each option carries `facts_args`. Keep the chosen options' `facts_args` and join them for step 3. For `from_commit` and `other_commit`, `facts_args` is only a prefix (`["--from"]` or `["--commit"]`): append the sha the user picks from `params.commits`. A `notices` entry `auto_answered` is a question with a single possible answer: do not ask it, mention it in one line, and use its `params.facts_args` as if it had been chosen. When in doubt about someone else's changes, include them.

Then show one summary line without asking: what is reviewed, against which base (`summary.base`), and how many rules were found (`summary.rule_count`).

## 3. Rules and facts

If `rule_files` is not empty, read each rule file (under the repo root) and translate its rules into structured targets, following [references/reglas.md](references/reglas.md). Then run:

`python3 "<SKILL_DIR>/scripts/explain_changes.py" facts <chosen facts_args> --targets-stdin` with the targets JSON on stdin through a heredoc. Without rules, omit `--targets-stdin` and `<<'EOF'`.

The range is exactly one of `--from <ref>` or `--commit <sha>`, plus the optional `--include-uncommitted`, `--exclude-merge <sha>`, `--include-merge <sha>`, `--exclude-author <email>` and `--only-new` that came from the options. Do not combine them any other way. The output lists `totals`, `batches` and `notices` (show them as in step 1). `references/mecanico.md` explains how changes are classified as mechanical or logic; when in doubt the script says logic.

If there are no logic batches (`batches` is empty), skip to step 5: the report will only list mechanical changes.

## 4. Interpretation

For every batch `N` in `batches`, run `python3 "<SKILL_DIR>/scripts/explain_changes.py" bundle --batch N`. The bundle holds `facts_summary`, `logic_hunks`, `logic_files` (logic files with no hunks, such as renames or mode changes, with their rules), `mechanical_summary`, `rules` (numbered lines) and `targets`.

Give the bundle to an **isolated interpreter**:

- **Claude Code**: launch a fresh subagent with medium reasoning effort. Its prompt contains **only** the bundle JSON, the output schema below and the prohibitions. Never include the conversation, your own opinions or the user's words.
- **Agents without subagents**: do it yourself in the same conversation and set `"interpreted_in": "same_conversation"` in the final JSON so the report says so.

The interpreter must produce this JSON and nothing else. It must **not** suggest improvements, judge quality or propose changes; it only says what the code does:

```json
{
  "groups": [
    {"id": "g1", "name": "short name", "order": 1,
     "what": "one or two sentences: what this group does",
     "locations": [{"file": "src/a.ts", "start": 10, "end": 30, "side": "new"}]}
  ],
  "rules": [
    {"rule": {"file": ".agents/rules/hooks.md", "line": 8},
     "status": "complies",
     "changes": [{"file": "src/useX.ts", "line": 12, "side": "new"}],
     "note": "optional, one sentence"}
  ],
  "interpreted_in": "same_conversation"
}
```

Rules for the JSON: group by intent, ordered for reading (what is defined before what uses it); `side` is `new` (default) or `old`; `status` is `complies`, `seems_not` or `not_applicable`; every `file:line` must come from the bundle (rules from `rules[].lines`), because `verify` checks each one; the id `ungrouped` is reserved; omit `interpreted_in` unless the interpreter ran in the same conversation. Logic files with no hunks are cited with a location on that file. Anything left unplaced is added by `verify` to an "Ungrouped" group, so nothing is lost.

With several batches, collect one interpretation per batch, then run one last merge step (same isolation) that receives only those interpretations and unifies groups that cross batches into a single JSON. Then run `verify` once.

## 5. Verify and report

1. `python3 "<SKILL_DIR>/scripts/explain_changes.py" verify` with the interpretation JSON on stdin (heredoc). It returns `unverified_count` and `ungrouped_count`.
2. `python3 "<SKILL_DIR>/scripts/explain_changes.py" report --lang <code>`, where `<code>` is the conversation language (`en`, `es`, ...). For any other language add `--labels-stdin` and send a JSON object of strings with every label key of the English set translated (see [references/reporte.md](references/reporte.md)). The result gives the report path and `notices`.

If `verify` or `report` returns `bad_input`, fix the JSON you sent and retry once; if it fails again, explain and stop.

## 6. Walkthrough

Tell the user where the report is (`.explain-changes/reporte.md`). Then:

1. **Summary first**: files and `+/-`, logic against mechanical lines, rules touched, and any unverified citations.
2. **Group by group** in `order`, one per step. Example (in the user's language):

   ```
   Group 2 of 4: Page size from screen height
     Files: getInfinitePageSize.ts (new, +21), useInfiniteScroll.ts (+38 -1)
     What it does: computes how many rows fit on screen and asks the server for that many
     Rules: .agents/rules/hooks.md:8 "hooks live in use*.ts files" -> complies
   ```

   After each group offer three options (translated): **Next** / **Explain more** / **Show me the code**. "Explain more" gives a deeper account of the same group; "Show me the code" shows the lines with a read-only command or by reading the file. Mention "changed since your last review" when the report says so. Unverified citations are marked as such, never presented as fact.
3. **Mechanical groups together** in one step: lockfiles, generated files, whitespace, moved code and repeated replacements (with their exceptions).
4. Finish by saying the walkthrough is over and where the report is.

## Never

- Never write, edit or delete files yourself, and never create temporary files: the script is the only writer, only inside `.explain-changes/`.
- Never commit, stage, stash, checkout or change the user's repo or Git config. The only network access is the fetch of the base inside `detect`.
- Never run tests, lint or typecheck.
- Never suggest improvements, risks, refactors or fixes, and never judge quality. Explain what the changes do, nothing more.
- Never hide a change: do not drop logic that does not fit a group, and do not skip the walkthrough of a group.
- Never answer a question the script did not ask, and never read from stdin without its flag.
