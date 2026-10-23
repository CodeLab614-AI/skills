# Report format

`report --lang <code>` writes two files, overwritten on every run, and the branch state:

- `.explain-changes/report.md`: the summary only, identical to the one shown in the conversation.
- `.explain-changes/report.html`: one self-contained file (no external resources, works offline, light and dark mode) with the same summary and every detail closed under it.
- `.explain-changes/state/<branch>-<hash>.json`: what was reviewed, so a later run can show only what is new.

Optional stdin: a JSON object `labels` of strings, read only when `--labels-stdin` is given; its keys replace the built-in texts for `--lang` (`en`, `es`) and let the agent supply any other language (send every key of the English set translated).

## The summary (report.md and the conversation)

1. **Lead line**: `N files, but what matters is X things:` (the script counts the files and the points).
2. **Numbered points**, at most about 5. Each one is a short bold title plus one or two lines: what was done and where.
3. **`The rest (N files): ...`** on a single line.
4. **`Not grouped (N files): ...`** only when the interpreter left logic files unplaced. They are never hidden.
5. **`Watch your rules:`** only when a rule seems not to be met: the concrete change, then `Your rule <name> says: «<what it says>».` Rules that are met or do not apply never appear. The name comes from the folder or the file (`.../preserve-comments/RULE.md` is `preserve-comments`), never an internal id such as `R1`. A warning whose citation could not be verified is marked with a warning sign and never presented as fact.

Texts allow only `` `inline code` `` and `**bold**`. Anything else is plain text.

In the conversation the agent shows this summary, then the paths of both files, then asks whether the user wants anything explained.

## What is important

Important: new reusable pieces (helper, hook, component, function), behavior changes, props, parameters, returns or exports that change or disappear, new configuration or dependencies. Not important (goes to "the rest"): tests, stories, docs, imports and exports in an index, cleanup that follows an important change, mechanical changes.

## report.html

Top to bottom: a gray line with the branch and the totals, the summary, then the details.

- Each point is a closed `<details>`. Open: a longer explanation, an optional table (for example parameter | what it is) and its files, each closed. A file header shows the path (dim folder, bold name), the tags `new` / `explained`, and `+/-`.
- Code is highlighted like an editor (keywords, strings, numbers, types, function calls, comments). New files look like normal code; modified files look like a diff with a faint green or red background.
- Explanatory comments for a junior developer sit inside the code of the important points only, in their own color and without line numbers: above the block they explain (one `/* ... */` block when long, `//` when short) or at the end of a line. A note at the bottom of the file says they are not in the user's code.
- "The rest" is one closed `<details>` with the files grouped by kind (tests, stories, docs, imports and exports, cleanup, other, mechanical), each closed. Files the interpreter did not place carry the tag "the AI did not explain it".
- Each rule warning has "See the rule and the code": the original rule text, `path:line` and the cited lines highlighted. Unverified citations carry a warning sign and no code.
- At the bottom, small: what was reviewed (range, base, exclusions).

Everything that comes from the repository or the interpreter is escaped.

## State and cleanup

The state stores fingerprints of the reviewed hunks so a later `facts --only-new` can show only what is new. With `--only-new` the new state is the union of the previous one and the new hunks. A detached HEAD keeps no state (`state_path` is null). States of branches that no longer exist, or whose saved head is already contained in the base, are deleted; a failure there becomes a `state_cleanup_failed` notice and never blocks the report.

## Questions after the summary

The old group-by-group walkthrough is gone. The user can ask about any file, helper, hook, function or point; the agent reads the code (read-only) and explains it in detail. No suggestions, risks or improvements, and nothing is committed.

## Label keys (English set)

For `--labels-stdin`, send a JSON object of strings with every key below, translated. Keep the keys and the `{placeholders}`, translate only the text.

| key | English text |
|---|---|
| `page_title` | What the AI did |
| `count_files_one` | {n} file |
| `count_files_many` | {n} files |
| `lead_many` | {files}, but what matters is {n} things: |
| `lead_one` | {files}, but what matters is 1 thing: |
| `lead_none` | {files}, with no logic changes to highlight. |
| `no_changes` | There are no changes to explain. |
| `rest_head` | The rest ({files}): |
| `and_more` | and {n} more |
| `warn_head` | Watch your rules: |
| `warn_rule` | Your rule {name} says: «{says}». |
| `unverified_citation` | unverified citation |
| `no_branch` | detached HEAD |
| `tag_new` | new |
| `tag_explained` | explained |
| `tag_unexplained` | the AI did not explain it |
| `code_title` | Code |
| `no_text_lines` | No text lines (binary file, rename or permission change). |
| `comment_note` | Comments in this color are explanations from the report; they are not in your code. |
| `see_rule` | See the rule and the code |
| `rule_original` | Original text |
| `old_version` | old version |
| `new_version` | new version |
| `kind_tests` | Tests |
| `kind_stories` | Stories |
| `kind_docs` | Documentation |
| `kind_exports` | Imports and exports |
| `kind_cleanup` | Cleanup |
| `kind_other` | Other |
| `kind_mechanical` | Mechanical changes |
| `kind_unexplained` | Not grouped |
| `kind_lockfile` | lockfile |
| `kind_generated` | generated |
| `kind_whitespace` | whitespace |
| `kind_move` | moved |
| `kind_repeated_replacement` | repeated replacement |
| `reviewed` | What was reviewed |
| `from` | from |
| `to` | to |
| `base` | base |
| `working_tree` | working tree |
| `excluded_merges` | excluded merges |
| `excluded_authors` | excluded authors |
| `none` | none |
| `same_conversation` | Interpreted in the same conversation |
