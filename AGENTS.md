# Instructions for coding agents

Disassembly of TMNT: Tournament Fighters (NES, U) for ca65. Read [README.md](README.md) first: layout, label-file
syntax, banking, checks.

## Language

- Docs, comments, label files and commit messages: English.
- `README.uk.md` is the Ukrainian translation of `README.md`. Change both in the same step; keep the sections,
  tables and numbers the same.
- Answer the user in the language they write in (usually Ukrainian).

## The loop

1. Change only `tools/labels/rom.txt`, `ram.txt`, `const.txt` (or the tools). **Never edit `src/`, `config.cfg`,
   `assemble.bat`, `compare.bat`**: `tools/disasm.py` owns them and overwrites them. `tools/labels/banks.txt` is
   written by `tools/mesen/merge_runs.py`; do not edit it by hand.
2. `python tools/disasm.py --build` must print `build: IDENTICAL`.
3. Then all of: `python tools/lint_labels.py` (0 problems), `python tools/reloc_test.py` (0 unexpected, 0 wrong,
   0 unresolved), `python tools/selftest.py` (OK), `python tools/docs_fresh.py` (reports up to date). Run them, do not assume; report the result.
4. After renames, regenerate `docs/xref.txt` with `python tools/xref.py` (it writes the file itself; do not redirect
   its output into the same file). After changes that classify bytes (`data`, `code`, new formats) also run
   `python tools/unknown_report.py` (`docs/unknown.txt`); `make docs` runs both.

## Naming rules

- Names by responsibility, not by address. RAM: lowerCamelCase; routines and ROM data: UpperCamelCase; constants:
  UPPER_CASE with a group prefix (`FST_`, `CHAR_`, `ATK_`, `SND_`, `MODE_` …).
- A guess gets `(?)` in its comment until it is verified (code read end to end, Mesen log values, or an emulator
  test). When evidence disagrees, rename; do not keep a wrong name.
- No magic numbers where a name helps: `@var` bindings, `use`, `data` in const.txt. The generator checks every
  expression against the real byte. Plain 0 / 1 / `$FF` idioms may stay numbers.
- Every new data format: decode it in the generator (a directive + constants), check it by re-assembly, document it
  once in `docs/` and link it from the README.
- Auto-detected word tables can be false (frame-number bytes in $9B-$E0 look like addresses). If a new label
  appears in the middle of an instruction or in a data table, find the false table and force it with `data`.

## Emulator (Mesen 2)

- `mesen/` in the project is a private copy made for these tools: `tools/mesen/run_mesen.py` runs it in place and patches its
  `settings.json` (Lua IO, zeroed RAM). Never point it at the user's own installed Mesen. Run one emulator instance at a
  time, headless. Do not download an emulator without asking.
- Output goes under `tmp/` (not in git).
- Useful Lua holds for tests (`--cfg`): `$0590`/`$0591` fighter HP, `$05F0` objHitDelay (blocks hits), `$0440`/
  `$0441` fighter X, `$0550` character. Mesen access counters are 0-based and include dummy reads.

## Environment notes (Windows)

- The project path contains `!` and spaces: always quote it.
- Run Python tools with `PYTHONIOENCODING=utf-8` when they print non-ASCII.
- In bash heredocs `\n` and other backslashes can be eaten; write Python with escapes to a file or edit with the
  editor tool instead.
- Run `.bat` files from PowerShell as `& .\compare.bat`.

## Git and sources

- Do not commit unless the user asks. ROMs, `gfx/`, `src/chr/`, `tmp/`, `mesen/` and build output are ignored.
- External hints (RAM maps, cheat codes) are hints only: verify them. Do not use TCRF as a source.
- Keep the user's personal data out of files and out of requests to outside services.
