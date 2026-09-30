# Deps: python3.10+ stdlib, git optional | Path: scripts | Filename: depgraph_selftest.py | Created: 2026-09-29
# -*- coding: utf-8 -*-
"""depgraph_selftest.py - the cases depgraph.py must not regress on.

Run:  python -B scripts/depgraph_selftest.py       (exit 0 = all green)

Each case builds a throwaway tree in a temp directory and drives depgraph.py
the way an agent drives it - through the command line, reading the exit code
and the output, never by importing its functions. The contract defended is the
command-line one, because that is what a session or a hook invokes.

Covered: each language (Python, JS/TS, Markdown, HTML), each subcommand,
a cycle, a missing file, a non-repo folder, a git repo with an ignored file,
an unresolvable import, generated files, a large file, determinism, and that
every command ends in a RESULT line.

Cases 15-20 each come from a real run that was wrong (a production failure is a
free test case): six files of a web app and of KiT saved with a byte-order mark
were reported "python that does not parse" and lost every edge; 26 local modules
imported through sys.path were counted as third-party; 67 image, video and
licence links were reported unresolved; the tour never reached the web app's
app.py because tests import it. Case 21: 65 of the web app's files and 16 of
KiT's that read another through a path joined from parts were missing from
`affected`, and a changed test was not run.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DG = os.path.join(HERE, "depgraph.py")

PASS, FAIL = [], []


def run(root, *args):
    # cwd is the harness's own folder, never the fixture: the first red run
    # crashed here on the case whose project path does not exist.
    p = subprocess.run([sys.executable, "-B", DG] + list(args) + ["--project", root],
                       cwd=HERE, capture_output=True, timeout=120)
    return p.returncode, p.stdout.decode("utf-8", "replace") + \
        p.stderr.decode("utf-8", "replace")


def git(cwd, *args):
    return subprocess.run(("git",) + args, cwd=cwd, capture_output=True,
                          timeout=60).returncode == 0


def commit(cwd, msg):
    git(cwd, "add", "-A")
    git(cwd, "-c", "user.name=t", "-c", "user.email=t@example.com",
        "commit", "-q", "-m", msg)


def put(root, relpath, text):
    p = os.path.join(root, relpath.replace("/", os.sep))
    d = os.path.dirname(p)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _remove(tmp):
    """Git writes read-only objects; clear the bit and retry (selftest.py)."""
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
        ("\n         " + detail.replace("\n", "\n         ")[:2500]) if
        (detail and not cond) else ""))


def last_line(out):
    lines = [x for x in out.strip().split("\n") if x.strip()]
    return lines[-1] if lines else ""


def result_line(name, rc, out, want_rc=None):
    ll = last_line(out)
    check("%s ends in a RESULT line%s" % (name, "" if want_rc is None else
                                          " and exits %d" % want_rc),
          ll.startswith("RESULT:") and (want_rc is None or rc == want_rc),
          "rc=%d\n%s" % (rc, out[-1500:]))


# --------------------------------------------------------------- fixtures

def fixture_mixed(root):
    """One tree with every language, a cycle, an unresolvable import, an
    inferred call, generated files and a wikilink."""
    put(root, "README.md", "# Demo\n\nSee [the guide](docs/guide.md).\n")
    put(root, "main.py",
        "import pkg.a as a\nfrom pkg.c import C\n\n\nclass Main(C):\n    pass\n\n\n"
        "def go():\n    a.run()\n    helper()\n")
    put(root, "pkg/__init__.py", "")
    put(root, "pkg/a.py",
        "from . import b\nfrom .c import C\nimport os, sys\nimport requests\n\n\n"
        "def run():\n    b.use()\n    return C()\n")
    put(root, "pkg/b.py",
        "from pkg import a\nfrom .missing import nothing\n\n\ndef use():\n    a.run()\n")
    put(root, "pkg/c.py", "class C:\n    pass\n")
    put(root, "pkg/d.py", "from pkg.c import C\n\n\nclass D(C):\n    pass\n")
    put(root, "tools/helper.py", "def helper():\n    return 1\n")
    put(root, "docs/guide.md",
        "# Guide\n\n[readme](../README.md)\n[[notes]]\n[gone](nope.md)\n"
        "[web](https://example.com/x.md)\n")
    put(root, "docs/notes.md", "# notes\n")
    put(root, "web/index.html",
        "<!doctype html><html><head>\n"
        "<link rel=\"stylesheet\" href=\"/web/t.css?v=3\">\n"
        "<script src=\"https://cdn.example.com/x.js\"></script>\n"
        "</head><body>\n<a href=\"../docs/guide.md\">g</a>\n"
        "<img src=\"logo.png\">\n<script src=\"app.js\"></script>\n"
        "<script src=\"gen.js?v=1\"></script>\n</body></html>\n")
    put(root, "web/app.js",
        "import './lib';\nimport x from './util.js';\n"
        "const c = require('./cfg');\nconst l = () => import('./lazy');\n"
        "export * from './re';\nimport React from 'react';\n"
        "// import './ghost'\nconst s = \"import './ghost2'\";\n"
        "/* import './ghost3' */\n")
    put(root, "web/lib/index.ts", "export const L = 1;\n")
    put(root, "web/util.ts", "export const U = 2;\n")
    put(root, "web/cfg.json", "{}\n")
    put(root, "web/lazy.tsx", "export default 1;\n")
    put(root, "web/re.mjs", "export const R = 3;\n")
    put(root, "web/t.css", "body{}\n")
    put(root, "web/logo.png", "not really a png\n")
    put(root, "web/app.min.js", "import './lib';\n")
    put(root, "web/gen.jsx", "import './util.js';\n")
    put(root, "web/gen.js", "import './util.js';\n")
    put(root, "node_modules/x/index.js", "import '../../web/util.js';\n")
    put(root, "dist/bundle.js", "import '../web/util.js';\n")


def fixture_real(root):
    """What the first real-repo runs got wrong, one file per defect."""
    put(root, "README.md", "# Real\n")
    put(root, "app.py",
        "import core\nimport deepmod\nimport twin\nimport json\n"
        "from pathlib import Path\n\nPath('x')\ncore.run()\n\n"
        "if __name__ == '__main__':\n    core.run()\n")
    put(root, "core.py", "def run():\n    return 1\n")
    put(root, "mypath.py", "class Path:\n    pass\n")
    put(root, "util/json.py", "X = 1\n")
    put(root, "lib/deepmod.py", "D = 1\n")
    put(root, "a1/twin.py", "W = 1\n")
    put(root, "a2/twin.py", "W = 2\n")
    # a web app's diagnostic script and KiT's kid/firstrun.py begin with EF BB BF
    put(root, "bom.py", "﻿import core\nimport os\n")
    put(root, "ns/one.py", "from . import two\nfrom .deep import three\n")
    # a web app's test suite: `import pkg` of a folder with no __init__.py
    # was counted as a third-party package
    put(root, "nsuser.py", "import ns as pkg\nimport ns.two\n")
    put(root, "ns/two.py", "T = 2\n")
    put(root, "ns/deep/three.py", "T = 3\n")
    put(root, "tests/test_app.py", "import app\nimport core\n")
    put(root, "img/logo.png", "not really a png\n")
    put(root, "LICENSE", "MIT\n")
    put(root, "docs/page.md",
        "# Page\n\n```\n[not a link](nowhere.md)\n```\n\n"
        "[logo](../img/logo.png) and [licence](../LICENSE) and [lib](../lib/)\n"
        "[^1]: See the notes\n[gone](missing.md)\n")
    put(root, "site/index.html",
        "<!doctype html><html><head>\n<link rel=\"icon\" href=\"../img/logo.png\">\n"
        "<script type=\"module\">\nimport './main.js';\n</script>\n"
        "<script src=\"{{ url_for('static', filename='app.js') }}\"></script>\n"
        "</head><body></body></html>\n")
    put(root, "site/main.js", "export const M = 1;\n")
    put(root, "static/app.js", "export const A = 1;\n")
    put(root, ".eslintrc.js", "module.exports = require('./lint-base.js');\n")
    put(root, "lint-base.js", "module.exports = {};\n")
    # a web app's build script reads its JSX source through
    # path.join(__dirname, 'static', 'app.jsx'); the graph missed it
    put(root, "tools/build.mjs",
        "const src = path.join(__dirname, '..', 'static', 'app.js');\n"
        "const w = new Worker('./worker.js');\nconst note = 'nothere.js';\n")
    put(root, "tools/worker.js", "self.onmessage = () => 0;\n")


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    tmp = tempfile.mkdtemp(prefix="dgselftest-")
    try:
        # ------------------------------------------------ 0 the script exists
        print("\n0. depgraph.py exists and answers --help")
        check("depgraph.py is present", os.path.isfile(DG), DG)

        m = os.path.join(tmp, "mixed")
        os.makedirs(m)
        fixture_mixed(m)

        # ------------------------------------------------ 1 json: the graph
        print("\n1. json - every language parsed into one sorted graph")
        rc, out = run(m, "json")
        result_line("json", rc, out, 0)
        body = out[:out.rfind("RESULT:")]
        try:
            g = json.loads(body)
        except ValueError:
            g = {}
        nodes = [n["id"] for n in g.get("nodes", [])]
        edges = g.get("edges", [])
        check("json parses and carries nodes and edges",
              bool(nodes) and bool(edges), body[:800])
        check("node ids are sorted", nodes == sorted(nodes), repr(nodes))
        keys = [(e["from"], e["to"], e["kind"]) for e in edges]
        check("edges are sorted", keys == sorted(keys), repr(keys[:20]))

        def has(src, dst, kind=None):
            return any(e["from"] == src and e["to"] == dst
                       and (kind is None or e["kind"] == kind) for e in edges)
        check("python: `import pkg.a as a` resolves to pkg/a.py",
              has("main.py", "pkg/a.py", "import"), repr(keys))
        check("python: `from . import b` resolves to pkg/b.py",
              has("pkg/a.py", "pkg/b.py", "import"), repr(keys))
        check("python: `from .c import C` resolves to pkg/c.py",
              has("pkg/a.py", "pkg/c.py", "import"), repr(keys))
        check("python: `from pkg import a` resolves to pkg/a.py",
              has("pkg/b.py", "pkg/a.py", "import"), repr(keys))
        check("python: a call through an imported module is a calls edge",
              has("main.py", "pkg/a.py", "calls") and has("pkg/a.py", "pkg/b.py", "calls"),
              repr(keys))
        check("python: a class base is an inherits edge",
              has("pkg/d.py", "pkg/c.py", "inherits") and has("main.py", "pkg/c.py", "inherits"),
              repr(keys))
        inf = [e for e in edges if e["from"] == "main.py" and e["to"] == "tools/helper.py"]
        check("python: a bare call defined in exactly one other file is an "
              "INFERRED calls edge", bool(inf) and all(e.get("inferred") for e in inf),
              repr(inf))
        check("js: a bare directory import resolves to its index.ts",
              has("web/app.js", "web/lib/index.ts", "import"), repr(keys))
        check("js: a `.js` specifier resolves to the `.ts` beside it",
              has("web/app.js", "web/util.ts", "import"), repr(keys))
        check("js: require() resolves, to json too",
              has("web/app.js", "web/cfg.json", "require"), repr(keys))
        check("js: a dynamic import() resolves",
              has("web/app.js", "web/lazy.tsx", "dynamic-import"), repr(keys))
        check("js: `export * from` is a reexport edge",
              has("web/app.js", "web/re.mjs", "reexport"), repr(keys))
        check("js: an import in a comment or a string is NOT an edge",
              not any("ghost" in e["to"] for e in edges)
              and not any("ghost" in u.get("spec", "") for u in g.get("unresolved", [])),
              repr(keys) + repr(g.get("unresolved")))
        check("markdown: a relative link, a wikilink and an upward link resolve",
              has("README.md", "docs/guide.md", "link")
              and has("docs/guide.md", "docs/notes.md", "link")
              and has("docs/guide.md", "README.md", "link"), repr(keys))
        check("html: script src, link href and a href resolve, root-absolute too",
              has("web/index.html", "web/app.js", "script")
              and has("web/index.html", "web/t.css", "link")
              and has("web/index.html", "docs/guide.md", "href"), repr(keys))
        check("html: a script that is the build output of a source beside it "
              "points at the source", has("web/index.html", "web/gen.jsx", "script"),
              repr(keys))
        unres = g.get("unresolved", [])
        check("an unresolvable relative import is reported, with its file and line",
              any(u["file"] == "pkg/b.py" and "missing" in u["spec"] for u in unres)
              and any(u["file"] == "docs/guide.md" and "nope.md" in u["spec"] for u in unres),
              repr(unres))
        ext = g.get("externals", {})
        check("stdlib and third-party imports are counted as external, not unresolved",
              "requests" in ext and "react" in ext and "os" in ext
              and not any(u["spec"] in ("requests", "react", "os") for u in unres),
              repr(ext) + repr(unres))
        skipped = {s["file"]: s["reason"] for s in g.get("skipped", [])}
        check("generated files are skipped and named with a reason",
              "minified" in skipped.get("web/app.min.js", "")
              and "gen.jsx" in skipped.get("web/gen.js", ""), repr(skipped))
        check("node_modules and dist are never walked",
              not any(n.startswith(("node_modules/", "dist/")) for n in nodes)
              and not any(s.startswith(("node_modules/", "dist/")) for s in skipped),
              repr(nodes) + repr(skipped))
        check("an image is not a node", "web/logo.png" not in nodes, repr(nodes))
        rc2, out2 = run(m, "json")
        check("json is byte-identical on a second run", out == out2)

        # ------------------------------------------------ 2 explain
        print("\n2. explain - what a file imports and who imports it")
        rc, out = run(m, "explain", "pkg/a.py")
        result_line("explain", rc, out, 0)
        sec = out.split("imported by")[0] if "imported by" in out else ""
        check("lists what it imports (out) before who imports it (in)",
              "pkg/b.py" in sec and "pkg/c.py" in sec, out)
        sec2 = out.split("imported by")[-1] if "imported by" in out else ""
        check("lists who imports it", "main.py" in sec2 and "pkg/b.py" in sec2, out)
        check("names its externals with stdlib told apart",
              "requests" in out and "os" in out and "stdlib" in out, out)
        rc, out = run(m, "explain", "pkg/b.py")
        check("names the unresolved import with its line",
              "missing" in out and ":2" in out, out)
        rc, out = run(m, "explain", "C")
        check("a symbol name resolves to the file that defines it",
              rc == 0 and "pkg/c.py" in out, out)
        rc, out = run(m, "explain", "nope.py")
        result_line("explain of a missing file", rc, out, 2)
        check("a missing file is refused by name", "nope.py" in out, out)
        rc, out = run(m, "explain", "a.py")
        check("a basename that matches one file is accepted", rc == 0 and "pkg/a.py" in out, out)

        # ------------------------------------------------ 3 path
        print("\n3. path - the shortest dependency path")
        rc, out = run(m, "path", "main.py", "pkg/b.py")
        result_line("path", rc, out, 0)
        check("finds main.py -> pkg/a.py -> pkg/b.py",
              re.search(r"main\.py.*\n.*pkg/a\.py.*\n.*pkg/b\.py", out) is not None
              and "2" in last_line(out), out)
        rc, out = run(m, "path", "pkg/c.py", "main.py")
        check("a path that only exists in reverse is found and said so",
              rc == 0 and "reverse" in out.lower(), out)
        rc, out = run(m, "path", "pkg/c.py", "web/app.js")
        result_line("path with no path", rc, out, 1)
        check("says no path", "no path" in out.lower(), out)

        # ------------------------------------------------ 4 affected
        print("\n4. affected - the reverse blast radius")
        rc, out = run(m, "affected", "pkg/c.py")
        result_line("affected", rc, out, 0)
        check("depth 1: its direct importers, including the inheritor",
              re.search(r"^\s*1\s+main\.py", out, re.M) and
              re.search(r"^\s*1\s+pkg/a\.py", out, re.M) and
              re.search(r"^\s*1\s+pkg/d\.py", out, re.M), out)
        check("depth 2: the importer of an importer",
              re.search(r"^\s*2\s+pkg/b\.py", out, re.M) is not None, out)
        check("the count and the deepest depth are in the RESULT line",
              "4" in last_line(out) and "depth 2" in last_line(out), out)
        rc, out = run(m, "affected", "pkg/c.py", "--max-depth", "1")
        check("--max-depth stops the walk", "pkg/b.py" not in out, out)
        rc, out = run(m, "affected", "docs/notes.md")
        check("a leaf nobody imports is still answered, through the doc link",
              rc == 0 and "docs/guide.md" in out, out)
        rc, out = run(m, "affected", "nope.py")
        result_line("affected of a missing file", rc, out, 2)

        # ------------------------------------------------ 5 hubs
        print("\n5. hubs - the most depended-on files")
        rc, out = run(m, "hubs")
        result_line("hubs", rc, out, 0)
        rows = [x for x in out.split("\n") if re.search(r"\.(py|js|ts|md|html)\b", x)]
        check("pkg/c.py (3 dependents) ranks first", rows and "pkg/c.py" in rows[0], out)
        check("each row shows in and out degree", re.search(r"\b3\b.*pkg/c\.py", out) is not None, out)
        rc, out = run(m, "hubs", "--top", "2")
        check("--top limits the list", len([x for x in out.split("\n")
                                             if re.search(r"^\s*\d+\s+\d+\s+", x)]) == 2, out)

        # ------------------------------------------------ 6 cycles
        print("\n6. cycles")
        rc, out = run(m, "cycles")
        result_line("cycles", rc, out, 0)
        check("the a <-> b import cycle is found, and only it",
              "pkg/a.py" in out and "pkg/b.py" in out and "main.py" not in out
              and "1 cycle" in last_line(out), out)
        rc, out = run(m, "cycles", "--fail-on-cycles")
        result_line("cycles --fail-on-cycles with a cycle present", rc, out, 1)

        # ------------------------------------------------ 7 clusters
        print("\n7. clusters")
        rc, out = run(m, "clusters")
        result_line("clusters", rc, out, 0)
        blocks = re.split(r"\n(?=cluster )", out)
        ab = [b for b in blocks if "pkg/a.py" in b]
        check("the python package lands in one cluster",
              ab and "pkg/b.py" in ab[0] and "web/app.js" not in ab[0], out)
        check("the web tree is another cluster",
              any("web/app.js" in b and "web/util.ts" in b for b in blocks), out)
        check("the RESULT names the count", re.search(r"RESULT: \d+ cluster", out) is not None, out)

        # ------------------------------------------------ 8 tour
        print("\n8. tour - an ordered reading path")
        rc, out = run(m, "tour")
        result_line("tour", rc, out, 0)
        steps = re.findall(r"^\s*(\d+)\.\s+(\S+)", out, re.M)
        files = [s[1] for s in steps]
        check("the tour starts at README.md", files and files[0] == "README.md", out)
        check("main.py, an entry point, comes before what it imports",
              "main.py" in files and "pkg/b.py" in files
              and files.index("main.py") < files.index("pkg/b.py"), out)
        check("every step is a real file, listed once",
              len(files) == len(set(files)) and set(files) <= set(nodes), out)
        rc, out = run(m, "tour", "--steps", "3")
        check("--steps caps the tour and says how many were left off",
              len(re.findall(r"^\s*\d+\.\s", out, re.M)) == 3 and "more" in out, out)

        # ------------------------------------------------ 9 html
        print("\n9. html - one self-contained file")
        hp = os.path.join(tmp, "out", "graph.html")
        rc, out = run(m, "html", "--out", hp)
        result_line("html", rc, out, 0)
        html = open(hp, encoding="utf-8").read() if os.path.isfile(hp) else ""
        check("the file is written and names every node",
              html and all(n in html for n in nodes), out)
        check("no CDN, no fetch, no external script or stylesheet",
              "://" not in html and "fetch(" not in html and "XMLHttpRequest" not in html
              and re.search(r"<script[^>]*\ssrc=", html) is None
              and "<link" not in html, html[:600])
        check("inline script and style", "<script>" in html and "<style>" in html)
        check("phone width and dark mode are declared",
              "width=device-width" in html and "prefers-color-scheme" in html
              and "@media" in html, html[:2000])
        rc, out = run(m, "html")
        check("without --out the page goes to stdout", "<!doctype html>" in out.lower(), out[:300])

        # ------------------------------------------------ 10 --graph reuse
        print("\n10. a saved json export answers the same as a fresh build")
        jp = os.path.join(tmp, "out", "g.json")
        rc, out = run(m, "json", "--out", jp)
        rc1, a1 = run(m, "hubs")
        rc2, a2 = run(m, "hubs", "--graph", jp)
        check("hubs --graph FILE equals hubs from the tree", rc1 == rc2 == 0 and a1 == a2,
              a1 + "\n---\n" + a2)

        # ------------------------------------------------ 11 a git repo
        print("\n11. inside a git repository, ignored files are not read")
        r = os.path.join(tmp, "repo")
        os.makedirs(r)
        put(r, ".gitignore", "ignored.py\n")
        put(r, "a.py", "import b\n")
        put(r, "b.py", "X = 1\n")
        put(r, "ignored.py", "import b\n")
        put(r, "café.py", "import b\n")
        git(r, "init", "-q")
        commit(r, "c1")
        rc, out = run(r, "explain", "b.py")
        check("the ignored importer is not in the graph",
              rc == 0 and "a.py" in out and "ignored.py" not in out, out)
        rc, out = run(r, "affected", "--since", "HEAD")
        result_line("affected --since with nothing changed", rc, out, 0)
        check("says nothing changed", "nothing" in out.lower(), out)
        put(r, "b.py", "X = 2\n")
        rc, out = run(r, "affected", "--since", "HEAD")
        check("an uncommitted change is taken from git and its importer named",
              rc == 0 and "b.py" in out and re.search(r"^\s*1\s+a\.py", out, re.M), out)
        put(r, "notes.txt", "new\n")
        rc, out = run(r, "affected", "--since", "HEAD")
        check("a changed file that is not in the graph is named as such",
              "notes.txt" in out and "not in" in out.lower(), out)
        rc, out = run(r, "affected", "--since", "no-such-ref")
        result_line("affected --since a ref that does not exist", rc, out, 2)
        put(r, "café.py", "import b\nimport a\n")
        rc, out = run(r, "affected", "--since", "HEAD")
        changed_line = [x for x in out.split("\n") if x.startswith("changed:")]
        check("a changed file with a non-ASCII name is read from git as itself",
              changed_line and "café.py" in changed_line[0], out)
        os.remove(os.path.join(r, "b.py"))
        rc, out = run(r, "affected", "--since", "HEAD")
        check("a deleted file is named as deleted, not as outside the graph",
              re.search(r"deleted.*\bb\.py", out) is not None, out)

        # ------------------------------------------------ 12 not a repo, empty
        print("\n12. a folder that is not a repository, and an empty one")
        check("the mixed tree above was not a repository (git ls-files absent)",
              not os.path.isdir(os.path.join(m, ".git")))
        e = os.path.join(tmp, "empty")
        os.makedirs(e)
        rc, out = run(e, "hubs")
        result_line("hubs on an empty folder", rc, out, 0)
        # `"0" in last_line` was green on "[Errno 2]" in the first red run:
        # the RESULT line itself must say zero hubs.
        check("says the graph is empty", re.match(r"RESULT: 0 hub", last_line(out)) is not None, out)
        rc, out = run(os.path.join(tmp, "does-not-exist"), "hubs")
        result_line("a project path that does not exist", rc, out, 2)

        # ------------------------------------------------ 13 a large file
        print("\n13. a large file is parsed, not capped away")
        big = os.path.join(tmp, "big")
        os.makedirs(big)
        filler = "const v%d = () => <div className=\"x\">{'%s'}</div>;\n"
        put(big, "src/big.jsx", "".join(filler % (i, "y" * 40) for i in range(6000))
            + "import { z } from './z';\n")
        put(big, "src/z.ts", "export const z = 1;\n")
        put(big, "big.py", "".join("def f%d():\n    return %d\n\n\n" % (i, i)
                                   for i in range(12000)) + "import helper\n")
        put(big, "helper.py", "H = 1\n")
        sz = os.path.getsize(os.path.join(big, "src", "big.jsx"))
        check("the fixture is over 300 KB", sz > 300000, str(sz))
        rc, out = run(big, "explain", "src/big.jsx")
        check("the import at the end of a 300 KB jsx is found",
              rc == 0 and "src/z.ts" in out, out)
        rc, out = run(big, "explain", "big.py")
        check("the import at the end of a 12,000-function python file is found",
              rc == 0 and "helper.py" in out, out)

        # ------------------------------------------------ 14 inferred is opt-in
        print("\n14. inferred edges are off by default and on with --inferred")
        rc, out = run(m, "affected", "tools/helper.py")
        check("without --inferred the bare call does not count",
              "main.py" not in out and "0" in last_line(out), out)
        rc, out = run(m, "affected", "tools/helper.py", "--inferred")
        check("with --inferred it does, and is marked inferred",
              "main.py" in out and "inferred" in out, out)

        # ------------------------------------------------ 15 what real repos broke
        print("\n15. what the first real-repo runs got wrong")
        x = os.path.join(tmp, "real")
        os.makedirs(x)
        fixture_real(x)
        rc, out = run(x, "json")
        body = out[:out.rfind("RESULT:")]
        try:
            gx = json.loads(body)
        except ValueError:
            gx = {}
        ex = gx.get("edges", [])
        ux = gx.get("unresolved", [])
        xnodes = [n["id"] for n in gx.get("nodes", [])]
        xskip = {s["file"]: s["reason"] for s in gx.get("skipped", [])}

        def hasx(src, dst, kind=None):
            return any(e["from"] == src and e["to"] == dst
                       and (kind is None or e["kind"] == kind) for e in ex)
        xkeys = repr([(e["from"], e["to"], e["kind"]) for e in ex])
        check("a python file saved with a byte-order mark is parsed, not skipped",
              hasx("bom.py", "core.py", "import") and "bom.py" not in xskip,
              xkeys + repr(xskip))
        dm = [e for e in ex if e["from"] == "app.py" and e["to"] == "lib/deepmod.py"]
        check("an import only sys.path can find resolves to the one local file "
              "of that name, and says it was matched by name",
              bool(dm) and all(e.get("by_name") is True for e in dm), xkeys)
        check("an import two local files could satisfy is reported ambiguous, "
              "never guessed",
              not hasx("app.py", "a1/twin.py") and not hasx("app.py", "a2/twin.py")
              and any(u["file"] == "app.py" and u["spec"] == "twin"
                      and "a1/twin.py" in u["reason"] and "a2/twin.py" in u["reason"]
                      for u in ux), xkeys + repr(ux))
        check("a stdlib name stays stdlib when a local file shares it",
              not hasx("app.py", "util/json.py")
              and gx.get("externals", {}).get("json", {}).get("stdlib") is True,
              xkeys + repr(gx.get("externals")))
        check("a namespace package's relative imports resolve",
              hasx("ns/one.py", "ns/two.py", "import")
              and hasx("ns/one.py", "ns/deep/three.py", "import"), xkeys)
        nsu = [n for n in gx.get("nodes", []) if n["id"] == "nsuser.py"]
        check("importing a local folder with no __init__.py is not a third-party "
              "package, and its module still resolves",
              bool(nsu) and "ns" not in nsu[0].get("externals", ["ns"])
              and "ns" not in gx.get("externals", {})
              and hasx("nsuser.py", "ns/two.py", "import"), repr(nsu) + xkeys)
        check("an image, a licence and a folder link are not unresolved",
              not any(("logo.png" in u["spec"] or "LICENSE" in u["spec"]
                       or u["spec"].rstrip("/").endswith("lib")) for u in ux)
              and hasx("docs/page.md", "LICENSE", "link")
              and gx.get("stats", {}).get("asset_refs", 0) >= 2,
              repr(ux) + repr(gx.get("stats")))
        check("a link inside a code fence is not read",
              not any("nowhere" in u["spec"] for u in ux)
              and not any("nowhere" in e["to"] for e in ex), repr(ux))
        check("a missing link after a code fence keeps its own line number (9)",
              any(u["file"] == "docs/page.md" and u["spec"] == "missing.md"
                  and u["line"] == 9 for u in ux), repr(ux))
        check("a footnote definition is not a link",
              not any(u["file"] == "docs/page.md" and u["spec"] == "See" for u in ux),
              repr(ux))
        check("html: an inline module script's import resolves",
              hasx("site/index.html", "site/main.js"), xkeys)
        check("html: a Flask url_for('static', filename=...) resolves",
              hasx("site/index.html", "static/app.js", "script")
              and not any("url_for" in u["spec"] for u in ux), xkeys + repr(ux))
        check("js: a file named in a string literal is a references edge, "
              "./-relative too, and a name that is no file is not reported",
              hasx("tools/build.mjs", "static/app.js", "references")
              and hasx("tools/build.mjs", "tools/worker.js", "references")
              and not any("nothere" in u["spec"] for u in ux), xkeys + repr(ux))
        rc, out = run(x, "json", "--inferred")
        check("a name bound by an external import never becomes an inferred call",
              '"to": "mypath.py"' not in out and '"from": "app.py"' in out, out[:600])
        rc, out = run(x, "explain", ".eslintrc.js")
        check("a dot-file is explained by its own name",
              rc == 0 and "lint-base.js" in out, out)
        rc, out = run(x, "explain", os.path.join(x, "core.py"))
        check("an absolute path inside the project is accepted",
              rc == 0 and out.startswith("core.py"), out)

        # ------------------------------------------------ 16 --graph keeps externals
        print("\n16. explain from a saved graph still names externals")
        jx = os.path.join(tmp, "out", "real.json")
        run(x, "json", "--out", jx)
        rc, out = run(x, "explain", "bom.py", "--graph", jx)
        check("explain --graph names the stdlib import",
              rc == 0 and re.search(r"external:.*\bos \(stdlib\)", out) is not None
              and "1 external" in last_line(out), out)

        # ------------------------------------------------ 17 tour entry
        print("\n17. the tour starts at the runnable app, and tests come last")
        rc, out = run(x, "tour", "--steps", "0")
        files = [s[1] for s in re.findall(r"^\s*(\d+)\.\s+(\S+)", out, re.M)]
        check("README, then app.py (it has a __main__ guard; only a test imports it)",
              files[:2] == ["README.md", "app.py"], out)
        check("core.py comes before the test that imports it",
              "core.py" in files and "tests/test_app.py" in files
              and files.index("core.py") < files.index("tests/test_app.py"), out)
        # a web app: its end-to-end driver (a __main__ script that imports app.py)
        # reached one file more than app.py and opened the tour ahead of the program
        dr = os.path.join(tmp, "drivers")
        os.makedirs(dr)
        put(dr, "README.md", "# Drivers\n")
        put(dr, "prog.py", "import lib1\nimport lib2\n\nif __name__ == '__main__':\n    lib1.go()\n")
        put(dr, "lib1.py", "def go():\n    return 1\n")
        put(dr, "lib2.py", "X = 2\n")
        put(dr, "lib3.py", "Y = 3\n")
        put(dr, "zz_driver.py", "import prog\nimport lib3\n\nif __name__ == '__main__':\n    prog.lib1.go()\n")
        rc, out = run(dr, "tour", "--steps", "0")
        files = [s[1] for s in re.findall(r"^\s*(\d+)\.\s+(\S+)", out, re.M)]
        check("a script that runs the program comes after the program it runs",
              files[:2] == ["README.md", "prog.py"] and "zz_driver.py" in files
              and files.index("lib2.py") < files.index("zz_driver.py"), out)

        # ------------------------------------------------ 18 tests named
        print("\n18. hubs and affected say which dependents are tests")
        rc, out = run(x, "hubs")
        check("hubs shows core.py with 3 dependents, 1 of them a test",
              re.search(r"^\s*3\s+\d+\s+1\s+core\.py", out, re.M) is not None, out)
        rc, out = run(x, "affected", "core.py")
        check("affected counts the tests in its RESULT",
              re.search(r"RESULT: 3 file\(s\) affected.*\b1 test", last_line(out))
              is not None, out)

        # ------------------------------------------------ 19 clusters
        print("\n19. files with no edges are one line, not one cluster each")
        rc, out = run(x, "clusters")
        check("no single-file clusters, and the unconnected files are named",
              re.search(r"^cluster \d+: 1 file", out, re.M) is None
              and re.search(r"^unconnected: \d+ file.*\n(?:.*\n)*?\s+mypath\.py", out, re.M)
              is not None, out)

        # ------------------------------------------------ 20 cycles --links
        print("\n20. doc links are cycles only when asked")
        rc, out = run(m, "cycles", "--links")
        check("cycles --links also finds README <-> docs/guide.md",
              "2 cycle" in last_line(out) and "README.md" in out, out)

        # ------------------------------------------------ 21 paths built from parts
        # a web app's test reads a module through
        # os.path.join(BASE, 'api', 'syms.py') and KiT
        # tests/test_brand.py:351 reads ROOT / "site" / "src" / "pages" / "index.astro";
        # neither test was among the tests `affected` said to run
        print("\n21. a path joined from parts is a reference, so its test is run")
        jn = os.path.join(tmp, "joins")
        os.makedirs(jn)
        put(jn, "api/syms.py", "def classify():\n    return 1\n")
        put(jn, "site/src/pages/index.astro", "---\n---\n<p>x</p>\n")
        put(jn, "tests/test_reads.py",
            "import os\nfrom pathlib import Path\n"
            "BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
            "ROOT = Path(__file__).resolve().parent.parent\n"
            "SRC = open(os.path.join(BASE, 'api',\n"
            "                        'syms.py')).read()\n"
            "PAGE = (ROOT / \"site\" / \"src\" / \"pages\" / \"index.astro\").read_text()\n"
            "ALSO = ROOT.joinpath(\"api\", \"syms.py\")\n"
            "GONE = os.path.join(BASE, 'api', 'nothere.py')\n"
            "DATA = os.path.join(BASE, 'tests', 'fixtures', 'data.json')\n")
        put(jn, "tests/fixtures/data.json", "{}\n")
        rc, out = run(jn, "json")
        try:
            gj = json.loads(out[:out.rfind("RESULT:")])
        except ValueError:
            gj = {}
        ej = gj.get("edges", [])
        jkeys = repr([(e["from"], e["to"], e["kind"], e["line"]) for e in ej])
        check("os.path.join(BASE, 'api', 'syms.py') over two lines is a references "
              "edge on the line the call starts",
              any(e["from"] == "tests/test_reads.py" and e["to"] == "api/syms.py"
                  and e["kind"] == "references" and e["line"] == 5 for e in ej), jkeys)
        check("ROOT / \"site\" / ... / \"index.astro\" is a references edge",
              any(e["from"] == "tests/test_reads.py" and e["to"] == "site/src/pages/index.astro"
                  and e["kind"] == "references" for e in ej), jkeys)
        check("a joined path that names no file is neither an edge nor a finding",
              not any("nothere" in e["to"] for e in ej)
              and not any("nothere" in u["spec"] for u in gj.get("unresolved", [])),
              jkeys + repr(gj.get("unresolved")))
        rc, out = run(jn, "affected", "api/syms.py")
        check("affected names the test that reads the file as a test to run",
              re.search(r"^tests to run: .*tests/test_reads\.py", out, re.M) is not None, out)
        # KiT --since 2ec977f: tests/test_brand.py and tests/test_landing_copy.py
        # changed themselves, and "tests to run" named neither
        rc, out = run(jn, "affected", "api/syms.py", "tests/test_reads.py",
                      "tests/fixtures/data.json")
        check("a test that changed is itself a test to run, and counted; "
              "a fixture under tests/ is data, not a test",
              re.search(r"^tests to run: .*tests/test_reads\.py", out, re.M) is not None
              and "data.json" not in "".join(l for l in out.split("\n")
                                             if l.startswith("tests to run"))
              and re.search(r"\b1 test\(s\) to run", last_line(out)) is not None, out)

    finally:
        _remove(tmp)

    print("\nRESULT: %d passed, %d failed" % (len(PASS), len(FAIL)))
    for f in FAIL:
        print("  FAILED: " + f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
