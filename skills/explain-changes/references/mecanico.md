# Mechanical classification

`facts` marks every hunk and file as `mechanical` or `logic`. The rules are deterministic. **When in doubt, it is logic.** A file is mechanical only if all of its hunks are. A file with no hunks is mechanical only in the explicit cases below (lockfile, generated, pure move). Binary and `too_large` files that match no lockfile or generated rule stay logic.

## Lockfiles (`mechanical_kind: lockfile`), matched by file name

`package-lock.json`, `npm-shrinkwrap.json`, `yarn.lock`, `pnpm-lock.yaml`, `bun.lock`, `bun.lockb`, `Cargo.lock`, `poetry.lock`, `Pipfile.lock`, `uv.lock`, `composer.lock`, `Gemfile.lock`, `go.sum`, `packages.lock.json`, `pubspec.lock`, `mix.lock`, `flake.lock`, `Podfile.lock`, `gradle.lockfile`.

## Generated files (`mechanical_kind: generated`)

- `git check-attr linguist-generated` is `set` or `true`.
- `@generated` appears in the first 5 lines of the new content.
- A directory segment of the path (any depth) is one of `dist`, `.next`, `coverage`, `__generated__`. Directories such as `build`, `out` or `generated` are not enough on their own (they often hold hand-written code); such files are generated only via the attribute or the header.
- The name ends in `.min.js`, `.min.css`, `.pb.go`, `_pb2.py`, `.g.dart` or `.freezed.dart`.

## Whitespace (`mechanical_kind: whitespace`)

The `-` and `+` lines of the hunk are equal line by line once all whitespace is removed (equivalent to `-w`); lines that are only whitespace are ignored. Joining or splitting lines is logic. A reindentation that also changes one character is logic.

In indentation-significant files (`.py`, `.pyi`, `.yml`, `.yaml`, `.mk`, `.coffee`, `.pug`, `.haml`, `.sass`, `.styl`, `Makefile`, `GNUmakefile`) a hunk where any line's leading indentation changed is logic. Spacing changes inside a line (`x=1` to `x = 1`) stay mechanical. Files whose only change is line endings (`eol_only`) are mechanical whitespace too (a CRLF change does not alter leading indentation, so this holds for `.py` as well); the `eol_only` flag stays on the file.

## Moves (`mechanical_kind: move`)

`status` is `renamed`, `similarity` is 100, the mode is unchanged and there are no hunks. A rename with any edit or a mode change is logic.

## Repeated replacements (`mechanical_kind: repeated_replacement`)

Runs after the rules above and looks only at hunks that are still logic. For each hunk with the same number of `-` and `+` lines, the lines are paired and every intraline change is widened to whole tokens (`[\w$]+`), giving `(old_token, new_token)` pairs. A hunk is **pure** for a pair `(o, n)` only if every line pair yields exactly that one pair and `old_line.replace(o, n) == new_line` holds exactly on every line. A change that cannot be widened to whole tokens, two different pairs in one hunk, or unequal `-`/`+` counts make the hunk not pure. Both tokens of a pair must be identifier-like (`[A-Za-z_$][\w$]*`, so pure numbers never qualify) and neither may be a literal or keyword: `true`, `false`, `True`, `False`, `TRUE`, `FALSE`, `null`, `None`, `nil`, `undefined`, `NaN`. Segments of one line that fall in the same token are merged before comparing. A pair qualifies when its pure hunks cover at least 3 distinct files; its pure hunks become mechanical and a file whose hunks are all mechanical becomes mechanical (mixed kinds read as `whitespace`).

The **exceptions** of a pair are the hunks that are not pure but, in any file, contain `o` in a `-` line and `n` in a `+` line. They stay logic. Hunks already marked mechanical (by this or another pair) are never listed. `facts` lists every qualifying pair under `replacements` (`old`, `new`, `hunk_ids`, `files`, `exceptions`), sorted by pair, file and id.

## Everything else

Logic.
