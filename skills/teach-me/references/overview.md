# Overview report (modes 1 and 2)

Read this for "Know what it is" and "Know what it is and how it is built". The person gets a researched report and then asks until they know whether it fits what they want to build. There is no syllabus and no exam, and you give **no verdict**: "it suits you / it does not" is the person's call.

## Competitors (3 to 5)

1. **Candidates**, from three places: comparison or "alternatives" pages in the docs and the README; `python3 "<SKILL_DIR>/scripts/teach_me.py" search-packages <id> --npm "<keywords>" [--size N]` (npm only); and your own web search if your agent has one. PyPI has no search (`search_not_available`): for Python, candidates come from the docs, the README and the web search.
2. **Verify each one** with `python3 "<SKILL_DIR>/scripts/teach_me.py" fetch-competitor <id> --repo OWNER/NAME [--npm NAME | --pypi NAME]`. It stores the licence, the latest version, the activity and the README under `competitors` in the profile. A competitor needs a GitHub repository; without one it is not listed. Mention `license_mismatch` and `no_readme` notices.
3. **Never from memory.** What is not verified is not listed. If fewer than 3 could be verified, show what there is (even none) and say so; do not fill the table.
4. Read the README of each (its `readme_url` is a saved page, citable as `{"kind": "doc", "url": <readme_url>, "quote": "..."}`) to write what it does and how it differs from the studied library. Each difference needs its own citation.

## What to read first

The entry pages, the README, the examples, what the package exposes and the manifest (research.md, "Light research"). The "Cobertura" (coverage) section and the licence, version and dates of the competitors table are written by the script from what it downloaded; you only send claims.

## Saving

Write every claim with citations, run `excerpts` and the support worker as in [sources.md](sources.md) (including the code check for a section with `code`), then send to `python3 "<SKILL_DIR>/scripts/teach_me.py" save-overview <id>` (stdin):

```
{"support_checked_in": "subagent",
 "sections": [
  {"kind": "what",       "claims": [...]},
  {"kind": "use_cases",  "claims": [...]},
  {"kind": "works_with", "claims": [...]},
  {"kind": "example",    "claims": [...], "code": "minimal example from the docs", "code_support": "supported"},
  {"kind": "competitors", "rows": [
    {"competitor": "owner/name",
     "one_liner":  {"text": "...", "kind": "fact", "sources": [...], "support": "supported"},
     "difference": {"text": "...", "kind": "fact", "sources": [...], "support": "supported"}}
  ]}
 ]}
```

Exactly these five sections, in this order. `works_with` covers language, environment, requirements, dependencies and installation; `example` is a minimal example from the docs or the examples (`code` is optional); `competitors` has 0 to 5 `rows`, and each `competitor` is the `OWNER/NAME` you fetched. Blocks: `competitor_not_fetched` (a row without `fetch-competitor`), `part_not_in_mode` (the mode has no overview), plus the support codes of sources.md. `python3 "<SKILL_DIR>/scripts/teach_me.py" show-part <id> overview` returns the saved report (`part_not_saved` if there is none).

## Presenting it

Do not paste the report. Tell it in short parts, **pausing after each**: what it is and does; what it is for; what it is used with; what using it looks like; the competitors; the coverage. Ask whether to go on or whether they have a doubt. Doubts go to the consult worker ([consult.md](consult.md)); there are no topics here, so nothing is recorded. If it is not saved, say "I did not bring that" and offer to download the page.

## New version

When `check-update` says `changed` in mode 1 or 2, regenerate the report from the new downloads: refresh the entry pages and the README, run `fetch-competitor` again for each listed competitor, and save again with `save-overview` (in mode 2, the tour too: built.md).
