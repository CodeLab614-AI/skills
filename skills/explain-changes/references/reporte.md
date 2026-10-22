# Report and walkthrough format

`report --lang <code>` writes `.explain-changes/reporte.md` (overwritten each run) and the
branch state `.explain-changes/estado/<branch>-<hash>.json`. Optional stdin: a JSON object
`labels` of strings, read only when `--labels-stdin` is given; its keys replace the built-in texts for `--lang` (`en`, `es`) and let
the agent supply any other language (send every key of the English set translated).

## Sections (fixed order)

1. **Summary**: file count with `+/-`, logic lines vs mechanical lines, number of rules touched.
2. **Rules**: grouped as complies / seems not to comply / not applicable, each item citing
   `rule file:line -> changed file:line`. With no rules the section says so.
3. **Logic changes**: one block per group, sorted by `order`: name, what it does, files with
   `+/-`, rules that apply, and a "changed since your last review" line when any hunk of the
   group changed after the saved review. The synthetic "ungrouped" group collects logic the
   interpreter did not place; logic is never dropped.
4. **Mechanical changes**: by kind (lockfiles, generated, whitespace, moved code, repeated
   replacements). Repeated replacements list `old -> new`, the file count and the exceptions.
   Omitted when there is nothing mechanical.
5. **Unverified citations**: every citation the script could not confirm, marked with a
   warning sign. Omitted when all citations verified. Unverified citations are also marked
   inline where they appear.
6. **Provenance**: from, to (or working tree), merge-base, excluded merges and authors, the reviewed commits (short sha and subject, at most 50, non-merge, excluded authors left out), and
   "interpreted in the same conversation" when `interpreted_in` is `same_conversation`.

## State and cleanup

The state stores fingerprints of the reviewed hunks so a later `facts --only-new` can show
only what is new. With `--only-new` the new state is the union of the previous one and the
new hunks. A detached HEAD keeps no state (`state_path` is null). States of branches that no
longer exist, or whose saved head is already contained in the base, are deleted; a failure
there becomes a `state_cleanup_failed` notice and never blocks the report.

## Walkthrough (step 6 of the flow)

After writing the report, the agent walks the user through the logic groups in `order`,
one group at a time, in the conversation language: say what the group does, point to its
files and lines, and wait for the user before moving on. The walkthrough adds no
suggestions, risks or improvements, and nothing is committed.


## Label keys (English set)

For `--labels-stdin`, send a JSON object of strings with every key below, translated. Keep the keys, translate only the text.

| key | English text |
|---|---|
| `title` | Change report |
| `h_summary` | Summary |
| `h_rules` | Rules |
| `h_groups` | Logic changes |
| `h_mechanical` | Mechanical changes |
| `h_unverified` | Unverified citations |
| `h_provenance` | Provenance |
| `files` | files |
| `additions` | additions |
| `deletions` | deletions |
| `logic_lines` | logic lines |
| `mechanical_lines` | mechanical lines |
| `rules_touched` | rules touched |
| `no_rules` | No rules apply to these changes. |
| `complies` | Complies |
| `seems_not` | Seems not to comply |
| `not_applicable` | Not applicable |
| `rule` | rule |
| `ungrouped` | Ungrouped |
| `unnamed` | Unnamed group |
| `changed_since_review` | Changed since your last review |
| `rules_label` | Rules |
| `kind_lockfile` | Lockfiles |
| `kind_generated` | Generated files |
| `kind_whitespace` | Whitespace and formatting |
| `kind_move` | Moved code |
| `kind_repeated_replacement` | Repeated replacements |
| `replaces` | replaced by |
| `in_files` | files |
| `exceptions` | Exceptions |
| `unverified_citation` | unverified citation |
| `from` | From |
| `to` | To |
| `working_tree` | working tree |
| `excluded_merges` | Excluded merges |
| `excluded_authors` | Excluded authors |
| `same_conversation` | Interpreted in the same conversation |
| `none` | none |
| `commits` | Commits |
| `commits_truncated` | (list truncated to the first 50) |
