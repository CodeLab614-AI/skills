# Project rules

Rules are the project's own instructions to agents and contributors. `detect` finds the files; you read them and turn them into targets; the script applies the targets deterministically. The script does not understand natural language, you do.

## Where rules come from (search order)

`detect` returns them in `rule_files` (each with `path`, `kind`, `line_count`, `imported_from`). The order is:

1. `.agents/rules/**`
2. `AGENTS.md`
3. `CLAUDE.md`, and every file it imports with `@path` (up to 5 levels, inside the repo only)
4. `.cursor/rules/**`
5. `.cursorrules`
6. `.github/copilot-instructions.md`
7. `.windsurfrules`
8. `CONTRIBUTING.md`

Also any `AGENTS.md` in a subfolder that contains a changed file. Only text files inside the repo count. If `rule_files` is empty there are no rules: skip targets, and the report says so.

## From rule to targets

Read every rule file. For each rule that talks about a kind of change or a path, emit one target. Targets are a JSON list sent on stdin to `facts --targets-stdin`:

```json
[
  {"id": "R1",
   "rule": {"file": ".agents/rules/types.md", "line": 4},
   "paths": ["**/*.ts"],
   "change_kinds": ["delete"],
   "line_pattern": "^export (type|interface)"}
]
```

- `id`: unique non-empty string (`R1`, `R2`, ...).
- `rule`: `file` is the rule file path from `rule_files`, `line` is the 1-based line of the rule in that file (the line numbers in the bundle's `rules` are the same).
- `paths`: globs relative to the repo root; `**/` crosses folders, `*` and `?` do not cross `/`. Empty or missing means any path. Renamed files match by new or old path.
- `change_kinds`: any of `add`, `modify`, `delete`, `rename`, `mode`, `add_dependency` (new line in a manifest such as `package.json`, `requirements*.txt`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `Gemfile`, `composer.json`). Empty or missing means any kind.
- `line_pattern`: optional regex tested against the added and removed lines of a hunk. Omit it or use `null` when the path and kind are enough. Keep it a plain, valid regex.

All present fields must match for a hunk to be hit. Be precise rather than broad, but when a rule is ambiguous prefer to match: hiding a relevant change is worse than listing an extra one.

Examples (rule text, then target):

- "Do not delete exported types": `{paths: ["**/*.ts"], change_kinds: ["delete"], line_pattern: "^export (type|interface)"}`
- "Hooks live in `use*.ts` files": `{paths: ["**/*.ts", "**/*.tsx"], change_kinds: ["add"], line_pattern: "\\buse[A-Z]\\w*\\s*\\("}`
- "Do not add dependencies without discussing": `{paths: [], change_kinds: ["add_dependency"]}`
- "Never touch `migrations/`": `{paths: ["migrations/**"], change_kinds: []}`
- "Scripts must stay executable": `{paths: ["scripts/**"], change_kinds: ["mode"]}`

Rules that only describe style or behaviour without pointing at a path or kind of change (for example "write clear names") need no target; you still cite them in the interpretation if a change clearly touches them.

## Rules beat mechanical classification

The script applies targets to every hunk and file, **including mechanical ones** (lockfiles, generated, whitespace, moves, repeated replacements; see [mecanico.md](mecanico.md)). A match lifts the change to logic and records the target id, so it is never hidden under "mechanical". The bundle also gives `mechanical_summary` (file and kind) so you can notice a rule that your targets missed; if a rule clearly touches a mechanical file, cite it in the interpretation anyway.

## The three states

For each rule that is touched, the interpretation sets `status` and cites the rule line and the changed lines (`verify` checks both). The report layout is in [reporte.md](reporte.md).

- `complies`: the change touches the rule and follows it.
- `seems_not`: the change touches the rule and seems not to follow it. State the fact (what the rule says, what the code does); give no advice and no fix.
- `not_applicable`: the rule is about something these changes do not touch.

The report groups them in that order. The status is the interpreter's reading, not a verdict, so the wording stays neutral.
