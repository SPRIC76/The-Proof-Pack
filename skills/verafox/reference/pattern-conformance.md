# The codebase is the memory

The principle, as its author put it on 2026-09-22, and this file exists to make it mechanical:

> The code bases themselves should act as a form of memory and context. That makes
> it so that there is no shortcut and the easiest and best path is always the right
> one. These code bases should be made to work optimally with agents who may not
> have an engineering or technical background, but could be anybody and have any
> level of context, including none.

The operative fact underneath it: **an agent writes what its neighbours wrote.**
Given a file to extend, it matches the surrounding style before it consults any
rule, because the surrounding style is concrete and present and the rule is
abstract and elsewhere. That is not a flaw to train out. It is the cheapest
correct behaviour available to something with no context, and it is the property
to build on.

It cuts both ways, and that is the whole design:

- A correct neighbour makes correct work free.
- An incorrect neighbour makes incorrect work free — **and each copy becomes a
  new neighbour.** That is why an anti-pattern behaves like an infection rather
  than a defect: its growth rate is proportional to how much of it already
  exists.

So the goal is never "write down the rules." It is to make the right path the
shortest one, and to make the wrong path cost something the moment it is taken.

## Two failures, not one

Most conformance tooling sees only the first.

| Failure | What it looks like | Why it survives review |
|---|---|---|
| **Contagion** | The wrong way, spreading | Each copy is locally consistent with its file |
| **Drift out of scope** | The *right* way, somewhere it was never designed for | Every occurrence looks like someone following the rules |

The second is the one the principle names specifically — *"have not drifted onto other items
that it was not designed for"* — and it is the harder one, because nothing about
any individual use looks wrong. A retry decorator that is correct on an outbound
API call is a double-charge when someone copies it onto a payment service. The
copier was being diligent. Diligence is exactly how it travelled.

`featuremap.py --check` measures both: `antipattern` counted inside `files`, and
`signature` counted **outside** `only_in`.

## The ratchet

You do not have to reach zero to be protected. You have to never grow.

Every pattern records a `ceiling` — the number of violations present when the rule
was written. Existing violations are grandfathered; the check fails the moment the
count exceeds it, naming each occurrence and its file.

This is what converts a rule from advice into a property of the system. The
standing order says it plainly: *if the constraint requires you to remember it, it
will be violated under time pressure — make it a property of the system.* A ceiling
in a file that a script enforces does not depend on anyone remembering anything.

`--ratchet` lowers a ceiling to the count actually present. **It will never raise
one.** Tightening cannot make the map claim more safety than reality; loosening
can. Raising a ceiling stays a hand edit with a reason written beside it, because
that is a decision to tolerate something, and a tolerance nobody argued for is how
a rule dies quietly.

When the count drops below the ceiling, `--check` says so and asks you to tighten.
Headroom left lying around is room to regrow.

## A pattern needs a canonical example, by path and line

The most important field is `canonical`, and it is not documentation.

An agent told "views must not query the database directly" has been given a
prohibition and no destination. An agent told "copy `services/orders.py:12`" has
been given the shortest action available — and taking it is now cheaper than
inventing something. A pattern without a canonical example is an opinion, and
`--check` fails when the canonical file has been deleted, because an agent sent to
copy a file that is gone will copy whatever is nearest instead.

That is the whole mechanism for *"the easiest and best path is always the
right one."* Not exhortation. A path.

## Writing for an agent with no context

Assume the reader has never seen this codebase, has no engineering background, and
will act on the first concrete thing it finds:

- **Name the rule in terms of the consequence, not the convention.** "Retrying
  inside a service double-charges" survives a refactor; "we use the decorator at
  the edge" does not, and nobody can tell whether it still applies.
- **Point at one file, not a style guide.** One example that compiles beats a page
  that argues.
- **Scope it explicitly.** A pattern with no `only_in` silently claims the entire
  tree, and then someone follows it into a place it was never meant to go — which
  is the second failure above, manufactured by the rule's own vagueness.
- **A rule that cannot run is not a rule in force.** An anti-pattern regex that
  does not compile is reported as a problem, never counted as zero hits. Silent
  zero is the worst possible reading: a rule that looks enforced and measures
  nothing.
- **Read the hit list before you trust the count.** Both failure directions showed
  up the first time these rules were pointed at a real tree. A rule written
  `^\s*except\s*:` measured zero against three real occurrences, because the regex
  was compiled without multiline and `^` bound to the start of the file — enforced
  in appearance, dormant in fact. And a rule matching `requests\.(get|post)\(`
  flagged two uses of a local dict called `self._requests`, which are not the
  library at all. A ceiling recorded from an unread hit list grandfathers the wrong
  things and protects nothing.

## Where this sits

The feature map answers *what exists and how a user reaches it*. Verification
answers *does it do what it should*. This answers *is it built the way this
codebase builds things, and has that way leaked somewhere it does not belong*.

All three are the same act: making the codebase able to tell a stranger the truth
about itself without a person in the loop.
