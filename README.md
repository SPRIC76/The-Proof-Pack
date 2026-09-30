# The Proof Pack

Four agent skills: Verafox, LevJev, Testcatch and measure-in-the-browser. They share one aim: an agent **verifies its own work before it says "done"**, and its evidence
can be re-read by someone else. Each is a folder with a `SKILL.md` and, where it needs one, standard-library Python
scripts, so any agent host that reads skill folders can load them; the install sections below are examples.

| Skill | Core question | Carries |
|-------|---------------|---------|
| **Verafox** | Did I drive it the way a user does, and read the result back? | A feature map of every capability, from the user's side and the developer's; four evidence grades (DRIVEN, TESTED, ASSERTED, UNKNOWN); a proof store; branch, commit and production comparison (`featuremap.py`, 235-case self-test); a dependency graph that names what a change can break and which tests to run (`depgraph.py`, 119-case self-test); Mutate, a read-only inventory of other people's skills, plugins and tools with their red flags, an overlap check against your own, and a ledger of what was absorbed (`mutate.py`, 128-case self-test) |
| **Testcatch** | Would this test go red if the thing it guards broke? | Re-injection probes: put the defect back on purpose and watch the check fail; the mutation check before a test file is finished; `floor_guard.py`, which lists every place a change lowered the test floor (a new skip, a lost assertion, a loosened threshold, a CI step gone) with a ratchet ledger, 88-case self-test |
| **measure-in-the-browser** | Did I measure the rendered page, or guess from the stylesheet? | Layout, colour, contrast and typography read from the live page, and a page's first load played frame by frame |
| **LevJev** | Is this a narrow judgment a typed model can make, and where in this codebase does the answer live? | `jev.py`, a pinned client for TypeSafe's Jev model, with its rules enforced in code and a 14-case self-test; `search.py`, repository search built on it, with a 30-case self-test |

Each skill works alone. Together, Verafox names what to check, measure-in-the-browser and Testcatch keep that check
honest, and LevJev adds a typed second reading where a judgment is narrow enough to ask.

## Install via skills.sh CLI

```bash
npx skills add SPRIC76/The-Proof-Pack
```

## Install (Claude Code)

Copy the folders under `skills/` into `~/.claude/skills/` (all projects) or `.claude/skills/` (one project). Keep
`verafox/` and `levjev/` side by side: Verafox finds the LevJev client beside it.

## Install (Cursor)

Copy the folders under `skills/` into `~/.cursor/skills/` (all projects) or `.cursor/skills/` (one project).

## Install (claude.ai and Claude Desktop)

Package each folder as `<name>.skill`, a zip archive with `<name>/SKILL.md` at its root, and upload it in your skill
settings. [Skillshaper](https://github.com/SPRIC76/Skillshaper) validates and packages in one step.

## Install (another host)

Any host that reads a folder of `SKILL.md` skills takes the folders under `skills/` as they are. The scripts need
only Python and, for the comparisons, git.

## Requirements

- **Python 3.10+** for the scripts under `verafox/scripts/`, `levjev/scripts/` and `testcatch/scripts/`. Standard
  library only.
- **git** for Verafox's comparisons and its staleness check, for the dependency graph inside a repository, and for
  the floor guard.
- **Optional:** a TypeSafe API key in `TYPESAFE_API_KEY`, or in `~/.agents/.env`, for Jev readings. Without it,
  everything else runs, and the Jev steps say what they did not judge. The key is never printed or written anywhere.

## Check it yourself

```bash
python -B skills/verafox/scripts/selftest.py
python -B skills/verafox/scripts/depgraph_selftest.py
python -B skills/verafox/scripts/mutate_selftest.py
python -B skills/levjev/scripts/selftest.py
python -B skills/levjev/scripts/search_selftest.py
python -B skills/testcatch/scripts/floor_guard_selftest.py
```

The self-tests build throwaway projects, repositories and fake services in a temporary folder with a home of their
own. They never read a real key or touch the network.

## How this pack is made

The skills are used daily in private projects. This repository holds a copy made by a build that removes private
project names and paths, then fails if any are left. It runs every self-test on the copy, writes `LICENSE`, checks
that the self-test counts above are the ones that just ran, and has Jev read every sentence of prose.

## License

Freeware — see [LICENSE](LICENSE). Copyright (c) 2026 MK1 Enterprise. Free to download and use; please link to this
repository rather than rehosting it.

---

The Proof Pack · [Freeware](LICENSE)

[MK1 Made](https://mk1made.us) • *deliberately designed, intelligently refined*
<p align="right">Artificer Intelligence</p>
