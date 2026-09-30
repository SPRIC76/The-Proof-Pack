# Deps: python3.10+ stdlib, git | Path: scripts | Filename: floor_guard_selftest.py | Created: 2026-09-29
# -*- coding: utf-8 -*-
"""floor_guard_selftest.py - the cases floor_guard.py must not regress on.

Run:  python -B scripts/floor_guard_selftest.py       (exit 0 = all green)

Every case builds a throwaway git repository in a temp folder, makes one kind
of change to it, and drives floor_guard.py the way a hook or a reviewer does -
through the command line, reading the exit code and the RESULT line, never by
importing it. The contract defended here is the command-line one.

The fixtures commit with `git -c user.name=t -c user.email=t@t`, so no git
configuration anywhere is read for identity or changed.

Each case names the break it catches in its print line: the defect in the
guard that would turn that case red.

A check that something is NOT reported also requires the positive beside it
(the guard read that repository and reported the other things). Alone, an
absence check passes against a guard that does nothing: the first red run
(2026-09-29) had six of them green against a stub that exits 2 on everything.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FG = os.path.join(HERE, "floor_guard.py")

PASS, FAIL = [], []
OUTPUTS = []   # every (rc, out) seen, for the RESULT-is-last-line check


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + (
        ("\n         " + str(detail).replace("\n", "\n         ")[:3000]) if
        (detail and not cond) else ""))


def run(repo, *args):
    p = subprocess.run([sys.executable, "-B", FG, "--repo", repo] + list(args),
                       capture_output=True, timeout=120)
    out = p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")
    OUTPUTS.append((p.returncode, out))
    return p.returncode, out


def git(repo, *args):
    p = subprocess.run(("git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t")
                       + args, capture_output=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError("git %s failed in %s: %s" % (
            " ".join(args), repo, p.stderr.decode("utf-8", "replace")))
    return p.stdout.decode("utf-8", "replace")


def put(repo, relpath, text):
    p = os.path.join(repo, *relpath.split("/"))
    d = os.path.dirname(p)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def rm(repo, relpath):
    os.remove(os.path.join(repo, *relpath.split("/")))


def commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


def new_repo(tmp, name, files, branch="main"):
    repo = os.path.join(tmp, name)
    os.makedirs(repo)
    git(repo, "init", "-q", "-b", branch)
    for rel, text in files.items():
        put(repo, rel, text)
    commit(repo, "baseline")
    return repo


def findings(out, kind):
    """The finding lines of one kind, as printed (indented, kind first)."""
    return [ln.strip() for ln in out.splitlines()
            if ln.startswith("  ") and ln.strip().startswith(kind + " ")]


def _remove(tmp):
    """Git writes its objects read-only, and on Windows rmtree cannot delete a
    read-only file. Clear the bit and retry; say so if anything still stays."""
    def again(func, path, _):
        os.chmod(path, 0o700)
        func(path)
    kw = {"onexc": again} if sys.version_info >= (3, 12) else {"onerror": again}
    try:
        shutil.rmtree(tmp, **kw)
    except OSError as e:
        print("NOTE the fixtures could not all be removed from %s: %s" % (tmp, e))


# ---------------------------------------------------------------- fixtures

CALC = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"

TEST_CALC = (
    "from src.calc import add, sub\n"
    "\n\n"
    "def test_add():\n"
    "    assert add(1, 2) == 3\n"
    "    assert add(0, 0) == 0\n"
    "\n\n"
    "def test_sub():\n"
    "    assert sub(5, 3) == 2\n"
    "\n\n"
    "def test_mul():\n"
    "    assert add(2, 2) == 4\n"
)

TEST_JS = (
    "const { add } = require('../src/calc');\n"
    "describe('calc', () => {\n"
    "  it('adds', () => {\n"
    "    expect(add(1, 2)).toBe(3);\n"
    "  });\n"
    "  it('subs', () => {\n"
    "    expect(add(5, -3)).toBe(2);\n"
    "  });\n"
    "});\n"
)

BASE = {"src/calc.py": CALC, "tests/test_calc.py": TEST_CALC,
        "tests/calc.test.js": TEST_JS}

CI_YML = (
    "name: ci\n"
    "on: [push]\n"
    "jobs:\n"
    "  test:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - uses: actions/checkout@v4\n"
    "      - name: unit tests\n"
    "        run: pytest -q\n"
    "      - name: lint\n"
    "        run: ruff check .\n"
)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if not os.path.isfile(FG):
        print("floor_guard.py is not beside this file: %s" % FG)
        print("RESULT: FAIL floor_guard.py missing, 0 of 0 checks ran")
        return 1
    tmp = tempfile.mkdtemp(prefix="floorguard-selftest-")
    try:
        # ------------------------------------------------ 1 a clean change
        print("\n1. a change that adds code and a test holds the floor"
              " (break: the guard fails a change that lowered nothing)")
        a = new_repo(tmp, "one", BASE)
        put(a, "src/calc.py", CALC + "\n\ndef mul(a, b):\n    return a * b\n")
        put(a, "tests/test_calc.py", TEST_CALC +
            "\n\ndef test_mul_real():\n    assert 2 * 3 == 6\n")
        status_before = git(a, "status", "--porcelain")   # git status refreshes the index
        # A file whose content is unchanged but whose timestamp moved is what
        # git's auto-refresh writes back into .git/index. Make one, after the
        # status call above, so the guard is the next thing to touch the index.
        js = os.path.join(a, "tests", "calc.test.js")
        st = os.stat(js)
        os.utime(js, ns=(st.st_atime_ns + 10 ** 10, st.st_mtime_ns + 10 ** 10))
        index = os.path.join(a, ".git", "index")
        with open(index, "rb") as fh:
            index_before = fh.read()
        index_mtime = os.stat(index).st_mtime_ns
        rc, out = run(a, "--base", "HEAD")
        check("GREEN: exit 0 and RESULT: PASS", rc == 0 and "RESULT: PASS" in out, out)
        check("the summary counts the files whose text differs, not a moved timestamp",
              "2 files" in out, out)
        with open(index, "rb") as fh:
            index_after = fh.read()
        check("the guard never writes .git/index, even over a stat-dirty file"
              " (break: git diff's auto-refresh rewrites the index)",
              rc == 0 and index_after == index_before
              and os.stat(index).st_mtime_ns == index_mtime, out)
        check("the guard writes nothing into the working tree",
              rc == 0 and git(a, "status", "--porcelain") == status_before, out)

        # ------------------------------------------------ 2 suppressions
        print("\n2. a new suppression is a floor drop"
              " (break: a suppression pattern missing or mis-anchored)")
        b = new_repo(tmp, "two", BASE)
        put(b, "src/calc.py", CALC +
            "x = 1  # noqa: E501\n"
            "y: int = 's'  # type: ignore\n"
            "z = 2  # pylint: disable=invalid-name\n"
            "w = 3  # pragma: no cover\n")
        put(b, "src/app.js",
            "// eslint-disable-next-line no-console\n"
            "console.log(1);\n"
            "// @ts-ignore\n"
            "const a = 1;\n"
            "// @ts-expect-error\n"
            "const b = 2;\n")
        rc, out = run(b, "--base", "HEAD")
        sup = findings(out, "suppression-added")
        check("RED: exit 1 and RESULT: FAIL", rc == 1 and "RESULT: FAIL" in out, out)
        check("every added suppression is listed, one line each",
              len(sup) == 7, out)
        check("noqa named with file:line (line 7 of src/calc.py)",
              any("src/calc.py:7" in s and "noqa" in s for s in sup), out)
        check("type: ignore, pylint and pragma named",
              any("type: ignore" in s for s in sup)
              and any("pylint" in s for s in sup)
              and any("pragma: no cover" in s for s in sup), out)
        check("eslint-disable, @ts-ignore and @ts-expect-error named with lines",
              any("src/app.js:1" in s and "eslint-disable" in s for s in sup)
              and any("src/app.js:3" in s and "@ts-ignore" in s for s in sup)
              and any("src/app.js:5" in s and "@ts-expect-error" in s for s in sup), out)

        print("    ...and one that only moved is not new"
              " (break: the guard reads a diff line, not a per-file count)")
        b2 = new_repo(tmp, "twob", {"src/a.py": "a = 1  # noqa\nb = 2\n"})
        put(b2, "src/a.py", "import os\nimport sys\na = 1  # noqa\nb = 2\n")
        rc, out = run(b2, "--base", "HEAD")
        check("GREEN: a suppression that moved down two lines is not a drop",
              rc == 0 and not findings(out, "suppression-added"), out)

        # ------------------------------------------------ 3 skips
        print("\n3. a new skip, xfail or .only is a floor drop"
              " (break: a skip pattern missing)")
        c = new_repo(tmp, "three", BASE)
        put(c, "tests/test_calc.py",
            "import sys\nimport unittest\nimport pytest\n"
            "from src.calc import add, sub\n\n\n"
            "@pytest.mark.skip(reason='later')\n"
            "def test_add():\n    assert add(1, 2) == 3\n    assert add(0, 0) == 0\n\n\n"
            "@pytest.mark.skipif(sys.platform == 'win32', reason='posix only')\n"
            "def test_sub():\n    assert sub(5, 3) == 2\n\n\n"
            "@pytest.mark.xfail\n"
            "def test_mul():\n    assert add(2, 2) == 4\n\n\n"
            "@unittest.skip('slow')\n"
            "def test_extra():\n    assert True\n")
        put(c, "tests/calc.test.js",
            "const { add } = require('../src/calc');\n"
            "describe.skip('old', () => {});\n"
            "describe('calc', () => {\n"
            "  it.skip('adds', () => {\n    expect(add(1, 2)).toBe(3);\n  });\n"
            "  it('subs', () => {\n    expect(add(5, -3)).toBe(2);\n  });\n"
            "  test.skip('t', () => {});\n"
            "  xit('x', () => {});\n"
            "  it.only('focus', () => {});\n"
            "});\n")
        rc, out = run(c, "--base", "HEAD")
        sk = findings(out, "skip-added")
        check("RED: exit 1", rc == 1, out)
        check("nine skips listed", len(sk) == 9, out)
        check("pytest skip, skipif, xfail and unittest.skip named",
              any("pytest.mark.skip(" in s for s in sk)
              and any("skipif" in s for s in sk)
              and any("xfail" in s for s in sk)
              and any("unittest.skip" in s for s in sk), out)
        check("it.skip, describe.skip, test.skip, xit and .only named with lines",
              any("tests/calc.test.js:4" in s and "it.skip" in s for s in sk)
              and any("describe.skip" in s for s in sk)
              and any("test.skip" in s for s in sk)
              and any("xit(" in s for s in sk)
              and any("tests/calc.test.js:12" in s and "it.only" in s for s in sk), out)
        check("no test counted as removed when it was only skipped",
              len(sk) == 9 and not findings(out, "test-removed"), out)

        # ------------------------------------------------ 4 deleted / renamed away
        print("\n4. a test file deleted or renamed away"
              " (break: deletions read off the +++ header, or renames unseen)")
        d = new_repo(tmp, "four", {
            "tests/test_a.py": "def test_a():\n    assert 1\n",
            "tests/test_b.py": "def test_b():\n    assert 2\n",
            "tests/test_c.py": "def test_c():\n    assert 3\n"})
        git(d, "rm", "-q", "tests/test_a.py")
        os.makedirs(os.path.join(d, "legacy"))
        git(d, "mv", "tests/test_b.py", "legacy/b_old.py")
        git(d, "mv", "tests/test_c.py", "tests/test_c2.py")
        rc, out = run(d, "--base", "HEAD")
        dl = findings(out, "test-file-deleted")
        ra = findings(out, "test-file-renamed-away")
        check("RED: exit 1", rc == 1, out)
        check("the deleted test file is named", any("tests/test_a.py" in s for s in dl), out)
        check("the file renamed out of the test set is named with both paths",
              any("tests/test_b.py" in s and "legacy/b_old.py" in s for s in ra), out)
        check("a test file renamed to another test file is not a drop",
              bool(dl) and bool(ra) and "test_c" not in out, out)

        print("    ...even when the move was not staged"
              " (break: only git's own rename detection is trusted)")
        d2 = new_repo(tmp, "fourb", {"tests/test_d.py": "def test_d():\n    assert 4\n"})
        os.makedirs(os.path.join(d2, "archive"))
        os.rename(os.path.join(d2, "tests", "test_d.py"),
                  os.path.join(d2, "archive", "d.py"))
        rc, out = run(d2, "--base", "HEAD")
        check("an unstaged move out of the test set is a rename-away, not a deletion",
              rc == 1 and any("archive/d.py" in s for s in
                              findings(out, "test-file-renamed-away"))
              and not findings(out, "test-file-deleted"), out)

        # ------------------------------------------------ 5 test removed
        print("\n5. a test function removed"
              " (break: names not read, or a rename read as a removal)")
        e = new_repo(tmp, "five", BASE)
        put(e, "tests/test_calc.py",
            "from src.calc import add, sub\n\n\n"
            "def test_add():\n    assert add(1, 2) == 3\n    assert add(0, 0) == 0\n\n\n"
            "def test_multiply():\n    assert add(2, 2) == 4\n")
        put(e, "tests/calc.test.js",
            "const { add } = require('../src/calc');\n"
            "describe('calc', () => {\n"
            "  it('adds', () => {\n    expect(add(1, 2)).toBe(3);\n  });\n"
            "});\n")
        rc, out = run(e, "--base", "HEAD")
        tr = findings(out, "test-removed")
        check("RED: exit 1", rc == 1, out)
        check("the removed python test is named, with the count",
              any("tests/test_calc.py" in s and "test_sub" in s and "3 -> 2" in s
                  for s in tr), out)
        check("a python test renamed with its body kept is not a removal",
              bool(tr) and not any("test_mul" in s for s in tr), out)
        check("the removed javascript test is named by its title",
              any("tests/calc.test.js" in s and "subs" in s for s in tr), out)

        print("    ...and a test renamed with a new body is a removal that names the newcomer"
              " (break: a rewrite reads as a plain loss, or as no change)")
        e2 = new_repo(tmp, "fiveb", {"tests/test_r.py":
                                     "def test_says_where():\n    assert 'menu' in 'the menu'\n"})
        put(e2, "tests/test_r.py", "def test_shows_it():\n    assert 'menu' not in 'the face'\n")
        rc, out = run(e2, "--base", "HEAD")
        tr2 = findings(out, "test-removed")
        check("RED: the old name is reported, and the line names the new test beside it",
              rc == 1 and len(tr2) == 1 and "test_says_where" in tr2[0]
              and "test_shows_it" in tr2[0], out)

        # ------------------------------------------------ 6 assertions dropped
        print("\n6. an assertion count that dropped in a test file"
              " (break: the count is not per file, or counts src too)")
        f = new_repo(tmp, "six", BASE)
        put(f, "tests/test_calc.py", TEST_CALC.replace(
            "    assert add(0, 0) == 0\n", ""))
        rc, out = run(f, "--base", "HEAD")
        ad = findings(out, "assertions-dropped")
        check("RED: exit 1 with the file and the counts",
              rc == 1 and any("tests/test_calc.py" in s and "4 -> 3" in s for s in ad),
              out)
        check("no test is reported removed when only an assertion went",
              bool(ad) and not findings(out, "test-removed"), out)
        f2 = new_repo(tmp, "sixb", BASE)
        put(f2, "tests/test_calc.py", TEST_CALC + "    assert add(1, 1) == 2\n")
        put(f2, "src/calc.py", CALC.replace("    return a + b\n",
                                            "    return a + b\n"))
        rc, out = run(f2, "--base", "HEAD")
        check("GREEN: adding an assertion is silent", rc == 0, out)
        f3 = new_repo(tmp, "sixc", {
            "src/guard.py": "def f(x):\n    assert x > 0\n    return x\n",
            "tests/test_g.py": "def test_f():\n    assert True\n"})
        put(f3, "src/guard.py", "def f(x):\n    return x\n")
        rc, out = run(f3, "--base", "HEAD")
        check("GREEN: an assert removed from source is not the test floor",
              rc == 0, out)
        f4 = new_repo(tmp, "sixd", BASE)
        put(f4, "tests/calc.test.js", TEST_JS.replace(
            "    expect(add(5, -3)).toBe(2);\n", "    add(5, -3);\n"))
        rc, out = run(f4, "--base", "HEAD")
        check("an expect() dropped from a javascript test is counted",
              rc == 1 and any("2 -> 1" in s for s in findings(out, "assertions-dropped")),
              out)
        f5 = new_repo(tmp, "sixe", BASE)
        put(f5, "tests/test_calc.py", "")
        rc, out = run(f5, "--base", "HEAD")
        check("a test file emptied in place drops every assertion it held"
              " (break: an empty file is read as absent)",
              rc == 1 and any("tests/test_calc.py" in s and "4 -> 0" in s
                              for s in findings(out, "assertions-dropped"))
              and len(findings(out, "test-removed")) == 3, out)

        # ------------------------------------------------ 7 thresholds
        print("\n7. a loosened tolerance, timeout or retry count"
              " (break: direction read wrong, or numbers paired wrong)")
        NUM_T = ("import math\n\n\n"
                 "def test_close(a=1.0, b=1.0, score=0.95, count=3):\n"
                 "    assert abs(a - b) < 1e-6\n"
                 "    assert score >= 0.9\n"
                 "    assert count <= 5\n"
                 "    assert 0.5 <= score\n"
                 "    assert math.isclose(a, b, rel_tol=1e-9)\n"
                 "    assert total_of() == 5\n"
                 "\n\n"
                 "class T:\n"
                 "    def test_places(self):\n"
                 "        self.assertAlmostEqual(1.0, 1.0, places=7)\n")
        PRODUCT = ("import urllib.request\n\n\n"
                   "def get(url):\n    return urllib.request.urlopen(url, timeout=5)\n\n\n"
                   "MAX_UPLOAD_MB = 10\n")
        g = new_repo(tmp, "seven", {
            "tests/test_num.py": NUM_T,
            "tests/settings.py": "TIMEOUT = 30\nRETRIES = 3\nMAX_ERRORS = 2\n",
            "setup.cfg": "[coverage:report]\nfail_under = 90\n",
            "pytest.ini": "[pytest]\ntimeout = 30\n",
            "jest.config.js": "module.exports = { testTimeout: 5000 };\n",
            "playwright.config.ts": "export default {\n  retries: 1,\n  timeout: 30000,\n};\n",
            ".github/workflows/ci.yml": CI_YML.replace(
                "    runs-on: ubuntu-latest\n",
                "    runs-on: ubuntu-latest\n    timeout-minutes: 10\n"),
            "src/client.py": PRODUCT})
        put(g, "tests/test_num.py", NUM_T
            .replace("< 1e-6", "< 1e-3").replace(">= 0.9\n", ">= 0.5\n")
            .replace("<= 5\n", "<= 50\n").replace("0.5 <= score", "0.1 <= score")
            .replace("rel_tol=1e-9", "rel_tol=1e-2").replace("== 5\n", "== 6\n")
            .replace("places=7", "places=3"))
        put(g, "tests/settings.py", "TIMEOUT = 300\nRETRIES = 10\nMAX_ERRORS = 20\n")
        put(g, "setup.cfg", "[coverage:report]\nfail_under = 80\n")
        put(g, "pytest.ini", "[pytest]\ntimeout = 120\n")
        put(g, "jest.config.js", "module.exports = { testTimeout: 60000 };\n")
        put(g, "playwright.config.ts", "export default {\n  retries: 3,\n  timeout: 90000,\n};\n")
        put(g, ".github/workflows/ci.yml", CI_YML.replace(
            "    runs-on: ubuntu-latest\n",
            "    runs-on: ubuntu-latest\n    timeout-minutes: 60\n"))
        put(g, "src/client.py", PRODUCT.replace("timeout=5", "timeout=50")
            .replace("MAX_UPLOAD_MB = 10", "MAX_UPLOAD_MB = 100"))
        rc, out = run(g, "--base", "HEAD")
        th = findings(out, "threshold-loosened")
        check("RED: exit 1", rc == 1, out)
        check("a tolerance raised: < 1e-6 -> < 1e-3",
              any("1e-6" in s and "1e-3" in s for s in th), out)
        check("a lower bound lowered: >= 0.9 -> >= 0.5, and 0.5 <= x -> 0.1 <= x",
              any(">= 0.9" in s and ">= 0.5" in s for s in th)
              and any("0.5 <= score" in s and "0.1 <= score" in s for s in th), out)
        check("an upper bound raised: <= 5 -> <= 50",
              any("<= 5" in s and "<= 50" in s for s in th), out)
        check("a keyword tolerance raised: rel_tol=1e-9 -> 1e-2",
              any("rel_tol=1e-9" in s and "rel_tol=1e-2" in s for s in th), out)
        check("places lowered: places=7 -> places=3",
              any("places=7" in s and "places=3" in s for s in th), out)
        check("TIMEOUT, RETRIES and MAX_ERRORS raised in a test-side settings module",
              any("TIMEOUT = 30" in s and "TIMEOUT = 300" in s for s in th)
              and any("RETRIES = 3" in s and "RETRIES = 10" in s for s in th)
              and any("MAX_ERRORS = 2" in s and "MAX_ERRORS = 20" in s for s in th), out)
        check("fail_under lowered, pytest timeout and jest testTimeout raised",
              any("fail_under = 90" in s and "fail_under = 80" in s for s in th)
              and any("pytest.ini" in s and "timeout = 120" in s for s in th)
              and any("testTimeout: 60000" in s for s in th), out)
        check("playwright retries and timeout raised, CI timeout-minutes raised",
              any("playwright.config.ts" in s and "retries: 3" in s for s in th)
              and any("playwright.config.ts" in s and "timeout: 90000" in s for s in th)
              and any("ci.yml" in s and "timeout-minutes: 60" in s for s in th), out)
        check("a fixture value with no direction (== 5 -> == 6) is not reported",
              bool(th) and not any("== 6" in s for s in th), out)
        check("a timeout or limit raised in product code is not the test floor"
              " (break: every file's numbers are read, not the tests' and their config)",
              bool(th) and not any("src/client.py" in s for s in th), out)
        check("exactly fifteen loosenings, nothing double-counted", len(th) == 15, out)

        g2 = new_repo(tmp, "sevenb", {
            "tests/test_num.py": NUM_T,
            "tests/settings.py": "TIMEOUT = 30\nRETRIES = 3\n",
            "setup.cfg": "[coverage:report]\nfail_under = 90\n"})
        put(g2, "tests/test_num.py", NUM_T
            .replace("< 1e-6", "< 1e-9").replace(">= 0.9\n", ">= 0.95\n")
            .replace("<= 5\n", "<= 3\n").replace("places=7", "places=9"))
        put(g2, "tests/settings.py", "TIMEOUT = 10\nRETRIES = 1\n")
        put(g2, "setup.cfg", "[coverage:report]\nfail_under = 95\n")
        rc, out = run(g2, "--base", "HEAD")
        check("GREEN: tightening is silent", rc == 0 and "RESULT: PASS" in out, out)

        print("    ...and a floor taken out of the config is a floor lowered"
              " (break: only a changed number is read, never a removed one)")
        g3 = new_repo(tmp, "sevenc", {
            "setup.cfg": "[coverage:report]\nfail_under = 90\nshow_missing = true\n",
            "pytest.ini": "[pytest]\naddopts = -q --cov-fail-under=85\n"})
        put(g3, "setup.cfg", "[coverage:report]\nshow_missing = true\n")
        put(g3, "pytest.ini", "[pytest]\naddopts = -q\n")
        rc, out = run(g3, "--base", "HEAD")
        th3 = findings(out, "threshold-loosened")
        check("RED: fail_under removed and --cov-fail-under removed are both named",
              rc == 1 and len(th3) == 2
              and any("setup.cfg" in s and "fail_under = 90" in s and "removed" in s
                      for s in th3)
              and any("pytest.ini" in s and "cov-fail-under=85" in s and "removed" in s
                      for s in th3), out)
        g4 = new_repo(tmp, "sevend", {
            "setup.cfg": "[coverage:report]\nfail_under = 90\nshow_missing = true\n"})
        put(g4, "setup.cfg", "[coverage:report]\nshow_missing = true\nfail_under = 90\n")
        rc, out = run(g4, "--base", "HEAD")
        check("GREEN: a floor that moved down a line is not a floor removed",
              rc == 0 and "RESULT: PASS" in out, out)

        # ------------------------------------------------ 8 CI and test paths
        print("\n8. a CI step removed or softened, a test path excluded"
              " (break: CI files not recognised, or a moved step read as removed)")
        h = new_repo(tmp, "eight", {
            ".github/workflows/ci.yml": CI_YML,
            "pytest.ini": "[pytest]\naddopts = -q\n",
            "jest.config.js": "module.exports = {\n  verbose: true,\n};\n",
            "package.json": '{\n  "scripts": {\n    "test": "jest"\n  }\n}\n',
            "tests/test_x.py": "def test_x():\n    assert 1\n"})
        put(h, ".github/workflows/ci.yml", CI_YML
            .replace("      - name: lint\n        run: ruff check .\n", "")
            .replace("        run: pytest -q\n",
                     "        run: pytest -q\n        continue-on-error: true\n"))
        put(h, "pytest.ini", "[pytest]\naddopts = -q --ignore=tests/slow\n")
        put(h, "jest.config.js",
            "module.exports = {\n  verbose: true,\n"
            "  testPathIgnorePatterns: ['/integration/'],\n};\n")
        put(h, "package.json", '{\n  "scripts": {\n    "test": "echo skipped"\n  }\n}\n')
        rc, out = run(h, "--base", "HEAD")
        rem = findings(out, "ci-step-removed")
        soft = findings(out, "ci-step-softened")
        exc = findings(out, "test-path-excluded")
        check("RED: exit 1", rc == 1, out)
        check("the removed lint step is named", any("ruff check" in s for s in rem), out)
        check("continue-on-error: true is a softened step",
              any("continue-on-error" in s and "ci.yml" in s for s in soft), out)
        check("a test script stubbed to echo is a softened step",
              any("package.json" in s and "echo skipped" in s for s in soft), out)
        check("--ignore= in pytest addopts is an excluded test path",
              any("pytest.ini" in s and "--ignore=tests/slow" in s for s in exc), out)
        check("testPathIgnorePatterns in jest config is an excluded test path",
              any("jest.config.js" in s and "testPathIgnorePatterns" in s for s in exc),
              out)
        h2 = new_repo(tmp, "eightb", {".github/workflows/ci.yml": CI_YML})
        put(h2, ".github/workflows/ci.yml", CI_YML
            .replace("      - name: unit tests\n        run: pytest -q\n", "")
            .replace("      - uses: actions/checkout@v4\n",
                     "      - uses: actions/checkout@v4\n"
                     "      - name: unit tests\n        run: pytest -q\n"))
        rc, out = run(h2, "--base", "HEAD")
        check("GREEN: a step that moved is not a step removed", rc == 0, out)
        h9 = new_repo(tmp, "eighti", {".github/workflows/ci.yml": CI_YML})
        put(h9, ".github/workflows/ci.yml", CI_YML.replace("run: pytest -q\n",
                                                           "run: pytest -q -x\n"))
        rc, out = run(h9, "--base", "HEAD")
        check("GREEN: a step whose check keeps running with a new flag is not removed"
              " (break: a step is known by its whole line)",
              rc == 0 and "RESULT: PASS" in out, out)
        h10 = new_repo(tmp, "eightj", {".github/workflows/ci.yml": CI_YML})
        put(h10, ".github/workflows/ci.yml", CI_YML
            .replace("run: pytest -q\n", "run: pytest -q --ignore=tests/slow\n")
            .replace("    runs-on: ubuntu-latest\n",
                     "    runs-on: ubuntu-latest\n    strategy:\n      matrix:\n"
                     "        os: [ubuntu-latest, windows-latest]\n        exclude:\n"
                     "          - os: windows-latest\n"))
        rc, out = run(h10, "--base", "HEAD")
        exc = findings(out, "test-path-excluded")
        check("RED: --ignore added to a CI run line is an excluded test path, and a"
              " matrix exclude is not (break: exclusions read only in test config)",
              rc == 1 and len(exc) == 1 and "ci.yml" in exc[0]
              and "--ignore=tests/slow" in exc[0]
              and not findings(out, "ci-step-removed"), out)

        print("    ...and a workflow deleted, renamed away or switched off"
              " (break: only a file that still exists is read)")
        h3 = new_repo(tmp, "eightc", {".github/workflows/ci.yml": CI_YML,
                                      "tests/test_x.py": "def test_x():\n    assert 1\n"})
        git(h3, "rm", "-q", ".github/workflows/ci.yml")
        rc, out = run(h3, "--base", "HEAD")
        rem = findings(out, "ci-step-removed")
        check("RED: every check step of a deleted workflow is named",
              rc == 1 and len(rem) == 2 and any("pytest -q" in s for s in rem)
              and any("ruff check" in s for s in rem), out)
        h4 = new_repo(tmp, "eightd", {".github/workflows/ci.yml": CI_YML})
        git(h4, "mv", ".github/workflows/ci.yml", ".github/workflows/ci.yml.off")
        rc, out = run(h4, "--base", "HEAD")
        rem = findings(out, "ci-step-removed")
        check("RED: a workflow renamed to a name CI does not run loses its steps",
              rc == 1 and len(rem) == 2 and all(".github/workflows/ci.yml" in s for s in rem),
              out)
        h5 = new_repo(tmp, "eighte", {".github/workflows/ci.yml": CI_YML})
        put(h5, ".github/workflows/ci.yml", CI_YML.replace(
            "      - name: lint\n", "      - name: lint\n        if: ${{ false }}\n"))
        rc, out = run(h5, "--base", "HEAD")
        check("RED: if: ${{ false }} on a step is a softened step, with its line",
              rc == 1 and any("ci.yml:11" in s and "if: false" in s
                              for s in findings(out, "ci-step-softened")), out)

        print("    ...and a GitLab script line or a package.json check script removed"
              " (break: only run:/uses: keys are read as steps)")
        GL = ("test:\n  stage: test\n  script:\n    - pip install -r requirements.txt\n"
              "    - pytest -q\n    - ruff check .\n")
        PKG = ('{\n  "scripts": {\n    "build": "vite build",\n    "test": "jest",\n'
               '    "lint": "eslint ."\n  }\n}\n')
        h6 = new_repo(tmp, "eightf", {".gitlab-ci.yml": GL, "package.json": PKG})
        put(h6, ".gitlab-ci.yml", GL.replace("    - ruff check .\n", ""))
        put(h6, "package.json", PKG.replace('"test": "jest",\n    "lint": "eslint ."',
                                            '"test": "jest"'))
        rc, out = run(h6, "--base", "HEAD")
        rem = findings(out, "ci-step-removed")
        check("RED: the GitLab ruff line and the lint script are named, nothing else",
              rc == 1 and len(rem) == 2
              and any(".gitlab-ci.yml:6" in s and "ruff check" in s for s in rem)
              and any("package.json:5" in s and "eslint" in s for s in rem), out)

        print("    ...and a collected path narrowed away"
              " (break: only an added --ignore is read, never a list that shrank)")
        h7 = new_repo(tmp, "eightg", {
            "pytest.ini": "[pytest]\ntestpaths = tests integration\n",
            "pyproject.toml": '[tool.pytest.ini_options]\npython_files = ["test_*.py", "check_*.py"]\n'})
        put(h7, "pytest.ini", "[pytest]\ntestpaths = tests\n")
        put(h7, "pyproject.toml", '[tool.pytest.ini_options]\npython_files = ["test_*.py"]\n')
        rc, out = run(h7, "--base", "HEAD")
        exc = findings(out, "test-path-excluded")
        check("RED: testpaths and python_files that lost an entry are named with it",
              rc == 1 and len(exc) == 2
              and any("pytest.ini:2" in s and "integration" in s for s in exc)
              and any("pyproject.toml:2" in s and "check_*.py" in s for s in exc), out)
        h8 = new_repo(tmp, "eighth", {"pytest.ini": "[pytest]\ntestpaths = tests\n"})
        put(h8, "pytest.ini", "[pytest]\ntestpaths = tests integration\n")
        rc, out = run(h8, "--base", "HEAD")
        check("GREEN: a collected path added is silent", rc == 0 and "RESULT: PASS" in out,
              out)

        # ------------------------------------------------ 9 exit 2
        print("\n9. what cannot be checked is an ERROR, never a PASS"
              " (break: a git failure falls through to exit 0)")
        nogit = os.path.join(tmp, "nogit")
        os.makedirs(nogit)
        rc, out = run(nogit, "--base", "HEAD")
        check("a folder that is not a repository exits 2 with RESULT: ERROR",
              rc == 2 and "RESULT: ERROR" in out and "RESULT: PASS" not in out, out)
        rc, out = run(a, "--base", "no-such-ref")
        check("a base ref that does not resolve exits 2", rc == 2
              and "RESULT: ERROR" in out and "no-such-ref" in out, out)
        rc, out = run(a, "--base", "HEAD~40")
        check("a base beyond the history exits 2", rc == 2 and "RESULT: ERROR" in out,
              out)
        i = new_repo(tmp, "nine", {"a.py": "a = 1\n"}, branch="trunk")
        put(i, "a.py", "a = 1  # noqa\n")
        rc, out = run(i)
        check("no upstream, no main, no master and no --base exits 2 and says so",
              rc == 2 and "RESULT: ERROR" in out and "--base" in out, out)
        rc, out = run(a, "--base", "HEAD", "--no-such-flag")
        lines = out.rstrip().splitlines()
        check("a flag the guard does not know exits 2 and still ends in RESULT: ERROR"
              " (break: the argument parser exits 2 with only its usage line)",
              rc == 2 and bool(lines) and lines[-1].startswith("RESULT: ERROR")
              and "no-such-flag" in out, out)

        print("    ...and the default base is the merge-base with main"
              " (break: the working tree compared to HEAD instead)")
        j = new_repo(tmp, "ninb", {"a.py": "a = 1\n"})
        git(j, "checkout", "-q", "-b", "feature")
        put(j, "a.py", "a = 1  # noqa\n")
        commit(j, "committed on feature")
        rc, out = run(j)
        check("a drop committed on a feature branch is found against main",
              rc == 1 and any("a.py:1" in s for s in findings(out, "suppression-added")),
              out)

        # ------------------------------------------------ 10 the ledger
        print("\n10. the ledger grandfathers a named drop, with a reason, and only shrinks"
              " (break: an entry without a reason, or a stale one, is accepted)")
        k = new_repo(tmp, "ten", BASE)
        put(k, "tests/test_calc.py", TEST_CALC.replace(
            "def test_sub():\n    assert sub(5, 3) == 2\n\n\n", ""))
        rc, out = run(k, "--base", "HEAD")
        check("RED: without a ledger the removal fails", rc == 1, out)

        def ledger(repo, items, **extra):
            doc = {"about": "test ledger", "items": items}
            doc.update(extra)
            put(repo, ".floor-guard.json", json.dumps(doc, indent=1))

        ledger(k, [{"kind": "test-removed", "file": "tests/test_calc.py",
                    "what": "test_sub", "verdict": "intended",
                    "why": "sub() left with the feature in K80"},
                   {"kind": "assertions-dropped", "file": "tests/test_calc.py",
                    "what": "4 -> 3", "verdict": "intended",
                    "why": "the one assertion of test_sub"}])
        rc, out = run(k, "--base", "HEAD")
        check("GREEN: a drop named in the ledger with a verdict and a reason passes",
              rc == 0 and "RESULT: PASS" in out, out)
        check("...and is printed as grandfathered, with its reason, not hidden",
              "grandfathered" in out and "K80" in out and "test_sub" in out, out)
        check("...and the RESULT line counts it",
              "2 grandfathered" in out, out)

        ledger(k, [{"kind": "test-removed", "file": "tests/test_calc.py",
                    "what": "test_sub", "verdict": "intended", "why": "  "},
                   {"kind": "assertions-dropped", "file": "tests/test_calc.py",
                    "what": "4 -> 3", "verdict": "intended", "why": "the one"}])
        rc, out = run(k, "--base", "HEAD")
        check("RED: an entry with no reason fails and is named",
              rc == 1 and "no reason" in out and "test_sub" in out, out)

        ledger(k, [{"kind": "test-removed", "file": "tests/test_calc.py",
                    "what": "test_sub", "verdict": "whatever", "why": "x"},
                   {"kind": "assertions-dropped", "file": "tests/test_calc.py",
                    "what": "4 -> 3", "verdict": "intended", "why": "the one"}])
        rc, out = run(k, "--base", "HEAD")
        check("RED: a verdict that is not one of the named ones fails",
              rc == 1 and "whatever" in out and "not one of" in out, out)

        ledger(k, [{"kind": "test-removed", "file": "tests/test_calc.py",
                    "what": "test_sub", "verdict": "intended", "why": "K80"},
                   {"kind": "assertions-dropped", "file": "tests/test_calc.py",
                    "what": "4 -> 3", "verdict": "intended", "why": "the one"},
                   {"kind": "test-removed", "file": "tests/test_calc.py",
                    "what": "test_nothing", "verdict": "intended", "why": "gone"}])
        rc, out = run(k, "--base", "HEAD")
        check("RED: an entry that matches no drop is stale and must be deleted",
              rc == 1 and "test_nothing" in out and "delete" in out, out)

        ledger(k, [{"kind": "test-removed", "file": "tests/test_calc.py",
                    "what": "test_sub", "verdict": "intended", "why": "K80"},
                   {"kind": "assertions-dropped", "file": "tests/test_calc.py",
                    "what": "4 -> 3", "verdict": "intended", "why": "the one"}],
               ceiling=1)
        rc, out = run(k, "--base", "HEAD")
        check("RED: more entries than the ceiling fails",
              rc == 1 and "ceiling" in out, out)

        ledger(k, [{"kind": "test-removed", "file": "tests/test_calc.py",
                    "what": "test_sub", "verdict": "moved", "why": "now in test_ops"}],
               ceiling=2)
        rc, out = run(k, "--base", "HEAD")
        check("RED: 'moved' or 'replaced' without 'by' fails",
              rc == 1 and "by" in out and "moved" in out, out)

        put(k, "tests/test_calc.py",
            "from src.calc import add, sub\n\n\n"
            "def test_mul():\n    assert add(2, 2) == 4\n")
        ledger(k, [{"kind": "test-removed", "file": "tests/test_calc.py",
                    "what": "test_sub", "verdict": "intended", "why": "K80"},
                   {"kind": "assertions-dropped", "file": "tests/test_calc.py",
                    "what": "4 -> 1", "verdict": "intended", "why": "with them"}])
        rc, out = run(k, "--base", "HEAD")
        check("RED: a NEW drop beside a grandfathered one still fails, and is the one named",
              rc == 1 and any("test_add" in s for s in findings(out, "test-removed"))
              and "grandfathered" in out, out)

        m = new_repo(tmp, "tenb", {"vendor/lib.py": "a = 1\n", "src/b.py": "b = 1\n"})
        put(m, "vendor/lib.py", "a = 1  # noqa\n")
        ledger(m, [], ignore=["vendor/*"])
        rc, out = run(m, "--base", "HEAD")
        check("GREEN: a path the ledger ignores is not scanned, and the ignore is printed",
              rc == 0 and "vendor/*" in out, out)
        put(m, "src/b.py", "b = 1  # noqa\n")
        rc, out = run(m, "--base", "HEAD")
        check("RED: the ignore covers only its own paths",
              rc == 1 and any("src/b.py:1" in s for s in findings(out, "suppression-added"))
              and not any("vendor/" in s for s in findings(out, "suppression-added")), out)

        print("    ...a deleted test file can be grandfathered by what the guard prints,"
              " and a ledger cannot pad itself (break: 'what' is empty for a deletion,"
              " a line twice or a ceiling in words is accepted)")
        q = new_repo(tmp, "tenc", {"tests/test_a.py": "def test_a():\n    assert 1\n",
                                   "tests/test_all.py": "def test_all():\n    assert 2\n"})
        git(q, "rm", "-q", "tests/test_a.py")
        rc, out = run(q, "--base", "HEAD")
        check("RED: the deletion is named, and its line shows 'file deleted'",
              rc == 1 and any("tests/test_a.py" in s and "file deleted" in s
                              for s in findings(out, "test-file-deleted")), out)
        gone = {"kind": "test-file-deleted", "file": "tests/test_a.py",
                "what": "file deleted", "verdict": "moved", "by": "tests/test_all.py",
                "why": "test_a's one check folded into test_all"}
        ledger(q, [gone])
        rc, out = run(q, "--base", "HEAD")
        check("GREEN: a deleted test file grandfathered as 'file deleted', with by and why",
              rc == 0 and "1 grandfathered" in out and "test_all" in out, out)
        ledger(q, [gone, dict(gone)])
        rc, out = run(q, "--base", "HEAD")
        check("RED: the same entry twice is a ledger problem",
              rc == 1 and "twice" in out, out)
        ledger(q, [gone], ceiling="1")
        rc, out = run(q, "--base", "HEAD")
        check("RED: a ceiling that is not a whole number is a ledger problem",
              rc == 1 and "ceiling" in out and "whole number" in out, out)

        # ------------------------------------------------ 11 untracked, and the last line
        print("\n11. untracked files are in the change too"
              " (break: only git diff is read, which cannot see a new file)")
        n = new_repo(tmp, "eleven", BASE)
        put(n, "tests/test_new.py",
            "import pytest\n\n\n@pytest.mark.skip\ndef test_new():\n    assert 1\n")
        rc, out = run(n, "--base", "HEAD")
        check("a skip in an untracked test file is found",
              rc == 1 and any("tests/test_new.py:4" in s for s in findings(out, "skip-added")),
              out)
        check("the summary counts the untracked file", "1 untracked" in out, out)

        # ------------------------------------------------ 12 prose is not code
        print("\n12. a suppression named in prose is not a suppression"
              " (break: every file is scanned, so a doc about noqa fails the change)")
        r = new_repo(tmp, "twelve", {"README.md": "# x\n", "src/a.py": "a = 1\n"})
        put(r, "README.md",
            "# x\n\nSilence one line with `# noqa` or `// eslint-disable-next-line`;"
            " focus one test with `it.only('x', () => {})`.\n\n"
            "```python\nimport x  # noqa: E402\n```\n")
        put(r, "src/a.py", "a = 1  # noqa\n")
        rc, out = run(r, "--base", "HEAD")
        sup = findings(out, "suppression-added")
        check("RED: the code suppression is named, and nothing in README.md is",
              rc == 1 and len(sup) == 1 and "src/a.py:1" in sup[0]
              and "README.md" not in out.split("FLOOR DROPPED")[-1], out)

        bad = [(rc, o) for rc, o in OUTPUTS
               if not o.rstrip().splitlines()
               or not o.rstrip().splitlines()[-1].startswith("RESULT: ")]
        check("every run ended in a RESULT line, PASS, FAIL or ERROR",
              not bad, bad[:2])
        wrong = [(rc, o) for rc, o in OUTPUTS if (
            (rc == 0 and "RESULT: PASS" not in o) or (rc == 1 and "RESULT: FAIL" not in o)
            or (rc == 2 and "RESULT: ERROR" not in o) or rc not in (0, 1, 2))]
        check("the exit code and the RESULT word never disagree", not wrong, wrong[:2])
    finally:
        _remove(tmp)

    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    for f in FAIL:
        print("  FAILED: " + f)
    total = len(PASS) + len(FAIL)
    if FAIL:
        print("RESULT: FAIL %d of %d checks" % (len(FAIL), total))
        return 1
    print("RESULT: PASS %d checks" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
