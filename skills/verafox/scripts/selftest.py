# -*- coding: utf-8 -*-
# The strings below are fixtures Mutate reads as data, not things this file does:
# mutate: fixture
"""selftest.py - the cases featuremap.py must not regress on.

Run:  python scripts/selftest.py       (exit 0 = all green)

Each case builds a throwaway fixture project in a temp directory, drives
featuremap.py as a user drives it - through the command line, reading the exit
code and the output, never by importing and calling the functions - and asserts
on the observable. Calling the function would prove the function works; the
contract this script defends is the command-line one, because that is what a
hook or a CI step actually invokes.

Case 5 exists because of a real failure, not an imagined one: the first run
against a live Flask app mapped `__esModule` and `default` as keyboard shortcuts
out of babel.min.js and mapped the same UI twice from a compiled .js beside its
.jsx. A reported failure becomes a kept case.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FM = os.path.join(HERE, "featuremap.py")

PASS, FAIL = [], []


SAFE = {}


def run(cwd, *args, env=None):
    # --record asks Jev since 1.3.6, and a Jev client may read this machine's
    # real key from a file in its home folder. A case that does not bring its own environment
    # runs with no key and a home of the test's own, so no fixture is ever sent.
    if env is None and SAFE:
        env = SAFE
    p = subprocess.run([sys.executable, FM, "--project", cwd] + list(args),
                       cwd=cwd, capture_output=True, timeout=120, env=env)
    return p.returncode, p.stdout.decode("utf-8", "replace") + \
        p.stderr.decode("utf-8", "replace")


def git(cwd, *args):
    return subprocess.run(("git",) + args, cwd=cwd, capture_output=True,
                          timeout=60).returncode == 0


def head(cwd):
    p = subprocess.run(("git", "rev-parse", "--short", "HEAD"), cwd=cwd,
                       capture_output=True, timeout=60)
    return p.stdout.decode("utf-8", "replace").strip()


def commit(cwd, msg):
    git(cwd, "add", "-A")
    git(cwd, "-c", "user.name=t", "-c", "user.email=t@example.com",
        "commit", "-q", "-m", msg)


def commit_only(cwd, msg, *paths):
    """Commit the named files alone; the map stays as it is in the working tree."""
    git(cwd, "add", "--", *paths)
    git(cwd, "-c", "user.name=t", "-c", "user.email=t@example.com",
        "commit", "-q", "-m", msg, "--", *paths)


def put(root, relpath, text):
    p = os.path.join(root, relpath.replace("/", os.sep))
    d = os.path.dirname(p)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def author(root, body):
    """Replace the authored half wholesale - the fixture's own convenience."""
    mp = os.path.join(root, "FEATURE-MAP.md")
    with open(mp, "r", encoding="utf-8") as fh:
        t = fh.read()
    a, b = "<!-- AUTHORED:BEGIN -->", "<!-- AUTHORED:END -->"
    t = t[:t.find(a) + len(a)] + "\n" + body + "\n" + t[t.find(b):]
    with open(mp, "w", encoding="utf-8", newline="") as fh:
        fh.write(t)


def _remove(tmp):
    """Git writes its objects read-only, and on Windows rmtree cannot delete a
    read-only file: with ignore_errors every run left its fixtures behind (276
    folders, 54 MB, by 2026-09-29). Clear the bit and retry; say so if anything
    still stays."""
    def again(func, path, _):
        os.chmod(path, 0o700)
        func(path)
    kw = {"onexc": again} if sys.version_info >= (3, 12) else {"onerror": again}
    try:
        shutil.rmtree(tmp, **kw)
    except OSError as e:
        print("NOTE the fixtures could not all be removed from %s: %s" % (tmp, e))


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + (
        ("\n         " + detail.replace("\n", "\n         ")) if
        (detail and not cond) else ""))


# This pack ships no Jev client. The cases that drive --judge and the reading at
# --record through one (28 and 53) run when a client is installed beside this
# skill, as jev-client/scripts/jev.py, and are named as not run when it is not.
CLIENT = os.path.exists(os.path.join(HERE, os.pardir, os.pardir, "jev-client", "scripts",
                                     "jev.py"))
NOT_RUN = []


class _NoClient(Exception):
    pass


# A skill is modular: any agent that reads SKILL.md can run it, in any workflow,
# beside any other skill or none (the owner, 2026-09-30). So a SKILL.md names a
# neighbor by its job, never by its name, except on the one line that declares
# an optional dependency; and it names an agent host only in an install section
# that names at least two, as examples. The same check is in each of the pack's
# self-tests, so each skill holds it alone. Names are the pack's and other public
# skills', anywhere; and any skill installed beside this one, where a line points
# at it as a skill: `name`, (name) or "name skill".
KNOWN_SKILLS = ("verafox", "testcatch", "measure-in-the-browser",
                "verify-before-done", "rules-that-can-fail", "skillshaper",
                "typesafe-ai", "frontend-design", "source-driven-development")
HOSTS = ("Claude Code", "Claude", "Cursor", "Codex", "Copilot", "Windsurf",
         "Gemini CLI", "Cline", "Aider")
_OPTIONAL_LINE = re.compile(r"^\s*(?:[-*]\s*)?(?:optional_dependency|Optional dependency)\s*:")


def installed_beside(skill_dir):
    """Names of the skill folders beside this one (each holding a SKILL.md)."""
    parent = os.path.dirname(os.path.abspath(skill_dir))
    try:
        return [n for n in os.listdir(parent)
                if os.path.isfile(os.path.join(parent, n, "SKILL.md"))]
    except OSError:
        return []


def skill_md_problems(text, own, beside=()):
    """Each line of a SKILL.md that names another skill (outside a declared
    optional-dependency line) or names an agent host outside an install section
    naming two or more, as "line N: why". `own` is the skill's own name and
    former names; `beside` the skills installed next to it."""
    def alt(names):
        return "|".join(map(re.escape, sorted(set(names) - set(own), key=len, reverse=True)))
    known = re.compile(r"(?<![\w-])(%s)(?![\w-])" % alt(KNOWN_SKILLS), re.I)
    near = [n for n in beside if len(n) >= 3 and n not in own]
    nearby = re.compile(r"`(%s)`|\((%s)\)|(?<![\w-])(%s) skill\b" % ((alt(near),) * 3), re.I) \
        if near else None
    host_rx = re.compile(r"(?<![\w-])(%s)(?![\w-])" % "|".join(map(re.escape, HOSTS)))
    lines, heads, section = text.split("\n"), {}, None
    for i, ln in enumerate(lines):
        if re.match(r"^#{1,6}\s", ln):
            section = i
        heads[i] = section
    install_hosts = {}
    for i, ln in enumerate(lines):
        s = heads[i]
        if s is not None and re.search(r"install", lines[s], re.I):
            install_hosts.setdefault(s, set()).update(host_rx.findall(ln))
    problems = []
    for i, ln in enumerate(lines):
        m = known.search(ln) or (nearby.search(ln) if nearby else None)
        if m and not _OPTIONAL_LINE.match(ln):
            name = next(g for g in m.groups() if g)
            problems.append("line %d: names the skill %s - name its job instead" % (i + 1, name))
        h = host_rx.search(ln)
        if h and len(install_hosts.get(heads[i], ())) < 2:
            problems.append("line %d: frames itself for %s - name hosts only as install "
                            "examples, two or more" % (i + 1, h.group(1)))
    return problems


def agnostic_cases(skill_md, own):
    """The check can fail, and this skill's own SKILL.md passes it."""
    other = [n for n in KNOWN_SKILLS if n not in own][0]
    bad = ("---\nname: x\ndescription: Not for how code works (%s).\n---\n\n# X\n\n"
           "Built for Claude Code. Pair it with the `made-up-sibling` skill.\n" % other)
    good = ("---\nname: x\ndescription: Not for how code works (a code-search tool).\n"
            "metadata:\n  optional_dependency: %s, for one flag\n---\n\n# X\n\n"
            "## Install\n\nCopy the folder where your agent reads skills (Claude Code, "
            "Cursor, Codex or any other). A made-up-sibling mention in prose is fine.\n"
            % other)
    found = skill_md_problems(bad, own, ["made-up-sibling"])
    check("the SKILL.md check can fail: a named skill, a skill installed beside it and "
          "a one-host frame are each caught", len(found) == 3, repr(found))
    found = skill_md_problems(good, own, ["made-up-sibling"])
    check("...and passes a declared optional dependency and hosts as install examples",
          found == [], repr(found))
    with open(skill_md, encoding="utf-8") as fh:
        found = skill_md_problems(fh.read(), own, installed_beside(os.path.dirname(skill_md)))
    check("RED: this skill's SKILL.md names no other skill and frames itself for no "
          "one host", not found, "\n".join(found))


ENTRY = """### %s

- name: %s
- surface: %s
- code: %s
- entry: /x
- does: a fixture feature
- observable: a value read back
- grade: %s
- verified_at: %s
"""


# --------------------------------------------------------------- fixtures

APP_V1 = """from flask import Flask
app = Flask(__name__)

@app.route('/health')
def health():
    return 'ok'

@app.route('/orders', methods=['POST'])
def orders():
    return 'made'
"""

APP_V2 = APP_V1 + """

@app.route('/refund', methods=['POST'])
def refund():
    return 'refunded'
"""


def fixture(root):
    put(root, "app.py", APP_V1)
    git(root, "init", "-q")
    git(root, "add", "app.py")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com",
        "commit", "-q", "-m", "baseline")


def main():
    # The harness prints what it read back when a case fails. On a legacy code
    # page that print crashed on the first non-ASCII character and hid every
    # result after it - found by the probe for case 11.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    tmp = tempfile.mkdtemp(prefix="fmselftest-")
    home0 = os.path.join(tmp, "home0")
    os.makedirs(os.path.join(home0, ".agents"))
    SAFE.update(os.environ, USERPROFILE=home0, HOME=home0)
    SAFE.pop("TYPESAFE_API_KEY", None)
    try:
        # ---------------------------------------------------- 1 red on unmapped
        print("\n1. a project whose code has features and whose map has none")
        a = os.path.join(tmp, "one")
        os.makedirs(a)
        fixture(a)
        rc, out = run(a, "--init")
        check("init scaffolds and derives", rc == 0 and "endpoint" not in out
              or rc == 0, out)
        # From a static site (2026-09-29): the header line is how its author dates and
        # places a file, so --init must write the template's, filled, as the map's first line.
        # The pack's review (2026-09-30): the stamp said "ET" on every machine; it
        # now carries the clock's own offset from UTC.
        with open(os.path.join(a, "FEATURE-MAP.md"), encoding="utf-8") as fh:
            first = fh.readline().rstrip("\n")
        stamp = re.search(r"Created: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) UTC([+-]\d{2}:\d{2})`$", first)
        age = (datetime.datetime.now() - datetime.datetime.strptime(stamp.group(1), "%Y-%m-%d %H:%M")
               ).total_seconds() if stamp else None
        z = datetime.datetime.now().astimezone().strftime("%z")
        check("--init writes the template's header line first, filled: this project's "
              "name, and a Created stamp read from the clock with its UTC offset, never ET",
              first.startswith("`Version 1.1 | Deps: verafox skill | Parent: one | Path: ./ | "
                               "Filename: FEATURE-MAP.md | Created: ")
              and "{{" not in first and age is not None and -60 <= age <= 600
              and stamp.group(2) == z[:3] + ":" + z[3:], first)
        rc, out = run(a, "--check")
        check("RED: exits non-zero on unmapped features", rc == 1, out)
        check("RED: names the unmapped ids", "endpoint.health" in out
              and "endpoint.orders" in out, out)

        # ---------------------------------------------------- 2 green
        print("\n2. the same project once every feature is authored")
        author(a, (ENTRY % ("endpoint.health", "health", "api", "app.py:4",
                            "DRIVEN", "2099-01-01 @ abc1234"))
               + (ENTRY % ("endpoint.orders", "orders", "api", "app.py:8",
                           "DRIVEN", "2099-01-01 @ abc1234")))
        rc, out = run(a, "--check")
        check("GREEN: exits zero when map and code agree", rc == 0, out)

        # ---------------------------------------------------- 3 red on new code
        print("\n3. code gains a feature the map does not have")
        put(a, "app.py", APP_V2)
        run(a, "--write")
        rc, out = run(a, "--check")
        check("RED: drift detected when code gains a feature", rc == 1, out)
        check("RED: names the NEW id specifically", "endpoint.refund" in out, out)

        # ---------------------------------------------------- 4 green again
        print("\n4. the map is reconciled to the new code")
        author(a, (ENTRY % ("endpoint.health", "health", "api", "app.py:4",
                            "DRIVEN", "2099-01-01 @ abc1234"))
               + (ENTRY % ("endpoint.orders", "orders", "api", "app.py:8",
                           "DRIVEN", "2099-01-01 @ abc1234"))
               + (ENTRY % ("endpoint.refund", "refund", "api", "app.py:13",
                           "DRIVEN", "2099-01-01 @ abc1234")))
        rc, out = run(a, "--check")
        check("GREEN: reconciling closes the drift", rc == 0, out)

        # ---------------------------------------------------- 5 build artifacts
        print("\n5. minified and compiled files must not become features")
        b = os.path.join(tmp, "two")
        os.makedirs(b)
        put(b, "src/ui.jsx", 'export const A = () => <button '
            'aria-label="Save" onClick={go}>S</button>\n')
        # The compiled sibling and a vendored bundle, shaped like the real ones.
        # The `keydown` string matters: ex_keyboard gates on it, so a fixture
        # without it makes the junk-feature assertion below pass vacuously. It
        # did exactly that on the first run of this harness - the assertion was
        # green because nothing could have been extracted at all.
        put(b, "src/ui.js", 'var x={};x.__esModule=!0;d.addEventListener('
            '"keydown",function(e){if(e.key==="__esModule"||e.key==="default"){}});\n')
        put(b, "vendor/babel.min.js", 'a' * 2500 + '\nwindow.addEventListener('
            '"keydown",function(e){if(e.key==="default"){}});\n')
        run(b, "--init")
        rc, out = run(b, "--check")
        mp = open(os.path.join(b, "FEATURE-MAP.md"), encoding="utf-8").read()
        check("no feature invented from minified/compiled code",
              "key.esmodule" not in mp and "key.default" not in mp, mp[-1500:])
        check("the real control IS found", "control.save" in mp, mp[-1500:])
        check("the compiled sibling is named as build output",
              "build output of ui.jsx" in mp, mp[-1500:])
        check("the vendored bundle is named, not silently dropped",
              "babel.min.js" in mp and "EXCLUDED" in mp, mp[-1500:])

        # ---------------------------------------------------- 6 stale proof
        print("\n6. proof older than the code it certifies")
        c = os.path.join(tmp, "three")
        os.makedirs(c)
        fixture(c)
        run(c, "--init")
        author(c, (ENTRY % ("endpoint.health", "health", "api", "app.py:4",
                            "DRIVEN", "2001-01-01 @ old1234"))
               + (ENTRY % ("endpoint.orders", "orders", "api", "app.py:8",
                           "DRIVEN", "2099-01-01 @ abc1234")))
        rc, out = run(c, "--check")
        check("RED: verified_at older than the code's last commit", rc == 1, out)
        check("RED: names the stale feature", "endpoint.health" in out, out)
        check("does NOT flag the feature whose proof is newer",
              out.count("endpoint.orders: verified") == 0, out)

        # ---------------------------------------------------- 7 unparsed
        print("\n7. a surface the extractor cannot read")
        d = os.path.join(tmp, "four")
        os.makedirs(d)
        fixture(d)
        put(d, "src/Thing.svelte", "<button on:click={go}>go</button>\n")
        run(d, "--init")
        author(d, (ENTRY % ("endpoint.health", "health", "api", "app.py:4",
                            "DRIVEN", "2099-01-01 @ abc1234"))
               + (ENTRY % ("endpoint.orders", "orders", "api", "app.py:8",
                           "DRIVEN", "2099-01-01 @ abc1234")))
        rc, out = run(d, "--check")
        check("RED: refuses to report clean over an unparsed surface", rc == 1,
              out)
        check("RED: names the unparsed file", "Thing.svelte" in out, out)

        # ---------------------------------------------------- 8 --write safety
        print("\n8. --write must never touch the authored half")
        before = open(os.path.join(a, "FEATURE-MAP.md"), encoding="utf-8").read()
        ab = before[before.find("<!-- AUTHORED:BEGIN -->"):]
        run(a, "--write")
        after = open(os.path.join(a, "FEATURE-MAP.md"), encoding="utf-8").read()
        check("authored half is byte-identical after --write",
              after[after.find("<!-- AUTHORED:BEGIN -->"):] == ab)
        rc, _ = run(a, "--init")
        check("--init refuses to overwrite an existing map", rc == 1)

        # ---------------------------------------------------- 9 record+analyze
        print("\n9. a capture is stored, and the next one is compared to it")
        rc, out = run(a, "--record", "--feature", "endpoint.refund",
                      "--grade", "DRIVEN", "--result", "pass",
                      "--observable", "refund row written, balance 0",
                      "--how", "POST /refund", "--metric", "duration_ms=100")
        check("first capture is recorded", rc == 0 and "recorded" in out, out)
        check("first capture says there is nothing to compare",
              "nothing to compare" in out, out)
        rc, out = run(a, "--record", "--feature", "endpoint.refund",
                      "--grade", "DRIVEN", "--result", "fail",
                      "--observable", "no row written",
                      "--how", "POST /refund", "--metric", "duration_ms=400")
        check("second capture reports the result transition",
              "pass -> fail" in out and "REGRESSION" in out, out)
        check("second capture reports the metric delta",
              "duration_ms" in out and "+300" in out, out)
        rc, out = run(a, "--record", "--feature", "x", "--grade", "DRIVEN",
                      "--result", "pass")
        check("a DRIVEN capture with no observable is refused", rc == 1, out)
        rc, out = run(a, "--record", "--feature", "x", "--grade", "PROBABLY",
                      "--result", "pass", "--observable", "y")
        check("an invented grade is refused", rc == 1, out)

        # ------------------------------------ 9b adopting on an existing codebase
        print("\n9b. an existing codebase must be able to reach green")
        h = os.path.join(tmp, "eight")
        os.makedirs(h)
        fixture(h)
        run(h, "--init")
        rc, out = run(h, "--check")
        check("RED: unmapped capabilities fail with no ceiling recorded", rc == 1,
              out)
        check("RED: tells you how to grandfather what is already there",
              "unmapped_ceiling: 2" in out, out)
        author(h, ENTRY % ("endpoint.health", "health", "api", "app.py:4",
                           "DRIVEN", "2099-01-01 @ abc1234")
               + "- unmapped_ceiling: 1\n")
        rc, out = run(h, "--check")
        check("GREEN: the existing backlog is grandfathered", rc == 0, out)
        put(h, "app.py", APP_V2)
        run(h, "--write")
        rc, out = run(h, "--check")
        check("RED: a NEW unmapped capability still fails", rc == 1, out)
        check("RED: names the new one", "endpoint.refund" in out, out)
        # authoring one entry must lower the bar, not just buy slack
        put(h, "app.py", APP_V1)
        run(h, "--write")
        author(h, ENTRY % ("endpoint.health", "health", "api", "app.py:4",
                           "DRIVEN", "2099-01-01 @ abc1234")
               + "- unmapped_ceiling: 1\n"
               + ENTRY % ("endpoint.orders", "orders", "api", "app.py:8",
                          "DRIVEN", "2099-01-01 @ abc1234"))
        rc, out = run(h, "--ratchet")
        check("--ratchet lowers the unmapped ceiling as entries get authored",
              rc == 0 and "1 -> 0" in out, out)

        # ------------------------------------------- 10 the anti-pattern ratchet
        print("\n10. an anti-pattern must not be able to spread")
        e = os.path.join(tmp, "five")
        os.makedirs(e)
        fixture(e)
        put(e, "views/a.py", "def a():\n    return db.session.query(X).all()\n")
        put(e, "services/orders.py", "def get(x):\n    return repo.orders(x)\n")
        run(e, "--init")
        base = (ENTRY % ("endpoint.health", "health", "api", "app.py:4",
                         "DRIVEN", "2099-01-01 @ abc1234")) \
            + (ENTRY % ("endpoint.orders", "orders", "api", "app.py:8",
                        "DRIVEN", "2099-01-01 @ abc1234"))
        PAT = """### pattern: no-query-in-view

- rule: a view never queries the database directly; it calls a service
- canonical: services/orders.py:1
- antipattern: db\\.session\\.query\\(
- ceiling: %d
"""
        author(e, base + (PAT % 1))
        rc, out = run(e, "--check")
        check("GREEN: an existing violation at its ceiling is grandfathered",
              rc == 0, out)

        put(e, "views/b.py", "def b():\n    return db.session.query(Y).all()\n")
        rc, out = run(e, "--check")
        check("RED: a SECOND occurrence breaks the ceiling", rc == 1, out)
        check("RED: names the file the copy landed in", "views/b.py" in out, out)
        check("RED: points at the canonical example to copy instead",
              "services/orders.py" in out, out)

        print("    ...and the ratchet may only ever tighten")
        rc, out = run(e, "--ratchet")
        check("--ratchet REFUSES to raise a ceiling to cover a spread",
              rc == 1 and "NOT changed" in out, out)
        os.remove(os.path.join(e, "views", "b.py"))
        os.remove(os.path.join(e, "views", "a.py"))
        rc, out = run(e, "--ratchet")
        check("--ratchet lowers the ceiling once the violations are gone",
              rc == 0 and "1 -> 0" in out, out)
        mp2 = open(os.path.join(e, "FEATURE-MAP.md"), encoding="utf-8").read()
        check("the lowered ceiling is written back to the map",
              "- ceiling: 0" in mp2, mp2[-800:])
        put(e, "views/c.py", "def c():\n    return db.session.query(Z).all()\n")
        rc, out = run(e, "--check")
        check("RED: once tightened to zero, one occurrence fails", rc == 1, out)

        print("    ...and a line-anchored rule must actually anchor to lines")
        g = os.path.join(tmp, "seven")
        os.makedirs(g)
        fixture(g)
        put(g, "w.py", "def w():\n    try:\n        go()\n    except:\n        pass\n")
        run(g, "--init")
        author(g, base + """### pattern: no-bare-except

- rule: a bare except
  swallows KeyboardInterrupt and SystemExit
- canonical: app.py:1
- antipattern: ^\\s*except\\s*:
- ceiling: 0
""")
        rc, out = run(g, "--check")
        # Without re.MULTILINE this regex matches nothing and the rule reports
        # clean while not running - which is how this case came to exist.
        check("RED: a `^`-anchored rule matches at line starts, not file start",
              rc == 1 and "no-bare-except" in out and "SPREAD" in out, out)
        check("RED: names the line the violation is on", "w.py:4" in out, out)
        check("a rule wrapped across lines is reported whole, not truncated",
              "swallows KeyboardInterrupt and SystemExit" in out, out)

        print("    ...and a GOOD pattern must not drift where it was not designed")
        f = os.path.join(tmp, "six")
        os.makedirs(f)
        fixture(f)
        put(f, "api/handlers.py", "@retry_on_429\ndef fetch(x):\n    return get(x)\n")
        put(f, "services/orders.py", "@retry_on_429\ndef place(x):\n    return x\n")
        run(f, "--init")
        author(f, base + """### pattern: retry-only-at-the-edge

- rule: the 429 retry decorator belongs on outbound API calls only; inside a
  service it retries business logic and double-charges
- canonical: api/handlers.py:1
- signature: @retry_on_429
- only_in: api/*.py
- ceiling: 0
""")
        rc, out = run(f, "--check")
        check("RED: the right pattern used in the wrong place is caught",
              rc == 1 and "DRIFTED out of scope" in out, out)
        check("RED: names where it drifted to",
              "services/orders.py" in out, out)
        check("RED: does NOT flag its legitimate use in scope",
              "api/handlers.py:1" not in out.split("DRIFTED")[-1], out)

        print("    ...and a rule that cannot run is not a rule")
        author(e, base + """### pattern: broken

- rule: a rule whose regex does not compile
- canonical: services/orders.py:1
- antipattern: db\\.session\\.query\\(  [unclosed
- ceiling: 0
""")
        rc, out = run(e, "--check")
        check("RED: an anti-pattern regex that does not compile is reported, "
              "not counted as zero", rc == 1 and "does not compile" in out, out)

        # ------------------------------ 11 a label written as an expression
        # From one web app, 2026-09-23: `aria-label={`Unpin ${title}`}` and its kind
        # labeled five real buttons that were neither mapped nor reported,
        # because the file was already claimed by the quoted labels beside them.
        print("\n11. a control labeled by an expression, not a quoted string")
        k = os.path.join(tmp, "nine")
        os.makedirs(k)
        put(k, "src/pins.jsx",
            "export const Pins = ({ pins, onUnpin, locked, toggle, label, go, id }) => (\n"
            "  <div>\n"
            "    {pins.map((pin) => (\n"
            "      <button type=\"button\" aria-label={`Unpin ${pin.config.title}`} onClick={() => onUnpin(pin.key)}>x</button>\n"
            "    ))}\n"
            "    <button aria-label={`Move ${id} up`} onClick={go}>u</button>\n"
            "    <button aria-label={locked ? 'Unlock all panels' : 'Lock all panels'} onClick={toggle}>L</button>\n"
            "    <button aria-label={label} onClick={go}>?</button>\n"
            "  </div>\n"
            ");\n")
        run(k, "--init")
        mp = open(os.path.join(k, "FEATURE-MAP.md"), encoding="utf-8").read()
        check("a template label is mapped by its fixed words",
              "`control.unpin`" in mp and "`control.move-up`" in mp, mp[-1500:])
        check("an expression label is mapped by the literal it shows",
              "`control.unlock-all-panels`" in mp, mp[-1500:])
        check("no id is invented from the expression's variable names",
              "control.pin-config-title" not in mp and "control.label" not in mp
              and "control.id" not in mp, mp[-1500:])
        rc, out = run(k, "--check")
        check("a label with no fixed words is reported by location, not dropped",
              "src/pins.jsx:8" in out and "aria-label={label}" in out, out)

        # ------------------------- 12 a report the console cannot encode
        print("\n12. a report containing a character the console cannot encode")
        n = os.path.join(tmp, "ten")
        os.makedirs(n)
        put(n, "v.py", "def a():\n    return db.session.query(X)  # joins \u2192 orders\n")
        run(n, "--init")
        author(n, """### pattern: no-query-in-view

- rule: a view calls a service
- canonical: v.py:1
- antipattern: db\\.session\\.query\\(
- ceiling: 0
""")
        rc, out = run(n, "--check")
        check("the check reports instead of crashing on an unencodable character",
              "Traceback" not in out and "SPREAD" in out and "\u2192" in out, out)

        # ------------------- 13 what the element is, not what sits nearby
        # From one web app, 2026-09-23: its labeled Explain drawer was dropped
        # because its buttons sat more than 300 characters below the label.
        print("\n13. a label names its own element, not whatever sits nearby")
        q = os.path.join(tmp, "eleven")
        os.makedirs(q)
        put(q, "src/drawer.jsx",
            "export const Drawer = ({ close, go }) => (\n"
            "  <div>\n"
            "    <aside className=\"drawer\" aria-label=\"Explain\" aria-live=\"polite\">\n"
            "      <p>" + "A term, its gloss, and a sentence of context. " * 9 + "</p>\n"
            "      <button onClick={close}>Close</button>\n"
            "    </aside>\n"
            "    <div role=\"group\" aria-label=\"Ticker shortcuts\">\n"
            "      <button aria-label=\"Refresh\" onClick={go}>R</button>\n"
            "    </div>\n"
            "    <span role=\"img\" aria-label=\"Logo mark\"></span>\n"
            "    <button onClick={go}>Go</button>\n"
            "    <div className=\"flex\" aria-label=\"Account\">\n"
            "      <button type=\"button\" onClick={go}>Sign in</button>\n"
            "    </div>\n"
            "    <div aria-label=\"Price chart\"><svg width=\"9\" height=\"9\"></svg></div>\n"
            "  </div>\n"
            ");\n")
        put(q, "src/card.jsx",
            "export const Card = ({ open }) => (\n"
            "  <div aria-label=\"Expand card\" className=\"" + "card " * 70
            + "\" onClick={() => open(1)}>E</div>\n"
            ");\n")
        run(q, "--init")
        mp = open(os.path.join(q, "FEATURE-MAP.md"), encoding="utf-8").read()
        check("a labeled landmark is a region, even with its buttons far below",
              "`region.explain`" in mp, mp[-1800:])
        check("a labeled group is a region, not a control",
              "`region.ticker-shortcuts`" in mp
              and "control.ticker-shortcuts" not in mp, mp[-1800:])
        check("a handler far from its label in the SAME tag still makes a control",
              "`control.expand-card`" in mp, mp[-1800:])
        check("a labeled image beside a button is not minted into a control",
              "logo-mark" not in mp, mp[-1800:])
        check("a plain labeled button is still a control",
              "`control.refresh`" in mp, mp[-1800:])
        check("a labeled plain container of controls is a region",
              "`region.account`" in mp and "control.account" not in mp,
              mp[-1800:])
        check("a labeled container with no control inside is not mapped",
              "price-chart" not in mp, mp[-1800:])

        # ------------------------------ 14 a shortcut is a condition, not a literal
        # From one web app, 2026-09-23: Alt+P was mapped twice (`key.p`, `key.keyp`)
        # without its Alt, and a card's Enter/Space activation was mapped as
        # two shortcuts. The settings panel's Escape guard was not seen at all.
        print("\n14. a shortcut is its whole condition, in the scope it listens on")
        w = os.path.join(tmp, "twelve")
        os.makedirs(w)
        put(w, "src/keys.jsx",
            "export const App = ({ toggle, close, expand, search }) => {\n"
            "  useEffect(() => {\n"
            "    const onKey = (e) => {\n"
            "      if (!e.altKey) return;\n"
            "      if (!(e.code === 'KeyP' || e.key === 'p' || e.key === 'P')) return;\n"
            "      toggle();\n"
            "    };\n"
            "    window.addEventListener('keydown', onKey, true);\n"
            "    return () => window.removeEventListener('keydown', onKey, true);\n"
            "  }, []);\n"
            "  useEffect(() => {\n"
            "    const onKey = (e) => {\n"
            "      if (e.key !== 'Escape') return;\n"
            "      close();\n"
            "    };\n"
            "    document.addEventListener('keydown', onKey);\n"
            "    return () => document.removeEventListener('keydown', onKey);\n"
            "  }, []);\n"
            "  return (\n"
            "    <div>\n"
            "      <div role=\"button\" tabIndex={0} onClick={expand}\n"
            "        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { expand(); } }}>card</div>\n"
            "      <input aria-label=\"Search\" onKeyDown={(e) => { if (e.key === 'Enter') search(); }} />\n"
            "    </div>\n"
            "  );\n"
            "};\n"
            "export const pick = (tab) => (tab.key === 'fundamentals' ? 1 : 0);\n")
        run(w, "--init")
        mp = open(os.path.join(w, "FEATURE-MAP.md"), encoding="utf-8").read()
        row = [x for x in mp.split("\n") if "`key.alt-p`" in x]
        check("keys tested in one condition are ONE shortcut, with its modifier",
              row and "`key.p`" not in mp and "`key.keyp`" not in mp, mp[-1800:])
        check("a window listener's shortcut is marked global",
              row and "global" in row[0], mp[-1800:])
        check("a guard that returns on every other key is read as that key",
              "`key.escape`" in mp, mp[-1800:])
        check("an element's own Enter/Space activation is not minted a shortcut",
              "key.space" not in mp and "enter-or-space" not in mp, mp[-1800:])
        check("Enter on a text input is still a keyboard feature",
              "`key.enter`" in mp, mp[-1800:])
        check("a comparison outside any listener is a key only if it names one",
              "fundamentals" not in mp, mp[-1800:])

        # ------------------ 15 an inlined image is not minification
        # From one web app, 2026-09-23: two long SVG data URIs got its hand-written
        # stylesheet excluded as "minified", so a rule over its CSS saw nothing.
        print("\n15. a long data URI does not make a stylesheet 'minified'")
        v = os.path.join(tmp, "thirteen")
        os.makedirs(v)
        put(v, "styles/theme.css",
            ":root {\n"
            "  --etch: url(\"data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 "
            + "%3Cpath d=%22M0 0%22/%3E" * 150 + "%3C/svg%3E\");\n"
            "}\n"
            ".card { color: red !important; }\n")
        put(v, "styles/bundle.css", ".a{b:c}" * 400 + "\n")
        run(v, "--init")
        author(v, """### pattern: no-important

- rule: !important wins every cascade fight and makes the next override impossible
- canonical: styles/theme.css:1
- antipattern: !important
- ceiling: 0
""")
        run(v, "--write")
        mp = open(os.path.join(v, "FEATURE-MAP.md"), encoding="utf-8").read()
        excluded = (mp.split("EXCLUDED")[-1].split("<!-- DERIVED:END -->")[0]
                    if "EXCLUDED" in mp else "")
        check("a stylesheet with a long data URI is not excluded as minified",
              "styles/theme.css" not in excluded, excluded)
        check("a genuinely minified stylesheet is still excluded",
              "styles/bundle.css" in excluded, excluded)
        rc, out = run(v, "--check")
        check("a rule over CSS measures the hand-written stylesheet",
              rc == 1 and "no-important" in out and "styles/theme.css:4" in out,
              out)

        # --------------- 16 staleness per commit and region, not day and file
        # From one web app, 2026-09-23: one 15,500-line file committed every round
        # staled every entry in it, and a change on the day of a proof was not
        # seen at all.
        print("\n16. proof goes stale when ITS code changes after ITS commit")
        s = os.path.join(tmp, "fourteen")
        os.makedirs(s)
        body = ["from flask import Flask", "app = Flask(__name__)", "",
                "@app.route('/health')", "def health():", "    return 'ok'"]
        body += ["# filler %d" % i for i in range(40)]
        body += ["", "@app.route('/orders', methods=['POST'])", "def orders():",
                 "    return 'made'", ""]
        put(s, "app.py", "\n".join(body))
        git(s, "init", "-q")
        commit(s, "baseline")
        base = head(s)
        today = datetime.date.today()
        run(s, "--init")
        author(s, (ENTRY % ("endpoint.health", "health", "api", "app.py:4",
                            "DRIVEN", "%s @ %s" % (today, base)))
               + (ENTRY % ("endpoint.orders", "orders", "api", "app.py:48",
                           "DRIVEN", "%s @ %s"
                           % (today - datetime.timedelta(days=1), base)))
               + (ENTRY % ("ui.old-note", "old", "web-ui", "app.py:1",
                           "DRIVEN", "2001-01-01 @ deadbee")))
        body[5] = "    return 'ok, and healthy'"
        put(s, "app.py", "\n".join(body))
        commit(s, "health changes the same day its proof was taken")
        rc, out = run(s, "--check")
        check("RED: a change the same day as the proof, inside its region",
              rc == 1 and "endpoint.health: verified @" in out, out)
        check("a change elsewhere in the same file does not stale a feature",
              "endpoint.orders: verified" not in out, out)
        check("a proof whose commit git cannot find says it was measured by day",
              "ui.old-note" in out and "by day only" in out, out)
        body[49] = "    return 'made twice'"
        put(s, "app.py", "\n".join(body))
        rc, out = run(s, "--check")
        check("RED: an uncommitted change inside the region stales it too",
              "endpoint.orders: verified @" in out, out)

        # ------------------------------------------ 17 the root is `root`
        # From one web app, 2026-09-23: its dashboard, served at `/`, was mapped as
        # `endpoint.unnamed`.
        print("\n17. a route's id is its path, and `/` is the root")
        y = os.path.join(tmp, "fifteen")
        os.makedirs(y)
        put(y, "app.py", "@app.route('/')\ndef home():\n    return render_template('i.html')\n")
        put(y, "pages/index.tsx", "export default function Home() { return null }\n")
        put(y, "pages/reindex.tsx", "export default function R() { return null }\n")
        put(y, "pages/blog/index.tsx", "export default function B() { return null }\n")
        run(y, "--init")
        mp = open(os.path.join(y, "FEATURE-MAP.md"), encoding="utf-8").read()
        check("a server route at `/` is endpoint.root",
              "`endpoint.root`" in mp and "endpoint.unnamed" not in mp, mp[-1500:])
        check("an index page at the top is route.root",
              "`route.root`" in mp and "route.unnamed" not in mp, mp[-1500:])
        check("`index` inside a page name is not stripped out of it",
              "`route.reindex`" in mp and "`route.re`" not in mp, mp[-1500:])
        check("a folder's index page is that folder's route",
              "`route.blog`" in mp, mp[-1500:])

        # ------------------------- 18 one id, several places: list them all
        # From one web app, 2026-09-23: `key.escape` is its look-up's Escape AND the
        # settings and report panels' global Escape; only the first was kept.
        print("\n18. an id found in several places lists every place")
        z = os.path.join(tmp, "sixteen")
        os.makedirs(z)
        put(z, "src/a.jsx", 'export const A = ({x}) => <button aria-label="Close" onClick={x}>x</button>;\n')
        put(z, "src/b.jsx", 'export const B = ({y}) => <button aria-label="Close" onClick={y}>y</button>;\n')
        put(z, "src/k.jsx",
            "const step = (key) => { if (key === 'Escape') return 1; return 0; };\n"
            "export const K = ({ close }) => {\n"
            "  useEffect(() => {\n"
            "    const onKey = (e) => { if (e.key === 'Escape') close(); };\n"
            "    document.addEventListener('keydown', onKey);\n"
            "  }, []);\n"
            "  return null;\n"
            "};\n")
        run(z, "--init")
        mp = open(os.path.join(z, "FEATURE-MAP.md"), encoding="utf-8").read()
        crow = [x for x in mp.split("\n") if "`control.close`" in x]
        krow = [x for x in mp.split("\n") if "`key.escape`" in x]
        check("a label used on two controls names both places",
              crow and "src/a.jsx:1" in crow[0] and "src/b.jsx:1" in crow[0],
              "\n".join(crow) or mp[-1500:])
        check("a key handled in two scopes of one file names both places",
              krow and "src/k.jsx:1" in krow[0] and "src/k.jsx:4" in krow[0],
              "\n".join(krow) or mp[-1500:])

        # --------------- 19 an authored id the code no longer derives
        # Found while fixing 1-6 for one web app: each fix renames ids it had
        # authored (endpoint.unnamed -> endpoint.root), and the old entry would
        # have stayed, pointing at a file that still exists, unflagged.
        print("\n19. an entry for an id the code no longer derives fails, with its successor")
        o = os.path.join(tmp, "seventeen")
        os.makedirs(o)
        put(o, "app.py", "@app.route('/')\ndef home():\n    return 'home'\n")
        put(o, "src/bar.jsx",
            "export const Bar = ({ go, toggle }) => {\n"
            "  useEffect(() => {\n"
            "    const onKey = (e) => {\n"
            "      if (!e.altKey) return;\n"
            "      if (e.key === 'p') toggle();\n"
            "    };\n"
            "    window.addEventListener('keydown', onKey);\n"
            "  }, []);\n"
            "  return (<div role=\"group\" aria-label=\"Ticker shortcuts\">\n"
            "    <button onClick={go}>AAPL</button></div>);\n"
            "};\n")
        run(o, "--init")
        author(o, (ENTRY % ("endpoint.unnamed", "home", "web-ui", "app.py:1",
                            "DRIVEN", "2099-01-01 @ abc1234"))
               + (ENTRY % ("control.ticker-shortcuts", "shortcuts", "web-ui",
                           "src/bar.jsx:9", "UNKNOWN", ""))
               + (ENTRY % ("key.p", "paulie", "web-ui", "src/bar.jsx:5",
                           "UNKNOWN", ""))
               + (ENTRY % ("ui.tour", "tour", "web-ui", "app.py:1", "UNKNOWN", ""))
               + "- unmapped_ceiling: 3\n")
        rc, out = run(o, "--check")
        section = out.split("no longer derives")[-1] if "no longer derives" in out else ""
        check("RED: an authored id the code no longer derives fails",
              rc == 1 and "endpoint.unnamed" in section, out)
        check("its successor is named: endpoint.unnamed -> endpoint.root",
              "endpoint.unnamed -> now endpoint.root?" in section, out)
        check("its successor is named: control.x -> region.x",
              "control.ticker-shortcuts -> now region.ticker-shortcuts?" in section, out)
        check("its successor is named: key.p -> key.alt-p",
              "key.p -> now key.alt-p?" in section, out)
        check("an entry mapped by hand outside the derived prefixes is left alone",
              "ui.tour" not in section, out)

        # ------------------------------ 20 a rule never counts its own text
        # Found 2026-09-23 while fixing one web app's blind spots: a clean tree
        # failed on `FEATURE-MAP.md:28 - signature: @retry_on_429`.
        print("\n20. a rule is not a violation of itself")
        u = os.path.join(tmp, "eighteen")
        os.makedirs(u)
        put(u, "api/handlers.py", "@retry_on_429\ndef fetch(x):\n    return get(x)\n")
        put(u, "services/orders.py", "def place(x):\n    return x\n")
        run(u, "--init")
        author(u, """### pattern: retry-only-at-the-edge

- rule: the 429 retry belongs on outbound calls only
- canonical: api/handlers.py:1
- signature: @retry_on_429
- only_in: api/*.py
- ceiling: 0

### pattern: no-debugger

- rule: a debugger statement left in halts every open devtools
- canonical: services/orders.py:1
- antipattern: debugger
- ceiling: 0
""")
        rc, out = run(u, "--check")
        check("a signature is not drift in the map that defines it",
              "DRIFTED" not in out, out)
        check("a plain-word anti-pattern is not spread in the map that defines it",
              "SPREAD" not in out, out)
        check("GREEN: a tree with no violation passes", rc == 0, out)

        # --------------------- 21 a route inside a string is not a route
        # This skill's own map counted `endpoint.health`, `.orders` and
        # `.refund` out of the fixture strings in this very file.
        print("\n21. a route decorator inside a string is not a route")
        t21 = os.path.join(tmp, "nineteen")
        os.makedirs(t21)
        put(t21, "app.py", "@app.route('/real')\ndef real():\n    return 'x'\n")
        put(t21, "tests/test_app.py",
            'FIXTURE = """\n@app.route(\'/ghost\')\ndef ghost():\n    return 1\n"""\n'
            'ONE = "@app.route(\'/phantom\')"\n')
        put(t21, "legacy.py", "print 'old'\n@app.route('/old')\ndef old():\n    return 1\n")
        run(t21, "--init")
        mp = open(os.path.join(t21, "FEATURE-MAP.md"), encoding="utf-8").read()
        check("a real route is found", "`endpoint.real`" in mp, mp[-1500:])
        check("a route inside a string is not",
              "ghost" not in mp and "phantom" not in mp, mp[-1500:])
        check("a file that does not parse is still read, by the pattern",
              "`endpoint.old`" in mp, mp[-1500:])

        # --------------------- 22 every capability has a face
        # The requirement: map it from both the user's face and the development face.
        print("\n22. every derived capability carries a user or dev face")
        t22 = os.path.join(tmp, "twentytwo")
        os.makedirs(t22)
        put(t22, "app.py",
            "from flask import render_template\n"
            "@app.route('/chat', methods=['POST'])\ndef chat():\n    return 'x'\n"
            "@app.route('/health')\ndef health():\n    return 'ok'\n"
            "@app.route('/page')\ndef page():\n    return render_template('p.html')\n"
            "@app.route('/api/stock/<ticker>')\ndef stock(ticker):\n    return ticker\n"
            "@app.route('/<ticker>')\ndef bare(ticker):\n    return ticker\n"
            "@app.route('/<path:ticker>/frame/today')\n"
            "def frame(ticker):\n    return ticker\n")
        put(t22, "server.js", "app.get('/internal', (q, s) => s.send('x'))\n")
        put(t22, "static/app.jsx",
            "fetch('/chat', {method: 'POST'})\n"
            "fetch(`/api/stock/${t}`)\n"
            "go(`/${enc}/frame/today`)\n"
            "const b = <button aria-label=\"Send\" onClick={go}>go</button>\n")
        put(t22, "tests/test_app.js", "fetch('/health')\n")
        put(t22, "cli.py", "import argparse\np = argparse.ArgumentParser()\n"
            "p.add_argument('--verbose')\n")
        put(t22, "package.json", '{"scripts": {"build": "x"}}\n')
        run(t22, "--init")
        mp = open(os.path.join(t22, "FEATURE-MAP.md"), encoding="utf-8").read()
        import re as _re

        def face(fid):
            m = _re.search(r"^\| `%s` \| (\w+) \|" % _re.escape(fid), mp, _re.M)
            return m.group(1) if m else None
        check("an API endpoint a screen calls is user face",
              face("endpoint.chat") == "user", mp[-2500:])
        check("...and the row names the file and line that calls it",
              "called from static/app.jsx:1" in mp, mp[-2500:])
        check("a parameterized endpoint called with a template is user face",
              face("endpoint.api-stock-ticker") == "user", mp[-2500:])
        check("an endpoint only a test calls is dev face",
              face("endpoint.health") == "dev", mp[-2500:])
        check("an endpoint defined in a server file is not called by that file",
              face("endpoint.internal") == "dev", mp[-2500:])
        check("a page that renders is user face", face("endpoint.page") == "user",
              mp[-2500:])
        check("a path with no fixed part is unclassified, not guessed",
              face("endpoint.ticker") == "unclassified", mp[-2500:])
        check("a fixed part after the parameter is still looked for",
              face("endpoint.path-ticker-frame-today") == "user", mp[-2500:])
        check("a control is user face", face("control.send") == "user", mp[-2500:])
        check("a CLI flag and an npm script are dev face",
              face("cli.verbose") == "dev" and face("script.build") == "dev",
              mp[-2500:])
        rc, out = run(t22, "--check")
        check("--check counts the map by face",
              "user 5, dev 4, unclassified 1" in out, out)

        # --------------------- 23 a route that serves an HTML file is a page
        # One web app's dashboard and landing page read their .html themselves, and
        # were mapped as APIs no screen calls - dev face, for the front door.
        print("\n23. a route that returns an HTML file is a page, not an API")
        t23 = os.path.join(tmp, "twentythree")
        os.makedirs(t23)
        put(t23, "app.py",
            "import os, json" + "\n"
            "@app.route('/')\ndef index():\n"
            "    with open(os.path.join(HERE, 'index.html')) as f:\n"
            "        return f.read()\n"
            "@app.route('/data')\ndef data():\n    return json.dumps({})\n")
        run(t23, "--init")
        mp = open(os.path.join(t23, "FEATURE-MAP.md"), encoding="utf-8").read()
        check("the route serving index.html is a web-ui page on the user face",
              "| `endpoint.root` | user | web-ui |" in mp, mp[-1500:])
        check("the route returning data is still an API",
              "| `endpoint.data` | dev | api |" in mp, mp[-1500:])

        # --------------------- 24 the dev face: settings, deploys, CI
        # Names only: a value in a deploy config is never read or printed.
        print("\n24. the dev face - environment names, deploy services, CI")
        t24 = os.path.join(tmp, "twentyfour")
        os.makedirs(t24)
        put(t24, "app.py", "import os\n"
            "DATA = os.environ.get('APP_DATA_DIR', '/tmp')\n"
            "KEY = os.environ['API_KEY']\n"
            "FIX = \"os.environ.get('GHOST')\"\n")
        put(t24, "web/client.js", "const u = process.env.PUBLIC_URL;\n"
            "const v = import.meta.env.VITE_MODE;\n")
        put(t24, "tests/test_app.py", "import os\nos.environ.get('TEST_ONLY')\n")
        put(t24, "render.yaml", "services:\n  - type: web\n    name: shop\n"
            "    healthCheckPath: /health\n    envVars:\n"
            "      - key: APP_DATA_DIR\n        value: /data\n"
            "      - key: PYTHON_VERSION\n        value: sk-live-DO-NOT-PRINT\n")
        put(t24, "Procfile", "web: gunicorn app:app --bind 0.0.0.0:$PORT\n")
        put(t24, ".github/workflows/test.yml", "name: tests\non: [push]\njobs: {}\n")
        run(t24, "--init")
        mp = open(os.path.join(t24, "FEATURE-MAP.md"), encoding="utf-8").read()

        def row(fid):
            m = _re.search(r"^\| `%s` \|.*$" % _re.escape(fid), mp, _re.M)
            return m.group(0) if m else ""
        check("an environment variable the code reads is a dev-face id",
              "| dev | config |" in row("env.app-data-dir"), mp[-3000:])
        check("...and the row says the deploy config declares it",
              "declared in render.yaml (service shop)" in row("env.app-data-dir"),
              row("env.app-data-dir"))
        check("a variable the deploy config does not declare says so",
              "not declared in render.yaml" in row("env.api-key"), row("env.api-key"))
        check("node and vite reads are found",
              row("env.public-url") and row("env.vite-mode"), mp[-3000:])
        check("a read inside a string is not a read, and a test's variable is not "
              "the app's", "env.ghost" not in mp and "env.test-only" not in mp,
              mp[-3000:])
        check("the render service is a dev-face deploy id",
              "| dev | deploy |" in row("deploy.shop"), mp[-3000:])
        check("...naming what it declares that no code reads",
              "declared but read by no code: PYTHON_VERSION" in row("deploy.shop"),
              row("deploy.shop"))
        check("a Procfile process and a CI workflow are mapped",
              row("deploy.web") and "GitHub workflow tests on [push]" in row("ci.test"),
              mp[-3000:])
        rc, out = run(t24, "--check")
        check("NO value from a deploy config reaches the map or the report",
              "DO-NOT-PRINT" not in mp and "DO-NOT-PRINT" not in out, out)

        # A project that is a folder inside its repository, as one web app is: the
        # render.yaml at the top governs it only through its rootDir.
        t24b = os.path.join(tmp, "twentyfourb")
        os.makedirs(t24b)
        put(t24b, "render.yaml", "services:\n  - type: web\n    name: api\n"
            "    rootDir: app\n  - type: worker\n    name: other\n"
            "    rootDir: elsewhere\n")
        put(t24b, "app/main.py", "print(1)\n")
        git(t24b, "init", "-q")
        commit(t24b, "c1")
        run(os.path.join(t24b, "app"), "--init")
        mp = open(os.path.join(t24b, "app", "FEATURE-MAP.md"), encoding="utf-8").read()
        check("the repository's render.yaml is read through its rootDir",
              "`deploy.api`" in mp and "`../render.yaml:2`" in mp, mp[-1500:])
        check("a service for another folder is not this project's",
              "deploy.other" not in mp, mp[-1500:])

        # --------------------- 25 a flag inside a string is not a flag
        print("\n25. an argparse flag inside a string is not a flag")
        t25 = os.path.join(tmp, "twentyfive")
        os.makedirs(t25)
        put(t25, "tool.py", "import argparse\nap = argparse.ArgumentParser()\n"
            "ap.add_argument('-q', '--quiet')\n")
        put(t25, "tests/test_tool.py",
            "FIXTURE = \"ap.add_argument('--ghost')\"\nimport argparse\n")
        put(t25, "old.py", "print 'x'\nap.add_argument('--legacy')\n")
        run(t25, "--init")
        mp = open(os.path.join(t25, "FEATURE-MAP.md"), encoding="utf-8").read()
        check("a real flag is found, even after its short form",
              "`cli.quiet`" in mp, mp[-1500:])
        check("a flag inside a string is not", "ghost" not in mp, mp[-1500:])
        check("a file that does not parse is still read, by the pattern",
              "`cli.legacy`" in mp, mp[-1500:])

        # --------------------- 26 any branch, any commit, side by side
        # The requirement: map it retroactively, and across any branches that
        # exist, for comparison's sake. Read out of git; the tree is untouched.
        print("\n26. --list and --compare read any ref without checking it out")
        t26 = os.path.join(tmp, "twentysix")
        os.makedirs(t26)
        put(t26, "app.py", "@app.route('/alpha')\ndef alpha():\n    return 1\n"
            "@app.route('/beta')\ndef beta():\n    return 1\n")
        run(t26, "--init")
        author(t26, ENTRY % ("endpoint.alpha", "a", "api", "app.py:1", "UNKNOWN", ""))
        git(t26, "init", "-q")
        commit(t26, "c1")
        c1 = head(t26)
        put(t26, "app.py", "@app.route('/alpha')\ndef alpha():\n    return 1\n"
            "@app.route('/gamma')\ndef gamma():\n    return 1\n")
        put(t26, "static/app.jsx", "fetch('/alpha')\n")
        author(t26, ENTRY % ("endpoint.alpha", "a", "api", "app.py:1", "DRIVEN",
                             "2026-09-23 @ " + c1))
        commit(t26, "c2")
        c2 = head(t26)
        put(t26, "app.py", "@app.route('/alpha')\ndef alpha():\n    return 1\n"
            "@app.route('/gamma')\ndef gamma():\n    return 1\n"
            "@app.route('/delta')\ndef delta():\n    return 1\n")
        before = subprocess.run(("git", "status", "--porcelain"), cwd=t26,
                                capture_output=True).stdout

        rc, out = run(t26, "--list", "--ref", c1)
        check("--list --ref reads the map as it stood at that commit",
              rc == 0 and "endpoint.beta" in out and "endpoint.gamma" not in out, out)
        rc, out = run(t26, "--list")
        check("--list without a ref is the working tree, uncommitted work included",
              "endpoint.delta" in out and "DRIVEN" in out, out)
        rc, out = run(t26, "--compare", c1, c2)
        check("--compare names what was added and removed between two refs",
              "+ endpoint.gamma" in out and "- endpoint.beta" in out, out)
        check("...a capability whose face changed",
              "endpoint.alpha" in out and "face dev -> user" in out, out)
        check("...and an entry whose grade changed",
              "grade UNKNOWN -> DRIVEN" in out, out)
        rc, out = run(t26, "--compare", c2)
        check("one ref compares against the working tree",
              "+ endpoint.delta" in out and "working tree" in out, out)
        rc, out = run(t26, "--compare", "no-such-branch")
        check("a ref that does not exist is refused, not read as empty",
              rc == 2 and "REFUSED" in out, out)
        rc, out = run(t26, "--list", "--json")
        import json as _json
        try:
            data = _json.loads(out)
        except ValueError:
            data = {}
        check("--list --json is machine-readable, with counts by face",
              data.get("counts", {}).get("user") == 1
              and data.get("counts", {}).get("dev") == 2, out[:600])
        after = subprocess.run(("git", "status", "--porcelain"), cwd=t26,
                               capture_output=True).stdout
        check("reading refs left the working tree and the index as they were",
              before == after, "%r -> %r" % (before, after))
        rc, out = run(os.path.join(t24b, "app"), "--list", "--ref", "HEAD")
        check("a folder project read at a ref still sees the repository's deploy file",
              "deploy.api" in out, out)

        # --------------------- 27 what production actually serves
        # The requirement: reflect what is live. Production is asked narrowly - GET only,
        # declared paths only, redirects never followed - and what it serves
        # is placed in git by the blob of a file it serves verbatim.
        print("\n27. --live asks production, narrowly, and places it in git")
        import http.server
        import threading
        seen, serve = [], {}

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.path)
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "http://example.invalid/x")
                    self.end_headers()
                    return
                code, body = serve.get(self.path, (404, b"no"))
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                seen.append("POST " + self.path)
                self.send_response(405)
                self.end_headers()

            def log_message(self, *args):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        try:
            t27 = os.path.join(tmp, "twentyseven")
            os.makedirs(t27)
            routes = ""
            for step, name in enumerate(("alpha", "beta", "gamma", "delta")):
                routes += "@app.route('/%s')\ndef %s():\n    return 1\n" % (name, name)
                put(t27, "app.py", routes)
                if step == 0:
                    put(t27, "static/app.js", "// v1\n")
                    run(t27, "--init")
                    git(t27, "init", "-q")
                    commit(t27, "c1")
                    branch = subprocess.run(
                        ("git", "rev-parse", "--abbrev-ref", "HEAD"), cwd=t27,
                        capture_output=True).stdout.decode().strip()
                    author(t27, "### live.production\n\n- name: production\n"
                           "- url: %s\n- fingerprint: static/app.js\n"
                           "- probes: /health, /redirect\n- branch: %s\n\n"
                           "### ui.danger\n\n- name: danger\n- code: app.py:1\n"
                           "- entry: /cache/clear\n" % (base, branch))
                elif step == 1:
                    put(t27, "static/app.js", "// v2\n")
                    commit(t27, "c2")
                elif step == 2:
                    commit(t27, "c3")
            serve.update({"/health": (200, b"ok"), "/static/app.js": (200, b"// v1\n")})
            rc, out = run(t27, "--live")
            check("production serving an older bundle is found BEHIND, and says so",
                  rc == 0 and "production is BEHIND" in out, out)
            check("...listing what the working tree has that production cannot",
                  "+ endpoint.beta" in out and "+ endpoint.delta" in out, out)
            check("a redirect is reported and never followed",
                  "redirect to http://example.invalid/x, not followed" in out, out)
            check("ONLY declared paths were requested, and nothing but GET",
                  set(seen) <= {"/health", "/redirect", "/static/app.js"}
                  and "/cache/clear" not in seen, repr(seen))
            serve["/static/app.js"] = (200, b"// v2\n")
            rc, out = run(t27, "--live")
            check("production serving the branch's current bundle is placed at it",
                  rc == 0 and "last changed it" in out and "+ endpoint.delta" in out
                  and "+ endpoint.beta" not in out, out)
            rc, out = run(t27, "--live", "--url", base, "--fingerprint",
                          "static/app.js", "--probe", "/health", "--branch", branch)
            check("the same check runs from the command line alone",
                  rc == 0 and "last changed it" in out, out)
            serve["/static/app.js"] = (200, b"// v9\n")
            rc, out = run(t27, "--live")
            check("a bundle no commit carries is UNKNOWN and fails, never guessed",
                  rc == 1 and "UNKNOWN" in out, out)
            serve.update({"/static/app.js": (200, b"// v2\n"),
                          "/health": (500, b"down")})
            rc, out = run(t27, "--live")
            check("a failing health probe fails the check",
                  rc == 1 and "/health" in out and "500" in out, out)
            serve["/health"] = (200, b"ok")
            rc, out = run(t27, "--live", "--url", base, "--fingerprint",
                          "static/app.js", "--probe", "C:/Program Files/Git/health",
                          "--branch", branch)
            check("a probe the shell rewrote into a Windows path is refused, not a "
                  "traceback", rc == 1 and "REFUSED probe" in out
                  and "Traceback" not in out, out)
            git(t27, "remote", "add", "origin", t27)
            git(t27, "fetch", "-q", "origin")
            rc, out = run(t27, "--live")
            check("against a remote branch it says when that was last fetched",
                  rc == 0 and "as last fetched here" in out, out)
            os.utime(os.path.join(t27, ".git", "FETCH_HEAD"), (1577880000, 1577880000))
            t27w = os.path.join(tmp, "twentyseven-worktree")
            git(t27, "worktree", "add", "-q", "-b", "wt", t27w)
            git(t27w, "fetch", "-q", "origin")
            rc, out = run(t27w, "--live")
            check("in a worktree, a fetch made there counts - not only the shared one",
                  "as last fetched here" in out and "2020-01-01" not in out, out)
        finally:
            srv.shutdown()
        rc, out = run(t26, "--live")
        check("with no live environment declared it refuses, and says how",
              rc == 2 and "REFUSED nothing declares" in out, out)

        # ------------------------------------------- 28 judged by Jev, safely
        # The Intended bar - does the observable speak to what was asked for -
        # goes to Jev through the one client that pins the model, refuses index
        # paths, asks everything in one request and never prints the key. A fake
        # service on this machine stands in for TypeSafe: this proves what is
        # SENT and what is done with the answer, never what Jev would say. The
        # client's own rules - retries, the key file, the endpoint, the lint -
        # are the client's own, tested with the client.
        print("\n28. --judge asks Jev once, pinned, and never shows the key")
        posts, reply = [], {"p": {}}

        class J(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(
                    int(self.headers.get("Content-Length") or 0)).decode("utf-8"))
                posts.append((self.headers.get("Authorization"), body))
                if reply.get("fail"):
                    self.send_response(reply["fail"].pop(0))
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                out = json.dumps({
                    "model": reply.get("model", body["model"]),
                    "answers": {q: {"type": "noul", "noul": reply["p"].get(q, 0.5)}
                                for q in body["questions"]},
                    "usage": {"input_tokens": 42, "output_tokens": 3}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *args):
                pass

        jsrv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), J)
        threading.Thread(target=jsrv.serve_forever, daemon=True).start()
        # A home of the test's own: this machine's real key sits in
        # ~/.agents/.env, and no test may ever read it.
        home28 = os.path.join(tmp, "home28")
        os.makedirs(os.path.join(home28, ".agents"))
        fake = dict(os.environ, TYPESAFE_API_KEY="test-key-not-real",
                    JEV_ENDPOINT="http://127.0.0.1:%d/v1/systemone"
                    % jsrv.server_address[1], USERPROFILE=home28, HOME=home28)
        nokey = dict(fake)
        del nokey["TYPESAFE_API_KEY"]
        try:
            if not CLIENT:
                raise _NoClient
            t28 = os.path.join(tmp, "twentyeight")
            os.makedirs(t28)
            put(t28, "app.py", APP_V1)
            run(t28, "--init")
            intents = {
                "endpoint.orders": "a customer can place an order and find it in "
                                   "their order history",
                "endpoint.health": "the operator can tell the whole service works, not just "
                                   "that it answers",
                "endpoint.search": "a search returns the matching records first"}
            obs = {"endpoint.orders": "GET /orders/history lists the new order",
                   "endpoint.health": "GET /health returns 200",
                   "endpoint.search": "the first result's title contains the query"}
            body = ""
            for fid in sorted(intents):
                body += "### %s\n\n- name: %s\n- intent: %s\n- observable: %s\n\n" % (
                    fid, fid, intents[fid], obs[fid])
            author(t28, body + "### ui.banner\n\n- name: banner\n- intent: the "
                   "banner warns in red\n- observable: the banner color is "
                   "#ff0000\n\n### ui.bare\n\n- name: bare\n- observable: x\n")
            rc, out = run(t28, "--judge", env=nokey)
            check("with no key nothing is asked, and it says what went unjudged",
                  rc == 2 and "NOT JUDGED" in out and "TYPESAFE_API_KEY is not set"
                  in out and not posts, out)
            reply["p"] = {"endpoint.orders": 0.9, "endpoint.health": 0.1}
            rc, out = run(t28, "--judge", env=fake)
            sent = posts[-1][1] if posts else {}
            check("every entry is asked in ONE request, to the pinned model",
                  rc == 0 and len(posts) == 1 and sent.get("model") == "jev-1.13.0",
                  out + repr(posts)[:400])
            check("...each question carries its own entry's text inline, never an "
                  "index into state",
                  sorted(sent.get("questions", {})) == sorted(intents) and all(
                      q["instructions"]["intent"] == intents[k]
                      and q["instructions"]["observable"] == obs[k]
                      for k, q in sent["questions"].items())
                  and "[" not in json.dumps(sent), json.dumps(sent)[:600])
            check("the key travels only in the header and is never printed",
                  bool(posts) and posts[-1][0] == "Bearer test-key-not-real"
                  and "test-key-not-real" not in out, out)
            low = out.split("may NOT show", 1)[-1].split("torn", 1)[0]
            check("a low reading is listed as possibly missing the intent - a "
                  "reading, not a failure",
                  rc == 0 and "may NOT show" in out and "endpoint.health" in low
                  and "0.10" in low, out)
            check("...a torn one is left for a person to read; a high one is shown",
                  "torn (" in out and "endpoint.search" in out.split("torn (", 1)[-1].split(
                      "shows the intent", 1)[0] and "endpoint.orders 0.90" in out, out)
            check("an entry carrying a literal Jev cannot read is not asked, by name",
                  "not judged ui.banner" in out.replace("  ", " ")
                  and "hex, RGB or binary" in out, out)
            check("an entry with nothing to judge is counted, not silently dropped",
                  "1 authored entry/entries carry no intent" in out, out)
            reply["model"] = "jev-1.14.0"
            rc, out = run(t28, "--judge", env=fake)
            check("an answer from any model but the pin is refused, not used",
                  rc == 2 and "REFUSED" in out and "answered by" in out
                  and "0.90" not in out, out)
            del reply["model"]
            # From 2026-09-24 07:50: --judge on a map fresh from --init sent the
            # template's example.id to TypeSafe as if it were an entry - one
            # real request, 387 input tokens of placeholder text.
            print("    ...and the template's own placeholder is never asked")
            t28b = os.path.join(tmp, "twentyeight-b")
            os.makedirs(t28b)
            put(t28b, "app.py", APP_V1)
            run(t28b, "--init")
            n = len(posts)
            rc, out = run(t28b, "--judge", env=fake)
            check("a fresh map's example entry is not sent, and it says so",
                  rc == 0 and len(posts) == n and "not judged example.id" in out
                  and "placeholder" in out, out)
            tpl = open(os.path.join(HERE, os.pardir, "templates", "FEATURE-MAP.md"),
                       encoding="utf-8").read()
            ph = [x for x in tpl.split("### example.id", 1)[1].split("\n")
                  if x.startswith(("- intent:", "- observable:"))]
            author(t28b, "### cli.copied\n\n- name: copied\n" + "\n".join(ph)
                   + "\n\n### endpoint.orders\n\n- name: orders\n- intent: %s\n"
                   "- observable: %s\n" % (intents["endpoint.orders"],
                                           obs["endpoint.orders"]))
            rc, out = run(t28b, "--judge", env=fake)
            sent = posts[-1][1] if len(posts) > n else {}
            check("...nor its text copied under a real id, while a real entry "
                  "beside it is asked", rc == 0 and len(ph) == 2
                  and len(posts) == n + 1
                  and sorted(sent.get("questions", {})) == ["endpoint.orders"]
                  and "not judged cli.copied" in out, out + repr(sent)[:300])
            # A map begun from an older template carries older placeholder
            # wording, so the example's id is matched too, not only its text.
            author(t28b, "### example.id\n\n- name: what a user would call it\n"
                   "- intent: the operator's words, as an older template put it\n"
                   "- observable: what you read back, as an older template put it\n")
            n = len(posts)
            rc, out = run(t28b, "--judge", env=fake)
            check("...nor an example left from an older template's wording",
                  rc == 0 and len(posts) == n and "not judged example.id" in out, out)
            # The client's own tests hold its rules. Without a client beside
            # this skill,
            # --judge must say so and ask nothing - never fall back to a copy.
            lonely = os.path.join(tmp, "lonely", "verafox", "scripts")
            os.makedirs(lonely)
            shutil.copy(FM, lonely)
            n = len(posts)
            p = subprocess.run([sys.executable, os.path.join(lonely, "featuremap.py"),
                                "--project", t28, "--judge"], capture_output=True,
                               timeout=120, env=fake)
            out = p.stdout.decode("utf-8", "replace")
            check("without a Jev client beside it, --judge asks nothing and says why",
                  p.returncode == 2 and "NOT JUDGED the optional Jev client (not "
                  "included) is not installed" in out and len(posts) == n, out)
            # With a client beside it, --judge must reach it.
            home = os.path.join(tmp, "clienthome")
            os.makedirs(os.path.join(home, "verafox", "scripts"))
            shutil.copy(FM, os.path.join(home, "verafox", "scripts"))
            shutil.copytree(os.path.join(HERE, os.pardir, os.pardir, "jev-client", "scripts"),
                            os.path.join(home, "jev-client", "scripts"),
                            ignore=shutil.ignore_patterns("__pycache__"))
            n = len(posts)
            p = subprocess.run([sys.executable, os.path.join(home, "verafox", "scripts",
                                "featuremap.py"), "--project", t28, "--judge"],
                               capture_output=True, timeout=120, env=fake)
            out = p.stdout.decode("utf-8", "replace")
            check("with a Jev client beside it, --judge asks through it",
                  p.returncode == 0 and len(posts) == n + 1, out)
            # One client, in one place: a copy here would be a second client to drift.
            check("this skill carries no copy of the Jev client",
                  not os.path.exists(os.path.join(HERE, "jev.py")),
                  "found %s" % os.path.join(HERE, "jev.py"))
        except _NoClient:
            NOT_RUN.append("28")
        finally:
            jsrv.shutdown()

        # ------------------------------ 29 environment names through constants
        # Found on a Jev client: `KEY_ENV = "TYPESAFE_API_KEY"`,
        # then `os.environ.get(KEY_ENV)`, and the dev face never listed the key.
        print("\n29. a read through a module constant is still that name")
        t29 = os.path.join(tmp, "twentynine")
        os.makedirs(t29)
        put(t29, "client.py", "import os\nKEY_ENV = \"SERVICE_TOKEN\"\n"
            "A, B = \"REGION_NAME\", \"ZONE_NAME\"\nTWICE = \"FIRST_NAME\"\n"
            "TWICE = \"SECOND_NAME\"\n\n\ndef key():\n"
            "    return (os.environ.get(KEY_ENV, \"\"), os.getenv(B),\n"
            "            os.environ.get(TWICE))\n")
        run(t29, "--init")
        mp = open(os.path.join(t29, "FEATURE-MAP.md"), encoding="utf-8").read()
        check("a read through a constant is derived under the constant's value, "
              "and says which constant", "(via KEY_ENV)" in row("env.service-token"),
              mp[-1500:])
        check("...a tuple-assigned constant too", row("env.zone-name"), mp[-1500:])
        check("...but a name assigned twice is not guessed at",
              "env.first-name" not in mp and "env.second-name" not in mp, mp[-1500:])

        # ------------------------------ 30 what a ref snapshot cannot see is said
        # Found while writing the bound for --ref: git archive honors
        # export-ignore, and a route in such a file vanished without a word.
        print("\n30. a file git archive leaves out is named, never silently skipped")
        t30 = os.path.join(tmp, "thirty")
        os.makedirs(t30)
        put(t30, "app.py", APP_V1)
        put(t30, "extra.py", "from app import app\n\n\n@app.route('/hidden')\n"
            "def hidden():\n    return 1\n")
        put(t30, ".gitattributes", "extra.py export-ignore\n")
        git(t30, "init", "-q")
        commit(t30, "c1")
        rc, out = run(t30, "--list", "--ref", "HEAD")
        check("a ref snapshot names the file it could not measure",
              rc == 0 and "not exported" in out and "extra.py" in out
              and "endpoint.hidden" not in out, out)
        p = subprocess.run([sys.executable, FM, "--project", t30, "--list", "--ref",
                            "HEAD", "--json"], cwd=t30, capture_output=True, timeout=120)
        try:
            listed = json.loads(p.stdout.decode("utf-8"))
        except ValueError:
            listed = None
        check("...and the note never corrupts --json",
              listed is not None and "not exported" in p.stderr.decode("utf-8", "replace"),
              p.stdout.decode("utf-8", "replace")[:300])

        # ------------------------------ 31 every unverified entry, by name
        # From KiT, 2026-09-24: 45 entries were unverified and --check listed
        # 40 under "listed by name, never rounded" - five cut without a count.
        print("\n31. the unverified list names every entry, however many there are")
        t31 = os.path.join(tmp, "thirtyone")
        os.makedirs(t31)
        put(t31, "app.py", APP_V1)
        run(t31, "--init")
        author(t31, (ENTRY % ("endpoint.health", "health", "api", "app.py:4",
                              "DRIVEN", "2099-01-01 @ abc1234"))
               + (ENTRY % ("endpoint.orders", "orders", "api", "app.py:8",
                           "DRIVEN", "2099-01-01 @ abc1234"))
               + "".join("### ui.thing-%02d\n\n- grade: %s\n\n"
                         % (i, "UNKNOWN" if i % 9 == 0 else "ASSERTED")
                         for i in range(45)))
        rc, out = run(t31, "--check")
        missing = [i for i in range(45) if "ui.thing-%02d " % i not in out]
        check("all 45 unverified entries are named, the 41st to 45th included",
              rc == 0 and "ASSERTED 40, UNKNOWN 5" in out and not missing,
              "missing: %s\n%s" % (missing, out))

        # ------------------------------ 32 a negated modifier is not demanded
        # Found fixing KiT's landing page, 2026-09-24: `!e.altKey &&` was read
        # as `e.altKey &&`, so Ctrl+Shift+D was minted as Ctrl+Alt+Shift+D.
        print("\n32. `!e.altKey &&` rules Alt out; it does not demand it")
        t32 = os.path.join(tmp, "thirtytwo")
        os.makedirs(t32)
        put(t32, "keys.js",
            "document.addEventListener('keydown', (e) => {\n"
            "  if (e.ctrlKey && e.shiftKey && !e.altKey && e.key === 'd') dark();\n"
            "  if (e.ctrlKey && ! e.metaKey && e.key === 's') save();\n"
            "});\n")
        run(t32, "--init")
        mp = open(os.path.join(t32, "FEATURE-MAP.md"), encoding="utf-8").read()
        check("a negated modifier is left out of the shortcut",
              "`key.ctrl-shift-d`" in mp and "`key.ctrl-s`" in mp
              and "alt-" not in mp and "meta-" not in mp,
              "\n".join(x for x in mp.split("\n") if x.startswith("| `key.")))

        # ------------------------------ 33 a branch is not a second shortcut
        # Found fixing KiT's landing page, 2026-09-24: inside the Ctrl+Shift+D/K
        # block, `set(k === "d" ? ...)` picks the branch - and was minted as a
        # bare D shortcut that does not exist.
        print("\n33. a key tested again inside its own shortcut's block is that "
              "shortcut")
        t33 = os.path.join(tmp, "thirtythree")
        os.makedirs(t33)
        put(t33, "keys.js",
            "document.addEventListener('keydown', (e) => {\n"
            "  if (e.ctrlKey && (e.key === 'd' || e.key === 'k')) {\n"
            "    e.preventDefault();\n"
            "    set(e.key === 'd' ? 'light' : 'night');\n"
            "    return;\n"
            "  }\n"
            "  if ((e.key === 'ArrowUp' || e.key === 'ArrowDown') && !busy) {\n"
            "    move(e.key === 'ArrowUp' ? -1 : 1);\n"
            "  }\n"
            "  if (e.key === 'l') set('light');\n"
            "});\n")
        run(t33, "--init")
        mp = open(os.path.join(t33, "FEATURE-MAP.md"), encoding="utf-8").read()
        keys33 = "\n".join(x for x in mp.split("\n") if x.startswith("| `key."))
        check("the branch inside a shortcut's block mints no shortcut of its own",
              "`key.d`" not in mp and "`key.arrowup`" not in mp, keys33)
        check("...while the shortcuts themselves, and the one after the block, "
              "are all found", "`key.ctrl-d-or-k`" in mp
              and "`key.arrowup-or-arrowdown`" in mp and "`key.l`" in mp, keys33)

        # ------------------------------ 34 a key read into a local first
        # From KiT's landing page, 2026-09-24:
        # `const k = e.key.toLowerCase()`, then `k === "l"` - no key. row at all.
        print("\n34. a shortcut tested through a local variable is still found")
        t34 = os.path.join(tmp, "thirtyfour")
        os.makedirs(t34)
        put(t34, "site/src/pages/index.astro",
            "---\nconst title = 'x';\n---\n<div id=\"screen\"></div>\n<script>\n"
            "  let mode = 'light';\n"
            "  document.addEventListener(\"keydown\", (e) => {\n"
            "    const t = e.target as HTMLElement;\n"
            "    if (t && /input|textarea|select/i.test(t.tagName)) return;\n"
            "    const k = e.key.toLowerCase();\n"
            "    if (e.ctrlKey && e.shiftKey && !e.altKey && (k === \"d\" || k === \"k\")) {\n"
            "      e.preventDefault();\n"
            "      set(k === \"d\" ? \"light\" : \"night\");\n"
            "      return;\n"
            "    }\n"
            "    if (e.ctrlKey || e.altKey || e.metaKey) return;\n"
            "    if (k === \"l\") set(\"light\");\n"
            "    else if (k === \"o\") set(\"off\");\n"
            "    else if (k === \"n\" && mode !== \"night\") set(\"night\");\n"
            "    else if (mode === \"night\" && ![\"tab\", \"shift\"].includes(k)) set(\"light\");\n"
            "  });\n"
            "  const pick = (k) => (k === \"q\" ? 1 : 0);\n"
            "</script>\n")
        run(t34, "--init")
        mp = open(os.path.join(t34, "FEATURE-MAP.md"), encoding="utf-8").read()
        keys34 = "\n".join(x for x in mp.split("\n") if x.startswith("| `key."))
        check("every key tested through the local is derived, with its modifiers",
              all(("`%s`" % i) in mp for i in ("key.ctrl-shift-d-or-k", "key.l",
                                               "key.o", "key.n")), keys34)
        check("...and says it was read through that local",
              "(tested as k)" in keys34, keys34)
        check("...but a `k` outside the listener that defines it is not a key",
              "`key.q`" not in mp and "`key.d`" not in mp, keys34)

        # ------------------------------ 35 a desktop GUI is a user surface
        # From KiT, 2026-09-24: a Tk control bar, a pystray tray menu and
        # RegisterHotKey chords derived nothing, and --check printed "every
        # surface file parsed" over them.
        print("\n35. a desktop GUI no extractor reads is reported UNPARSED")
        t35 = os.path.join(tmp, "thirtyfive")
        os.makedirs(t35)
        put(t35, "app.py", APP_V1)
        put(t35, "gui/bar.py", "import tkinter as tk\n\n\nclass Bar(tk.Frame):\n"
            "    pass\n")
        put(t35, "gui/tray.py", "from pystray import Menu, MenuItem\n\n"
            "MENU = Menu(MenuItem('Light', None))\n")
        put(t35, "gui/keys.py", "import ctypes\n\nuser32 = ctypes.windll.user32\n\n\n"
            "def bind(h):\n    return user32.RegisterHotKey(h, 1, 6, 0x44)\n")
        # Claimed by the argparse extractor - which read its flag, not its window.
        put(t35, "gui/launch.py", "import argparse\nimport tkinter.messagebox as mb\n"
            "p = argparse.ArgumentParser()\np.add_argument('--tray')\n")
        put(t35, "gui/notes.py", '"""No RegisterHotKey for bare Escape; tkinter '
            'is imported lazily."""\nX = "import pystray"\n')
        put(t35, "tests/test_bar.py", "import tkinter\n")
        run(t35, "--init")
        entries35 = ((ENTRY % ("endpoint.health", "health", "api", "app.py:4",
                               "DRIVEN", "2099-01-01 @ abc1234"))
                     + (ENTRY % ("endpoint.orders", "orders", "api", "app.py:8",
                                 "DRIVEN", "2099-01-01 @ abc1234"))
                     + (ENTRY % ("cli.tray", "tray", "cli", "gui/launch.py:4",
                                 "DRIVEN", "2099-01-01 @ abc1234")))
        author(t35, entries35)
        rc, out = run(t35, "--check")
        gui = ("gui/bar.py", "gui/tray.py", "gui/keys.py", "gui/launch.py")
        check("RED: every file that imports tkinter or pystray, or calls "
              "RegisterHotKey, is named UNPARSED",
              rc == 1 and all(g in out for g in gui), out)
        check("...with the reason, so a stranger knows why a .py counts",
              "imports tkinter" in out and "imports pystray" in out
              and "calls RegisterHotKey" in out, out)
        check("...but not a file that only names them in a string, nor a test",
              "gui/notes.py" not in out and "test_bar.py" not in out, out)
        mp = open(os.path.join(t35, "FEATURE-MAP.md"), encoding="utf-8").read()
        check("...and the map's UNPARSED list carries them too",
              "UNPARSED" in mp and "`gui/tray.py`" in mp, mp[-1500:])
        author(t35, entries35 + "- unparsed_accepted: " + ", ".join(gui) + "\n")
        rc, out = run(t35, "--check")
        check("GREEN: mapped by hand and accepted by name, it passes", rc == 0,
              out)

        # ------------------------------ 36 a PASS says what it did not parse
        # Found fixing case 35: once accepted, the files it names were back
        # under "every surface file parsed" - true of none of them.
        print("\n36. a PASS over hand-mapped surface files names them")
        passing = [x for x in out.split("\n") if x.startswith("PASS")]
        check("the PASS line names each accepted file as mapped by hand, not parsed",
              rc == 0 and passing and "mapped by hand, not parsed" in passing[0]
              and all(g in passing[0] for g in gui), out)
        rc, out = run(a, "--check")
        check("...and a project with nothing accepted keeps the plain PASS",
              rc == 0 and "PASS no drift, no stale proof, every surface file "
              "parsed\n" in out.replace("\r", ""), out)

        # ------------------------------ 37 every UNPARSED file, by name
        # Logged open on 2026-09-24 beside case 31: this list stopped at 40
        # while its header counted every file, and each one it dropped is a
        # name `unparsed_accepted` needs.
        print("\n37. every surface file no extractor read is named, however many")
        t37 = os.path.join(tmp, "thirtyseven")
        os.makedirs(t37)
        put(t37, "app.py", APP_V1)
        for i in range(45):
            put(t37, "gui/w%02d.py" % i, "import tkinter\n")
        run(t37, "--init")
        rc, out = run(t37, "--check")
        missing = [i for i in range(45) if "gui/w%02d.py" % i not in out]
        check("all 45 unparsed GUI files are named, the 41st to 45th included",
              rc == 1 and "45 user-surface file(s)" in out and not missing,
              "missing: %s\n%s" % (missing, out[-2500:]))

        # ------------------------------ 38 every label computed at runtime
        print("\n38. every label computed at runtime is named, however many")
        t38 = os.path.join(tmp, "thirtyeight")
        os.makedirs(t38)
        put(t38, "src/many.jsx", "export const Many = ({ go }) => (\n  <div>\n"
            + "".join("    <button aria-label={l%d} onClick={go}>x</button>\n" % i
                      for i in range(45)) + "  </div>\n);\n")
        run(t38, "--init")
        rc, out = run(t38, "--check")
        missing = [i for i in range(45) if "src/many.jsx:%d " % (i + 3) not in out]
        check("all 45 runtime labels are listed by location, the 41st to 45th "
              "included", "45 control(s) or region(s)" in out and not missing,
              "missing: %s\n%s" % (missing, out[-2500:]))

        # ------------------------------ 39 SPREAD shows every occurrence
        # It said "every occurrence, so you can see which are new" and stopped
        # at 30: the new ones past the thirtieth could not be seen.
        print("\n39. an anti-pattern that SPREAD lists every occurrence it promises")
        t39 = os.path.join(tmp, "thirtynine")
        os.makedirs(t39)
        fixture(t39)
        put(t39, "w.py", "".join("try:\n    go()\nexcept:\n    pass\n"
                                 for _ in range(35)))
        run(t39, "--init")
        base39 = (ENTRY % ("endpoint.health", "health", "api", "app.py:4",
                           "DRIVEN", "2099-01-01 @ abc1234")) \
            + (ENTRY % ("endpoint.orders", "orders", "api", "app.py:8",
                        "DRIVEN", "2099-01-01 @ abc1234"))
        author(t39, base39 + "### pattern: no-bare-except\n\n- rule: a bare "
               "except swallows KeyboardInterrupt\n- canonical: app.py:1\n"
               "- antipattern: ^\\s*except\\s*:\n- ceiling: 0\n")
        rc, out = run(t39, "--check")
        missing = [k for k in range(35) if "w.py:%d " % (4 * k + 3) not in out]
        check("all 35 occurrences are listed, the 31st to 35th included",
              rc == 1 and "35 occurrence(s)" in out and not missing,
              "missing: %s\n%s" % (missing, out[-2500:]))

        # ------------------------------ 40 DRIFT names every use
        print("\n40. a pattern that DRIFTED lists every use outside its scope")
        t40 = os.path.join(tmp, "forty")
        os.makedirs(t40)
        fixture(t40)
        put(t40, "api/handlers.py", "@retry_on_429\ndef fetch(x):\n    return x\n")
        for i in range(35):
            put(t40, "services/s%02d.py" % i, "@retry_on_429\ndef f():\n    return 1\n")
        run(t40, "--init")
        author(t40, base39 + "### pattern: retry-only-at-the-edge\n\n- rule: the "
               "429 retry belongs on outbound calls only\n- canonical: "
               "api/handlers.py:1\n- signature: @retry_on_429\n- only_in: "
               "api/*.py\n- ceiling: 0\n")
        rc, out = run(t40, "--check")
        missing = [i for i in range(35) if "services/s%02d.py:1" % i not in out]
        check("all 35 uses outside the scope are listed, the 31st to 35th included",
              rc == 1 and "35 use(s) outside" in out and not missing,
              "missing: %s\n%s" % (missing, out[-2500:]))

        # ------------------------------ 41 every proof measured by day
        print("\n41. every proof measured by day only is named")
        t41 = os.path.join(tmp, "fortyone")
        os.makedirs(t41)
        fixture(t41)
        run(t41, "--init")
        author(t41, base39 + "".join(
            ENTRY % ("ui.day-%02d" % i, "day", "web-ui", "app.py:1", "DRIVEN",
                     "2001-01-01") for i in range(15)))
        rc, out = run(t41, "--check")
        note = [x for x in out.split("\n") if "measured by day only" in x]
        missing = [i for i in range(15)
                   if not note or "ui.day-%02d" % i not in note[0]]
        # 17: the two base entries name no commit this repository has either.
        check("all 15 are named on the by-day note, the 13th to 15th included",
              note and "17 proof(s)" in note[0] and not missing,
              "missing: %s\n%s" % (missing, out[-2500:]))

        # ------------------------------ 42 every changed line in a stale region
        print("\n42. stale proof names every line that changed inside its region")
        t42 = os.path.join(tmp, "fortytwo")
        os.makedirs(t42)
        lines = ["# line %d" % i for i in range(1, 61)]
        put(t42, "big.py", "\n".join(lines) + "\n")
        put(t42, "app.py", APP_V1)
        git(t42, "init", "-q")
        commit(t42, "baseline")
        run(t42, "--init")
        author(t42, base39 + ENTRY % ("ui.big", "big", "web-ui", "big.py:1-60",
                                      "DRIVEN", "%s @ %s"
                                      % (datetime.date.today(), head(t42))))
        changed = [5, 12, 19, 26, 33, 40, 47, 54]
        for n in changed:
            lines[n - 1] = "# changed %d" % n
        put(t42, "big.py", "\n".join(lines) + "\n")
        rc, out = run(t42, "--check")
        stale = [x for x in out.split("\n") if "ui.big: verified @" in x]
        check("all 8 changed lines are named, the 7th and 8th included",
              rc == 1 and stale and ", ".join(str(n) for n in changed) in stale[0],
              out[-2500:])

        # ------------------------------ 43 one commit, one file count
        # One web app's same commit read 661, 500 and 301 files in three checkouts:
        # the count took in whatever git ignores (logs, snapshots, .env).
        print("\n43. two checkouts of one commit read the same files")
        t43 = os.path.join(tmp, "fortythree")
        os.makedirs(t43)
        put(t43, "app.py", APP_V1)
        put(t43, ".gitignore", "build/\n*.log\n")
        git(t43, "init", "-q")
        commit(t43, "baseline")
        t43b = os.path.join(tmp, "fortythree-clone")
        git(tmp, "clone", "-q", t43, t43b)
        put(t43, "build/bundle.py", "x = 1\n")
        put(t43, "run.log", "noise\n")
        counts = []
        for r in (t43, t43b):
            run(r, "--init")
            run(r, "--write")
            with open(os.path.join(r, "FEATURE-MAP.md"), encoding="utf-8") as fh:
                m43 = re.search(r"from (\d+) file\(s\)", fh.read())
            counts.append(m43 and m43.group(1))
        check("files git ignores are not read, so both checkouts count alike",
              counts[0] and counts[0] == counts[1], "counts: %s" % counts)

        # ------------------------------ 44 a stale generated half is not a PASS
        # KiT's DERIVED block was four days old - 20 capabilities where the code
        # had 24, no UNPARSED list, moved line numbers - and --check said PASS.
        print("\n44. the generated half must match the code, or --check fails")
        t44 = os.path.join(tmp, "fortyfour")
        os.makedirs(t44)
        fixture(t44)
        run(t44, "--init")
        e3 = lambda: ((ENTRY % ("endpoint.health", "health", "api", "app.py:4",
                                "DRIVEN", "2099-01-01 @ abc1234"))
                      + (ENTRY % ("endpoint.orders", "orders", "api", "app.py:8",
                                  "DRIVEN", "2099-01-01 @ abc1234")))
        author(t44, e3())
        rc0, out0 = run(t44, "--check")
        put(t44, "app.py", APP_V2)
        author(t44, e3() + (ENTRY % ("endpoint.refund", "refund", "api",
                                      "app.py:13", "DRIVEN", "2099-01-01 @ abc1234")))
        rc, out = run(t44, "--check")
        check("a DERIVED half written before the code changed fails, naming "
              "what it lacks", rc0 == 0 and rc == 1 and "DERIVED" in out
              and "endpoint.refund" in out and "--write" in out,
              out0[-800:] + "\n---\n" + out[-1500:])
        run(t44, "--write")
        rc, out = run(t44, "--check")
        check("--write brings it level and --check passes again", rc == 0,
              out[-1500:])

        # ------------------------------ 45 every unmapped capability, by name
        # One web app's --check stopped at 40 ("...and 54 more"), the class 1.3.1
        # closed in six other lists.
        print("\n45. every unmapped capability is named")
        t45 = os.path.join(tmp, "fortyfive")
        os.makedirs(t45)
        put(t45, "app.py", "from flask import Flask\napp = Flask(__name__)\n"
            + "".join("\n@app.route('/r%02d')\ndef r%02d():\n    return 'x'\n"
                      % (i, i) for i in range(1, 46)))
        git(t45, "init", "-q")
        commit(t45, "baseline")
        run(t45, "--init")
        rc, out = run(t45, "--check")
        missing = [i for i in range(1, 46) if "endpoint.r%02d" % i not in out]
        check("all 45 are listed, the 41st to 45th included",
              rc == 1 and not missing and "more" not in out,
              "missing: %s\n%s" % (missing, out[-1500:]))

        # ------------------------------ 46 a site served from public/
        # A static site serves public/licenses/X.txt at /licenses/X.txt (Astro,
        # Vite, Next), so looking the served path up in git as-is found nothing
        # and --live said UNKNOWN on a site that runs main.
        print("\n46. --live places a file served from public/")
        import http.server
        import threading

        class H46(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"license v1\n" if self.path == "/licenses/X.txt" else b"no"
                self.send_response(200 if body != b"no" else 404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        srv46 = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H46)
        threading.Thread(target=srv46.serve_forever, daemon=True).start()
        base46 = "http://127.0.0.1:%d" % srv46.server_address[1]
        try:
            t46 = os.path.join(tmp, "fortysix")
            os.makedirs(t46)
            put(t46, "app.py", APP_V1)
            put(t46, "public/licenses/X.txt", "license v1\n")
            git(t46, "init", "-q")
            commit(t46, "c1")
            run(t46, "--init")
            br46 = subprocess.run(("git", "rev-parse", "--abbrev-ref", "HEAD"),
                                  cwd=t46, capture_output=True).stdout.decode().strip()
            for label, extra in (("declared", "- root: public\n"), ("found", "")):
                author(t46, "### live.production\n\n- name: production\n- url: %s\n"
                       "- fingerprint: licenses/X.txt\n%s- branch: %s\n"
                       % (base46, extra, br46))
                rc, out = run(t46, "--live")
                check("a served root %s: placed in git, not UNKNOWN" % label,
                      "production serves" in out and "UNKNOWN" not in out
                      and "public/licenses/X.txt" in out, out[-1500:])
        finally:
            srv46.shutdown()

        # ------------------------------ 47 a hand-mapped range that moved
        # A static site, 2026-09-28: lines added above three ranges moved the
        # code they named, the old numbers held other code, and --check passed.
        print("\n47. a code range that moved under its pointer fails, and --reaim moves it")
        t47 = os.path.join(tmp, "fortyseven")
        os.makedirs(t47)
        l47 = ["# line %d" % i for i in range(1, 61)]
        put(t47, "big.py", "\n".join(l47) + "\n")
        put(t47, "app.py", APP_V1)
        git(t47, "init", "-q")
        commit(t47, "baseline")
        run(t47, "--init")
        vat = "%s @ %s" % (datetime.date.today(), head(t47))
        author(t47, base39 + ENTRY % ("ui.span", "span", "web-ui", "big.py:20-25",
                                      "DRIVEN", vat)
               + ENTRY % ("ui.one", "one", "web-ui", "big.py:40", "DRIVEN", vat)
               + ENTRY % ("ui.top", "top", "web-ui", "big.py:1-3", "UNKNOWN", ""))
        commit(t47, "map written against these lines")
        put(t47, "big.py", "# new 1\n# new 2\n# new 3\n" + "\n".join(l47) + "\n")
        commit(t47, "three lines added above every range")
        rc, out = run(t47, "--check")
        check("RED: a range whose lines moved fails, naming where they are now",
              rc == 1 and "big.py:23-28" in out and "big.py:43" in out
              and "ui.span" in out and "ui.one" in out, out[-2000:])
        check("an ungraded entry's pointer is held to the same truth",
              "big.py:4-6" in out, out[-2000:])
        check("moved lines are not stale proof: the code they certify is unchanged",
              "ui.span: verified @" not in out, out[-2000:])
        rc, out = run(t47, "--reaim")
        with open(os.path.join(t47, "FEATURE-MAP.md"), encoding="utf-8") as fh:
            m47 = fh.read()
        # A one-line pointer stays one line; since 1.4.5 --reaim also stamps
        # each range with the commit whose lines it is in (case 58).
        check("--reaim rewrites each moved range in place",
              rc == 0 and "big.py:23-28" in m47
              and re.search(r"big\.py:43( @ [0-9a-f]{7,})?\n", m47)
              and "big.py:4-6" in m47 and "big.py:20-25" not in m47, out[-1500:])
        rc, out = run(t47, "--check")
        check("after --reaim, --check passes", rc == 0, out[-1500:])
        commit(t47, "re-aimed")
        rc, out = run(t47, "--check")
        check("a range re-aimed in a later commit is read in that commit's lines",
              rc == 0, out[-1500:])

        # ------------------------------ 48 stale lines numbered on both sides
        # A static site: "changed at line(s) 322-326, inside its region 332-347"
        # - the change was read on one side of the diff and printed from the other.
        print("\n48. a stale region's changed lines say which side of the diff they are on")
        t48 = os.path.join(tmp, "fortyeight")
        os.makedirs(t48)
        l48 = ["# line %d" % i for i in range(1, 61)]
        put(t48, "big.py", "\n".join(l48) + "\n")
        put(t48, "app.py", APP_V1)
        git(t48, "init", "-q")
        commit(t48, "baseline")
        run(t48, "--init")
        author(t48, base39 + ENTRY % ("ui.mid", "mid", "web-ui", "big.py:30-40",
                                      "DRIVEN", "%s @ %s"
                                      % (datetime.date.today(), head(t48))))
        commit(t48, "map")
        l48[31] = "# changed"
        put(t48, "big.py", "\n".join(l48[10:]) + "\n")
        rc, out = run(t48, "--check")
        st = [x for x in out.split("\n") if "ui.mid: verified @" in x]
        check("the change is 32 at the proof's commit and 22 now, said so",
              rc == 1 and st and "32 at " in st[0] and "22 now" in st[0]
              and "inside its region" not in st[0], out[-1500:])

        # ------------------------------ 49 a region read in its own lines
        # A static site, 2026-09-29: --reaim moved ui.foundry to 355-360, the
        # lines it sits in now, and --check then called its proof older than
        # its code - for the reel's script, changed at 354-357 in the PROOF's
        # lines and 40 lines below the passage. Each side of the diff was held
        # against a region numbered in only one of them, so a range could
        # collide with the other side's code by number, or miss its own change.
        print("\n49. a code range is held against the side of the diff it is numbered in")
        t49 = os.path.join(tmp, "fortynine")
        os.makedirs(t49)
        l49 = ["# line %d" % i for i in range(1, 61)]
        put(t49, "big.py", "\n".join(l49) + "\n")
        put(t49, "app.py", APP_V1)
        git(t49, "init", "-q")
        commit(t49, "baseline")
        run(t49, "--init")
        vat = "%s @ %s" % (datetime.date.today(), head(t49))
        author(t49, base39 + ENTRY % ("ui.low", "low", "web-ui", "big.py:20-25",
                                      "DRIVEN", vat)
               + ENTRY % ("ui.high", "high", "web-ui", "big.py:45-50", "DRIVEN", vat))
        commit(t49, "map, in the proof's lines")
        top = lambda n: "\n".join(["# above %d" % i for i in range(n)] + l49) + "\n"
        put(t49, "big.py", top(5))
        run(t49, "--reaim")
        commit(t49, "5 lines above both, the ranges re-aimed to 25-30 and 50-55")
        # 5 more above, and the proof's lines 28, 32 and 47 changed: the first
        # two between the ranges, the third inside ui.high.
        l49[27], l49[31], l49[46] = "# changed 28", "# changed 32", "# changed 47"
        put(t49, "big.py", top(10))
        rc, out = run(t49, "--check")
        check("a range written between the proof and now is read in its own "
              "commit's lines: a change below it is not in it",
              "ui.low: verified @" not in out and "big.py:30-35" in out, out[-2000:])
        hi49 = [x for x in out.split("\n") if "ui.high: verified @" in x]
        check("RED: ...and a change inside it is, in the proof's lines",
              rc == 1 and hi49 and "47 at " in hi49[0] and "57 now" in hi49[0]
              and "region 45-50 at " in hi49[0], out[-2000:])
        rc, out = run(t49, "--reaim")
        # Until 1.4.5 this asserted silence about ui.high; a range --reaim
        # declines is now named, with where it sits (case 60).
        check("--reaim moves ui.low to today's lines and leaves ui.high, whose "
              "code changed, naming it", "big.py:25-30 -> big.py:30-35" in out
              and "ui.high: big.py:50-55 -> big.py:55-60 not moved" in out, out[-1500:])
        rc, out = run(t49, "--check")
        check("a re-aimed range is held against today's side of the diff alone: "
              "the proof's line 32 is not today's",
              "ui.low: verified @" not in out and "ui.high: verified @" in out,
              out[-2000:])
        put(t49, "big.py", top(10).replace("# line 25\n", "# line 25\n# added\n"))
        rc, out = run(t49, "--check")
        check("RED: a line added right after its last line stales it, as it did "
              "read on the proof's side", rc == 1 and "ui.low: verified @" in out,
              out[-2000:])
        l49[21] = "# changed 22"
        put(t49, "big.py", top(10))
        rc, out = run(t49, "--check")
        lo49 = [x for x in out.split("\n") if "ui.low: verified @" in x]
        check("RED: a change inside a re-aimed range still stales its proof",
              rc == 1 and lo49 and "22 at " in lo49[0] and "32 now" in lo49[0]
              and "region 30-35 now" in lo49[0], out[-2000:])

        # ------------------------------ 50 a change the proof already covers
        # A static site, 2026-09-29: ui.workshop-plates was written at one
        # commit, its block grew, the proof was taken on the grown block, then
        # lines were added above it. --reaim refused (a change inside) and
        # --check was silent, though the proof covers that change.
        print("\n50. a range whose inside changed before its proof is still carried")
        t50 = os.path.join(tmp, "fifty")
        os.makedirs(t50)
        l50 = ["# line %d" % i for i in range(1, 61)]
        put(t50, "big.py", "\n".join(l50) + "\n")
        put(t50, "app.py", APP_V1)
        git(t50, "init", "-q")
        commit(t50, "baseline")
        base50 = head(t50)
        run(t50, "--init")
        author(t50, base39 + ENTRY % ("ui.blk", "blk", "web-ui", "big.py:20-30",
                                      "DRIVEN", "2001-01-01")
               + ENTRY % ("ui.late", "late", "web-ui", "big.py:40-45",
                          "DRIVEN", "%s @ %s" % (datetime.date.today(), base50)))
        commit(t50, "map written")
        l50[24] = "# changed 25"
        l50[41] = "# changed 42"
        put(t50, "big.py", "\n".join(l50) + "\n")
        commit(t50, "both blocks change")
        mp50 = os.path.join(t50, "FEATURE-MAP.md")
        with open(mp50, encoding="utf-8") as fh:
            m50 = fh.read()
        with open(mp50, "w", encoding="utf-8", newline="") as fh:
            fh.write(m50.replace("- verified_at: 2001-01-01",
                                 "- verified_at: %s @ %s"
                                 % (datetime.date.today(), head(t50))))
        commit(t50, "ui.blk proved on the changed block")
        put(t50, "big.py", "# new 1\n# new 2\n# new 3\n# new 4\n# new 5\n"
            + "\n".join(l50) + "\n")
        commit(t50, "five lines added above both")
        rc, out = run(t50, "--check")
        check("RED: a range whose inside changed before its proof fails as moved, "
              "naming where it is now", rc == 1 and "big.py:25-35" in out, out[-2000:])
        # Until 1.4.5 this asserted that ui.late's move stayed unsaid; the
        # drift is now named beside the stale proof and NOT re-aimed (case 60).
        check("...while one whose inside changed after its proof stays stale "
              "proof, its move named beside it and not made",
              "ui.late: verified @" in out and "big.py:40-45 (written @" in out
              and "-> big.py:45-50 NOT re-aimed" in out, out[-2000:])
        rc, out = run(t50, "--reaim")
        with open(mp50, encoding="utf-8") as fh:
            m50 = fh.read()
        check("--reaim carries it through the proof's commit",
              "big.py:25-35" in m50 and "big.py:40-45" in m50, out[-1500:])

        # ------------------------------ 51 the map's own lists are whole
        # 1.3.1 made every list --check prints whole; the map document kept
        # "...and N more" at 60 (UNPARSED, runtime labels) and 40 (artifacts).
        print("\n51. every list the map document carries is whole")
        t51 = os.path.join(tmp, "fiftyone")
        os.makedirs(t51)
        put(t51, "app.py", APP_V1)
        for i in range(65):
            put(t51, "gui/w%02d.py" % i, "import tkinter\n")
        put(t51, "src/many.jsx", "export const Many = ({ go }) => (\n  <div>\n"
            + "".join("    <button aria-label={l%d} onClick={go}>x</button>\n" % i
                      for i in range(65)) + "  </div>\n);\n")
        for i in range(45):
            put(t51, "static/b%02d.min.js" % i, "var a=1;\n")
        run(t51, "--init")
        with open(os.path.join(t51, "FEATURE-MAP.md"), encoding="utf-8") as fh:
            m51 = fh.read()
        miss = ([i for i in range(65) if "gui/w%02d.py" % i not in m51]
                + [i for i in range(65) if "src/many.jsx:%d`" % (i + 3) not in m51]
                + [i for i in range(45) if "static/b%02d.min.js" % i not in m51])
        check("RED: 65 unparsed files, 65 runtime labels and 45 build artifacts, "
              "each named in the map", not miss and "more" not in m51,
              "missing: %s" % miss)

        # ------------------------------ 52 a file count the map no longer says
        # A static site's map said 77 files when the code had 93 and --check said
        # nothing: the count is masked so it cannot fail, but it is still a claim.
        print("\n52. a file count the map no longer matches is noted, not failed")
        t52 = os.path.join(tmp, "fiftytwo")
        os.makedirs(t52)
        fixture(t52)
        run(t52, "--init")
        author(t52, base39)
        put(t52, "lib/util.py", "X = 1\n")
        put(t52, "lib/more.py", "Y = 2\n")
        rc, out = run(t52, "--check")
        m52 = re.search(r"from (\d+) source file", out)
        check("RED: the notice names both counts and the way to refresh it, and "
              "the check still passes", rc == 0 and "NOTE" in out
              and "--write refreshes" in out and m52
              and re.search(r"says %d file" % (int(m52.group(1)) - 2), out),
              out[-1500:])

        # ------------------------------ 53 a proof is read by Jev when recorded
        # 2026-09-29: at most four Jev requests in a day, a sign it was
        # not being used. --judge ran only when an agent thought to ask;
        # --record runs at every proof, so the reading goes there.
        print("\n53. --record asks Jev whether the observable it captured shows the intent")
        posts53, p53 = [], {"v": 0.2}

        class J53(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(
                    int(self.headers.get("Content-Length") or 0)).decode("utf-8"))
                posts53.append(body)
                out = json.dumps({
                    "model": body["model"],
                    "answers": {q: {"type": "noul", "noul": p53["v"]}
                                for q in body["questions"]},
                    "usage": {"input_tokens": 40, "output_tokens": 2}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *args):
                pass

        srv53 = http.server.ThreadingHTTPServer(("127.0.0.1", 0), J53)
        threading.Thread(target=srv53.serve_forever, daemon=True).start()
        try:
            if not CLIENT:
                raise _NoClient
            fake53 = dict(SAFE, TYPESAFE_API_KEY="test-key-not-real",
                          JEV_ENDPOINT="http://127.0.0.1:%d/v1/systemone"
                          % srv53.server_address[1])
            t53 = os.path.join(tmp, "fiftythree")
            os.makedirs(t53)
            fixture(t53)
            run(t53, "--init")
            author(t53, "### endpoint.orders\n\n- name: orders\n- intent: a "
                   "customer finds the order they placed in their history\n"
                   "- observable: POST /orders returns 201\n\n"
                   "### endpoint.health\n\n- name: health\n- observable: 200\n")
            seen = "GET /orders/history lists the order just placed"
            rc, out = run(t53, "--record", "--feature", "endpoint.orders",
                          "--grade", "DRIVEN", "--result", "pass",
                          "--observable", seen, env=fake53)
            q = posts53[-1]["questions"] if posts53 else {}
            q = list(q.values())[0]["instructions"] if len(q) == 1 else {}
            with open(os.path.join(t53, ".verify", "proof", "endpoint.orders",
                                   "latest.json"), encoding="utf-8") as fh:
                rec53 = json.load(fh)
            check("RED: one request, asking about the observable just captured "
                  "against the entry's intent", rc == 0 and len(posts53) == 1
                  and q.get("observable") == seen and "history" in q.get("intent", ""),
                  out[-1500:] + repr(posts53)[:300])
            check("...its reading is printed as a reading and kept with the proof",
                  "0.20" in out and "may NOT show" in out and "never a gate" in out
                  and (rec53.get("judged") or {}).get("noul") == 0.2
                  and rec53["judged"].get("model") == "jev-1.13.0", out[-1500:])
            n = len(posts53)
            rc, out = run(t53, "--record", "--feature", "endpoint.orders",
                          "--grade", "DRIVEN", "--result", "pass",
                          "--observable", seen)
            check("with no key the proof is still recorded, and says it went "
                  "unjudged", rc == 0 and "recorded" in out and "NOT JUDGED" in out
                  and len(posts53) == n, out[-1500:])
            rc, out = run(t53, "--record", "--feature", "endpoint.health",
                          "--grade", "DRIVEN", "--result", "pass",
                          "--observable", "GET /health 200", env=fake53)
            check("an entry with no intent: is not asked, and says why",
                  rc == 0 and "no intent" in out and len(posts53) == n, out[-1500:])
            rc, out = run(t53, "--record", "--feature", "endpoint.orders",
                          "--grade", "DRIVEN", "--result", "fail",
                          "--observable", "history is empty", env=fake53)
            check("a failed result is not asked: there is nothing it could show",
                  rc == 0 and len(posts53) == n, out[-1500:])
        except _NoClient:
            NOT_RUN.append("53")
        finally:
            srv53.shutdown()

        # ------------------------------ 54 two captures in one second both stay
        # The pack's reviewer (2026-09-30) recorded twice inside one second and
        # found one dated file: the name was taken to the second, so the later
        # capture replaced the earlier one, and its analysis compared against a
        # proof that no longer existed.
        print("\n54. two captures inside one second are two files")
        t54 = os.path.join(tmp, "fiftyfour")
        os.makedirs(t54)
        fixture(t54)
        run(t54, "--init")
        pd54 = os.path.join(t54, ".verify", "proof", "endpoint.health")
        ats, outs = [], []
        for _attempt in range(8):
            # a record takes ~250 ms here: start just past a second boundary so
            # both land in the same one, and read back which second each got
            time.sleep(1.0 - (time.time() % 1.0))
            for _ in range(2):
                rc, out = run(t54, "--record", "--feature", "endpoint.health",
                              "--grade", "TESTED", "--result", "fail",
                              "--observable", "GET /health 500")
                outs.append(out)
                try:
                    with open(os.path.join(pd54, "latest.json"), encoding="utf-8") as fh:
                        ats.append(json.load(fh).get("at"))
                except (OSError, ValueError):
                    ats.append(None)
            if ats[-1] and ats[-1] == ats[-2]:
                break
        same = bool(ats[-1]) and ats[-1] == ats[-2]
        stamp = (ats[-1] or "").replace("-", "").replace(":", "")
        pair = sorted(f for f in os.listdir(pd54)
                      if f != "latest.json" and f.startswith(stamp + "-"))
        check("RED: two captures stamped in the same second leave two dated files",
              same and len(pair) == 2,
              "same second: %s; files for %s: %s" % (same, stamp, pair))
        m54 = re.search(r"recorded (\S+)", outs[-1])
        named = m54.group(1).replace("\\", "/").rsplit("/", 1)[-1] if m54 else None
        check("...the second capture's file is the one it printed, and it sorts "
              "after the first", same and len(pair) == 2 and named == pair[-1],
              outs[-1][-600:] + "\n" + repr(pair))

        # ------------------------------ 55 the template's face hint is not a face
        # The pack's reviewer (2026-09-30): --list on a map fresh from --init
        # printed "user · dev — only to overrule the derived face, with the
        # reason 1" as a bucket, because the example entry's face: line is the
        # template's hint, and an authored face was taken as written.
        print("\n55. --list on a fresh map: the example's face hint is not a bucket")
        t55 = os.path.join(tmp, "fiftyfive")
        os.makedirs(t55)
        fixture(t55)
        run(t55, "--init")
        rc, out = run(t55, "--list")
        head55 = out.split("\n", 1)[0]
        buckets = [b.rsplit(" ", 1)[0] for b in head55.split(" - ", 1)[-1].split(", ")]
        check("RED: every bucket in the header is a face",
              rc == 0 and buckets and set(buckets) <= {"user", "dev", "unclassified"},
              head55)
        check("...and the example entry, mapped by hand, sits in unclassified",
              re.search(r"^\s+unclassified\s+example\.id\b", out, re.M), out[-1500:])
        author(t55, "### endpoint.orders\n\n- name: orders\n- surface: api\n"
               "- face: user — the checkout page posts here\n- grade: UNKNOWN\n")
        rc, out = run(t55, "--list", "--face", "user")
        check("an authored face with its reason beside it still overrules",
              rc == 0 and "endpoint.orders" in out and "user 1" in out, out[-1500:])

        # ------------------------------ 56 a move that rewrites nothing is no move
        # KiT, 2026-09-30: a release script's line 1, written at one
        # commit; the script's header grew around line 1 and the proof was taken
        # after. Carried through the proof the line widened to 1-8, a one-line
        # pointer prints only its start, so --check said ":1 -> :1", --reaim
        # wrote :1 over :1, blame still named the old commit, and it looped.
        print("\n56. a one-line pointer carried to its own line is not moved, and --reaim settles")
        t56 = os.path.join(tmp, "fiftysix")
        os.makedirs(t56)
        l56 = ["# line %d" % i for i in range(1, 41)]
        put(t56, "tool.py", "\n".join(l56) + "\n")
        put(t56, "app.py", APP_V1)
        git(t56, "init", "-q")
        commit(t56, "baseline")
        run(t56, "--init")
        author(t56, base39 + ENTRY % ("dev.tool", "tool", "cli", "tool.py:1",
                                      "DRIVEN", "2001-01-01"))
        commit(t56, "map written")
        put(t56, "tool.py", "# header v2\n# updated a\n# updated b\n# updated c\n"
            + "\n".join(l56[1:]) + "\n")
        commit(t56, "the header grows around line 1")
        mp56 = os.path.join(t56, "FEATURE-MAP.md")
        with open(mp56, encoding="utf-8") as fh:
            m56 = fh.read()
        with open(mp56, "w", encoding="utf-8", newline="") as fh:
            fh.write(m56.replace("- verified_at: 2001-01-01", "- verified_at: %s @ %s"
                                 % (datetime.date.today(), head(t56))))
        commit(t56, "dev.tool proved on the grown header")
        rc, out = run(t56, "--check")
        check("RED: --check reports no move from tool.py:1 to tool.py:1, and passes",
              rc == 0 and not re.search(r"tool\.py:1 \(written[^\n]*-> tool\.py:1\s*$", out, re.M),
              out[-1500:])
        run(t56, "--reaim")
        rc, out = run(t56, "--reaim")
        check("...and a second --reaim finds nothing to move", rc == 0
              and "no code range has moved" in out, out[-800:])

        # ------------------------------ 57 a label where a commit belongs
        # KiT, 2026-09-30: verified_at "2026-09-29 @ TICKET-X" names a work label,
        # not a commit, so --check reads it by day and by whole file - any change
        # to the file on a later day stales it, and one later that day is missed.
        # --record knows the commit it captured at; it says what to write.
        print("\n57. --record says the verified_at to write, and warns on a label")
        t57 = os.path.join(tmp, "fiftyseven")
        os.makedirs(t57)
        fixture(t57)
        run(t57, "--init")
        author(t57, base39 + ENTRY % ("dev.lab", "lab", "cli", "app.py:4",
                                      "DRIVEN", "2026-09-29 @ TICKET-X"))
        commit(t57, "map with a label")
        rc, out = run(t57, "--record", "--feature", "dev.lab", "--grade", "DRIVEN",
                      "--result", "pass", "--observable", "a value read back", "--how", "ran it")
        want57 = "%s @ %s" % (datetime.date.today(), head(t57)[:7])
        check("RED: a passing capture names the verified_at to write, with its commit",
              rc == 0 and want57 in out, out[-800:])
        check("...and warns that the label it replaces is read by day only",
              "TICKET-X" in out and "by day" in out, out[-800:])

        # ------------------------------ 58 a re-aimed range left uncommitted
        # A static site, 2026-09-30: --reaim moved nine ranges at one commit,
        # the map stayed uncommitted while a later commit added a line above
        # them, and nothing read them again - blame said zeros, and a line
        # blame cannot place was taken to be in today's lines. Nine pointers
        # one short, and --check PASS. Now --reaim stamps each range it moves
        # with the commit whose lines it is in (`@ <commit>`), read before
        # blame; a hand-written, uncommitted, unstamped pointer is still read
        # in today's lines, and the PASS says so when its file has moved on.
        print("\n58. a range re-aimed and left uncommitted is still read in its own commit's lines")
        t58 = os.path.join(tmp, "fiftyeight")
        os.makedirs(t58)
        l58 = ["# line %d" % i for i in range(1, 61)]
        put(t58, "big.py", "\n".join(l58) + "\n")
        put(t58, "app.py", APP_V1)
        git(t58, "init", "-q")
        commit(t58, "baseline")
        run(t58, "--init")
        author(t58, base39 + ENTRY % ("ui.span", "span", "web-ui", "big.py:20-25",
                                      "DRIVEN", "%s @ %s"
                                      % (datetime.date.today(), head(t58))))
        commit(t58, "map written against these lines")
        put(t58, "big.py", "# new 1\n# new 2\n# new 3\n" + "\n".join(l58) + "\n")
        commit(t58, "three lines above")
        at3 = head(t58)
        rc, out = run(t58, "--reaim")
        mp58 = os.path.join(t58, "FEATURE-MAP.md")
        with open(mp58, encoding="utf-8") as fh:
            m58 = fh.read()
        check("RED: --reaim stamps the range it moves with the commit whose lines it is in",
              rc == 0 and "big.py:23-28 @ %s" % at3 in m58,
              out[-1500:] + "\n" + m58[-1200:])
        # The map stays uncommitted; one more line lands above, code only.
        put(t58, "big.py", "# new 0\n# new 1\n# new 2\n# new 3\n" + "\n".join(l58) + "\n")
        commit_only(t58, "one more line above, the map not committed", "big.py")
        rc, out = run(t58, "--check")
        check("RED: the uncommitted, stamped range is read in its stamp's lines: "
              "one short, named", rc == 1 and "ui.span: big.py:23-28 (written @ %s) "
              "-> big.py:24-29" % at3 in out, out[-2000:])
        rc, out = run(t58, "--reaim")
        with open(mp58, encoding="utf-8") as fh:
            m58 = fh.read()
        check("--reaim moves it on, re-stamped",
              "big.py:24-29 @ %s" % head(t58) in m58, out[-1500:])
        rc, out = run(t58, "--check")
        check("...and --check passes", rc == 0, out[-1500:])
        # The normal flow: a pointer written by hand against today's lines,
        # after commits touched its file, passes - and the PASS says the bound.
        with open(mp58, "w", encoding="utf-8", newline="") as fh:
            fh.write(m58.replace("<!-- AUTHORED:END -->", ENTRY % (
                "ui.hand", "hand", "web-ui", "big.py:44-46", "UNKNOWN", "")
                + "<!-- AUTHORED:END -->"))
        rc, out = run(t58, "--check")
        check("a hand-written, uncommitted pointer is read in today's lines and passes",
              rc == 0, out[-1500:])
        tail58 = out.split("PASS")[-1]
        check("...and the PASS names that bound, its file having changed since the "
              "map's last commit", "today's lines" in tail58 and "big.py" in tail58,
              out[-1500:])
        # A file with changes not in HEAD: --reaim moves, cannot stamp, says so.
        put(t58, "big.py", "# new -1\n# new 0\n# new 1\n# new 2\n# new 3\n"
            + "\n".join(l58) + "\n")
        rc, out = run(t58, "--reaim")
        with open(mp58, encoding="utf-8") as fh:
            m58 = fh.read()
        check("a range moved in a file with uncommitted changes carries no stamp, "
              "and --reaim says so", "big.py:25-30\n" in m58
              and "carry no `@ commit`" in out, out[-1500:] + "\n" + m58[-1500:])
        commit(t58, "file and map together")
        rc, out = run(t58, "--check")
        check("...committed together, it is read by blame and passes", rc == 0,
              out[-1500:])

        # ------------------------------ 59 every pointer in a field is read
        # A static site, 2026-09-30: `code: A:99-103; its mark B:403-436`,
        # `code: B:263-285; its order B:71; its figures C:201-241`, and an
        # `entry:` holding `its slot is B:310-312` were never re-aimed or
        # checked - the old pattern read one pointer, at the end of a `code:`
        # line. Four pointers sat four lines short under a PASS, and a bare
        # `Shell.astro:138` in an entry named no file at all.
        print("\n59. every path:N pointer in a code: or entry: field is read, and one naming no file is named")
        t59 = os.path.join(tmp, "fiftynine")
        os.makedirs(t59)
        l59 = ["# line %d" % i for i in range(1, 61)]
        o59 = ["# other %d" % i for i in range(1, 41)]
        put(t59, "big.py", "\n".join(l59) + "\n")
        put(t59, "other.py", "\n".join(o59) + "\n")
        put(t59, "app.py", APP_V1)
        git(t59, "init", "-q")
        commit(t59, "baseline")
        run(t59, "--init")
        vat = "%s @ %s" % (datetime.date.today(), head(t59))
        multi = ("### ui.multi\n\n- name: multi\n- surface: web-ui\n"
                 "- code: other.py:5-8; its mark big.py:20-25\n"
                 "- entry: / (its slot is big.py:40-42, framed by other.py:30)\n"
                 "- does: a fixture feature\n- observable: a value read back\n"
                 "- grade: DRIVEN\n- verified_at: %s\n\n" % vat)
        bare = ("### ui.bare\n\n- name: bare\n- surface: web-ui\n- code: big.py:50\n"
                "- entry: the footer, under its links (Layout.astro:138)\n"
                "- does: a fixture feature\n- observable: a value read back\n"
                "- grade: UNKNOWN\n- verified_at: \n\n")
        author(t59, base39 + multi + bare)
        commit(t59, "map written against these lines")
        put(t59, "big.py", "# new 1\n# new 2\n# new 3\n" + "\n".join(l59) + "\n")
        put(t59, "other.py", "# new a\n# new b\n" + "\n".join(o59) + "\n")
        commit(t59, "lines added above every range in both files")
        rc, out = run(t59, "--check")
        check("RED: both pointers of a code: field, and both inside an entry: "
              "field, are named as moved",
              rc == 1 and "other.py:5-8 (written @" in out and "-> other.py:7-10" in out
              and "big.py:20-25 (written @" in out and "-> big.py:23-28" in out
              and "big.py:40-42 (written @" in out and "-> big.py:43-45" in out
              and "other.py:30 (written @" in out and "-> other.py:32" in out,
              out[-2500:])
        check("RED: a pointer-shaped string naming no file is reported, never skipped",
              "Layout.astro:138" in out and "no such file" in out, out[-2500:])
        rc, out = run(t59, "--reaim")
        mp59 = os.path.join(t59, "FEATURE-MAP.md")
        with open(mp59, encoding="utf-8") as fh:
            m59 = fh.read()
        check("--reaim moves all four in place and keeps the prose around them",
              rc == 0 and re.search(r"- code: other\.py:7-10 @ \w+; its mark "
                                    r"big\.py:23-28 @ \w+\n", m59)
              and re.search(r"- entry: / \(its slot is big\.py:43-45 @ \w+, framed "
                            r"by other\.py:32 @ \w+\)\n", m59)
              and "big.py:53 @" in m59, out[-1500:] + "\n" + m59[-2000:])
        # A change inside the second pointer's range stales the proof, and the
        # stale line names that pointer's file and region, not the first's.
        l59[22] = "# changed 23"
        put(t59, "big.py", "# new 1\n# new 2\n# new 3\n" + "\n".join(l59) + "\n")
        rc, out = run(t59, "--check")
        st59 = [x for x in out.split("\n") if "ui.multi: verified @" in x]
        check("RED: a change inside a code: field's second pointer stales its proof, "
              "named by its own file and region",
              rc == 1 and st59 and "big.py changed" in st59[0] and "23 at " in st59[0]
              and "26 now" in st59[0] and "region 20-25 at" in st59[0]
              and "other.py" not in st59[0], out[-2500:])
        with open(mp59, "w", encoding="utf-8", newline="") as fh:
            fh.write(m59.replace("(Layout.astro:138)", "(other.py:1)"))
        put(t59, "big.py", "# new 1\n# new 2\n# new 3\n"
            + "\n".join("# line %d" % i for i in range(1, 61)) + "\n")
        rc, out = run(t59, "--check")
        check("with the bare name made a path and the change undone, --check passes",
              rc == 0, out[-1500:])

        # ------------------------------ 60 a move --reaim declines is named
        # A static site, 2026-09-30: one section's source range gained
        # a header line above and a comment change inside at a later commit. --reaim
        # rightly left it - the change postdates its proof - but printed "no
        # code range has moved", and --check showed the stale proof alone: the
        # drift sat hidden until a hand fix. Now both name it.
        print("\n60. a range moved AND changed inside: --reaim names what it declines, --check the drift beside the stale proof")
        t60 = os.path.join(tmp, "sixty")
        os.makedirs(t60)
        l60 = ["# line %d" % i for i in range(1, 61)]
        put(t60, "big.py", "\n".join(l60) + "\n")
        put(t60, "app.py", APP_V1)
        git(t60, "init", "-q")
        commit(t60, "baseline")
        base60 = head(t60)
        run(t60, "--init")
        author(t60, base39 + ENTRY % ("ui.scene", "scene", "web-ui", "big.py:20-30",
                                      "DRIVEN", "%s @ %s"
                                      % (datetime.date.today(), base60))
               + ENTRY % ("ui.raw", "raw", "web-ui", "big.py:40-45", "UNKNOWN", ""))
        commit(t60, "map written")
        wrote60 = head(t60)
        l60[24], l60[41] = "# changed 25", "# changed 42"
        put(t60, "big.py", "# header\n" + "\n".join(l60) + "\n")
        commit(t60, "one line above, one changed inside each")
        rc, out = run(t60, "--reaim")
        check("RED: --reaim names the range it declines, where it sits now, and why",
              rc == 0 and "ui.scene: big.py:20-30 -> big.py:21-31 not moved: a change "
              "inside it postdates its proof @ %s" % base60 in out
              and "no code range has moved" not in out, out[-1500:])
        check("...and one with no proof to carry it, by that reason",
              "ui.raw: big.py:40-45 -> big.py:41-46 not moved: a change inside it, "
              "and no DRIVEN or TESTED proof" in out, out[-1500:])
        mp60 = os.path.join(t60, "FEATURE-MAP.md")
        with open(mp60, encoding="utf-8") as fh:
            m60 = fh.read()
        check("...and writes neither", "big.py:20-30\n" in m60
              and "big.py:40-45\n" in m60, m60[-1500:])
        rc, out = run(t60, "--check")
        st60 = [x for x in out.split("\n") if "ui.scene: verified @" in x]
        check("RED: --check reports the drift beside the stale proof, not instead of it",
              rc == 1 and st60 and "25 at " in st60[0] and "-> big.py:21-31" in st60[0]
              and "not re-aimed" in st60[0], out[-2500:])
        check("RED: an ungraded range with a change inside is named as moved and "
              "not re-aimed", "ui.raw: big.py:40-45 (written @ %s) -> big.py:41-46 "
              "NOT re-aimed" % wrote60 in out, out[-2500:])
        # Re-driven, the proof covers the change and --reaim carries it.
        with open(mp60, "w", encoding="utf-8", newline="") as fh:
            fh.write(m60.replace("- verified_at: %s @ %s" % (datetime.date.today(), base60),
                                 "- verified_at: %s @ %s"
                                 % (datetime.date.today(), head(t60))))
        rc, out = run(t60, "--reaim")
        with open(mp60, encoding="utf-8") as fh:
            m60 = fh.read()
        check("re-driven, --reaim carries it through the new proof and still names ui.raw",
              "big.py:21-31" in m60
              and re.search(r"ui\.scene: big\.py:20-30 -> big\.py:21-31\s*$", out, re.M)
              and "ui.raw: big.py:40-45 -> big.py:41-46 not moved" in out, out[-1500:])
        with open(mp60, "w", encoding="utf-8", newline="") as fh:
            fh.write(m60.replace("big.py:40-45", "big.py:41-46"))
        rc, out = run(t60, "--check")
        check("set by hand, the ungraded range passes", rc == 0, out[-1500:])

        # ------------------------------ 61 a host with a port is not a pointer
        # The pack's review (2026-09-30): `entry: app.example.com:8443` read as a
        # pointer naming no file - a dotted host ends in a TLD, which looked like
        # an extension. A token is a pointer when its path names a file under the
        # project, or is shaped as no host is: a folder separator, or an extension
        # that is not a TLD-like label. A bare name naming no file (Layout.astro:138,
        # Shell.astro:138) is still named, as 1.4.5 named it.
        print("\n61. a host with a port in an entry: field is never read as a pointer")
        t61 = os.path.join(tmp, "sixtyone")
        os.makedirs(t61)
        l61 = ["# line %d" % i for i in range(1, 41)]
        put(t61, "big.py", "\n".join(l61) + "\n")
        put(t61, "app.py", APP_V1)
        git(t61, "init", "-q")
        commit(t61, "baseline")
        run(t61, "--init")
        hosts = ("app.example.com:8443 and localhost:3000; https://x.y:443/path; "
                 "127.0.0.1:8080; [::1]:5173")
        hosted = ("### ui.hosts\n\n- name: hosts\n- surface: web-ui\n- code: big.py:20-25\n"
                  "- entry: %s\n- does: a fixture feature\n- observable: a value read back\n"
                  "- grade: UNKNOWN\n\n" % hosts)
        author(t61, base39 + hosted
               + "### ui.bare\n\n- name: bare\n- surface: web-ui\n"
               "- entry: the footer (Layout.astro:138) under Shell.astro:138\n"
               "- does: a fixture feature\n- observable: a value read back\n"
               "- grade: UNKNOWN\n\n")
        rc, out = run(t61, "--check")
        check("RED: no host:port is named as code that does not exist",
              rc == 1 and not any(h in out for h in ("app.example.com", "x.y:443",
                                                       "localhost:3000", "127.0.0.1:8080",
                                                       "1]:5173")), out[-2500:])
        check("...while a bare name naming no file still is, both of them",
              "ui.bare -> Layout.astro:138" in out
              and "ui.bare -> Shell.astro:138" in out, out[-2500:])
        author(t61, base39 + hosted)
        rc, out = run(t61, "--check")
        check("...and with the bare names gone, the hosts alone pass --check",
              rc == 0, out[-1500:])
        commit(t61, "map written")
        put(t61, "big.py", "# new 1\n# new 2\n" + "\n".join(l61) + "\n")
        commit(t61, "two lines above")
        rc, out = run(t61, "--reaim")
        with open(os.path.join(t61, "FEATURE-MAP.md"), encoding="utf-8") as fh:
            m61 = fh.read()
        check("--reaim moves the code: range and leaves every host as written",
              rc == 0 and "big.py:22-27 @" in m61 and "- entry: %s\n" % hosts in m61,
              out[-1500:] + "\n" + m61[-1200:])

        # ------------------------------ 62 a sibling's modifier does not leak
        # The pack's review (2026-09-30): `(e.ctrlKey || e.metaKey) && e.key === 'k'`
        # then `e.altKey && e.key === 'h'` in one listener minted key.mod-alt-h -
        # the either-test was read from the whole handler above the condition, so an
        # earlier sibling's modifier leaked into the next shortcut. It is read now
        # from the shortcut's own condition, from a guard (`if (!(a || b)) return`),
        # or from a local the condition tests (`const mod = a || b`).
        print("\n62. a modifier in an earlier sibling condition does not leak into the next shortcut")
        t62 = os.path.join(tmp, "sixtytwo")
        os.makedirs(t62)
        put(t62, "static/first.js", "window.addEventListener('keydown', (e) => {\n"
            "  if ((e.ctrlKey || e.metaKey) && e.key === 'k') { x(); }\n"
            "  if (e.altKey && e.key === 'h') { fetch('/health'); }\n"
            "});\n")
        put(t62, "static/second.js", "window.addEventListener('keydown', (e) => {\n"
            "  if (e.altKey && e.key === 'h') { fetch('/health'); }\n"
            "  if ((e.ctrlKey || e.metaKey) && e.key === 'k') { x(); }\n"
            "});\n")
        put(t62, "static/local.js", "window.addEventListener('keydown', (e) => {\n"
            "  const mod = e.ctrlKey || e.metaKey;\n"
            "  if (mod && e.key === 'p') { p(); }\n"
            "  if (e.shiftKey && e.key === 'q') { q(); }\n"
            "});\n")
        put(t62, "static/guard.js", "window.addEventListener('keydown', (e) => {\n"
            "  if (!(e.ctrlKey || e.metaKey)) return;\n"
            "  if (e.key === 'j') { j(); }\n"
            "});\n")
        put(t62, "app.py", APP_V1)
        git(t62, "init", "-q")
        commit(t62, "baseline")
        run(t62, "--init")
        rc, out = run(t62, "--list")
        ids62 = set(re.findall(r"\bkey\.[\w-]+", out))
        check("RED: mod-k then alt-h derives key.alt-h, not key.mod-alt-h, in either order",
              rc == 0 and "key.alt-h" in ids62 and "key.mod-k" in ids62
              and "key.mod-alt-h" not in ids62, " ".join(sorted(ids62)))
        check("...a modifier read into a local, and an either-guard, still give mod; a "
              "shift beside the local stays shift",
              "key.mod-p" in ids62 and "key.shift-q" in ids62 and "key.mod-j" in ids62
              and "key.mod-shift-q" not in ids62, " ".join(sorted(ids62)))

        # ------------------------------ 63 a CRLF map stays CRLF
        # The pack's review (2026-09-30): on a map committed with CRLF, --reaim's
        # one-pointer edit rewrote every line ending, so the diff was the whole file
        # without --ignore-cr-at-eol, and --write did the same; _rewrite's docstring
        # said "a CR is kept" while read() had already dropped them all.
        print("\n63. a map committed with CRLF stays CRLF under --reaim, --write and --ratchet")
        t63 = os.path.join(tmp, "sixtythree")
        os.makedirs(t63)
        l63 = ["# line %d" % i for i in range(1, 41)]
        put(t63, "big.py", "\r\n".join(l63) + "\r\n")
        put(t63, "app.py", APP_V1.replace("\n", "\r\n"))
        git(t63, "init", "-q")

        def crlf_commit(msg):
            git(t63, "-c", "core.autocrlf=false", "add", "-A")
            git(t63, "-c", "core.autocrlf=false", "-c", "user.name=t",
                "-c", "user.email=t@example.com", "commit", "-q", "-m", msg)

        def crlf_numstat():
            p = subprocess.run(("git", "-c", "core.autocrlf=false", "diff", "--numstat",
                                "--", "FEATURE-MAP.md"), cwd=t63, capture_output=True,
                               timeout=60)
            return p.stdout.decode("utf-8", "replace").strip()

        def crlf_map():
            with open(mp63, "rb") as fh:
                return fh.read()

        crlf_commit("baseline, crlf committed")
        run(t63, "--init")
        mp63 = os.path.join(t63, "FEATURE-MAP.md")
        raw63 = crlf_map().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        a63 = raw63.index(b"<!-- AUTHORED:BEGIN -->") + len(b"<!-- AUTHORED:BEGIN -->")
        b63 = raw63.index(b"<!-- AUTHORED:END -->")
        entry63 = ("\n" + base39 + ENTRY % ("ui.span", "span", "web-ui", "big.py:20-25",
                                            "DRIVEN", "%s @ %s"
                                            % (datetime.date.today(), head(t63)))
                   + "\n").replace("\n", "\r\n").encode("utf-8")
        with open(mp63, "wb") as fh:
            fh.write(raw63[:a63] + entry63 + raw63[b63:])
        crlf_commit("map, crlf committed")
        put(t63, "big.py", "# new 1\r\n# new 2\r\n# new 3\r\n" + "\r\n".join(l63) + "\r\n")
        crlf_commit("three lines above, crlf")
        rc, out = run(t63, "--reaim")
        raw63 = crlf_map()
        check("RED: --reaim on a CRLF map is a one-line diff, without --ignore-cr-at-eol",
              rc == 0 and b"big.py:23-28 @" in raw63
              and raw63.count(b"\r\n") == raw63.count(b"\n")
              and crlf_numstat().startswith("1\t1\t"),
              "%s\nCRLF %d of %d | numstat %s" % (out[-600:], raw63.count(b"\r\n"),
                                                  raw63.count(b"\n"), crlf_numstat()))
        crlf_commit("re-aimed")
        rc, out = run(t63, "--write")
        raw63 = crlf_map()
        check("RED: --write keeps every line of a CRLF map CRLF",
              rc == 0 and raw63.count(b"\r\n") == raw63.count(b"\n")
              and b"<!-- DERIVED:END -->" in raw63,
              "CRLF %d of %d" % (raw63.count(b"\r\n"), raw63.count(b"\n")))
        with open(mp63, "wb") as fh:
            fh.write(raw63.replace(b"<!-- AUTHORED:END -->",
                                   b"### pattern: no-bare-except\r\n\r\n- rule: a bare "
                                   b"except swallows KeyboardInterrupt\r\n- canonical: "
                                   b"app.py:1\r\n- antipattern: ^\\s*except\\s*:\r\n"
                                   b"- ceiling: 3\r\n\r\n<!-- AUTHORED:END -->"))
        crlf_commit("a ceiling to lower")
        rc, out = run(t63, "--ratchet")
        raw63 = crlf_map()
        check("RED: --ratchet lowers the ceiling and changes that one line only",
              rc == 0 and b"- ceiling: 0\r\n" in raw63
              and raw63.count(b"\r\n") == raw63.count(b"\n")
              and crlf_numstat().startswith("1\t1\t"),
              "%s\nCRLF %d of %d | numstat %s" % (out[-600:], raw63.count(b"\r\n"),
                                                  raw63.count(b"\n"), crlf_numstat()))
        rc, out = run(t63, "--check")
        check("...and --check passes on it", rc == 0, out[-1500:])

        # ------------------------------ 64 argparse subcommands are derived
        # The pack's review (2026-09-30): --check said "every surface file parsed"
        # over depgraph.py and mutate.py, whose nine and four argparse subcommands
        # no extractor read; the map carried them by hand as cmd.*. add_parser is
        # read from the syntax tree now, a Parser subclass included, and cmd. is a
        # derived prefix: an authored cmd. entry the code no longer derives fails.
        print("\n64. argparse subcommands are derived as cmd.<file>-<name> on the dev face")
        t64 = os.path.join(tmp, "sixtyfour")
        os.makedirs(t64)
        put(t64, "tool.py", "import argparse\n\n\ndef main():\n"
            "    ap = argparse.ArgumentParser()\n"
            "    sub = ap.add_subparsers(dest='cmd')\n"
            "    p = sub.add_parser('explain', help='what a file imports')\n"
            "    p.add_argument('--graph')\n"
            "    sub.add_parser('hubs')\n"
            "    return ap.parse_args()\n")
        put(t64, "mut.py", "import argparse\n\n\n"
            "class Parser(argparse.ArgumentParser):\n"
            "    def error(self, message):\n        raise SystemExit(2)\n\n\n"
            "def main():\n    ap = Parser()\n"
            "    sub = ap.add_subparsers(dest='cmd', parser_class=Parser)\n"
            "    sub.add_parser('inventory', help='read-only').add_argument('--out')\n"
            "    return ap.parse_args()\n")
        put(t64, "app.py", APP_V1)
        git(t64, "init", "-q")
        commit(t64, "baseline")
        run(t64, "--init")
        with open(os.path.join(t64, "FEATURE-MAP.md"), encoding="utf-8") as fh:
            m64 = fh.read()
        rows64 = {r[0]: r for r in re.findall(
            r"^\| `([^`]+)` \| (\w+) \| cli \| `([^`]+)` \| ([^|]+?) \|$", m64, re.M)}
        check("RED: each add_parser name is a cmd.<file>-<name> capability on the dev "
              "face, at its line, found as a subcommand",
              rows64.get("cmd.tool-explain", ("",) * 4)[1:] == ("dev", "tool.py:7",
                                                                  "subcommand explain")
              and "cmd.tool-hubs" in rows64
              and rows64.get("cmd.mut-inventory", ("",) * 4)[2] == "mut.py:12"
              and "cli.graph" in rows64 and "cli.out" in rows64, " ".join(sorted(rows64)))
        author(t64, base39 + ENTRY % ("cmd.tool-gone", "gone", "cli", "tool.py:9",
                                      "UNKNOWN", ""))
        rc, out = run(t64, "--check")
        check("...and an authored cmd. entry the code no longer derives fails as such",
              rc == 1 and "cmd.tool-gone" in out and "no longer derives" in out,
              out[-2000:])

        # ------------------------------ 65 a declined range, read by its text
        # KiT, 2026-09-30: a job's range of 41 lines in its main module had been
        # authored 33 lines into its function at one commit; --reaim declined it at
        # a later one and printed 811-851 - faithful to those numbers, and nothing said
        # what the lines held, so the reading looked wrong and could not be checked.
        # A declined range now says what its first and last lines hold, whether that
        # text sits where the numbers put it now, and which end changed inside the
        # hunk and so is read as that change's edge, not by its text.
        print("\n65. a range --reaim declines is read back by the text at its ends")
        t65 = os.path.join(tmp, "sixtyfive")
        os.makedirs(t65)
        l65 = (["# line %d" % i for i in range(1, 20)] + ["def poll():"]
               + ["    step %d" % i for i in range(1, 11)]
               + ["# tail %d" % i for i in range(1, 11)])
        put(t65, "mod.py", "\n".join(l65) + "\n")
        put(t65, "app.py", APP_V1)
        git(t65, "init", "-q")
        commit(t65, "baseline")
        base65 = head(t65)
        run(t65, "--init")
        author(t65, base39 + ENTRY % ("job.sync", "sync", "job", "mod.py:22-30", "DRIVEN",
                                      "%s @ %s" % (datetime.date.today(), base65)))
        commit(t65, "map written two lines into the body")
        l65b = (l65[:20] + ["    setup a", "    setup b", "    setup c"] + l65[20:29]
                + ["    step ten"] + l65[30:])
        put(t65, "mod.py", "\n".join(l65b) + "\n")
        commit(t65, "the function grows at its top, and its last line changes")
        rc, out = run(t65, "--reaim")
        line65 = [x for x in out.split("\n") if "job.sync:" in x]
        check("RED: the declined range is printed with its first line's text, where "
              "that text is now",
              rc == 0 and line65 and "mod.py:22-30 -> mod.py:25-33 not moved" in line65[0]
              and 'its first line, "step 2", is at 25 now' in line65[0], out[-1500:])
        check("...and its last line, which changed, is named as the uncertain end",
              line65 and 'its last line, "step 10", changed' in line65[0]
              and "33 is the edge of that change" in line65[0], out[-1500:])

        # ------------------------------ 66 mod in a guard, an alias guard, a block
        # The pack's second review (2026-09-30): 1.4.6 read the either-test only in
        # the shortcut's own condition, an unbraced guard, or a local the condition
        # names, so three common forms lost mod and minted key.k for Ctrl/Cmd+K:
        # a braced guard `if (!(a || b)) { return; }`, a local used in a guard
        # `if (!mod) return;`, and a shortcut nested in `if (a || b) { ... }`. The
        # sibling leak case 62 guards stays shut: a block that has closed, or a
        # negated either-test, gives nothing to what follows it.
        print("\n66. mod from a braced guard, an alias guard and an enclosing block")
        t66 = os.path.join(tmp, "sixtysix")
        os.makedirs(t66)
        put(t66, "static/braces.js", "document.addEventListener('keydown', (e) => {\n"
            "  if (!(e.ctrlKey || e.metaKey)) { return; }\n"
            "  if (e.key === 'b') { open(); }\n"
            "});\n")
        put(t66, "static/aliasguard.js", "document.addEventListener('keydown', (e) => {\n"
            "  const mod = e.ctrlKey || e.metaKey;\n"
            "  if (!mod) return;\n"
            "  if (e.key === 'd') { open(); }\n"
            "});\n")
        put(t66, "static/nested.js", "document.addEventListener('keydown', (e) => {\n"
            "  if (e.ctrlKey || e.metaKey) {\n"
            "    if (e.key === 'f') { open(); }\n"
            "  }\n"
            "  if (e.key === 'z') { zoom(); }\n"
            "});\n")
        put(t66, "static/aliasblock.js", "document.addEventListener('keydown', (e) => {\n"
            "  const cmd = e.ctrlKey || e.metaKey;\n"
            "  if (cmd) {\n"
            "    if (e.key === 'g') { go(); }\n"
            "  }\n"
            "});\n")
        put(t66, "static/negated.js", "document.addEventListener('keydown', (e) => {\n"
            "  if (!(e.ctrlKey || e.metaKey)) {\n"
            "    if (e.key === 'n') { next(); }\n"
            "  }\n"
            "});\n")
        put(t66, "static/altbraces.js", "document.addEventListener('keydown', (e) => {\n"
            "  if (!e.altKey) { return; }\n"
            "  if (e.key === 'w') { w(); }\n"
            "});\n")
        put(t66, "app.py", APP_V1)
        git(t66, "init", "-q")
        commit(t66, "baseline")
        run(t66, "--init")
        rc, out = run(t66, "--list")
        ids66 = set(re.findall(r"\bkey\.[\w-]+", out))
        check("RED: a braced either-guard, a local in a guard and an enclosing either-"
              "block each give mod (key.mod-b, key.mod-d, key.mod-f, key.mod-g)",
              rc == 0 and {"key.mod-b", "key.mod-d", "key.mod-f", "key.mod-g"} <= ids66
              and not ids66 & {"key.b", "key.d", "key.f", "key.g"}, " ".join(sorted(ids66)))
        check("...a braced single-modifier guard gives its modifier (key.alt-w)",
              "key.alt-w" in ids66 and "key.w" not in ids66, " ".join(sorted(ids66)))
        check("...while a closed block and a negated either-block give nothing "
              "(key.z, key.n)",
              "key.z" in ids66 and "key.n" in ids66
              and not ids66 & {"key.mod-z", "key.mod-n"}, " ".join(sorted(ids66)))

        # ------------------------------ 67 a file name is not a host
        # The pack's second review (2026-09-30): 1.4.6 left out any dotted name
        # whose last label was on a host-label list, so Dockerfile.test:3,
        # .env.local:2, deploy.run:4 and index.page:9 - files that do not exist -
        # passed --check silently. A host now needs a host's shape: lower-case
        # labels, a port of two to five digits, and either two dots or one dot
        # before a TLD that is not also a common file extension; localhost and
        # an IPv4 address have no extension and were never pointers.
        print("\n67. a missing file whose extension is a host label is still named")
        t67 = os.path.join(tmp, "sixtyseven")
        os.makedirs(t67)
        put(t67, "big.py", "\n".join("# line %d" % i for i in range(1, 41)) + "\n")
        put(t67, "app.py", APP_V1)
        git(t67, "init", "-q")
        commit(t67, "baseline")
        run(t67, "--init")
        # notes.dev:12 was here until 1.4.9, when dev behind one dot became a
        # host with a port-sized number (case 71); notes.dev:9 keeps dev's file
        # side pinned.
        files67 = ("Dockerfile.test:3", ".env.local:2", "deploy.run:4", "index.page:9",
                   "notes.dev:9")
        hosts67 = ("app.example.com:8443", "example.com:443", "api.staging.test:8080",
                   "localhost:3000", "127.0.0.1:8080")
        author(t67, base39 + "### ui.files\n\n- name: files\n- surface: web-ui\n"
               "- code: big.py:20-25\n- entry: see %s\n- does: a fixture feature\n"
               "- observable: a value read back\n- grade: UNKNOWN\n\n"
               "### ui.hostsonly\n\n- name: hostsonly\n- surface: web-ui\n"
               "- code: big.py:20-25\n- entry: served at %s\n- does: a fixture feature\n"
               "- observable: a value read back\n- grade: UNKNOWN\n\n"
               % (", ".join(files67), ", ".join(hosts67)))
        rc, out = run(t67, "--check")
        check("RED: each missing file with a host-label extension is named",
              rc == 1 and all("ui.files -> %s" % f in out for f in files67), out[-2500:])
        check("...and no host:port is",
              not any(h in out for h in hosts67), out[-2500:])

        # ------------------------------ 68 every flag says what it does
        # The pack's second review (2026-09-30): --record and --live were listed in
        # SKILL.md, but the flags they need (--feature, --grade, --observable, --url
        # ...) were documented nowhere, and --help printed each one bare.
        print("\n68. featuremap.py --help says what every flag does")

        def bare_flags(help_text):
            """Flags --help lists with nothing beside or below them."""
            lines, bare = help_text.split("\n"), []
            for i, ln in enumerate(lines):
                m = re.match(r"^  (--?[\w-]+)", ln)
                if not m or m.group(1) == "-h":
                    continue
                same = re.search(r"\S\s{2,}\S", ln[2:])
                below = i + 1 < len(lines) and re.match(r"^ {10,}\S", lines[i + 1])
                if not same and not below:
                    bare.append(m.group(1))
            return bare

        rc, out = run(tmp, "--help")
        bare68 = bare_flags(out)
        check("RED: --help gives every flag a line of help",
              rc == 0 and "--observable" in out and not bare68, " ".join(bare68) or out[-800:])

        # ------------------------------ 69 a rewritten block, never collapsed
        # verafox 1.4.7 (2026-09-30): its own ten cli.* pointers sat in an argparse
        # block rewritten at 054b1eb. Re-recorded after the rewrite, --reaim carried
        # every one through its proof onto 3414, the block's first line, and said
        # the proof still held. A one-line pointer whose line was rewritten is found
        # by the capability's derived flag, or named "rewritten: re-aim by hand",
        # and --check fails until it is.
        print("\n69. a pointer whose line is rewritten in a block is found by its flag")
        t69 = os.path.join(tmp, "sixtynine")
        os.makedirs(t69)
        cli69 = ("import argparse\n\n\ndef main():\n"
                 "    ap = argparse.ArgumentParser()\n"
                 "    ap.add_argument(\"--alpha\", action=\"store_true\")\n"
                 "    ap.add_argument(\"--beta\", action=\"store_true\")\n"
                 "    ap.add_argument(\"--keep\", action=\"store_true\")\n"
                 "    ap.add_argument(\"--gamma\", action=\"store_true\")\n"
                 "    return ap.parse_args()\n\n\nif __name__ == \"__main__\":\n"
                 "    main()\n")
        put(t69, "cli.py", cli69)
        git(t69, "init", "-q")
        commit(t69, "baseline")
        base69 = head(t69)
        run(t69, "--init")
        ptrs69 = (("cli.alpha", 6), ("cli.beta", 7), ("cli.keep", 8), ("cli.gamma", 9))

        def map69(proof):
            return "".join(ENTRY % (fid, fid[4:], "cli", "cli.py:%d @ %s" % (n, base69),
                                    "DRIVEN", "%s @ %s" % (datetime.date.today(), proof))
                           for fid, n in ptrs69)
        author(t69, map69(base69))
        commit(t69, "map written")
        put(t69, "cli.py", cli69.replace(
            "    ap.add_argument(\"--alpha\", action=\"store_true\")\n"
            "    ap.add_argument(\"--beta\", action=\"store_true\")\n"
            "    ap.add_argument(\"--keep\", action=\"store_true\")\n"
            "    ap.add_argument(\"--gamma\", action=\"store_true\")\n",
            "    # every flag says what it does\n"
            "    ap.add_argument(\"--beta\", action=\"store_true\",\n"
            "                    help=\"the second\")\n"
            "    ap.add_argument(\"--keep\", action=\"store_true\")\n"
            "    ap.add_argument(\"--alpha\", action=\"store_true\",\n"
            "                    help=\"the first\")\n"
            "    ap.add_argument(\"--delta\", action=\"store_true\",\n"
            "                    help=\"gamma, renamed\")\n"))
        commit(t69, "the argparse block rewritten: reordered, one renamed, one kept")
        author(t69, map69(head(t69)))       # re-recorded after the rewrite
        commit(t69, "proofs re-recorded after the rewrite")
        rc, out = run(t69, "--check")
        rows69 = dict((fid, [x for x in out.split("\n") if x.strip().startswith(fid + ":")])
                      for fid, _ in ptrs69)
        check("RED: --check names each rewritten pointer with its flag's line now",
              rc == 1 and rows69["cli.alpha"] and "-> cli.py:10" in rows69["cli.alpha"][0]
              and "REWRITTEN" in rows69["cli.alpha"][0]
              and rows69["cli.beta"] and "REWRITTEN" in rows69["cli.beta"][0]
              and rows69["cli.gamma"] and "rewritten: re-aim by hand" in rows69["cli.gamma"][0],
              out[-3000:])
        rc, out = run(t69, "--reaim")
        said69 = dict((fid, " ".join(x for x in out.split("\n") if fid + ":" in x))
                      for fid, _ in ptrs69)
        with open(os.path.join(t69, "FEATURE-MAP.md"), encoding="utf-8") as fh:
            code69 = dict(re.findall(r"### (cli\.\w+)\n(?:.*\n)*?- code: cli\.py:(\d+)",
                                     fh.read()))
        check("RED: --reaim re-aims a rewritten flag by its derived line, not the "
              "block's first",
              rc == 0 and code69.get("cli.alpha") == "10" and "rewritten" in said69["cli.alpha"]
              and "--alpha" in said69["cli.alpha"], out[-3000:] + "\n" + repr(code69))
        check("...one rewritten in place is named, not kept silently at its number",
              code69.get("cli.beta") == "7" and "rewritten" in said69["cli.beta"],
              out[-3000:])
        check("...a renamed one is declined as rewritten: re-aim by hand, left as written",
              code69.get("cli.gamma") == "9"
              and "rewritten: re-aim by hand" in said69["cli.gamma"], out[-3000:])
        check("...a kept flag whose text did not change moves as before",
              code69.get("cli.keep") == "9", out[-3000:] + "\n" + repr(code69))
        check("...and no rewritten pointer is said to keep its proof",
              not any("still holds" in said69[f] for f in ("cli.alpha", "cli.beta",
                                                            "cli.gamma"))
              and "re-aimed 1 code range(s); the proof on each still holds" in out,
              out[-3000:])
        rc, out = run(t69, "--check")
        rows69 = dict((fid, [x for x in out.split("\n") if x.strip().startswith(fid + ":")])
                      for fid, _ in ptrs69)
        check("...and --check still fails on the one left to re-aim by hand, alone",
              rc == 1 and rows69["cli.gamma"]
              and "rewritten: re-aim by hand" in rows69["cli.gamma"][0]
              and not rows69["cli.alpha"] and not rows69["cli.beta"]
              and not rows69["cli.keep"], out[-3000:])

        # ------------------------------ 70 an old number that holds another flag
        # A Jev client (2026-09-30): cli.check-question's scripts/jev.py:266 was
        # rewritten, and 266 came to hold --ping's line. --reaim and --check left
        # it at 266 without a word. A project in a subfolder of its repository, as
        # that client is, with a proof taken before the rewrite.
        print("\n70. an old line number that now holds another flag is not kept")
        r70 = os.path.join(tmp, "seventy")
        t70 = os.path.join(r70, "tool")
        os.makedirs(t70)
        jev70 = ("\"\"\"a client\"\"\"\nimport argparse\n\n\ndef main(argv=None):\n"
                 "    ap = argparse.ArgumentParser()\n"
                 "    ap.add_argument(\"--ping\", action=\"store_true\")\n"
                 "    ap.add_argument(\"--model\", default=\"pin-1\")\n"
                 "    ap.add_argument(\"--check-question\")\n"
                 "    return ap.parse_args(argv)\n")
        put(t70, "jev.py", jev70)
        git(r70, "init", "-q")
        commit(r70, "baseline")
        base70 = head(r70)
        run(t70, "--init")
        author(t70, ENTRY % ("cli.check-question", "check-question", "cli",
                             "jev.py:9 @ %s" % base70, "DRIVEN",
                             "%s @ %s" % (datetime.date.today(), base70)))
        commit(r70, "map written")
        put(t70, "jev.py", "\"\"\"a client\n\nUpdated: every flag says what it does\"\"\"\n"
            + jev70.split("\n", 1)[1].replace(
                "    ap.add_argument(\"--ping\", action=\"store_true\")\n"
                "    ap.add_argument(\"--model\", default=\"pin-1\")\n"
                "    ap.add_argument(\"--check-question\")\n",
                "    ap.add_argument(\"--ping\", action=\"store_true\",\n"
                "                    help=\"one greeting\")\n"
                "    ap.add_argument(\"--model\", default=\"pin-1\",\n"
                "                    help=\"the model\")\n"
                "    ap.add_argument(\"--check-question\", metavar=\"FILE\",\n"
                "                    help=\"lint offline\")\n"))
        commit(r70, "every flag says what it does")
        rc, out = run(t70, "--check")
        row70 = [x for x in out.split("\n") if x.strip().startswith("cli.check-question: jev.py")]
        check("RED: --check names the pointer whose old line now holds --ping",
              rc == 1 and row70 and "-> jev.py:13" in row70[0] and "REWRITTEN" in row70[0],
              out[-3000:])
        rc, out = run(t70, "--reaim")
        said70 = " ".join(x for x in out.split("\n") if "cli.check-question:" in x)
        with open(os.path.join(t70, "FEATURE-MAP.md"), encoding="utf-8") as fh:
            map70 = fh.read()
        check("RED: --reaim finds it at its flag's line and says its proof predates "
              "the rewrite",
              rc == 0 and "- code: jev.py:13 @ " in map70 and "rewritten" in said70
              and "stale" in said70 and "still holds" not in out, out[-3000:])
        rc, out = run(t70, "--check")
        check("...and --check then fails on its stale proof, not on its pointer",
              rc == 1 and "cli.check-question: verified @ %s" % base70 in out
              and not [x for x in out.split("\n")
                       if x.strip().startswith("cli.check-question: jev.py")],
              out[-3000:])

        # ------------------------------ 71 dev hosts behind one dot
        # The pack's third review (2026-09-30): 1.4.7's one-dot rule knew only
        # common TLDs, so myapp.test:8080, printer.local:631, api.localhost:3000,
        # web.dev:443 and shop.app:8443 were named as missing files. Behind one
        # dot a host may now end in a special-use name or in dev or app, with a
        # two-to-five-digit port and lower-case labels. Where that meets a file
        # name, a path that exists is a file (checked at its line), and a
        # one-digit number, a capital or a leading dot is never a host.
        print("\n71. dev and special-use hosts behind one dot, and the files beside them")
        t71 = os.path.join(tmp, "seventyone")
        os.makedirs(t71)
        l71 = ["# line %d" % i for i in range(1, 41)]
        put(t71, "big.py", "\n".join(l71) + "\n")
        put(t71, "shop.app", "\n".join(l71) + "\n")
        put(t71, "app.py", APP_V1)
        git(t71, "init", "-q")
        commit(t71, "baseline")
        run(t71, "--init")
        hosts71 = ("myapp.test:8080", "printer.local:631", "api.localhost:3000",
                   "web.dev:443", "svc.internal:9000", "site.example:8080",
                   "x.invalid:80", "notes.dev:12")
        files71 = ("Dockerfile.test:3", ".env.local:2", "deploy.run:4", "index.page:9",
                   "notes.dev:9", "Web.dev:443", "Notes.test:20")
        vat71 = "%s @ %s" % (datetime.date.today(), head(t71))
        author(t71, base39
               + "### ui.devhosts\n\n- name: devhosts\n- surface: web-ui\n"
               "- code: big.py:20-25\n- entry: served at %s\n- does: a fixture feature\n"
               "- observable: a value read back\n- grade: UNKNOWN\n\n"
               "### ui.devfiles\n\n- name: devfiles\n- surface: web-ui\n"
               "- code: big.py:20-25\n- entry: see %s\n- does: a fixture feature\n"
               "- observable: a value read back\n- grade: UNKNOWN\n\n"
               % (", ".join(hosts71), ", ".join(files71))
               + ENTRY % ("ui.shopfile", "shopfile", "web-ui", "shop.app:12", "DRIVEN",
                          vat71))
        commit(t71, "map written against these lines")
        rc, out = run(t71, "--check")
        check("RED: no dev or special-use host behind one dot is named as a missing "
              "file (myapp.test:8080, printer.local:631, api.localhost:3000, "
              "web.dev:443)",
              not any(h in out for h in hosts71), out[-2500:])
        check("...while each file-shaped name is, a missing notes.dev:9 among them",
              rc == 1 and all("ui.devfiles -> %s" % f in out for f in files71),
              out[-2500:])
        put(t71, "shop.app", "# new 1\n# new 2\n# new 3\n" + "\n".join(l71) + "\n")
        commit(t71, "three lines added above shop.app:12")
        rc, out = run(t71, "--check")
        check("...and shop.app:12, host-shaped but a file that exists, is checked as "
              "a file: its moved line is named",
              rc == 1 and "shop.app:15" in out and "ui.shopfile" in out, out[-2500:])

        # ------------------------------ 72 one big handler lists in linear time
        # The pack's third review (2026-09-30): 1.4.7 re-read a handler from its
        # top for every shortcut, so one keydown handler holding 2,400 enclosed
        # shortcuts took 40.7 s to --list, against 4.2 s at 1.4.6. 1.4.9 reads
        # each handler once. The bound is generous - about ten times what 1.4.9
        # takes on a slow machine - and 1.4.7's code misses it by far.
        print("\n72. a keydown handler holding 4,800 shortcuts lists in linear time")
        t72 = os.path.join(tmp, "seventytwo")
        os.makedirs(t72)
        body72 = "".join("  if (e.ctrlKey || e.metaKey) {\n    if (e.key === 'k') "
                         "{ f(%d); }\n  }\n  if (e.key === 'q') { g(%d); }\n" % (i, i)
                         for i in range(2400))
        put(t72, "static/big.js", "document.addEventListener('keydown', (e) => {\n"
            + body72 + "});\n")
        put(t72, "app.py", APP_V1)
        git(t72, "init", "-q")
        commit(t72, "baseline")
        t0 = time.time()
        try:
            rc, out = run(t72, "--list")
        except subprocess.TimeoutExpired:
            rc, out = None, "--list was stopped after 120 s"
        took72 = time.time() - t0
        ids72 = set(re.findall(r"\bkey\.[\w-]+", out))
        check("RED: --list over 2,400 enclosed shortcuts and 2,400 plain ones in one "
              "handler takes under 15 s (took %.1f s)" % took72,
              rc == 0 and took72 < 15 and {"key.mod-k", "key.q"} <= ids72
              and "key.k" not in ids72 and "key.mod-q" not in ids72,
              " ".join(sorted(ids72)) + " " + out[-800:])

        # ------------------------------ 73 names a job, not a skill; no one host
        print("\n73. SKILL.md names no other skill and frames itself for no one host")
        agnostic_cases(os.path.join(HERE, os.pardir, "SKILL.md"),
                       ("verafox", "verify-before-done"))

        # ------------------------------ 74 alone, without its optional Jev client
        # The owner, 2026-09-30: each skill is modular and works in any workflow.
        # This one's only dependency, an optional Jev client, serves --judge and the
        # reading at --record; installed alone, everything else must run, and
        # both must say by name what is missing and that it is optional, asking
        # nothing.
        print("\n74. installed alone, it runs, and names the optional client it lacks")
        solo = os.path.join(tmp, "solo", "verafox")
        shutil.copytree(os.path.join(HERE, os.pardir, "templates"),
                        os.path.join(solo, "templates"))
        os.makedirs(os.path.join(solo, "scripts"))
        shutil.copy(FM, os.path.join(solo, "scripts"))
        fm74 = os.path.join(solo, "scripts", "featuremap.py")
        env74 = dict(SAFE, TYPESAFE_API_KEY="test-key-not-real")
        t74 = os.path.join(tmp, "seventyfour")
        os.makedirs(t74)
        fixture(t74)

        def solo74(*args):
            p = subprocess.run([sys.executable, fm74, "--project", t74] + list(args),
                               cwd=t74, capture_output=True, timeout=120, env=env74)
            return p.returncode, p.stdout.decode("utf-8", "replace") + \
                p.stderr.decode("utf-8", "replace")

        rc_i, out_i = solo74("--init")
        author(t74, "### endpoint.orders\n\n- name: orders\n- intent: a customer "
               "finds the order they placed\n- observable: POST /orders returns 201\n\n")
        rc_l, out_l = solo74("--list")
        rc_c, out_c = solo74("--check")
        check("installed alone, --init, --list and --check run without the Jev client",
              rc_i == 0 and rc_l == 0 and rc_c in (0, 1) and "endpoint.orders" in out_l
              and "Traceback" not in out_i + out_l + out_c, (out_i + out_l + out_c)[-1500:])
        rc, out = solo74("--record", "--feature", "endpoint.orders", "--grade", "DRIVEN",
                         "--result", "pass", "--observable", "GET /orders lists it")
        rec74 = os.path.join(t74, ".verify", "proof", "endpoint.orders", "latest.json")
        judged74 = {}
        if os.path.exists(rec74):
            with open(rec74, encoding="utf-8") as fh:
                judged74 = json.load(fh).get("judged") or {}
        check("RED: --record stores the proof and says the optional Jev client is missing, "
              "by name, asking nothing",
              rc == 0 and "recorded" in out
              and "NOT JUDGED the optional Jev client (not included) is not installed"
              in out and "Unavailable" not in out and "not_judged" in judged74, out[-1500:])
        rc, out = solo74("--judge")
        check("RED: --judge refuses by name, exit 2, and says the rest runs without it",
              rc == 2 and "NOT JUDGED the optional Jev client (not included) is not "
              "installed" in out and "everything but --judge" in out, out[-1500:])

    finally:
        _remove(tmp)

    print("\n%d passed, %d failed%s" % (len(PASS), len(FAIL), (
        "; cases %s not run: no Jev client beside this skill (optional, not included)"
        % " and ".join(NOT_RUN)) if NOT_RUN else ""))
    for f in FAIL:
        print("  FAILED: " + f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
