`Version 1.1 | Deps: verafox skill | Parent: {{PROJECT}} | Path: ./ | Filename: FEATURE-MAP.md | Created: {{CREATED}}`

# {{PROJECT}} — feature map

What exists, how a user reaches it, how they operate it, and what evidence each
capability currently holds. Maintained by
`python <skills>/verafox/scripts/featuremap.py --check --project .`

Two halves, and the script only ever writes one of them. Coverage is reported as
counts per grade, never as a single percentage: eighty percent ASSERTED is not
eighty percent verified.

<!-- DERIVED:BEGIN -->
<!-- DERIVED:END -->

<!-- AUTHORED:BEGIN -->

Judgment lives here and no script touches it. One `###` section per feature, keyed
by the same `id` the derived table uses. Fields are `- key: value` lines; a missing
`grade` reads as UNKNOWN, which is the honest default.

Copy this block for each feature. Delete the example before the first `--check`.

### example.id

- name: what a user would call it
- surface: web-ui
- face: user · dev — only to overrule the derived face, with the reason
- code: src/thing.tsx:42 — or src/thing.tsx:42-90 for its span; staleness looks only there
- status: live
- entry: /the/url — or the command, endpoint or event that starts it
- path: the ordered steps from a cold start to this being usable
- operate: click · type · drag · keyboard — say which, they fail independently
- keys: every shortcut, and whether it is global or scoped to a focused element
- selector: [data-testid=thing] — prefer testid, then aria-label/role, then text, CSS path last
- precondition: the state that must exist first (signed in, cart non-empty, file loaded)
- does: one sentence, in user terms
- observable: what you read back to know it worked — a value, not an adjective
- must_not: the negative contract (no double charge, no silent truncation, no data loss)
- effect_of: for a setting — what changes elsewhere when it is on versus off
- intent: the operator's own words, verbatim, where they exist
- grade: UNKNOWN
- proof: .verify/proof/example.id/latest.json
- verified_at: YYYY-MM-DD @ commit — the commit is what staleness is measured from
- bound: what the verification did NOT cover — an unbounded pass claim is the defect
- unparsed_accepted: only on one entry — comma-separated surface files mapped by hand
- unmapped_ceiling: only on one entry — how many capabilities were unmapped when
  this map was adopted. Grandfathers an existing codebase so `--check` fails on
  growth rather than on history; `--ratchet` lowers it as entries get authored

For `--live` to read production, give the deployment an entry with the fields below:
on the `deploy.` id that `--write` derived from render.yaml, or on a `live.` id of your
own where no deploy file declares one. Fill this example in or delete it before the
first `--check`; left as it is, `--live` refuses its placeholder address.

### live.production

- name: production
- url: https://your-app.example.com — scheme and host only, no path
- fingerprint: static/app.js — a file production serves byte for byte from the repository
- probes: /health — safe GET paths only, comma-separated; never one with side effects
- branch: main — the branch production deploys from

## How this codebase does things

An agent writes what its neighbours wrote — that is the cheapest correct behaviour
available to something with no context, and it is what makes a bad neighbour
contagious. Each rule below names the wrong way so it can be counted, and the right
way by `path:line` so copying it is the shortest action available.

`ceiling` is the number of violations present when the rule was written. Existing
ones are grandfathered; the check fails the moment the count grows. You never have
to reach zero to be protected, only to never grow. `--ratchet` lowers a ceiling to
what is actually present and will never raise one.

Copy this block per rule. Delete the example before the first `--check`.

### pattern: example-rule

- rule: state the consequence, not the convention — "retrying inside a service
  double-charges" outlives a refactor; "we use the decorator at the edge" does not
- canonical: path/to/the/right/example.py:12
- antipattern: a regex matching the WRONG way
- files: where the anti-pattern is counted — e.g. `views/*.py` (omit for the whole tree)
- signature: a regex matching this pattern's OWN use
- only_in: where this pattern is allowed to appear — e.g. `api/*.py`
- ceiling: 0

`antipattern` + `files` catches contagion. `signature` + `only_in` catches the
opposite failure: the right pattern drifting somewhere it was never designed for,
where every occurrence looks correct in isolation. Declare either, or both.

<!-- AUTHORED:END -->

## Reading this map

- `UNKNOWN` and `ASSERTED` are listed by name in `--check`, not summarized. A named
  gap gets closed; a counted gap does not.
- A feature whose code changed inside its region after the commit in `verified_at`
  — committed or not — is stale, and `--check` fails on it. Evidence that predates
  its implementation is not evidence.
- An authored id under a derived prefix (`endpoint.` `route.` `control.` `region.`
  `key.` `cli.` `cmd.` `script.` `env.` `deploy.` `ci.`) that the code no longer derives fails `--check`, which
  names its likely successor. A feature found by hand takes its own prefix (`ui.`,
  `setting.`).
- Error, empty and loading states are features. They are the least-driven part of
  any project and the most likely to be what a user actually meets.
