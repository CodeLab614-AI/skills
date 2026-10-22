# Mechanical classification

`facts` marks every hunk and file as `mechanical` or `logic`. The rules are deterministic. **When in doubt, it is logic.** A file is mechanical only if all of its hunks are. A file with no hunks is mechanical only in the explicit cases below (lockfile, generated, pure move). Binary and `too_large` files that match no lockfile or generated rule stay logic.

## Lockfiles (`mechanical_kind: lockfile`), matched by file name

`package-lock.json`, `npm-shrinkwrap.json`, `yarn.lock`, `pnpm-lock.yaml`, `bun.lock`, `bun.lockb`, `Cargo.lock`, `poetry.lock`, `Pipfile.lock`, `uv.lock`, `composer.lock`, `Gemfile.lock`, `go.sum`, `packages.lock.json`, `pubspec.lock`, `mix.lock`, `flake.lock`, `Podfile.lock`, `gradle.lockfile`.

## Generated files (`mechanical_kind: generated`)

- `git check-attr linguist-generated` is `set` or `true`.
- `@generated` appears in the first 5 lines of the new content.
- A path segment is one of `dist`, `build`, `out`, `.next`, `coverage`, `__generated__`, `generated`.
- The name ends in `.min.js`, `.min.css`, `.pb.go`, `_pb2.py`, `.g.dart` or `.freezed.dart`.

## Whitespace (`mechanical_kind: whitespace`)

The `-` and `+` lines of the hunk are equal once all whitespace is removed (equivalent to `-w`). A reindentation that also changes one character is logic.

## Moves (`mechanical_kind: move`)

`status` is `renamed`, `similarity` is 100 and there are no hunks. A rename with any edit is logic.

## Everything else

Logic.
