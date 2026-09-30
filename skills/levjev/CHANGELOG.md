# LevJev changes

What changed for someone upgrading, newest first, with what an upgrade can change
for a caller under **Upgrade effect**.

## 1.0.6 (2026-09-30)

- American spelling throughout. `jev.py` and `search.py` behave as before.
- SKILL.md names neighbors by their job, not by a skill's name, frames itself for
  no one host, and says the client depends on no other skill; its self-test holds
  that.

## 1.0.5 (2026-09-30)

- `jev.py --help` says what `--ping`, `--model` and `--check-question` do, and the
  usage block names `--help`.

## 1.0.4 (2026-09-30)

- **The documented question shape is the one the client accepts:** a map of id to
  `{type, instructions, criteria}`, a choice's criteria an object of options and a
  score's a list of levels. The self-test runs every map SKILL.md shows through
  `--check-question`. The client's rules did not change: the older inline shape the
  docs showed was always refused.
- **A 401 or 403 says where the rejected key came from,** the environment or
  `~/.agents/.env` by its path, never the key. **Upgrade effect:** a caller
  matching the old message text should match `was rejected by the service`.
- `search.py --top` and `--excerpt-lines` are documented and tested.

## 1.0.3 (2026-09-30)

- The search plan names each file over the size cap with its size and the
  `--max-file-bytes` that reads it, without `--show-skipped`: a bare count had hidden
  a project's largest source files.
- A top that is mostly documentation says which `--exclude` searches the code
  alone.
