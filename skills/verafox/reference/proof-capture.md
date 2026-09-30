# Capturing proof, and analyzing it

A capture nobody compares is a souvenir. The point of writing proof down in a fixed
shape is that the **next** run can be subtracted from it — that is where regressions,
timing drift and silent scope loss become visible, and it is where real numbers come
from without building a separate metrics project.

## The store

```
<project>/.verify/
  proof/<feature-id>/<UTC-timestamp>-<commit>.json   one capture, one run
  proof/<feature-id>/latest.json                     copy of the newest
  artifacts/<feature-id>/<timestamp>-<name>.<ext>     screenshots, response bodies, logs
```

In the project, not in the skill: proof belongs beside the code it certifies, travels
with the clone, and is reviewable in a diff. The skill holds the schema and the
registry; the project holds its own evidence.

## A capture record

Every field is required. A record missing one is not a capture.

| Field | Example | Why |
|---|---|---|
| `feature` | `checkout.submit` | ties to the map |
| `at` | `2026-09-22T14:02:11Z` | ordering, and staleness against the code |
| `commit` | `b57e1ab` | the exact tree that behaved this way |
| `grade` | `DRIVEN` | what this run earned |
| `how` | the steps actually performed | a reader must be able to repeat it |
| `observable` | `order row 8841 exists; cart count 0` | the read-back, in values not adjectives |
| `result` | `pass` · `fail` · `blocked` | blocked is a real outcome, not a failure to report |
| `bound` | `one item, Chrome 1920, card 4242` | what this run does **not** cover |
| `metrics` | `{duration_ms: 812, requests: 14, console_errors: 0}` | free from the run; see below |
| `artifacts` | relative paths | the third-party re-readable part |
| `conditions` | browser, width, theme, OS, dataset, user role | a before and an after are comparable only when taken the same way |

Values, never adjectives. "Fast" is not a metric and "looked right" is not an
observable.

## Metrics fall out of the driving

A run that drove the feature already knows these, so not recording them is throwing
away the measurement you already paid for:

- **duration** of the user-visible action, wall clock, from the act to the observable
- **counts**: network requests, queries, retries, rows touched
- **errors**: console errors, warnings, 4xx/5xx, stderr lines
- **size**: payload bytes, bundle delta, rows returned
- **resource**: peak memory or CPU where the surface makes it cheap to read

These are diagnostics on the first run and telemetry on the fiftieth. Do not
instrument new code to obtain them; read what driving the feature already produced.

## Analysis — the step that makes it worth storing

On every capture, compare to `latest.json` for that feature and report:

1. **Result transition** — pass→fail is a regression and must block the report.
   fail→pass is the fix's evidence. blocked→blocked twice means escalate.
2. **Metric delta with a threshold you set in advance**, because a number with no
   threshold is a number nobody acts on. Duration up materially, requests up,
   console errors non-zero when they were zero: each is a finding even when the
   feature still passes. **Silent slow-down is the regression that ships.**
3. **Bound shrinkage** — this run covered less than the last one. Coverage quietly
   narrowing while the grade stays DRIVEN is how a suite hollows out.
4. **Staleness** — proof older than the last change to the feature's `code` path is
   not evidence. `featuremap.py --check` computes this from git history and reports
   it; an implementation that moved after its certification is UNKNOWN again.

Validate every threshold against this project's own history. A number from a vendor
cookbook describes their app.

## Failure is a result, and it is kept

Keep failing captures. They are the highest-value records in the store: each one is a
regression test that already reproduced, and deleting it to keep the store tidy
throws away the only proof the failure was ever real. A store containing only passes
is a store that has been curated, and a curated evidence store is not evidence.
