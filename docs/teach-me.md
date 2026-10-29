# teach-me: usage guide

`teach-me` researches a library, framework, tool or open source project from a URL and then teaches it to you like a professor who already prepared the subject: an ordered syllabus, step by step lessons, doubts answered from what was saved, and varied exams that are graded against the saved sources. You run it yourself (for example `/teach-me https://ai-sdk.dev`); it never starts on its own. It speaks the language of your conversation, and the files it saves are named in that language.

## What it does

- Downloads once, at the start, the documentation pages and (when it exists) the public code of the library, and writes down what it read, what it left out and every page that failed (the "coverage").
- For a monorepo (many packages in one repository) it saves only the package you study, the root files (README, license, changelog, manifests) and up to 300 examples that use it. The rest is listed as "not saved" in the coverage, and when a doubt needs one of those folders the skill offers to download it.
- Writes a syllabus ordered by prerequisites (about one or two days of study) and explains why each topic goes where it goes.
- Teaches one topic at a time in 6 blocks (problem, idea, minimal example, predict, internals, pitfalls), stopping after each block so you can answer or ask.
- Answers your doubts from the saved sources only, citing the page or the `file:line`. Anything it cannot verify is shown with a warning sign, never as a fact. If the answer is not in what was saved, it says "I did not bring that" and offers to download the exact page.
- Closes each topic with an exam of 5 to 8 varied questions (multiple choice, open, predict, when to use, and at most one "read it yourself"). More than 50 percent is right; the exam is passed when the average is above 50 percent. A failed exam never blocks you: you can repeat it or continue.
- Resumes where you stopped, with a quick review of 2 or 3 questions when it has been a while (a review never changes your grades), and tells you when a new version of the library came out.

## What it does not do

- It does not search by name. It always needs a URL (see below).
- It does not write your own notes; those are yours.
- It never runs downloaded code, and it treats everything downloaded as data, never as instructions.
- It does not use Git and writes only inside `~/.teach-me/`.

## The four modes

On every run the first question is "What do you want to do?":

1. Know what it is: **coming soon**
2. Know what it is and how it is built (must be open source): **coming soon**
3. **Study how to use it**
4. Study how to use it and how it is built (must be open source): **coming soon**

Only "Study how to use it" works today. If you pick another one, the skill tells you it is not built yet and offers "Study how to use it".

## Always with a URL

Invoke it with an `http(s)` URL: the documentation, the website or the repository. A bare name such as "Vercel SDK" is never accepted, and the skill never searches by name, so it cannot research the wrong thing by mistake. If you invoke it without a URL, it lists the libraries you already have saved (with their URLs, so you can copy one) and asks for a URL. If the URL belongs to a library you already studied, it resumes that one.

## What if there is no public code

- If the URL does not lead to a public GitHub repository, the research continues from the documentation only, and the coverage says "no public code". Only GitHub is supported for code in this version: a project hosted somewhere else is treated the same way, with a notice.
- "Study how to use it" still works if there is public usage documentation (guides or API reference). If there is none, the skill says so and stops.
- It never deduces how something is built from indirect signs (HTTP headers, code that reaches the browser, job offers) and never reverse engineers anything.

## What is saved, and where

Everything is Markdown in a hidden folder in your home directory, `~/.teach-me/`, with one folder per library. The names of files and folders follow the language of the conversation **in which the library was first studied**; the language is fixed when the folder is created. Spanish and English are built in; for another language the AI translates the names once.

```
~/.teach-me/
  README.md                       index: library | URLs | version | mode | status
  config.md                       worker models per agent (see below)
  ai-sdk/                         one folder per library (English names shown)
    profile.md                    language, roots, license, version, phases, coverage
    syllabus.md                   topics in order, why each goes there, their sources
    topics/01-<slug>.md           material of each topic, with sources and literal excerpts
    exams/01-<slug>-attempt-1.md  each exam attempt, with the report
    progress.md                   status of each topic and what is pending
    sources/docs/…                every downloaded page, with its origin URL and date
    sources/code/<version>/…      the code as downloaded (a monorepo: only the studied package,
                                  the root files and the examples that use it; the rest is
                                  listed as not saved)
    sources/meta/…                npm, PyPI and GitHub answers
```

| Spanish | English |
|---|---|
| `ficha.md` | `profile.md` |
| `temario.md` | `syllabus.md` |
| `temas/01-que-es.md` | `topics/01-what-it-is.md` |
| `examenes/01-…-intento-1.md` | `exams/01-…-attempt-1.md` |
| `avance.md` | `progress.md` |
| `fuentes/docs`, `fuentes/codigo`, `fuentes/meta` | `sources/docs`, `sources/code`, `sources/meta` |

`README.md` and `config.md` at the root keep those names in every language. Only the skill's script writes in this folder; to move the data somewhere else, set the `TEACH_ME_HOME` environment variable.

### Seeing the hidden folder

- **Finder (macOS):** open your home folder and press `Cmd + Shift + .` to show or hide hidden folders.
- **Terminal:** `open ~/.teach-me` (macOS) or `ls -a ~`.
- **Obsidian:** the files are plain Markdown, so you can open `~/.teach-me/` as a vault ("Open folder as vault"). The topics link to each other and to the profile with `[[name]]` links, which Obsidian draws as a graph and any other editor shows as normal text. Obsidian is optional; the skill does not need it.
- If Obsidian does not open a hidden folder well, make a visible shortcut and open that as the vault: `ln -s ~/.teach-me ~/teach-me`.

## `config.md`: models of the helpers

Three cheap helpers do small tasks: **consult** (answers doubts), **support** (checks each claim against its excerpt) and **grading** (grades the exams). Their models are listed per agent in `~/.teach-me/config.md`, created the first time it is needed. You may edit the values in the front matter at the top of the file; your edits are kept.

| Agent | consult | support | grading | effort | Status |
|---|---|---|---|---|---|
| `claude-code` | `haiku` | `haiku` | `sonnet` | `medium` | tested |
| `codex` | `gpt-6-luna` | `gpt-6-luna` | empty | empty | not verified (taken from the [Codex subagents docs](https://learn.chatgpt.com/docs/agent-configuration/subagents)) |
| `cursor` | empty | empty | empty | empty | not verified |
| `opencode` | empty | empty | empty | empty | not verified |
| `antigravity` | empty | empty | empty | empty | not verified |

Empty means the work stays in the same conversation, and the saved files say so (`same_conversation`). The helpers run one at a time, never in parallel.

## Example of an exam report

For a made-up library called `tiny-cache`, topic "Expiring entries":

```
Exam: Expiring entries (attempt 1)

1. ✅ 100%  Which option sets how long an entry lives?
   Right: you chose `ttl`.
   Reference: `ttl` is the lifetime in seconds. Source: docs/options (https://tiny-cache.example/docs/options)

2. ❌ 40%   Explain in your own words what happens to an expired entry.
   Right: it is no longer returned.
   Missing: it is removed lazily, on the next read, not at the moment it expires.
   Reference: "Expired entries are deleted on access." Source: docs/expiry (https://tiny-cache.example/docs/expiry)

3. ✅ 60%   What does `cache.get("a")` return if `"a"` expired a minute ago?
   Right: `undefined`, not an error.
   Missing: the expired entry is deleted by that same call.
   Reference: "Expired entries are deleted on access." Source: docs/expiry (https://tiny-cache.example/docs/expiry)

4. ✅ 80%   When would you use `get` and when `peek`?
   Right: `peek` does not refresh the entry.
   Missing: `get` also extends the lifetime when `refresh` is on.
   Reference: src/cache.ts:42-58

5. ⏭️ Skipped  Read `Cache.sweep` in src/cache.ts yourself and say what it does.
   You read this one yourself; it is not graded and not part of the average.

Score: 70% (average of 4 graded questions; the one you read yourself is excluded). Passed.
```

A check means more than 50 percent, a cross means 50 or less. The script computes the percentages, the average and whether it passed; the AI only shows them. If you do not pass, you choose between repeating the exam (new questions) or continuing (the topic stays pending and is reminded later).

## `GITHUB_TOKEN` (optional)

GitHub limits anonymous requests. If you hit the limit (see `github_rate_limited` below), set a `GITHUB_TOKEN` environment variable in your terminal before starting the agent. The script reads it from the environment only, uses it only for `api.github.com` and `codeload.github.com`, and never writes it to disk or prints it. The skill never asks you for it in the conversation.

## Updating to a new version

On a library you already studied, the skill runs `check-update` first. If a new version came out, it says so and updates only what changed:

1. Reads the changelog between your version and the new one.
2. Fetches the new version information and the new code (when there is public code).
3. Discovers and downloads new documentation pages, and re-downloads the pages the changelog says changed with `fetch-docs --url <page> --refresh` (without `--refresh`, a page already downloaded is never fetched again).
4. Marks the affected topics as outdated and adds topics to the syllabus if needed. Your progress is kept by topic.

## Requirements

Python 3.9 or newer. Standard library only: nothing to install with `pip`. The skill checks the version before anything else and stops with a clear message if Python is missing or too old.

## Troubleshooting

Blocks stop the step before anything unsafe happens, and the skill explains them in plain words.

### `github_rate_limited`

GitHub refused more anonymous requests. Set the `GITHUB_TOKEN` environment variable (see above), restart the agent and run again; what is already downloaded is kept and the research resumes from where it stopped. Waiting about an hour also works.

### `too_large`

A page or file is bigger than the technical safety limit. The skill does not ask for confirmation to download everything, but it skips what exceeds the limit and declares it in the coverage. You can still ask about it; the skill reports that it was not read.

### `busy`

Another session is writing to the same library folder. The skill waits a few seconds and retries. If it persists, close the other session. A lock older than 10 minutes is treated as abandoned and replaced.

### `not_writable`

The skill cannot write in `~/.teach-me/` (or in the folder set by `TEACH_ME_HOME`). The message gives the path. Fix its permissions or point `TEACH_ME_HOME` to a folder you can write to.

### Pages that only show with JavaScript

Some documentation sites render empty or navigation-only pages without JavaScript. If your agent has its own web or browser tool, the skill uses it to read those pages and says so in the coverage; otherwise it lists them as not downloaded with the reason. If many pages fail this way, try a URL of the repository or of a documentation mirror.

## Invocation lock per agent

`teach-me` is meant to run only when you invoke it. It sets `disable-model-invocation: true` and includes `agents/openai.yaml` with `policy.allow_implicit_invocation: false` for Codex. The full table per agent, with what is documented and what is not verified, is in the [README](../README.md#invocation-lock-per-agent).
