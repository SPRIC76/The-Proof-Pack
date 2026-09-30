# Jev in Verafox — the one question, and when its number may gate

Verafox asks Jev (TypeSafe's System One model, pinned to `jev-1.13.0`) one kind of
question: **would reading back this entry's `observable` show whether its `intent`
was met?** That is the Intended bar. No test suite checks it, because the suite was
written from the same reading as the code. Everything else is code's job.

## The one path

Every Jev call goes through one Jev client, not included in this pack: `jev.py`,
installed beside this skill as `jev-client/scripts/jev.py` in the same skills folder.
The pin, the lint, the key and the retries are that client's rules, defended by its
own tests. Here
is only what `--judge` itself adds, each defended by Verafox's selftest case 28:

| What `--judge` does | The test that fails if it breaks |
|---|---|
| Narrow questions, ONE request: every entry goes in one call | "every entry is asked in ONE request, to the pinned model" |
| Inline the text: each question carries its own `intent` and `observable` as named fields | "each question carries its own entry's text inline" |
| Jev decides, code computes: the two thresholds below live in `featuremap.py`; Jev only returns a probability | the low / torn / high cases |
| An entry carrying a literal Jev cannot read is listed as not judged, by name | "an entry carrying a literal Jev cannot read is not asked" |
| No key, or no Jev client, means nothing is asked and it says so; with a client beside it, it asks | "with no key nothing is asked", "without a Jev client beside it, --judge asks nothing", "with a Jev client beside it, --judge asks through it" |

## The gate: not yet

| Reading | Threshold | What it means today |
|---|---|---|
| below 0.30 | `JUDGE_LOW` | listed as possibly not showing the intent |
| 0.30 to 0.70 | — | torn. Read the two fields yourself |
| 0.70 or more | `JUDGE_HIGH` | listed as showing the intent |

Both numbers are placeholders. The order is to validate thresholds on the operator's own
data and never inherit a vendor's number. Until the table below is filled, `--judge`
exits 0 whatever it reads, so it gives a reading to look at and never a gate. A Noul
of 0.5 means torn, not "medium confidence".

## Calibrating on the operator's own data

1. Collect every authored entry, across the registered maps, that carries both
   `intent:` and `observable:`.
2. Label each by hand before Jev sees it: would reading back that observable show
   whether that intent was met? The label is the truth. Either the operator makes it, or an
   agent shows them each pair and records their answer.
3. Run `featuremap.py --judge --project <dir>` on each map and record every reading
   beside its label. Since 1.3.6 every passing DRIVEN or TESTED `--record` also
   keeps a reading in its capture (`.verify/proof/<id>/*.json`, field `judged`), so
   readings build up with ordinary work. Collect them too, each against the
   observable it was taken on. One reading is one sample: identical requests moved
   73 of 316 readings by up to 0.08 (a static site, 2026-09-29). Ask an entry within
   0.08 of a candidate threshold at least three times, and set the thresholds on
   the spread, not on one number.
4. Set `JUDGE_LOW` so that no entry labeled "shows it" falls below it, and
   `JUDGE_HIGH` so that no entry labeled "does not" rises above it. Readings
   between the two are torn by definition. When the labels overlap, favor the
   costlier mistake: calling a hollow observable fine lets a hollow verification
   stand.
5. Record the table, the date, the pin and the counts here. Then change the two
   numbers in `featuremap.py`, with a selftest case, as one variable.
6. Only after that may a caller gate on the reading, and only at the level the cost
   of a wrong gate warrants.

## Status

| Item | State |
|---|---|
| Client, pin, lint, one-request batching, retries, key handling | **TESTED** 2026-09-23 against a fake service on this machine: selftest 28, with each rule broken on purpose and seen to turn it red. Since 2026-09-24 the client's rules are tested with the client itself, re-proved there the same way; `--judge` keeps case 28 for what it adds, run when a client is installed beside this skill |
| A real request to TypeSafe | **Verified 2026-09-23.** A `--ping` answered in 1228 ms, 275 input tokens, noul 0.99, from jev-1.13.0. A client that looks for its key in only one place can report a key missing that is set elsewhere, so it reads both the environment and its key file |
| Thresholds | **Unvalidated** placeholders until the procedure above runs |
| A reading at every recorded proof | **TESTED** 2026-09-29, selftest 53 against the fake service; **driven** the same day against TypeSafe on Verafox's own `cli.reaim`: 0.43, torn, jev-1.13.0, kept in the capture. Its intent was written as a history ("three ranges named other code...") rather than as an outcome, and a history is hard to hold an observable against. Intents written as outcomes are worth checking first when calibrating |
| Question ids containing dots (`endpoint.orders`) | **Verified** 2026-09-23: both real `--judge` requests used them and were answered |
| Vendor docs versus the measured rule | The vendor's docs, and its `typesafe-ai` skill, teach `ticket.messages[0].text`. The first measured run failed on exactly that form, so the rule forbids it and this client refuses it |

## First real readings — withheld from whoever labels

Do not show these to the labeler before the labels are written; a label made
after seeing Jev's number calibrates Jev against itself. They are a first look at
the pipeline, not calibration data: step 3 above re-runs `--judge` on the text as it
stands when labeling happens.

2026-09-23 20:02 ET, jev-1.13.0, one request per map. Verafox's own map: 10 entries,
1167 ms, 1785 input tokens. A web app: 9 entries, 1037 ms, 1602 input
tokens. Printed to two places.

| Map | Entry | Noul |
|---|---|---|
| verafox | `cli.judge` | 0.20 |
| verafox | `cli.check-question` | 0.36 |
| verafox | `cli.compare` | 0.38 |
| verafox | `cli.list` | 0.38 |
| verafox | `cli.write` | 0.38 |
| verafox | `cli.ping` | 0.47 |
| verafox | `cli.record` | 0.51 |
| verafox | `cli.check` | 0.55 |
| verafox | `cli.live` | 0.56 |
| verafox | `cli.init` | 0.57 |
| a web app | nine entries, named privately | 0.22 to 0.55 |

Nothing read 0.70 or more. One reading that is worth a sentence already:
`cli.judge` reads low because its intent is "utilizing Jev consistently,
correctly, and reliably", and printing a line of readings does not show that - true
of the entry as written, and exactly the gap between Specified and Intended this
command exists to surface.

## Later readings, kept at `--record`

| When (UTC) | Map | Entry | Commit | Noul | The observable Jev read |
|---|---|---|---|---|---|
| 2026-09-29 12:52:07 | a static site | `dev.jev-read` | one commit | 0.20 | the steps taken: "the self-test (offline) went red first ... the probe passed, 11 x 4" |
| 2026-09-29 12:52:40 | a static site | `dev.jev-read` | the same | 0.63 | the outcome the intent asks for: "Jev is asked on every site check with nobody remembering to: 2 requests and 392 readings ... per check" |

Both are kept in that repository's proof store (`.verify/proof/dev.jev-read/`). The
intent was the operator's own words in both: that Jev be used far more often. The model, the question and the commit were the same, 33 seconds apart,
so the 0.43 rise is the observable's wording, not drift (one reading's spread is
0.08). An observable written as the outcome the intent asks for read higher than
one written as the steps taken, which matches the `cli.reaim` note above. Label
pairs like this first when calibrating.

Verafox's own `cli.judge` was said to read 0.27 on 2026-09-29, but no capture holds
it (its map records nothing at `--record`), so it is not a reading here; retake it
with `--record` before it counts.
