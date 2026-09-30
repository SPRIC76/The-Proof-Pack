# Testcatch changes

What changed for someone upgrading, newest first, with what an upgrade can turn red
in a repository with no change to its tests under **Upgrade effect**.

## 1.2.4 (2026-09-30)

- American spelling throughout. `floor_guard.py`'s command line, exit codes and
  printed lines are unchanged; an internal function is now `analyze()`.
- SKILL.md names neighbors by their job, not by a skill's name, frames itself for
  no one host, and says `floor_guard.py` depends on no other skill; its self-test
  holds that.

## 1.2.3 (2026-09-30)

- **A ceiling that is not a whole number** (`"2"`, `true`, `-1`, `1.5`) is a bad
  ledger: exit 2, naming it, as the docs promise for any key of the wrong type.
  **Upgrade effect:** such a ledger exited 1 before; it now exits 2 until the
  ceiling is a whole number.
- The ledger's `about` key is described: free text for the reader, never read by
  the guard.

## 1.2.2 (2026-09-30)

- **A ledger key the guard does not take** (`{"drops": [...]}`), or a known key of
  the wrong type (`ignore` as a string, `verdicts` as a list), exits 2 naming it.
  **Upgrade effect:** a ledger with a misspelled key read as empty before, so the
  drop it meant to grandfather failed as new; it now stops with exit 2 and names
  the key.

## 1.2.1 (2026-09-30)

- Renamed from `rules-that-can-fail` to `testcatch`. **Upgrade effect:** a path or
  a hook that names the old folder must name the new one.
