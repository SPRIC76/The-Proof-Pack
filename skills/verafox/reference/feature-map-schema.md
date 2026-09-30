# The feature map schema

A feature map answers one question per field, and every field exists because
omitting it has let a verification pass over a broken feature. Documentation
describes; this map is **drivable** — an agent must be able to operate the feature
from the map alone, without reading the source first.

## The two halves, never mixed

| Half | Who writes it | `--write` behaviour |
|---|---|---|
| **DERIVED** | `featuremap.py`, from routes, handlers, JSX, CLI definitions, the rendered DOM | overwritten on every `--write` |
| **AUTHORED** | a human or an agent exercising judgment | **never** touched by any script, beyond `--reaim` moving a `code:` or `entry:` pointer's numbers to where git measures its unchanged lines now, stamped ` @ <commit>` with the commit those lines are in, and `--ratchet` lowering a ceiling. `--write`, `--reaim` and `--ratchet` keep the map's line endings as they read them: a map committed with CRLF stays CRLF, and each edit is a diff of the lines it changed (1.4.6) |

They are separated by explicit markers in the file so the generator can never eat
the judgment. A map that mixes them loses the authored half the first time someone
regenerates it, which is the one failure that makes people stop keeping maps.

## Fields

### Identity — DERIVED

| Field | Answers | Why it exists |
|---|---|---|
| `id` | stable slug, e.g. `checkout.submit` | proof records and drift reports reference features across renames |
| `name` | what a user would call it | the operator asks "does it have X" in their words, not the function's name |
| `surface` | `web-ui` · `setting` · `cli` · `api` · `job` · `data` · `auth` | the verification method differs per surface; picking the wrong one is how a setting gets "verified" by watching it save |
| `code` | `path:line` of the thing that decides, or `path:first-last` for its span | so the next agent changes the right place, and so staleness is measured on that region alone: a change within 30 lines of a single line, or inside a declared span, stales the proof; a change elsewhere in the same file does not. The numbers are read in the lines of the commit that last wrote that map line (git blame), and `--check` fails when code added or removed above them has moved those lines; `--reaim` moves them. A change is held against the side of the diff those numbers are in: today's lines when the file has not changed since that map line was written (a range `--reaim` just moved, for one), otherwise the range carried into the proof commit's lines. Only where git cannot blame the map are both sides tried, and then a range can meet the other side's code by number. A range with a change inside it is moved only when its DRIVEN or TESTED proof names a later commit, which covers that change: it is carried through the proof's lines to today's. A move is reported only when it changes the pointer's text: a one-line pointer carried to a region that starts on its own line stays as written (1.4.3, KiT's line-1 loop). A field may hold several pointers, alone or in prose (`A:99-103; its mark B:403-436`), and each is read on its own - moved, checked and staled by its own file. A pointer may carry ` @ <commit>`, the commit whose lines its numbers are in: `--reaim` writes it on each range it moves while the file is clean at HEAD, and it is read before blame, so a re-aimed map left uncommitted is still read in its own commit's lines; a hand edit of the numbers drops the stamp or sets it to the commit the new numbers are in. A pointer neither committed nor stamped is read in today's lines, and the PASS says so by name when its file has changed since the map's last commit. A range that moved with a change inside it that no proof covers stays where it is and is named - by `--reaim` as not moved, with why, and by `--check` beside its stale proof and as NOT re-aimed. A pointer-shaped string naming no file under the project (`Layout.astro:138`, no folder) fails `--check` by name (1.4.5, a static site). A host with a port is not a pointer - `localhost:3000`, `app.example.com:8443`, `127.0.0.1:8080`, `[::1]:5173`, a URL - because a pointer names a path: a `/` in it, an extension that is not a host label, or a file that exists (1.4.6). A range `--reaim` declines is printed with the text at its ends: where its first line is now, and, for an end whose text changed, that the number is the edge of that change and not a line read by its text (1.4.6) |
| `status` | `live` · `hidden` · `flagged` · `dead` | a feature behind a flag verified in the on state is not verified for users |

### Reach — how the user gets there — AUTHORED, DOM parts DERIVED

| Field | Answers | Why it exists |
|---|---|---|
| `entry` | the URL, command, endpoint or event that starts it | "how does the user reach it". A `path:line` pointer inside it (`its slot is src/pages/index.astro:310-312`) is read like one in `code:` - re-aimed and checked for movement, and named when it resolves to no file - but never stales the proof (1.4.5). A host with a port (`localhost:3000`, `https://x.y:443/path`) is the entry itself, never a pointer (1.4.6) |
| `path` | the ordered steps from a cold start to the feature being usable | a feature reachable only from state you forgot to set up reads as broken |
| `operate` | exactly how it is worked: click, type, drag, keyboard | their question — click *or* keyboard, and they fail independently |
| `keys` | every keyboard shortcut, and whether it is global or scoped | a shortcut that works only while an input is unfocused is a different feature. Derived shortcuts arrive as `key.<modifiers>-<keys>` with their scope in the found-as column |
| `selector` | the DOM element acted on — prefer `data-testid`, then `aria-label`/role, then text, and CSS path last | their question. Ordered by durability: a CSS path breaks on every refactor, so a map built on CSS paths rots fastest |
| `precondition` | the state that must exist first — signed in, cart non-empty, file loaded | you cannot drive checkout with an empty cart, and an undriveable map entry is why verification gets skipped |

### Contract — what it does, and must not do — AUTHORED

| Field | Answers | Why it exists |
|---|---|---|
| `does` | what the feature is for, in one sentence, in user terms | their question: what are the capabilities and what do they do |
| `observable` | the thing you read back to know it worked: URL change, row written, status code, rendered text, exit code, file on disk | **the single most important field.** Without it, "verify" has no object and becomes "it looked fine" |
| `must_not` | the negative contract: no double charge, no data loss, no silent truncation | a feature can satisfy its purpose and still be a defect; nothing else in the map catches that |
| `effect_of` | for a `setting`: what changes *elsewhere* when it is on versus off | a setting that persists but does nothing passes every save-and-reload check |
| `intent` | the operator's own words where they exist, verbatim | the Intended bar. Paraphrase loses the thing that makes intent different from spec |

### Evidence — AUTHORED, staleness DERIVED

| Field | Answers | Why it exists |
|---|---|---|
| `grade` | `DRIVEN` · `TESTED` · `ASSERTED` · `UNKNOWN` | conflating a read-through with a driven run is how "fully verified" gets claimed over untested code |
| `proof` | pointer into the proof store | a grade with no artifact is an opinion |
| `verified_at` | `date @ commit` | the commit is what staleness is measured from: any change to the feature's region since then, committed or not, stales the proof. With no commit git can resolve, it is measured by day only, and `--check` says so by name. A passing DRIVEN or TESTED `--record` prints the value to write, `date @ commit` of the capture, and warns when the entry holds a work label (a ticket id) instead (1.4.3) |
| `bound` | what the verification did **not** cover | an unbounded pass claim is the defect |

## Derived ids

The extractor mints ids under fixed prefixes, and an authored entry keyed by one of
them is tied to the code: `endpoint.` · `route.` · `control.` · `region.` · `key.` ·
`cli.` · `cmd.` · `script.` · `env.` · `deploy.` · `ci.`. A feature found by hand takes its own prefix — `ui.`, `setting.`,
`job.` — and is never judged against the derived table.

- A route's id is its path, and `/` is `root`.
- An argparse subcommand (`add_parser("explain")`, on a subparsers object or a
  Parser subclass) is `cmd.<file>-<name>` on the dev face, at the line that adds
  it, found as `subcommand <name>`: `cmd.depgraph-explain` for depgraph.py (1.4.6).
  Its flags stay `cli.` capabilities of the file, as before.
- A control or region is named by its `aria-label` or `data-testid`: a quoted string
  as written, a template by its fixed words (`Unpin ${title}` is `unpin`), any other
  expression by the first literal it shows. A label with no fixed words has no id; it
  is listed under **NO FIXED NAME** with its location, and never dropped.
- The element's own opening tag decides what a label names. A button, an input, a
  handler or a button-like role makes a `control.`; a landmark (`aside`, `nav`,
  `dialog`, `form`), a grouping role, or a plain container holding controls makes a
  `region.`; a label on anything else names neither.
- A shortcut is every key tested in one condition plus the modifiers it demands:
  `key.alt-p`, `key.mod-k`. The found-as column says whether it is global (a window or
  document listener), on a focused element, or outside any listener the extractor can
  follow. Enter or Space in a button-like element's own handler is that element's
  keyboard activation, not a shortcut. A key read into a local first
  (`const k = e.key.toLowerCase()`, then `k === "l"`) is followed inside the listener
  that defines it, and the found-as column says `(tested as k)`. A negated modifier
  (`!e.altKey &&`) rules that modifier out rather than demanding it, and a key tested
  again inside its own shortcut's block (`set(k === "d" ? … )`) is a branch of that
  shortcut, not a second one.
- One id found in several places lists every place (`— also at …`). The entry for
  that id covers all of them, or is split by hand under your own prefix.
- An authored entry under a derived prefix that the code no longer derives fails
  `--check`, which names its likely successor. Rename the entry and move
  `.verify/proof/<old id>/` with it.

## Faces — who reaches it

Every derived capability carries a face, because the map is asked for from both the
user's face and the development face.

| Face | What lands there | Why |
|---|---|---|
| `user` | `route.` `control.` `region.` `key.`; an endpoint that serves a page; an endpoint a client file calls (the found-as column names the file and line) | a person reaches it from a screen |
| `dev` | `cli.` `cmd.` `script.` `env.` `deploy.` `ci.`; an endpoint no client file calls | an operator or developer reaches it, or nothing in the client does |
| `unclassified` | an endpoint whose path has no fixed part to search for (`/<id>`) | guessing would put it on the wrong face half the time |

A test file is never counted as a client. An authored `- face: user` or `- face: dev`
overrules the derived face in `--list` and `--compare`; write the reason beside it,
after a dash (`- face: dev — only tests reach it`). Any other value is not a face and
the derived one stands, so the template's hint line never becomes a bucket.

The dev face lists environment variables **by name only**. A value is never read,
printed or stored: the value of a key is the secret, and a map is a tracked file. A
read through a module constant (`KEY = "X"`, then `os.environ.get(KEY)`) is found as
`X`; a name assigned twice is not guessed at. Each `env.` row says whether the deploy
config declares it, and a deploy row lists what it declares that no code reads.

## Any commit, any branch, and production

`--list --ref <ref>` and `--compare <A> [<B>]` read the project out of git into a
temporary folder with `git archive` — never a checkout, so the working tree, the
index and whatever another session has open stay untouched — and measure it with the
same extractor, so two refs differ only where their code differs. A project that is a
folder inside its repository brings the repository's own render.yaml, Procfile,
Dockerfile and `.github` with it. `git archive` leaves out what `.gitattributes`
marks `export-ignore`, and a submodule's contents; any file left out is named on
stderr and is not measured.

`--live` reads four fields from an authored entry — normally the `deploy.` id derived
from render.yaml — or the same four from the command line:

| Field | Answers | Why it exists |
|---|---|---|
| `url` | scheme and host of production, no path | where to ask |
| `fingerprint` | a file production serves byte for byte from the repository | its blob is found in the branch's history, which places production between the commit that last changed that file and the branch head |
| `probes` | safe GET paths, comma-separated | a health check is read back; a path with side effects must never be listed, because it would be requested |
| `branch` | the branch production deploys from (default: render.yaml's, else `main`) | what the fingerprint is placed in |
| `root` | the repository folder the site serves at `/` (`public` for Astro, Vite, Next) | `/licenses/X.txt` is `public/licenses/X.txt` in git; undeclared, the path as served, then `public/` and `static/`, are tried, matched by content |

From the command line, for a production the map does not declare (`root` is read
from the map only):

```
python -B scripts/featuremap.py --live --url https://app.example.com \
  --fingerprint robots.txt --probe /health --probe /version --branch main
```

`--fingerprint` is the path as production serves it (`robots.txt`, found in the
repository as `public/robots.txt`), `--probe` repeats, and with no `--url` every
authored entry that declares a `url:` is read instead.

Only those paths and the fingerprint are requested, always with GET, and a redirect is
reported, never followed. The answer is only as current as the last `git fetch`,
which it prints. A fingerprint production rewrites (minified, stamped) matches no
commit and reads UNKNOWN, which fails the check rather than guessing. In Git Bash a
probe typed as `/health` is rewritten into a Windows path before Python sees it:
declare probes in the map, or set `MSYS_NO_PATHCONV=1`. A rewritten probe is refused.

## Judged by Jev — the Intended bar

`--judge` pairs each authored entry's `intent` with its `observable` and asks Jev one
question per entry, all in one request: would reading back this observable show
whether this intent was met? It reads, never gates: the thresholds are unvalidated
until `jev-calibration.md` records the operator's own data. Entries missing either field are
counted, never dropped silently, and an entry carrying a literal Jev cannot read (hex,
RGB, binary) is named as not judged.

## Adopting on a codebase that already exists

A real project has dozens of capabilities the day you add the map, and a check that
cannot go green until every one is authored does not get satisfied — it gets
switched off. A disabled check is worse than a lenient one, because it reports
nothing at all.

So the unmapped count ratchets like everything else here. Record
`- unmapped_ceiling: <n>` on any authored entry to grandfather what exists today;
`--check` then fails only when the count **grows**, which is exactly when new work
arrived unmapped. `--ratchet` lowers the ceiling as entries get authored, so
writing one entry permanently lowers the bar instead of buying slack.

Measured: a live web app's tree has 39 capabilities. Unadopted it fails with 39
unmapped and a line telling you the number to record. Grandfathered at 39 it
passes. Add one endpoint and it fails again, naming that endpoint alone.

Re-measured 2026-09-23, after that app's own session adopted the map and opened six
blind spots by hand: the same tree now yields 64, where the extractor it adopted
with yields 48 — 23 found that it could not see (labels written as templates,
labelled regions, a shortcut's modifier) and 7 renamed or retired. A grandfathered
ceiling set before an extractor improves has to be raised by hand once, with that
reason written beside it; the ratchet never raises one.

Author a feature when you change it, and the map grows along the work. Authoring
all of them in one sitting means authoring them from the code, which is the same
misreading verification exists to catch.

## Coverage is reported, never rounded up

The map reports counts per grade and **never a single percentage**: eighty percent
ASSERTED is not eighty percent verified, and one number invites exactly that
reading. `UNKNOWN` entries are listed by name, not summarized — a named gap gets
closed and a counted gap does not.

## Scope: what belongs in the map

Every user-reachable capability, and that is wider than the screens. Routes and
pages · buttons, forms and controls · keyboard shortcuts · **settings, toggles and
config with their downstream effects** · CLI commands and flags · API endpoints ·
background jobs and schedules · auth and permission boundaries · imports, exports
and file handling · empty, loading and error states · anything behind a feature flag,
with its flag named.

Error and empty states are features. They are the least-driven part of every app and
the most likely to be what a user actually meets.

## What the map is not

Not the architecture (that is a different document and a different question), not a
changelog, and not a test suite — it is the addressing system a verification run
uses to find the thing it must drive, plus the record of what that run found.
