# Verafox changes

What changed for someone upgrading, newest first. Each version says what an upgrade
can turn red in a project with no change to its code, under **Upgrade effect**.
Run `python scripts/featuremap.py --check` after installing, and read what it names
before you raise a ceiling.

## 1.4.9 (2026-09-30)

- **Dev hosts behind one dot are hosts again.** In a `code:` or `entry:` field,
  `myapp.test:8080`, `printer.local:631`, `api.localhost:3000`, `web.dev:443` and
  `shop.app:8443` are read as a host and port, not as a missing file. The rule, in
  order: a path that exists under the project is a file; otherwise a name is a host
  when its labels are lower-case, its number is a port of two to five digits, and
  its last label is, behind one dot, a TLD, a special-use name (`test`, `local`,
  `localhost`, `internal`, `example`, `invalid`) or `dev` or `app`, and behind two
  dots or more, any of those or a TLD that is also a word (`run`, `page`, ...);
  anything else with an extension is a file. `Dockerfile.test:3`, `.env.local:2`,
  `deploy.run:4`, `index.page:9` and `notes.dev:9` are still named when missing.
  **Upgrade effect:** a missing name shaped like `notes.dev:12` or
  `fixtures.test:20`, which 1.4.7 and 1.4.8 named as missing, is now read as a
  host and no longer named.
- **A big keyboard handler lists in linear time.** Each handler is read once, not
  once per shortcut: `--list` over one handler holding 2,400 enclosed shortcuts
  takes about half a second, where 1.4.7 and 1.4.8 took 40 s or more. The derived
  ids are unchanged.
- **Installed alone, it says what it lacks.** Without the optional Jev client
  beside it, `--record` stores the proof and `--judge` exits 2, each printing
  `NOT JUDGED the optional Jev client (not included) is not installed beside
  this one (no <path>)` and that everything else runs. **Upgrade effect:** a
  script matching the old line should match `NOT JUDGED` instead.
- **This pack no longer includes a Jev client.** `--judge` and the reading at
  `--record` look for one at `jev-client/scripts/jev.py` beside this skill, and the
  self-test runs cases 28 and 53 only when one is there. **Upgrade effect:** a
  copy that judged through the client this pack used to carry now says NOT
  JUDGED until a client is installed there.
- **American spelling throughout**, in prose, help, messages and comments.
  `mutate.py ledger --license` is the documented flag and `--licence` still
  works. The inventory JSON keys `licence` and `licences`, and the `licence`
  field of saved ledger rows, keep their names, so saved ledgers and their
  readers keep working. **Upgrade effect:** in a map of this skill's own scripts,
  the derived `cli.licence` is now `cli.license`.
- SKILL.md names neighbors by their job, not by a skill's name, and frames itself
  for no one host.

## 1.4.8 (2026-09-30)

- **A rewritten pointer line is found, or named.** A one-line pointer whose own
  line was rewritten inside a change (not moved) was carried to the change's first
  line, or left on a number that now held other code, and said to keep its proof.
  `--reaim` now finds it by its unchanged text, else by what the code derives for
  the entry (its flag, key or route), and marks the move REWRITTEN: the move
  carries no proof, and it says whether the proof came before the rewrite. Found
  by neither, it is named `rewritten: re-aim by hand`.
  **Upgrade effect:** `--check` fails on such a pointer until it is set, where 1.4.7
  passed; run `--reaim`, then re-drive each proof it says predates the rewrite.
- Declined ranges read their ends in a project that is a subfolder of its
  repository.

## 1.4.7 (2026-09-30)

- **Shortcut modifiers kept.** A braced guard `if (!(e.ctrlKey || e.metaKey)) {
  return; }`, a local holding the either-test used in a guard (`if (!mod)
  return;`), and a shortcut nested in an either-block give `mod` again
  (`key.mod-k`), as 1.4.5 did; a braced single-modifier guard counts too.
  **Upgrade effect from 1.4.6:** those ids change back from `key.k` to
  `key.mod-k`, and an authored `key.k` entry fails `--check` as no longer derived.
- **A missing file with a host-like extension is named.** 1.4.6 hid
  `Dockerfile.test:3`, `.env.local:2`, `deploy.run:4` and `index.page:9` as hosts;
  1.4.7 names them. (Its one-dot rule also named dev hosts; 1.4.9 corrects that.)
- Every `featuremap.py` flag has `--help` text; `reference/proof-capture.md` shows
  a whole `--record` call and `reference/feature-map-schema.md` a whole `--live`
  call.

## 1.4.6 (2026-09-30)

- **Argparse subcommands are derived.** `add_parser("name")` on a subparsers
  object, or on a Parser subclass, is `cmd.<file>-<name>` on the dev face, at the
  line that adds it. **Upgrade effect: a project with argparse subcommands gains
  unmapped `cmd.` capabilities, and a ratcheted `unmapped_ceiling` then fails
  `--check` with no code change.** Map them, or raise the ceiling once, with a
  reason.
- A host with a port in an `entry:` field (`app.example.com:8443`,
  `localhost:3000`, `127.0.0.1:8080`, `[::1]:5173`, a URL) is not a pointer.
- A modifier in an earlier sibling condition no longer leaks into the next
  shortcut: `e.altKey && e.key === 'h'` after a Ctrl/Cmd+K condition is
  `key.alt-h`, not `key.mod-alt-h`. **Upgrade effect:** such ids change, and an
  authored entry under the old id fails `--check`.
- `--reaim`, `--write` and `--ratchet` keep a CRLF map CRLF.
- `--init` stamps `Created` with the local time and its UTC offset.
- A range `--reaim` declines says which of its ends is uncertain.
- `mutate.py` is quieter on five false positives: `.gitattributes` named without
  a write verb, a determiner on the line above "commit this", a test's staleness
  wording, "upload it in your skill settings", and a README's own
  skills-installer command under its install heading. **Upgrade effect:** fewer red flags,
  and a higher count of defensive mentions set apart.

## 1.4.5 (2026-09-30)

- **Every pointer is read.** Every `path:N` or `path:N-M` in a `code:` or
  `entry:` field is read on its own, alone or in prose, and each `code:` pointer
  is its own stale region. A pointer-shaped name that names no file fails
  `--check` by name. **Upgrade effect:** a map with pointers in prose, in an
  `entry:` field, or a second pointer in one `code:` field can fail `--check`
  where 1.4.4 passed.
- `--reaim` stamps each range it moves `path:N-M @ <commit>` while the file is
  clean at HEAD, and the stamp is read before git blame; it names each range it
  declines, where it is now, and why.
- A pointer neither committed nor stamped is read in today's lines, and the PASS
  says so by name when its file has changed since the map's last commit.
