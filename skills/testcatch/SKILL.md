---
name: testcatch
description: Testcatch (formerly rules-that-can-fail) - how to write a test, guard or checker rule that will actually go red when the thing it protects is broken, prove it with a re-injection probe, and hold the test floor with floor_guard.py. Use when adding or reviewing any test, lint rule, assertion, safety check or regression case; before writing a test body, to name the break it catches; when an expected value is built by the code under test; when a test passes on the first run with no drama; when a fix turns an existing test red; when a design ruling is reversed; when a check has started failing every time; and before calling a change safe or reviewing any change that touches tests, test config or CI, a helper agent's included - a new skip, noqa or ts-ignore, a test or assertion gone, a tolerance or timeout loosened, a CI step dropped. Not for proving a change works end to end (verafox). Derived 2026-09-15 from the rule files of a real project, where each pattern below let a defect ship under a green run.
metadata:
  version: 1.2.1
  renamed_from: rules-that-can-fail (2026-09-30)
  source: derived from the review record of a real project (2026-09)
  credits: "floor-guard contract (diff scoped, exit 0/1/2, 2 never clean) from addyosmani/agent-skills skills/constraint-driven-development/references/floor-guard.md @ 2686b620fc1fed2e8f60c704839c766b8594c6b6 (MIT); name the break, no mirror assertions and the mutation check from obra/superpowers skills/test-driven-development/writing-good-tests.md @ 8ca22dba9a94f28898bbce59f2537ff4d87c747d (MIT). Rewritten in its author's words and built as original code; no text or code copied."
  owner: SPRIC76
---

# Testcatch — rules that can fail

A rule exists to fail before a defect ships. One that cannot fail is worse than no
rule, because it reads as coverage. Every pattern below produced a green run over
a real defect.

## Before the body: name the break

Before the first assert, write down the change to the shipped code that should turn
this test red, and whether that change is a bug or a decision.

- **You cannot name one:** the test measures nothing yet. Point it at something the
  code moves (an output, a side effect, a file, an exit code).
- **Only a decision can break it** (a constant's value, the exact wording, the file
  layout): it is a change detector. It goes red on every redesign and sleeps through
  every bug. Test what the decision drives: not `HOLD_SECONDS == 2` but "a two-second
  hold fires Off and a 1.9-second hold does not".
- **Put the break in the test's name or docstring,** so the probe knows what to
  inject, and whoever deletes the test knows what went unprotected.
  `scripts/floor_guard_selftest.py` names the break on every case.

## Ways a green rule is not measuring anything

| Pattern | What happened | Write it instead |
|---|---|---|
| **Answered by a corpse** | `assertIn(literal, source)` passed after the feature was disabled — the string still sat in the dead branch. A DOTALL regex with no entry boundary was answered by a neighbouring entry. | Pin the expression that *decides*, anchored to its label, bounded to its entry. |
| **Passes on a dead declaration** | `assertIn('text-align: center;', block)` passed with a later `text-align: left;` in the same block. Order is the whole of CSS. | Parse the block, collect every declaration of the property, require exactly one, compare its value. |
| **Pinned literal is the copy the rule forbids** | The rule asserted the shipped tile equals `tile(0.12, 0.12)`; when the generator's inputs changed, the rule was the stale copy. | Call the generator's own constants; never restate its inputs. |
| **Derives its own threshold** | `spread * (LEVELS / spread) < LEVELS` — true of every wall ever built. | The rule and the code it grades must not share a source. Read the shipped value; compare to what the derivation says it should be. |
| **Mirror assertion** | `want = face_line("KiT", TAGLINE)` then `assert face_line("KiT", TAGLINE) == want`. The code under test wrote both sides: a lost dash, an empty return and a swapped order all stayed green (2026-09-29). The expected-value form of *Derives its own threshold*. | Write the answer by hand: `== "KiT — Keep it Ticking."`, or a fixture checked by eye. That pins what the code must produce. Checking that a shipped file is still what its generator makes is a different test, and there calling the generator is right (*Pinned literal*). |
| **Asserts against a field that never exists** | `assertIsNone(card.get('ma50'))` — the card never carried `ma50`. A node parse check read its own `argv[1]`. | Assert on the field the behaviour actually moves; make the negative case produce the value first. |
| **A token passes by not being seen** | A three-digit hex was invisible to a six-digit regex, so the "every colour has a light answer" audit never asked. | Make the scanner reject what it cannot parse, rather than skip it. |
| **A check that always fails** | A staleness check said STALE on every input because it carried its own second compiler. Nobody read it; it was silent about the one real staleness. | A warning that fires unconditionally carries no information — fix or delete it the day it starts. |
| **An error is not a red test** | A rename made two rules raise `AttributeError`; a type change made `'Q' in some_dict` ask about keys. Both stopped measuring. | Treat an ERROR in a rules file as a rule pointing at nothing, not a harness nit. Re-point it before moving on. |
| **A matching count in the wrong order** | Three colours for three bands, positions 2 and 3 swapped. | When zipping by position, check order, not only count. |
| **An asset rule that pins the asset** | Filename, width, height and caption date were literals; refreshing the capture reddened all three with nothing wrong. | Find the filename by regex in the page, derive the date from it, read width and height out of the PNG's own header. |

## Before the test file is finished: the mutation check

Break the shipped code in your head, one fault at a time. For each fault that could
really happen here, at least one test must go red:

- **A wrong value:** a constant, an argument, an off-by-one, the neighbouring entry.
- **The other branch:** the condition inverted, the fallback taken, the wrong handler.
- **A missing effect:** the write, the flag, the log line, the file that should appear.
- **An empty return:** `None`, `[]`, `0`, `""`, the default.
- **An input nobody guarded:** zero, empty, missing, malformed, not allowed.
- **The order swapped** (*A matching count in the wrong order*).

A fault nothing catches is behaviour nobody protects, or a test that cannot fail.
Write the missing test, or say in the change which fault is left unguarded and why.
The check picks the faults; the probe below proves the ones you doubt.

## Prove it with a re-injection probe

A rule is only known to work after a probe put the defect back and the rule went
red. Rules for the probe:

- **Inject the fault the guard exists to prevent**, not a no-op. Nulling a guard
  whose absence raises two lines later changes nothing and proves nothing. If the
  probe passes with no drama, check that the mutated path was reachable and the
  observable output moved.
- **Prove the probe landed.** A text replace whose target is not in the file
  changes nothing, and the rule stays green for no reason. Assert the target
  occurs exactly once before replacing and that the bytes differ after, then
  assert the red message itself, not only a non-zero exit (a static site,
  2026-09-28: a `make_logo.py --check` probe replaced a string the file did not
  hold, and only its own byte check caught it).
- **A rename probe must not leave the substring.** `fooZZ` still contains `foo`,
  so an `assertIn` stays green and the probe falsely accuses a good rule. Rename to
  something disjoint.
- **Report MISSED honestly.** A probe that stays green is the finding.

## Hold the floor: scripts/floor_guard.py

A change can lower the floor with every test still green: a new skip or `.only`, a
`noqa` or `@ts-ignore`, a test or an assertion gone, a tolerance, timeout or retry
count loosened, a CI step dropped or switched off, a test path excluded.
`floor_guard.py` reads the change against its base (staged, unstaged and untracked
alike) and lists each drop as file:line and kind.

Run it:

- **before you call a change safe, done or ready;**
- **whenever you review a change that touches tests, test config or CI, a helper
  agent's included.** Its "all tests pass" is a claim, and a skipped test passes.

`python -B scripts/floor_guard.py --repo <repo>` compares with the merge-base of the
upstream, else main, else master; `--base <ref>` picks another. Its own proof is
`python -B scripts/floor_guard_selftest.py`.

- **Exit 0:** the floor held. **Exit 1:** it dropped; each drop is listed with the
  ledger line that would grandfather it. **Exit 2:** it could not check (not a
  repository, no base, a git error, a bad ledger, a bad flag).
- **Exit 2 is never clean.** It is a question nobody answered, not a pass. Fix what
  stopped it and run it again; never report "no drops" off a 2. The last line is
  always `RESULT: PASS`, `FAIL` or `ERROR`; read that line, not the scrollback.
- **A drop that is the point of the change** goes in `.floor-guard.json` at the
  repository root, with a verdict and a why (`moved` and `replaced` also name
  `by`). An entry without a reason fails, an entry that matches no drop is stale
  and fails, the same entry twice fails, and the ceiling only comes down. The shape
  is a production-supersession ledger: a test that fails on any silent loss unless
  a fixture names the verdict and the reason. An entry written to turn
  the run green is the rule edited to pass: the reason has to be true.
- **A finding is a question, not a verdict.** KiT's first run (2026-09-29, five
  commits) named two: two README assertions folded into one share-card check, and
  a test rewritten after a ruling was reversed. Both want a ledger line (`replaced`,
  by the new check), not a revert.
- **Read its green for what it is.** It is regular expressions over lines: it
  catches the cheap road to green, not a determined hand. It reads numbers only in
  tests, test config and CI, because a product timeout raised is a product
  decision. Its own fixtures read as suppressions, so a repository that carries it
  lists `*floor_guard*.py` under the ledger's `ignore`. The full bounds are in its
  docstring.
- **It is read-only,** down to `.git/index`. Its first build's `git diff` rewrote
  the index whenever a file's timestamp had moved; git's auto-refresh is off now.

## When a rule goes red

- **Your fix turned it red: that is a design argument.** The rule is a claim someone
  made about the design with a reason attached. Win the argument on the merits or
  move the fix — never edit the rule to make it pass.
- **A reversal reddens the rules that held the old ruling.** When the operator
  changed their mind on purpose, keep both quotations in the docstring, keep the
  class name if it names the shape of the guarantee, and make sure the rewritten
  rule still checks something. "Make it green" and "make it still check" are
  different tasks.
- **A solved artifact must be regenerated, not patched.** When a downstream
  constant is a solver's answer for an upstream input (a ramp, a palette), the
  failing tests are reporting the truth; re-run the solver rather than raising
  thresholds to colours it never verified.

## Environment traps that silently corrupt a rule

- The shell heredoc eats backslashes: `r'\\b'` arrives as a backspace and a
  whole-word fence matches nothing, green. Write test files with a file-writing
  tool or build the character with `chr(92)`.
- Never count off a truncated listing; compute and print the number.
- Python trusts a `.pyc` whose recorded source mtime (whole seconds) and size
  still match, so a same-size edit made within the same second runs the old
  bytecode: an injection stays green and falsely accuses the rule, a restore
  stays red. `-B` stops writing bytecode, not reading it. Run each probe, and the
  check after the restore, under `python -X pycache_prefix=<fresh empty folder>`.
  (KiT 2026-09-25: a restored `MONITOR_POWER_OFF = 2` still read as 1.)
