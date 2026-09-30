# The Proof Pack

Three agent skills: Verafox, Testcatch and measure-in-the-browser. They share one aim: an agent **verifies its own work before it says "done"**, and its evidence
can be re-read by someone else. Each is a folder with a `SKILL.md` and, where it needs one, standard-library Python
scripts, so any agent host that reads skill folders can load them; the install sections below are examples.

| Skill | Core question | Carries |
|-------|---------------|---------|
| **Verafox** | Did I drive it the way a user does, and read the result back? | A feature map of every capability, from the user's side and the developer's; four evidence grades (DRIVEN, TESTED, ASSERTED, UNKNOWN); a proof store; branch, commit and production comparison (`featuremap.py`, 255-case self-test); a dependency graph that names what a change can break and which tests to run (`depgraph.py`, 119-case self-test); Mutate, a read-only inventory of other people's skills, plugins and tools with their red flags, an overlap check against your own, and a ledger of what was absorbed (`mutate.py`, 137-case self-test) |
| **Testcatch** | Would this test go red if the thing it guards broke? | Re-injection probes: put the defect back on purpose and watch the check fail; the mutation check before a test file is finished; `floor_guard.py`, which lists every place a change lowered the test floor (a new skip, a lost assertion, a loosened threshold, a CI step gone) with a ratchet ledger, 99-case self-test |
| **measure-in-the-browser** | Did I measure the rendered page, or guess from the stylesheet? | Layout, color, contrast and typography read from the live page, and a page's first load played frame by frame |

Each skill works alone. Together, Verafox names what to check, and measure-in-the-browser and Testcatch keep that
check honest.

## Install via skills.sh CLI

```bash
npx skills add SPRIC76/The-Proof-Pack
```

## Install (Claude Code)

Copy the folders under `skills/` into `~/.claude/skills/` (all projects) or `.claude/skills/` (one project).

## Install (Cursor)

Copy the folders under `skills/` into `~/.cursor/skills/` (all projects) or `.cursor/skills/` (one project).

## Install (claude.ai and Claude Desktop)

Package each folder as `<name>.skill`, a zip archive with `<name>/SKILL.md` at its root, and upload it in your skill
settings. [Skillshaper](https://github.com/SPRIC76/Skillshaper) validates and packages in one step.

## Install (another host)

Any host that reads a folder of `SKILL.md` skills takes the folders under `skills/` as they are. The scripts need
only Python and, for the comparisons, git.

## Requirements

- **Python 3.10+** for the scripts under `verafox/scripts/` and `testcatch/scripts/`. Standard library only.
- **git** for Verafox's comparisons and its staleness check, for the dependency graph inside a repository, and for
  the floor guard.
- **Optional, not included:** a Jev client, which Verafox's `--judge` and its reading at `--record` use as a
  decision layer: for each entry, a typed probability that its observable would show its intent. Install one beside
  `verafox/` as `jev-client/scripts/jev.py`, with the key it reads. Without it, everything else runs, and those two
  say by name that they did not judge.

## Check it yourself

```bash
python -B skills/verafox/scripts/selftest.py
python -B skills/verafox/scripts/depgraph_selftest.py
python -B skills/verafox/scripts/mutate_selftest.py
python -B skills/testcatch/scripts/floor_guard_selftest.py
```

The self-tests build throwaway projects, repositories and fake services in a temporary folder with a home of their
own. They never read a real key or touch the network. Without a Jev client beside `verafox/`, Verafox's self-test
names the two cases that need one as not run.

## How this pack is made

The skills are used daily in private projects. This repository holds a copy made by a build that rewrites the
private project names, paths, commits and work labels it lists, then fails if any on its list are left. It runs
every self-test on the copy, writes `LICENSE`, checks that the self-test counts above are the ones that just ran,
and asks Jev, as an optional decision layer, three narrow yes-or-no questions of every sentence of prose: flags for
a person to read, never a gate.

Run Mutate over this pack (`mutate.py inventory skills`) and it reads RED, exit 1, by design: the flags are what
these tools do - Verafox's `--live` sends GET requests to production, and `--judge` names the key an optional Jev
client reads - plus this README's install paths and the patterns Mutate and the floor guard look for, which it
cannot tell from the things they detect. Defensive mentions and the self-tests' fixtures are counted apart, the
fixtures by their own `mutate: fixture` line; read every flag it prints.

## License

Freeware — see [LICENSE](LICENSE). Copyright (c) 2026 MK1 Enterprise. Free to download and use; please link to this
repository rather than rehosting it.

---

The Proof Pack · [Freeware](LICENSE)

[MK1 Made](https://mk1made.us) • *deliberately designed, intelligently refined*
<p align="right">Artificer Intelligence</p>
