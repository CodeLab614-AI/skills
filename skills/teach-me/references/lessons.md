# Syllabus and lessons

## Syllabus

Send to `python3 "<SKILL_DIR>/scripts/teach_me.py" save-syllabus <id>` (stdin JSON). Only modes 3 and 4 have a syllabus (modes 1 and 2: `part_not_in_mode`). Each topic has a `part`: `use`, or `internals` (mode 4 only; in mode 3 it is blocked with `part_not_in_mode`, and without public code with `no_public_code`). Put every `use` topic first and the `internals` topics after them: the order of the file is the order of study.

```
{"topics": [
  {"slug": "what-it-is", "title": "What it is",
   "objective": "Explain what the library is for and install it.",
   "why_here": "Everything else assumes it is installed.",
   "part": "use", "depends_on": [],
   "sources": [{"kind": "doc", "url": "https://...", "quote": "literal text"}]},
  {"slug": "streaming", "title": "Streaming text", "objective": "...", "why_here": "...",
   "part": "use", "depends_on": ["what-it-is"], "sources": [...]}
]}
```

Rules: slugs match `^[a-z0-9][a-z0-9-]*$`, are unique, and are in the dossier language. `depends_on` lists only earlier slugs (order by prerequisites; no topic uses what was not seen). Every topic has at least one citation, checked against the saved sources. Slugs, titles and reasons are written in the conversation language. Aim for a syllabus that takes one or two days. Saving again keeps progress by slug.

### Second part: how it is built (mode 4)

After the `use` part, add the `internals` topics (usually 3 to 6): the map of the main pieces, how they connect, what happens inside in one or two typical uses, and the design decisions the code or its docs explain. Read the internal modules first (built.md says how) and cite code (`kind: "code"`) for each topic. Each `internals` topic lists in `depends_on` the `use` topics it needs and any earlier `internals` topic, so a person who finished the `use` part continues straight into it. When mode 3 changes to mode 4, call `save-syllabus` again with all the topics (the existing `use` ones unchanged plus the new `internals` ones): progress and notes are kept by slug. When mode 4 changes to mode 3 the `internals` topics are set aside, not deleted, and do not count as pending. Lessons and exams of an `internals` topic work like any other topic. Show the person the result: number, title, objective and why it goes there.

## Writing a topic

Written when the topic starts, from what was already downloaded (use `search`, then read the pages or code you need). Send `python3 "<SKILL_DIR>/scripts/teach_me.py" save-topic <id>` the JSON below after the `excerpts` and support steps in sources.md:

```
{"slug": "streaming", "support_checked_in": "subagent",
 "blocks": [
  {"kind": "problem",   "claims": [...]},
  {"kind": "idea",      "claims": [...]},
  {"kind": "example",   "claims": [...], "code": "minimal runnable example", "code_support": "supported"},
  {"kind": "predict",   "claims": [...], "code": "snippet whose output the person predicts", "code_support": "supported"},
  {"kind": "internals", "claims": [...]},
  {"kind": "pitfalls",  "claims": [...]}
 ]}
```

Exactly these six blocks, in this order, each with at least one claim. `code` is optional; every block with code needs `code_support` from the support worker (see sources.md), and the code must use only what the excerpts of that block show (cite where it comes from in a claim of that block). Links to other topics and to the syllabus are written by the script.

## Teaching the six blocks

Teach in short blocks and **pause after each one**: stop, let the person digest, write notes, and ask. Only continue when they say they have it. Never put several new concepts in one block.

1. **The problem it solves.** One concrete situation without the library. Pause.
2. **The idea in one sentence.** One sentence only. Pause.
3. **A minimal example.** The smallest code that works, line by line. Pause.
4. **Predict what it does.** Show a variation and ask the person to predict the result before you reveal it. Wait for their answer, then explain. Pause.
5. **How it is built inside** (file and line). Show where in the saved code or docs this behavior comes from, with the citation. Only what the usage needs. Pause.
6. **Typical mistakes.** The common errors and how to recognize them. Pause, then say the topic is over and the exam comes next.

Between blocks, answer doubts with the consult worker and record each one (`progress <id> doubt --topic <slug>`, text on stdin). Do not send the person to read the docs or the code during the lesson; if something is missing, say "I did not bring that" and download it.
