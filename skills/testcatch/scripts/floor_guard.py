# Deps: python3.10+ stdlib, git | Path: scripts | Filename: floor_guard.py | Created: 2026-09-29
# -*- coding: utf-8 -*-
"""floor_guard.py - report every place the test floor went DOWN in a change.

Run:  python -B scripts/floor_guard.py [--repo PATH] [--base REF] [--ledger PATH]
                                       [--ignore GLOB ...]

The floor is everything that can make a run go red: the tests, their
assertions, the thresholds they hold, the checks CI runs, the paths the runner
collects, and the absence of anything that silences a checker. This reads the
change between a base commit and the working tree (staged, unstaged and
untracked alike, because `git diff` alone cannot see a new file) and lists each
place that floor is lower than it was, with its file, line and kind:

  suppression-added         a new noqa, type: ignore, pylint/eslint-disable,
                            @ts-ignore, @ts-expect-error, pragma: no cover ...
  skip-added                a new pytest skip/skipif/xfail, unittest.skip,
                            it/describe/test.skip, xit, .only, t.Skip ...
  test-file-deleted         a test file gone
  test-file-renamed-away    a test file renamed to a name the runner no longer
                            collects (staged or not)
  test-removed              a test function gone by name (a rename whose body is
                            kept is not a removal; a rename with a new body is,
                            and its line names the newcomer)
  assertions-dropped        fewer assertion calls in a test file than before
  threshold-loosened        a tolerance, timeout, retry count, bound or ceiling
                            in a test, test config or CI file that got looser,
                            read by its comparator or keyword; or a floor
                            (fail_under, --cov-fail-under, min ...) taken out
  ci-step-removed           a CI or pre-commit step, a GitLab script line or a
                            package.json check script that ran a check, gone -
                            with its workflow deleted or renamed away too
  ci-step-softened          continue-on-error, allow_failure, if: false,
                            `|| true`, a test script stubbed to echo
  test-path-excluded        --ignore, --deselect, -k not ... added in test config
                            or on a CI line; norecursedirs, collect_ignore,
                            testPathIgnorePatterns, omit, exclude ... added in
                            test config; testpaths / python_files / testMatch
                            that lost an entry

Tightening is silent; only a drop is printed. A count that only moved (a
suppression reindented, a CI step reordered) is not a drop: every kind is a
per-file count at base against the same count now, never a diff line read on
its own. Numbers in product code are not the floor: a product timeout raised
is a product decision, not a test made easier.

Exit codes: 0 the floor held; 1 it dropped (each drop listed); 2 it could not
be checked (not a repository, no base, a git error, a bad ledger, a bad flag).
A 2 is never read as clean: the last line is always
`RESULT: PASS|FAIL|ERROR ...`.

Read-only: git runs with GIT_OPTIONAL_LOCKS=0 and diff.autoRefreshIndex off,
so not even .git/index is rewritten; a file whose timestamp moved but whose
text did not is not counted.

The ratchet: a known drop is grandfathered only by a ledger entry with a
verdict and a reason. `.floor-guard.json` at the repository root is read when
it exists, or the file named by --ledger:

  {"items": [{"kind": "test-removed", "file": "tests/test_calc.py",
              "what": "test_sub", "verdict": "intended",
              "why": "sub() left with the feature in ticket 80"}],
   "ceiling": 1, "ignore": ["vendor/*"], "about": "why these drops are known"}

`what` is the name, the line text or the counts exactly as the guard prints
them ("file deleted" for a deleted test file); each dropped line prints its
ledger form. An entry with no reason fails. An entry that matches no drop in
the change is stale and fails: the ledger only shrinks. The same entry twice
fails. `ceiling`, when given, is a whole number and only comes down.
`verdicts` may name the ledger's own verdicts and what each needs; the
defaults are intended, moved (needs `by`), replaced (needs `by`) and deferred.
`about`, when given, is text for the reader - what the ledger is for - and
the guard never reads it. Those five keys are the ledger's whole vocabulary: a
key it does not take, or one of the wrong type (a ceiling that is not a whole
number included), is a bad ledger, and the run ends in RESULT: ERROR naming it
(exit 2) rather than reading past it.
Canonical for the shape: a production-supersession ledger, where a test fails on
any silent loss unless a fixture names the verdict and the reason.

Bounds, stated so a green run is read for what it is: names are read for
Python (`def test_*`), JavaScript and TypeScript (`it(`/`test(` with a string
title) and Go (`func Test*`); a threshold whose direction cannot be read from a
comparator or a keyword (`== 5` becoming `== 6`) is not reported, and a number
is compared only when the rest of its line is unchanged; a floor is known by
its key (fail_under, min, coverage ...), so a coverage threshold keyed only
`lines` is not; a CI step is known by its key and the first check it names
(`run: pytest -q -x` is still `run:pytest`), so a second check dropped from
the same line is not seen; a list of test paths, and a check inside a
multi-line `run: |` block, is read on its first line only; suppressions and skips are
not read in prose (.md, .rst, .txt, .adoc), but are read in string literals,
so a file of fixtures like floor_guard_selftest.py reads as suppressions and
belongs in the ledger's `ignore`; a rename of a JavaScript test is matched by
its lines up to the closing `})` at the same indent; a file with a NUL byte is
skipped and said so; a file over 1 MB is counted but not line-paired, and said
so. The patterns are regular expressions over lines, chosen to catch the cheap
road to green, not a determined hand.

The floor-guard contract - diff scoped, five moves, exit 0/1/2 where 2 never
reads as clean - is from addyosmani/agent-skills,
skills/constraint-driven-development/references/floor-guard.md at 2686b620fc1fed2e8f60c704839c766b8594c6b6 (MIT);
this is an original build of it in Python, with a ratchet ledger of the shape
above.
"""
import argparse
import difflib
import fnmatch
import json
import os
import re
import subprocess
import sys
from collections import Counter

VERSION = "1.0"

KINDS = ("suppression-added", "skip-added", "test-file-deleted",
         "test-file-renamed-away", "test-removed", "assertions-dropped",
         "threshold-loosened", "ci-step-removed", "ci-step-softened",
         "test-path-excluded")

DEFAULT_VERDICTS = {
    "intended": "the drop is the point of the change; 'why' says what left with it",
    "moved": "the test or check lives elsewhere now; 'by' names where",
    "replaced": "a stronger check took its place; 'by' names it",
    "deferred": "put back by a named commit or date; 'why' names it",
}
NEEDS_BY = ("moved", "replaced")

LARGE = 1024 * 1024
DELETED = "file deleted"


class GitError(Exception):
    pass


# ------------------------------------------------------------------ patterns

SUPPRESS = (
    ("noqa", re.compile(r"#\s*noqa\b")),
    ("type: ignore", re.compile(r"#\s*type:\s*ignore\b")),
    ("pylint: disable", re.compile(r"#\s*pylint:\s*disable")),
    ("pragma: no cover", re.compile(r"#\s*pragma:\s*no\s*cover\b")),
    ("mypy: ignore-errors", re.compile(r"#\s*mypy:\s*ignore-errors")),
    ("nosec", re.compile(r"#\s*nosec\b")),
    ("eslint-disable", re.compile(r"eslint-disable")),
    ("@ts-ignore", re.compile(r"@ts-ignore\b")),
    ("@ts-expect-error", re.compile(r"@ts-expect-error\b")),
    ("@ts-nocheck", re.compile(r"@ts-nocheck\b")),
    ("biome-ignore", re.compile(r"biome-ignore\b")),
    ("istanbul ignore", re.compile(r"istanbul\s+ignore\b")),
    ("nolint", re.compile(r"//\s*nolint\b")),
    ("allow(...)", re.compile(r"#\[allow\(")),
)

SKIPS = (
    ("pytest.mark.skip", re.compile(r"pytest\.mark\.skip\b(?!if)")),
    ("pytest.mark.skipif", re.compile(r"pytest\.mark\.skipif\b")),
    ("pytest.mark.xfail", re.compile(r"pytest\.mark\.xfail\b")),
    ("pytest.skip()", re.compile(r"\bpytest\.skip\s*\(")),
    ("unittest.skip", re.compile(
        r"\bunittest\.skip\w*\b|@skip(?:If|Unless)?\s*\(|\bskipTest\s*\(")),
    ("it/describe/test.skip", re.compile(
        r"\b(?:it|describe|test|context|suite)\.skip\s*\(")),
    ("it/describe/test.todo", re.compile(r"\b(?:it|describe|test)\.todo\s*\(")),
    ("xit/xdescribe/xtest", re.compile(r"\b(?:xit|xdescribe|xtest|xcontext)\s*\(")),
    (".only", re.compile(
        r"\b(?:it|describe|test|context)\.only\s*\(|\b(?:fit|fdescribe)\s*\(")),
    ("t.Skip", re.compile(r"\bt\.Skip(?:f|Now)?\s*\(")),
    ("#[ignore]", re.compile(r"#\[ignore\]")),
)

PROSE_EXT = (".md", ".markdown", ".rst", ".txt", ".adoc")

ASSERT = re.compile(
    r"(?<![\w.])assert\w*\b(?!\s*=)|\.assert\w*\s*\(|\bexpect\s*\(|\.should\b"
    r"|\bt\.(?:Error|Errorf|Fatal|Fatalf|Fail|FailNow)\s*\(|\bpytest\.raises\s*\(")

PY_TEST = re.compile(r"^(\s*)(?:async\s+)?def\s+(test\w*)\s*\(")
JS_TEST = re.compile(
    r"^(\s*)(?:it|test)(?:\.(?:skip|only|todo|failing|concurrent))?"
    r"(?:\.each\(.*?\))?\s*\(\s*(['\"`])((?:(?!\2).)*)\2")
GO_TEST = re.compile(r"^()func\s+(Test\w+)\s*\(")

TEST_DIR = re.compile(r"(^|/)(tests?|__tests__|specs?|testing)(/|$)")
TEST_NAME = re.compile(
    r"(^|/)(test_[^/]*\.py|[^/]*_test\.(py|go)|[^/]*\.(test|spec)\.[cm]?[jt]sx?"
    r"|[^/]*Tests?\.(java|kt|cs|swift)|[^/]*_spec\.rb)$")
CODE_EXT = (".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".rb",
            ".java", ".kt", ".cs", ".rs", ".swift")
NOT_A_TEST = ("conftest.py", "__init__.py", "setup.py")

CI_FILE = re.compile(
    r"(^|/)(\.github/workflows/[^/]+\.ya?ml|\.gitlab-ci\.ya?ml|\.circleci/config\.ya?ml"
    r"|azure-pipelines\.ya?ml|bitbucket-pipelines\.ya?ml|\.travis\.ya?ml|Jenkinsfile"
    r"|\.pre-commit-config\.ya?ml|package\.json)$")
# A step: a run/uses/script/id/sh/bat/entry/command key, or a plain YAML list
# item that is not itself a mapping (GitLab's `script:` lines, `- pytest -q`).
CI_STEP = re.compile(
    r"^\s*-?\s*(run|uses|script|id|sh|bat|entry|command)\s*:?\s*(.+)$"
    r"|^\s*-\s+(?![\w.-]+\s*:(?:\s|$))(.+)$")
# A package.json script that runs a check; a dependency version is not one.
PKG_SCRIPT = re.compile(
    r"^\"((?:pre|post)?(?:test|lint|typecheck|type-check|check|verify|coverage|e2e|ci)"
    r"[\w:.-]*)\"\s*:\s*\"(?![\^~<>=*\d]|workspace:|npm:|file:|link:|git)(.*)\"$")
CHECK_WORD = re.compile(
    r"\b(tests?|pytest|unittest|jest|vitest|mocha|karma|cypress|playwright|lint|eslint"
    r"|ruff|flake8|pylint|mypy|pyright|tsc|typecheck|check|coverage|cov|verify"
    r"|selftest|audit|spec|bandit|semgrep|gitleaks|pre-commit)\b", re.I)
SOFTEN = (
    ("continue-on-error", re.compile(r"continue-on-error:\s*true\b")),
    ("allow_failure", re.compile(r"allow_failure:\s*true\b|allowFailure")),
    ("if: false", re.compile(r"\bif:\s*(?:false\b|\$\{\{\s*false\s*\}\})")),
    ("|| true", re.compile(r"\|\|\s*(?:true|exit\s+0)\b")),
    ("set +e", re.compile(r"\bset\s+\+e\b")),
    ("--no-verify", re.compile(r"--no-verify\b")),
    ("test script stubbed", re.compile(
        r"\"(?:test|lint|typecheck|check[\w:-]*|verify|e2e|coverage)\"\s*:\s*\"\s*"
        r"(?:echo\b|exit\s+0|true\b|:\s*\")")),
)

TEST_CONFIG = re.compile(
    r"(^|/)(pytest\.ini|pyproject\.toml|setup\.cfg|tox\.ini|conftest\.py|\.coveragerc"
    r"|codecov\.ya?ml|jest\.config\.[cm]?[jt]s|vitest\.config\.[cm]?[jt]s"
    r"|vite\.config\.[cm]?[jt]s|playwright\.config\.[cm]?[jt]s|\.mocharc(\.\w+)?"
    r"|karma\.conf\.js|package\.json|\.nycrc(\.\w+)?)$")
# Flags that narrow a run, read in test config and on CI lines alike.
EXCLUDE_FLAGS = (
    ("--ignore", re.compile(r"--ignore(?:-glob)?[=\s]")),
    ("--deselect", re.compile(r"--deselect[=\s]")),
    ("-p no:", re.compile(r"-p\s+no:")),
    ("-k not", re.compile(r"-k\s*[\"']?\s*not\b")),
    ("--no-cov", re.compile(r"--no-cov\b")),
)
# Keys that narrow a run, read in test config only (a CI matrix has `exclude:`).
EXCLUDE_KEYS = (
    ("norecursedirs", re.compile(r"\bnorecursedirs\b")),
    ("collect_ignore", re.compile(r"\bcollect_ignore")),
    ("testPathIgnorePatterns", re.compile(r"\btestPathIgnorePatterns\b")),
    ("coveragePathIgnorePatterns", re.compile(r"\bcoveragePathIgnorePatterns\b")),
    ("testIgnore", re.compile(r"\btestIgnore\b")),
    ("omit", re.compile(r"^\s*omit\s*=")),
    ("exclude", re.compile(r"^\s*exclude\s*[=:]|\bexclude\s*:\s*\[")),
)
# A list of what the runner collects; an entry lost narrows the floor.
COLLECTS = re.compile(
    r"^\s*[\"']?(testpaths|python_files|python_classes|python_functions|testMatch"
    r"|roots|specPattern|include)[\"']?\s*[=:]\s*(.*)$")
TOKENS = re.compile(r"[\s,\[\]()'\"]+")

NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w.])")
KEY_BEFORE = re.compile(r"([A-Za-z_][\w\-.]*)\s*(?:[=:(,\[]|=>)?\s*$")
UP_WORDS = {"timeout", "timeouts", "retry", "retries", "attempts", "reruns", "tol",
            "tolerance", "atol", "rtol", "eps", "epsilon", "delta", "margin", "slack",
            "leeway", "deadline", "abs", "rel", "allowed", "budget", "max", "maximum",
            "upper", "ceiling", "flaky"}
DOWN_WORDS = {"places", "precision", "under", "min", "minimum", "lower", "floor",
              "coverage", "required", "least"}


# ------------------------------------------------------------------- helpers

GIT_ENV = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")


def git(root, *args, ok=(0,)):
    try:
        p = subprocess.run(("git", "-c", "diff.autoRefreshIndex=false") + args,
                           cwd=root, capture_output=True, timeout=300, env=GIT_ENV)
    except OSError as e:
        raise GitError("git could not run: %s" % e)
    if p.returncode not in ok:
        err = p.stderr.decode("utf-8", "replace").strip() or "exit %d" % p.returncode
        raise GitError("git %s: %s" % (" ".join(args[:2]), err.splitlines()[0]))
    return p.stdout


def text_of(data):
    return data.decode("utf-8", "replace")


def is_binary(data):
    return b"\0" in data[:8192]


def is_test(path):
    base = path.rsplit("/", 1)[-1]
    if base in NOT_A_TEST:
        return False
    if TEST_NAME.search(path):
        return True
    return bool(TEST_DIR.search(path)) and base.endswith(CODE_EXT)


def is_ci(path):
    return bool(CI_FILE.search(path))


def is_config(path):
    return bool(TEST_CONFIG.search(path))


def segments(key):
    key = key.rsplit(".", 1)[-1].replace("-", "_")
    key = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    return {s for s in key.lower().split("_") if s}


def direction(line, m):
    """How the number at m loosens: 'up' (a max, a tolerance, a timeout), 'down'
    (a min, places, coverage), or None when the line does not say."""
    b = line[:m.start()].rstrip()
    a = line[m.end():].lstrip()
    for op, d in ((">=", "down"), ("<=", "up"), ("==", None), ("!=", None),
                  (">", "down"), ("<", "up")):
        if b.endswith(op):
            return d
    for op, d in ((">=", "up"), ("<=", "down"), ("==", None), ("!=", None),
                  (">", "up"), ("<", "down")):
        if a.startswith(op):
            return d
    km = KEY_BEFORE.search(b)
    if not km:
        return None
    segs = segments(km.group(1))
    up, down = bool(segs & UP_WORDS), bool(segs & DOWN_WORDS)
    if up and not down:
        return "up"
    if down and not up:
        return "down"
    return None


def counted(lines, rx):
    """Stripped text of every line rx matches, in order (comment lines too:
    a suppression is a comment)."""
    return [ln.strip() for ln in lines if rx.search(ln)]


def new_matches(old_lines, new_lines, rx):
    """Lines in new that rx matches and that old did not already carry, as
    (lineno, text). A line that only moved is matched off against old."""
    have = Counter(counted(old_lines, rx))
    out = []
    for i, ln in enumerate(new_lines, 1):
        if rx.search(ln):
            s = ln.strip()
            if have[s] > 0:
                have[s] -= 1
            else:
                out.append((i, s))
    return out


def py_body(lines, i, indent):
    j = i + 1
    while j < len(lines):
        ln = lines[j]
        if ln.strip() and (len(ln) - len(ln.lstrip())) <= len(indent):
            break
        j += 1
    return lines[i:j]


def js_body(lines, i, indent):
    j = i + 1
    while j < len(lines):
        ln = lines[j]
        if ln.strip().startswith("})") and (len(ln) - len(ln.lstrip())) == len(indent):
            return lines[i:j + 1]
        j += 1
    return lines[i:i + 1]


def go_body(lines, i, _indent):
    j = i + 1
    while j < len(lines):
        if lines[j].rstrip() == "}":
            return lines[i:j + 1]
        j += 1
    return lines[i:i + 1]


def tests_in(path, lines):
    """[(name, normalized body, lineno)] for the tests this file declares."""
    ext = os.path.splitext(path)[1]
    if ext == ".py":
        rx, body = PY_TEST, py_body
    elif ext in (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"):
        rx, body = JS_TEST, js_body
    elif ext == ".go":
        rx, body = GO_TEST, go_body
    else:
        return []
    out = []
    for i, ln in enumerate(lines):
        m = rx.match(ln)
        if not m:
            continue
        indent, name = m.group(1), m.group(m.lastindex)
        norm = "\n".join(x.replace(name, "\x00") for x in body(lines, i, indent))
        out.append((name, norm, i + 1))
    return out


def assertions(lines):
    n = 0
    for ln in lines:
        s = ln.lstrip()
        if s.startswith(("#", "//", "*", "/*")):
            continue
        n += len(ASSERT.findall(ln))
    return n


def ci_steps(path, lines):
    """[(lineno, identity, text)] for each line of a CI file that runs a check.
    A step is known by its key and the first check it names (`run:pytest`), so
    a flag added to it is not a removal; a package.json script by its name."""
    out = []
    pkg = path.rsplit("/", 1)[-1] == "package.json"
    for i, ln in enumerate(lines, 1):
        s = ln.strip().rstrip(",").strip()
        if not s or s.startswith("#"):
            continue
        if pkg:
            m = PKG_SCRIPT.match(s)
            if m:
                out.append((i, m.group(1), s))
            continue
        m = CI_STEP.match(ln)
        w = m and CHECK_WORD.search(m.group(2) or m.group(3) or "")
        if w:
            out.append((i, "%s:%s" % (m.group(1) or "-", w.group(1).lower()), s))
    return out


def floors(lines):
    """[(lineno, text, key)] for each line holding a number its key calls a floor."""
    out = []
    for i, ln in enumerate(lines, 1):
        for m in NUM.finditer(ln):
            if direction(ln, m) == "down":
                km = KEY_BEFORE.search(ln[:m.start()].rstrip())
                out.append((i, ln.strip(), km.group(1) if km else ""))
                break
    return out


def collects(lines):
    """{key: (lineno, set of entries)} for the lists of what the runner collects."""
    out = {}
    for i, ln in enumerate(lines, 1):
        m = COLLECTS.match(ln)
        if m:
            toks = {t for t in TOKENS.split(m.group(2)) if t}
            line, have = out.get(m.group(1), (i, set()))
            out[m.group(1)] = (i, have | toks)
    return out


class Finding:
    def __init__(self, kind, file, line, at_base, what, detail):
        self.kind, self.file, self.line, self.at_base = kind, file, line, at_base
        self.what, self.detail = what, detail
        self.ledger = None

    @property
    def key(self):
        return (self.kind, self.file, self.what)

    def loc(self):
        if self.line is None:
            return self.file + ("(base)" if self.at_base else "")
        return "%s:%d%s" % (self.file, self.line, "(base)" if self.at_base else "")

    def form(self):
        return json.dumps({"kind": self.kind, "file": self.file, "what": self.what,
                           "verdict": "", "why": ""}, ensure_ascii=False)

    def __str__(self):
        return "  %-24s%s  %s" % (self.kind, self.loc(), self.detail)


# ------------------------------------------------------------------ analysis

def analyze(path, old, new, findings, notes):
    """old and new are the file's text at base and now ('' when absent, or
    when the file was renamed to a name that no longer does its job)."""
    ol, nl = old.splitlines(), new.splitlines()
    test, ci, cfg = is_test(path), is_ci(path), is_config(path)

    if not path.lower().endswith(PROSE_EXT):
        for label, rx in SUPPRESS:
            for i, s in new_matches(ol, nl, rx):
                findings.append(Finding("suppression-added", path, i, False, s,
                                        "%s  (%s)" % (s, label)))
        for label, rx in SKIPS:
            for i, s in new_matches(ol, nl, rx):
                findings.append(Finding("skip-added", path, i, False, s,
                                        "%s  (%s)" % (s, label)))

    if test:
        ot, nt = tests_in(path, ol), tests_in(path, nl)
        old_names = Counter(n for n, _, _ in ot)
        new_names = Counter(n for n, _, _ in nt)
        added = [[n, b] for n, b, _ in nt if new_names[n] > old_names.get(n, 0)]
        gone = []
        for name, body, lineno in ot:
            if new_names.get(name, 0) >= old_names[name]:
                continue
            old_names[name] -= 1
            twin = next((a for a in added if a[1] == body), None)
            if twin is not None:
                added.remove(twin)          # renamed, body kept: not a removal
                continue
            gone.append((name, lineno))
        fresh = [n for n, _ in added]
        hint = ""
        if fresh:
            hint = "; new here: " + ", ".join(fresh[:3]) + (
                " +%d more" % (len(fresh) - 3) if len(fresh) > 3 else "")
        for name, lineno in gone:
            findings.append(Finding("test-removed", path, lineno, True, name,
                                    "%s (tests %d -> %d%s)" % (name, len(ot), len(nt), hint)))
        oa, na = assertions(ol), assertions(nl)
        if na < oa:
            what = "%d -> %d" % (oa, na)
            findings.append(Finding("assertions-dropped", path, None, False, what,
                                    "assertions " + what))

    if ci:
        for label, rx in SOFTEN:
            for i, s in new_matches(ol, nl, rx):
                findings.append(Finding("ci-step-softened", path, i, False, s,
                                        "%s  (%s)" % (s, label)))
        have = Counter(k for _, k, _ in ci_steps(path, nl))
        for i, k, s in ci_steps(path, ol):
            if have[k] > 0:
                have[k] -= 1
            else:
                findings.append(Finding("ci-step-removed", path, i, True, s, s))

    if ci or cfg:
        for label, rx in EXCLUDE_FLAGS:
            for i, s in new_matches(ol, nl, rx):
                findings.append(Finding("test-path-excluded", path, i, False, s,
                                        "%s  (%s)" % (s, label)))

    if cfg:
        for label, rx in EXCLUDE_KEYS:
            for i, s in new_matches(ol, nl, rx):
                findings.append(Finding("test-path-excluded", path, i, False, s,
                                        "%s  (%s)" % (s, label)))
        now = collects(nl)
        for key, (_, was) in collects(ol).items():
            if key not in now:
                continue                    # the default collects instead: not read
            line, has = now[key]
            lost = sorted(was - has)
            if lost:
                what = "%s no longer lists %s" % (key, ", ".join(lost))
                findings.append(Finding("test-path-excluded", path, line, False, what,
                                        "%s  (%s)" % (what, nl[line - 1].strip())))

    if ci or cfg:
        have = Counter(ln.strip() for ln in nl)
        for i, s, key in floors(ol):
            if have[s] > 0:
                have[s] -= 1
                continue
            if key and any(re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(key), ln)
                           for ln in nl):
                continue                    # still set: a changed value is paired below
            what = "%s -> (removed)" % s
            findings.append(Finding("threshold-loosened", path, i, True, what, what))

    if not (test or ci or cfg):
        return                              # product code's numbers are not the floor
    if not old or not new:
        return
    if len(old) > LARGE or len(new) > LARGE:
        notes.append("%s: over 1 MB, counted but not line-paired" % path)
        return
    sm = difflib.SequenceMatcher(None, ol, nl, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "replace":
            continue
        used = set()
        for i in range(i1, i2):
            osk = NUM.sub("#", ol[i]).strip()
            if "#" not in osk:
                continue
            for j in range(j1, j2):
                if j in used or NUM.sub("#", nl[j]).strip() != osk:
                    continue
                used.add(j)
                for om, nm in zip(NUM.finditer(ol[i]), NUM.finditer(nl[j])):
                    try:
                        ov, nv = float(om.group()), float(nm.group())
                    except ValueError:
                        continue
                    if ov == nv:
                        continue
                    d = direction(nl[j], nm)
                    if (d == "up" and nv > ov) or (d == "down" and nv < ov):
                        what = "%s -> %s" % (ol[i].strip(), nl[j].strip())
                        findings.append(Finding("threshold-loosened", path, j + 1,
                                                False, what, what))
                        break
                break


# --------------------------------------------------------------------- ledger

LEDGER_KEYS = ("about", "items", "verdicts", "ceiling", "ignore")


def load_ledger(path):
    """The ledger as an object with the keys it takes, each of its type, or a
    GitError (exit 2, never clean). {"drops": [...]} used to read as an empty
    ledger, and the drop it meant to grandfather failed as new (the pack's
    review, 2026-09-30); a ceiling in words, true or -1 was a ledger problem,
    exit 1, where the docs promise exit 2 (its second review, the same day)."""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        raise GitError("ledger %s could not be read: %s" % (path, e))
    if not isinstance(doc, dict):
        raise GitError("ledger %s is not an object" % path)
    unknown = sorted(k for k in doc if k not in LEDGER_KEYS)
    if unknown:
        raise GitError("ledger %s: key %s is not one the guard takes - it takes %s"
                       % (path, ", ".join(repr(k) for k in unknown), ", ".join(LEDGER_KEYS)))
    if not isinstance(doc.get("items", []), list):
        raise GitError("ledger %s: items is not a list" % path)
    if "verdicts" in doc and not (isinstance(doc["verdicts"], dict) and all(
            isinstance(k, str) and isinstance(v, str) for k, v in doc["verdicts"].items())):
        raise GitError("ledger %s: verdicts is not an object of name -> what it needs"
                       % path)
    if "ignore" in doc and not (isinstance(doc["ignore"], list)
                                and all(isinstance(g, str) for g in doc["ignore"])):
        raise GitError("ledger %s: ignore is not a list of path patterns" % path)
    if "about" in doc and not isinstance(doc["about"], str):
        raise GitError("ledger %s: about is not text" % path)
    if "ceiling" in doc and not (isinstance(doc["ceiling"], int)
                                 and not isinstance(doc["ceiling"], bool)
                                 and doc["ceiling"] >= 0):
        raise GitError("ledger %s: ceiling %r is not a whole number"
                       % (path, doc["ceiling"]))
    return doc


def apply_ledger(doc, name, findings):
    """Mark grandfathered findings; return the list of ledger problems."""
    problems = []
    verdicts = doc.get("verdicts") or DEFAULT_VERDICTS
    items = doc.get("items", [])
    by_key = {}
    for f in findings:
        by_key.setdefault(f.key, []).append(f)
    seen = {}
    for n, it in enumerate(items, 1):
        if not isinstance(it, dict):
            problems.append("item %d: not an object" % n)
            continue
        key = (it.get("kind"), it.get("file"), it.get("what"))
        tag = "item %d (%s %s %s)" % (n, it.get("kind"), it.get("file"), it.get("what"))
        if key in seen:
            problems.append("%s: the same drop twice (as item %d) - delete one" % (
                tag, seen[key]))
            continue
        seen[key] = n
        bad = False
        if it.get("kind") not in KINDS:
            problems.append("%s: kind is not one of %s" % (tag, ", ".join(KINDS)))
            bad = True
        if it.get("verdict") not in verdicts:
            problems.append("%s: verdict %r is not one of %s" % (
                tag, it.get("verdict"), ", ".join(sorted(verdicts))))
            bad = True
        if not str(it.get("why", "")).strip():
            problems.append("%s: no reason - a grandfathered drop needs its verdict "
                            "and why" % tag)
            bad = True
        if it.get("verdict") in NEEDS_BY and not str(it.get("by", "")).strip():
            problems.append("%s: verdict %r needs 'by' naming where it lives now"
                            % (tag, it.get("verdict")))
            bad = True
        hits = by_key.get(key, [])
        if not hits:
            problems.append("%s: matches no drop in this change - delete it; the "
                            "ledger only shrinks" % tag)
            continue
        if bad:
            continue
        for f in hits:
            f.ledger = "[%s] %s%s" % (it["verdict"], str(it["why"]).strip(),
                                      ("  by: " + str(it["by"])) if it.get("by") else "")
    if "ceiling" in doc:
        ceiling = doc["ceiling"]                  # a whole number: load_ledger
        if len(items) > ceiling:
            problems.append("%d items > ceiling %d - the ceiling only comes down; "
                            "raise it only with the operator's word" % (len(items), ceiling))
        elif len(items) < ceiling:
            print("  ledger %s: %d items under a ceiling of %d - lower it to %d"
                  % (name, len(items), ceiling, len(items)))
    return problems


# ----------------------------------------------------------------------- main

def resolve_base(root, base):
    if base is None:
        for cand in ("@{upstream}", "main", "master"):
            try:
                git(root, "rev-parse", "--verify", "--quiet", cand + "^{commit}")
            except GitError:
                continue
            base = cand
            break
        else:
            raise GitError("no upstream, main or master to compare with: give --base <ref>")
    try:
        mb = text_of(git(root, "merge-base", base, "HEAD")).strip()
    except GitError as e:
        raise GitError("base %r: %s" % (base, e))
    if not mb:
        raise GitError("no merge base between %r and HEAD" % base)
    return base, mb


def changed_files(root, mb):
    raw = text_of(git(root, "diff", "--name-status", "-M", "-z", mb, "--"))
    toks = raw.split("\0")
    out, k = [], 0
    while k < len(toks) and toks[k]:
        st = toks[k]
        if st[0] in "RC":
            out.append((st[0], toks[k + 1], toks[k + 2]))
            k += 3
        else:
            out.append((st[0], toks[k + 1], toks[k + 1]))
            k += 2
    untracked = [t for t in text_of(git(root, "ls-files", "--others",
                                        "--exclude-standard", "-z")).split("\0") if t]
    return out, untracked


def read_now(root, path):
    p = os.path.join(root, *path.split("/"))
    try:
        with open(p, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def read_base(root, mb, path):
    return git(root, "show", "%s:%s" % (mb, path))


def same_text(a, b):
    return a == b or text_of(a).splitlines() == text_of(b).splitlines()


def guard(args):
    if not os.path.isdir(args.repo):
        raise GitError("not a folder: %s" % args.repo)
    try:
        root = text_of(git(args.repo, "rev-parse", "--show-toplevel")).strip()
    except GitError:
        raise GitError("not a git repository: %s" % os.path.abspath(args.repo))
    base, mb = resolve_base(root, args.base)

    ledger_path = args.ledger or os.path.join(root, ".floor-guard.json")
    ledger = None
    if args.ledger or os.path.isfile(ledger_path):
        ledger = load_ledger(ledger_path)
    ledger_rel = os.path.relpath(ledger_path, root).replace(os.sep, "/")
    ignores = list(args.ignore or []) + list((ledger or {}).get("ignore") or [])

    def ignored(path):
        return path == ledger_rel or any(fnmatch.fnmatch(path, g) for g in ignores)

    changes, untracked = changed_files(root, mb)
    findings, notes, binaries = [], [], []
    pending_deleted = []
    consumed = set()
    differ = 0

    for st, old_path, new_path in changes:
        if st == "D":
            if ignored(old_path):
                continue
            differ += 1
            if is_test(old_path) or is_ci(old_path) or is_config(old_path):
                pending_deleted.append(old_path)
            continue
        if ignored(new_path):
            continue
        old = b"" if st == "A" else read_base(root, mb, old_path)
        new = read_now(root, new_path)
        if new is None:
            new = b""
        if st not in "RC" and same_text(old, new):
            continue                        # a moved timestamp, not a change
        differ += 1
        if is_binary(old) or is_binary(new):
            binaries.append(new_path)
            continue
        if st in "RC" and is_test(old_path) and not is_test(new_path):
            findings.append(Finding("test-file-renamed-away", old_path, None, True,
                                    new_path, "%s -> %s" % (old_path, new_path)))
            continue
        if st in "RC" and ((is_ci(old_path) and not is_ci(new_path))
                           or (is_config(old_path) and not is_config(new_path))):
            analyze(old_path, text_of(old), "", findings, notes)
            continue
        analyze(new_path, text_of(old), text_of(new), findings, notes)

    for old_path in pending_deleted:
        old = read_base(root, mb, old_path)
        match = None
        for u in untracked:
            if u in consumed or ignored(u):
                continue
            if read_now(root, u) == old:
                match = u
                break
        if match is not None:
            consumed.add(match)
        if is_test(old_path):
            if match is None:
                findings.append(Finding("test-file-deleted", old_path, None, True,
                                        DELETED, DELETED))
            elif is_test(match):
                analyze(match, text_of(old), text_of(old), findings, notes)
            else:
                findings.append(Finding("test-file-renamed-away", old_path, None, True,
                                        match, "%s -> %s (not staged)" % (old_path, match)))
        elif match is not None and is_ci(match) == is_ci(old_path) \
                and is_config(match) == is_config(old_path):
            continue                        # moved, still doing its job
        else:
            analyze(old_path, text_of(old), "", findings, notes)

    for u in untracked:
        if u in consumed or ignored(u):
            continue
        new = read_now(root, u)
        if new is None:
            continue
        if is_binary(new):
            binaries.append(u)
            continue
        analyze(u, "", text_of(new), findings, notes)

    print("floor guard %s: %s" % (VERSION, root))
    print("  base %s = %s (merge-base with HEAD); %d files differ (%d untracked)%s"
          % (base, mb[:7], differ + len(untracked) - len(consumed),
             len(untracked) - len(consumed),
             ("; ignore: " + ", ".join(ignores)) if ignores else ""))
    if binaries:
        notes.append("%d binary files skipped: %s%s" % (
            len(binaries), ", ".join(binaries[:3]),
            " +%d more" % (len(binaries) - 3) if len(binaries) > 3 else ""))
    for n in notes:
        print("  note: " + n)

    problems = []
    if ledger is not None:
        problems = apply_ledger(ledger, ledger_rel, findings)

    live = [f for f in findings if f.ledger is None]
    kept = [f for f in findings if f.ledger is not None]
    if live:
        print("\nFLOOR DROPPED (%d):" % len(live))
        for f in live:
            print(f)
        print("\nTo grandfather one, add its ledger form to %s with a verdict and why:"
              % ledger_rel)
        for f in live:
            print("  " + f.form())
    if kept:
        print("\ngrandfathered by %s (%d):" % (ledger_rel, len(kept)))
        for f in kept:
            print("%s  %s" % (f, f.ledger))
    if problems:
        print("\nLEDGER PROBLEMS (%s):" % ledger_rel)
        for p in problems:
            print("  " + p)

    files = differ + len(untracked) - len(consumed)
    if live or problems:
        print("\nRESULT: FAIL %d floor drops, %d grandfathered, %d ledger problems, "
              "%d files, base %s" % (len(live), len(kept), len(problems), files, mb[:7]))
        return 1
    print("\nRESULT: PASS floor held, 0 drops (%d grandfathered), %d files compared, "
          "base %s" % (len(kept), files, mb[:7]))
    return 0


class Parser(argparse.ArgumentParser):
    """A bad flag is a run that could not check: exit 2, and say so last."""

    def error(self, message):
        self.print_usage(sys.stdout)
        print("could not check: %s" % message)
        print("RESULT: ERROR %s" % message)
        sys.exit(2)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = Parser(description="Report every place the test floor went down in a change.")
    ap.add_argument("--repo", default=".", help="a folder inside the repository")
    ap.add_argument("--base", default=None,
                    help="the ref to compare with (its merge-base with HEAD); default "
                         "the upstream, else main, else master")
    ap.add_argument("--ledger", default=None,
                    help="the ratchet ledger (default .floor-guard.json at the root)")
    ap.add_argument("--ignore", action="append", metavar="GLOB",
                    help="a repository-relative glob to leave out (repeatable)")
    args = ap.parse_args(argv)
    try:
        return guard(args)
    except GitError as e:
        print("could not check: %s" % e)
        print("RESULT: ERROR %s" % e)
        return 2
    except Exception as e:  # never let a crash read as clean
        print("could not check: %s: %s" % (type(e).__name__, e))
        print("RESULT: ERROR %s: %s" % (type(e).__name__, e))
        return 2


if __name__ == "__main__":
    sys.exit(main())
