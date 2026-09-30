# Driving and reading back, per surface

One rule sits above all of them: **verify at the layer the user meets, not the layer
you edited.** A change to a handler is verified by reaching the handler the way a
user reaches it. Every shortcut below the user's layer proves the shortcut works.

For anything about rendered appearance — geometry, colour, contrast, occlusion,
theme — stop here and use the `measure-in-the-browser` skill. For whether a test
could have failed at all, use `testcatch`. This file is about behaviour.

## Web UI

- **Drive the element in the map's `selector`, from the map's `entry`, after setting
  its `precondition`.** Do not call the function; press the thing.
- **Read the `observable` back from the page or the system, not from the click's own
  return.** A click handler that resolves says the handler resolved. The cart being
  empty and an order row existing says checkout happened.
- **Read a state's value and its visible effect, never only its presence.**
  `toggleAttribute("aria-current")` writes an empty value, which ARIA reads as
  false, and the CSS keyed on `aria-current="page"` never matched - a proof that
  read "the attribute is there" passed on it (a static site).
  Read the value, and read what it was for: the underline drawn, the item
  announced.
- **Wait on a condition, never on a duration.** A sleep long enough to pass today is
  a flake tomorrow and a false pass under load.
- **Confirm the negative in the same run.** Press it twice if `must_not` says no
  double submit. The second press is the test.
- **Keyboard and click are two features.** Drive both when both are mapped. Shortcut
  scope matters: run it with focus in an input and outside one.
- **Drive one error path.** Submit the form empty, or with the network refused. An
  app verified only on its happy path is verified for the case that rarely breaks.

## Settings and config

The class with the highest false-pass rate, because the obvious check — it saved, it
still shows the new value after reload — tests persistence, not effect.

- **Drive both states and observe `effect_of` somewhere else.** Turn it on, go to the
  surface it governs, read the change. Turn it off, read it back.
- **Confirm the default** on a fresh profile or a cleared store. The default is what
  almost every user gets, and it is the value nobody tests.
- **Cross the boundary the setting lives on.** A per-user setting: check a second
  user is unaffected. A per-project setting: check a second project. A cached one:
  check after a restart, because "takes effect until restart" is a defect.
- **Name the permutation matrix you drove and the one you skipped.** Settings
  combine combinatorially; you cannot drive all of them and must not imply you did.
- **An environment variable or config file is a setting.** Drive it at the level it
  is read, and confirm precedence when more than one source can set it.

## CLI

- **Run the command as documented, in a clean working directory**, and assert on
  **exit code plus the effect**, not on stdout wording. Text is the least stable
  contract a CLI has.
- **Run it twice.** Idempotence is a contract almost nobody writes down and users
  discover.
- **Drive the failure path and the flags.** A flag with no driven run is an
  UNKNOWN feature that looks implemented because it parses.

## API

- **Call the endpoint over the network the client uses**, with the client's auth, and
  assert status, shape and the persisted effect.
- **Drive rejection**: missing auth, malformed body, wrong content type. An endpoint
  verified only on valid input has an unverified security surface.
- **Read the effect out of the store, not out of the response.** A 200 with no row
  written is the failure this catches.

## Background jobs and schedules

- **Trigger it directly once** to prove the body works, then **prove the trigger
  fires** — those are two verifications and the second is the one that is usually
  missing. A job whose body is perfect and whose cron never fires is scheduled
  theatre.
- **Assert on the state it was supposed to leave behind**, and on what it did to a
  record that was already correct (re-runs must not double-apply).

## Data and migrations

- **Count before, count after, and state both.** A migration verified by "it ran
  without error" has not been verified.
- **Check a row you predicted by hand.** Aggregates hide per-row corruption.
- **Prove the rollback path exists** before the forward path is called verified.

## Auth and permissions

- **Verify from the denied side.** Confirming the permitted user gets in says nothing
  about whether anyone else does. Drive it as the wrong user, as no user, and as a
  user whose permission was just revoked.

## When you cannot drive it

Say so, in the report and in the map's `bound`. Then take the best grade honestly
available and name why: no credentials, no test data, a third-party sandbox, a
device you do not have. **A named gap is workable; a quiet ASSERTED dressed as
verified is not.** Escalate the ones only the operator can unblock — and check
whether they have already unblocked it before asking again.
