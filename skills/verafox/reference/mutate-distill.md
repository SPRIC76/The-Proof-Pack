# Distill: keep only what beats what we have

The bar, from `mutate.md`: read-only inspect and inventory, then collate, distill,
mutate, calibrate and evolve; keep all of the functionality and capability intact,
but build it ourselves.

This stage follows collate and comes before mutate (`mutate.md` has all six). It
takes the inventory (stage 1) and the collate table (stage 2). It hands on a
**capability list**: one row for each thing the source can do, marked keep,
rebuild or leave out, with a reason on every row. That list becomes the parity
ledger in stage 4. If a capability has no row, it was lost without anyone
deciding to lose it.

## Three passes, in this order

1. **Does it beat what we have?** Set each capability beside the agent's native
   abilities (plan mode, `/code-review`, `/simplify`), the homed skills (collate's
   DUPLICATE and sibling rows) and the plugins in use. If one of those already
   does it and the source is not measurably better, the row says **leave out -
   duplicates X**.
2. **Is it safe?** A red flag from the inventory is never carried over. It becomes
   either a leave-out, or a rebuild without the flagged part, and the row names
   the flag by file and line. A defensive mention (a line warning against the
   thing) is not a flag. The inventory already counts those separately.
3. **Is it lean?** This is ponytail's pass. Run it twice: once on the source, so
   we do not rebuild its bloat, and once on our rebuild after stage 4.
   "Superseding" means ours does the same job in fewer lines, or names what
   every extra line buys.

## The lean pass

One line per finding: `<file>:L<line>: <tag> <what to cut>. <what replaces it>.`
On a diff, the lines go in line order. On a whole tree, rank them biggest cut
first. End with `net: -N lines, -M deps possible.`, or `Lean already. Ship.`
when there is nothing to cut.

| Tag | Cut | Replacement |
|---|---|---|
| `delete:` | dead code, flexibility nobody uses, a speculative feature | nothing |
| `stdlib:` | a hand-rolled thing the standard library ships | name the function |
| `native:` | a dependency or code doing what the platform or agent already does | name the feature |
| `yagni:` | an abstraction with one implementation, config nobody sets, a layer with one caller | inline it until a second exists |
| `shrink:` | the same logic in more lines than it needs | show the shorter form |
| `dup:` (ours) | the same capability or rule said twice, in one source or across the homed skills | one home, the other points at it |

**Hunt for:**
- dependencies the stdlib or platform already ships;
- interfaces with one implementation;
- factories with one product;
- wrappers that only delegate;
- files exporting one thing;
- dead flags and config;
- hand-rolled stdlib.

We add three more:
- a count copied into prose (it goes stale; `SKILL.md` for Verafox says so too);
- a fixture nothing asserts;
- a check whose name promises more than its assertion tests. The inherited
  self-test counted "≥ 5 injection flags" under a name that listed five labels,
  and one of those labels never fired.

**Measure it where you can, don't just eyeball it:**
- *Dead names:* read the syntax tree for top-level names that nothing uses.
- *Unused detectors:* a detector that fires on no real source and no fixture is
  untested weight.

`mutate_selftest.py` holds the second as a ratchet: every detector must fire at least
once in its fixture.

**Scope:** complexity only. Correctness goes to a normal review. Security goes to
the inventory's red flags, which this stage reads but never waives.

## Source

The lean pass takes its design from `DietrichGebert/ponytail` at `e3ba2aa6` (MIT,
Copyright (c) 2026 DietrichGebert), two skills of 57 and 41 lines: the five tags,
one line per finding naming its replacement, the net lines-and-deps metric, `Lean
already. Ship.`, both modes and the hunt list, rebuilt here in this pack's words.
Distill runs once per source and holds nothing across turns, so no always-on mode
came with it; and a test here stays only when it has been shown red (`testcatch`),
so a check that can never fail is `delete:` weight.

## Worked example: the pass on mutate.py itself

Measured 2026-09-30: a dead-name read of its syntax tree found 0 unused names out
of 108, and was proven able to fail (an injected unused `def` was flagged, exit 1);
all 37 detectors fire in the self-test fixture, which is now a ratchet - a detector
added with no fixture line turns it red.

- `scripts/mutate.py scan_text: dup: two detectors sharing one label on one line made two flags ("ACTIVE EVERY RESPONSE" counted twice). Now one flag with both matches; self-test case, shown red.`
- `scripts/mutate.py relate: yagni: two shared name parts alone made a sibling ("subagent-driven-development" ~ "source-driven-development", jaccard 0.01). Now they also need some shared content; self-test case, shown red.`
- `scripts/mutate.py parse_frontmatter: kept, not stdlib: the stdlib has no YAML, and a dependency for two keys would break "stdlib only".`
- `scripts/mutate.py --licence/--license: kept: one flag, two spellings, 0 extra lines.`
- `scripts/mutate.py: kept: the two injection detectors that fire only in the fixture ("just do it", "do not consult the user") are one regex each, and a missed injection costs the most.`

`net: -480 lines kept out of the install set (the one-off calibration tools stayed behind), -0 deps (already 0). The install set is mutate.py, mutate_selftest.py and this file.`
