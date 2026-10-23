# explain-changes: usage guide

`explain-changes` tells you, in under two minutes, what the AI did on your current Git branch. You already know what you planned; this shows you what actually happened. You run it yourself (for example `/explain-changes`); it never starts on its own. It speaks the language of your conversation: the questions, the summary, the reports and the comments inside the code come out in that language.

## What it does

- Writes a short summary in the conversation: "N files, but what matters is X things:" and a numbered list (about 5 at most), each with a bold title and one or two lines about what was done and where. Important means new reusable pieces (helper, hook, component, function), behavior changes, props, parameters, returns or exports that change or disappear, and new configuration or dependencies. Tests, stories, docs, exports in an index, follow-up cleanup and mechanical changes go in a single line: "The rest (N files)".
- Adds "Watch your rules:" only when a rule of your project (`AGENTS.md`, `CLAUDE.md`, `.cursor/rules/**` and similar) seems not to be met: the concrete change and "Your rule <name> says: «...»". Rules that are met or do not apply are not mentioned, and no internal ids appear.
- Writes `.explain-changes/report.md` (that same summary) and `.explain-changes/report.html` (one self-contained file, no internet needed, light and dark mode) where each point opens to a longer explanation, a table when it helps and its code, highlighted like an editor, with explanations for a junior developer written inside the code (in their own color, marked as not being in your code).
- Separates mechanical changes (lockfiles, generated files, whitespace-only edits, moved code, repeated replacements) from logic, deterministically. When in doubt, a change counts as logic.
- Checks every file, rule line, cited line and code comment against the real diff. What cannot be confirmed is dropped (comments) or marked as unverified and shown without code, never presented as fact. Files the AI did not place in a point are never hidden: they show up as "not grouped".
- Then asks whether you want something explained. You can ask about any file, helper, hook, function or point; the agent reads the code (read-only) and explains it in detail.
- Leaves out what came from the base branch, from other people's merged branches and from other authors, if you choose so. Nothing of yours is hidden: when in doubt, it is included. A change of file mode (for example making a script executable) is always shown as logic, even next to a whitespace edit, and a file the script cannot read (a nested repository or an unreadable file) is reported in a notice instead of being silently dropped.

## What it does not do

- It does not suggest improvements, point out risks or judge quality.
- It does not fix anything and does not generate correction prompts.
- It does not run tests, lint or typecheck.
- It does not commit, stage, stash or check out anything.
- It writes only inside `.explain-changes/`. The only network access is a `git fetch` of the base branch, which updates remote references only.

## Requirements

Git and Python 3.9 or newer. Nothing else: no `pip install`, no `gh`, no `jira`.

The heredoc examples in the skill assume a POSIX shell (bash, zsh). On Windows PowerShell the agent pipes a here-string to the command instead (`@'` ... `'@ | python ...`).

## The flow in 6 steps

1. **Detect.** The script inspects the repo: branch, base branch, your commits, merged branches that are not yours, other authors' commits, uncommitted changes, the last review and the rule files found.
2. **Questions.** Only the ones that apply: what to review (the whole branch, only what is new since your last review, from a commit you choose, only uncommitted work, or the commit that merged or squashed the branch), whether to leave out merged branches that are not yours, and whether to leave out other authors' commits. A question with a single possible answer is not asked. Then one summary line: what is reviewed, against which base and how many rules were found.
3. **Facts.** The agent turns your rules into structured targets and the script computes the diff against the merge-base, classifies mechanical against logic, applies the rule targets and splits very large changes into batches.
4. **Interpretation.** An isolated interpreter (a fresh subagent where the agent supports it; otherwise the same conversation, and the report says so) picks the points that matter, groups the rest, finds the rules that seem not to be met and writes the explanatory comments for the code.
5. **Verify and report.** The script verifies every citation and comment, places any file that was left out in "not grouped" so nothing is lost, and writes `report.md` and `report.html`.
6. **Summary and questions.** The agent shows the summary, says where both reports are and asks whether you want anything explained.

## Example of the summary

```
49 files, but what matters is 3 things:

1. **New reusable helper `getTotal`** in `src/helpers/`: adds up the prices of a cart.
2. **`useCart` now uses it:** the cart views pass the price list and the total updates by itself.
3. **The discount selector was removed from `CartSummary`**: its 3 props disappear.

**The rest (46 files):** tests and stories adjusted, exports in `index.ts`, docs.

**Watch your rules:**

- Two comments were deleted along with the old selector. Your rule **preserve-comments** says: «do not delete comments when refactoring».
```

## What is written, and where

Everything lives in `.explain-changes/` at the root of the repo:

| Path | Content |
|---|---|
| `report.md` | The summary, identical to the one in the conversation. Overwritten on every run. |
| `report.html` | The same summary plus the code of every point, closed until you open it. Overwritten on every run. |
| `run/` | Working files of the current run (`facts.json`, `verified.json`). |
| `state/<branch>-<hash>.json` | Per-branch state: last reviewed commit and fingerprints of reviewed changes. Kept between runs. |

Before writing, the script adds `/.explain-changes/` to `.git/info/exclude` (a local file, never committed) and confirms with `git check-ignore` that it is excluded. If it cannot guarantee that, it writes nothing (see `not_excluded`). Each run removes only the files the skill itself created earlier, and removes the state of branches that no longer exist or are already merged into the base. Your tracked and untracked files are never touched, and nothing is ever committed.

### What "from a commit" and merged branches mean

- **From a commit** is inclusive: you pick a commit and the review starts with that commit's own change and includes everything after it (`--from-commit`). Picking the first commit of the repository works too.
- **A branch that was already merged.** If it was merged with a merge commit or squashed, the commit that merged it is offered and recommended. If it was merged by content (the same files now match the base) or by fast-forward, a single commit would cover only part of your work, so the whole branch since the merge-base is recommended when there is one, and "the merge commit" is not offered.

### What counts as mechanical

Lockfiles, generated files, moved files, repeated token replacements and whitespace-only edits. The whitespace rule keeps word boundaries: `foo( a )` to `foo(a)` or `x=1` to `x = 1` is mechanical, but `a b` to `ab` or `"Hello World"` to `"HelloWorld"` is logic. In Python, YAML, Makefiles and similar files a changed indentation is logic. A file whose mode changed never gets whitespace-mechanical hunks. When in doubt, it is logic.

## Only what is new

When there is a previous review of the branch and new commits since, the first question offers "only what is new". Changes after the last reviewed commit, plus uncommitted work, are shown. If you rewrote history (rebase, amend), what is new is detected by content instead, and you are told so.

## Troubleshooting

Blocks stop the run before anything is written, and the skill explains them in plain words. It never tries to repair your repository.

### `not_a_git_repo`

The current folder is not inside a Git repository. Open the agent in a folder that is inside a repo (or run `git init`) and invoke the skill again.

### `rebase_in_progress`

A rebase is running. Finish it (`git rebase --continue`) or abort it (`git rebase --abort`), then run again.

### `merge_in_progress`

A merge is running. Finish it (commit the merge) or abort it (`git merge --abort`), then run again.

### `unresolved_conflicts`

Some files have unresolved conflicts. Resolve them and mark them as resolved, then run again.

### `shallow_no_merge_base`

The clone is shallow and the base branch is not reachable from it, so no merge-base can be computed. The skill never deepens a clone for you. If you want to, do it yourself (for example `git fetch --deepen=100` or `git fetch --unshallow`) and run again.

### `no_base_branch`

No base branch was found: neither `origin/HEAD` nor `main`, `master` or `develop`. Create or fetch one of them (for example `git remote add origin ...` and `git fetch`) and run again.

### `not_excluded`

`.explain-changes/` could not be excluded from Git, so nothing was written. Usually `.git/info/exclude` is not writable. Make it writable or add the line `/.explain-changes/` to it yourself, then run again.

### `bad_input`

A call to the script was malformed (for example an invalid flag or invalid JSON on stdin). The skill corrects the call and retries once; if it fails again it shows the message. If you see this repeatedly, please report it with the message.

### Python not found, or older than 3.9

The skill needs Python 3.9 or newer and checks it before anything else; if it is missing or too old it tells you and stops. Install a current Python 3 (on macOS, `xcode-select --install` or python.org; on Windows, python.org, where the command may be `python` instead of `python3`) and run again.

### `fetch_failed` (a notice, not a block)

The `git fetch` of the base branch failed, usually for lack of network. The run continues with your local copy of the base and says so. Run again once you are online to compare against a fresher base. To skip the fetch on purpose, ask for no network access and the skill passes `--no-fetch`.

## Invocation lock per agent

The skill is meant to run only when you invoke it. Whether the agent enforces that depends on the agent; the table is in the [README](../README.md#invocation-lock-per-agent). Summary: Claude Code and Codex have a documented lock (`disable-model-invocation: true` and `agents/openai.yaml`); Cursor documents the same frontmatter field (not verified in a live run); OpenCode needs `opencode.json` settings; Antigravity documents no lock, so only the `description` guides it. Everything not tested live is marked "not verified" there.
