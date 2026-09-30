# Deps: python3.10+ stdlib, git optional | Path: scripts | Filename: depgraph.py | Created: 2026-09-29
# -*- coding: utf-8 -*-
"""depgraph.py - a deterministic dependency graph of a repository, and the
questions only a graph answers in one step.

WHAT IT READS (locally, no model, no network)
    Python      `ast`: imports (relative, namespace-package and src/ layouts
                resolved; a name only sys.path can find is matched to the one
                local file of that name and labeled so), calls through an
                imported name, class bases, and file names in string literals
                or joined from parts (os.path.join, Path / "x", joinpath).
    JS / TS     import, export-from, require() and import(), by a tokenizer
                that skips strings and comments; ./ paths resolved with the
                .ts/.tsx/.js/.jsx/index conventions; a string literal that
                names a file is a reference. Also .astro/.vue/.svelte.
    Markdown    [text](path), [id]: path and [[wikilinks]] between files, with
                code fences and comments left out.
    HTML        <script src>, inline module scripts, <link href>, <a href> and
                every other src; Flask's url_for('static', filename=...).
    Images, media and fonts are never nodes (a link to one is counted, not
    reported); node_modules, dist, .git and what git ignores are never read;
    minified and compiled files are skipped and named, and a reference to a
    compiled file points at its source.

COMMANDS (each ends in a RESULT: line; exit 0 ok, 1 finding, 2 could not run)
    explain FILE|SYMBOL     what it imports, who imports it, externals, unresolved
    path A B                the shortest dependency path (reverse if only that exists)
    affected FILE... [--since REF]
                            the reverse blast radius: what could break if these
                            change, and the tests to run (changed tests too);
                            --since takes the changed files from git
    hubs [--top N]          the most depended-on files, with how many dependents are tests
    cycles [--links] [--fail-on-cycles]
                            import cycles over code edges; --links adds doc links
    clusters                communities (Louvain, deterministic order)
    tour [--steps N]        an ordered reading path: README, the runnable entry,
                            what it depends on most, ... tests last
    html [--out FILE]       one self-contained page, no CDN, phone width, dark mode
    json [--out FILE]       the whole graph, sorted; --graph FILE reuses it

HONEST EDGES
    An edge read from an import, a base class or a call through an imported
    name is EXTRACTED. An import only sys.path could satisfy, matched to the one
    local file of that name, is EXTRACTED and marked by_name. A bare call whose
    name is defined in exactly one other file is INFERRED, and inferred edges
    count only with --inferred. What could not be resolved is reported by file
    and line - an import two local files could satisfy is "ambiguous", never
    guessed.

WHAT IT WILL NEVER DO
    Write into the project (json and html go to --out or stdout). Ask a model.
    Fetch anything. Follow a symlink. Take a git lock (GIT_OPTIONAL_LOCKS=0).
    Say "nothing depends on it" about a file it never saw: a file not in the
    graph is refused (exit 2).

USAGE
    python depgraph.py affected app.py --project C:\\path\\to\\project
    python depgraph.py affected --since origin/main --project .
    python depgraph.py html --out graph.html --project .
"""
import argparse
import ast
import builtins
import json
import os
import posixpath
import re
import subprocess
import sys
import time
from bisect import bisect_right
from collections import Counter, deque
from html.parser import HTMLParser
from urllib.parse import unquote

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".next", "dist", "build",
             ".venv", "venv", "site-packages", ".verify", "Archives", ".cursor"}
PY_EXT = (".py",)
JS_EXT = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts",
          ".vue", ".svelte", ".astro")
MD_EXT = (".md", ".markdown")
HTML_EXT = (".html", ".htm")
PARSED_EXT = PY_EXT + JS_EXT + MD_EXT + HTML_EXT
# What a reference may point at and still be a node: code, docs, styles, data,
# and extensionless text (LICENSE, Makefile). Anything else is an asset.
NODE_EXT = PARSED_EXT + (".css", ".scss", ".json", ".txt", ".csv", ".yaml",
                         ".yml", ".toml", ".sql", ".ini", ".cfg", ".xml", ".svg")
JS_RESOLVE_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts",
                  ".json", ".vue", ".svelte", ".astro", ".css")
JS_SWAP = {".js": (".ts", ".tsx"), ".jsx": (".tsx",), ".mjs": (".mts",),
           ".cjs": (".cts",)}
COMPILES_TO_JS = (".jsx", ".ts", ".tsx", ".coffee", ".svelte", ".vue")
MAX_BYTES = 8 * 1024 * 1024
STDLIB = frozenset(getattr(sys, "stdlib_module_names", ()))
BUILTINS = frozenset(dir(builtins))
_DATA_URI = re.compile(r"([\"'])data:[^\"']*\1|url\(\s*data:[^)]*\)")
# The kinds an import cycle is made of. A README and a guide that link to each
# other are not a defect, so doc links, hrefs and file-name references join
# cycles only with --links.
CODE_KINDS = ("import", "calls", "inherits", "require", "dynamic-import", "reexport")
_TEST_DIRS = {"tests", "test", "__tests__", "spec", "specs"}
_GIT_ENV = dict(os.environ, GIT_OPTIONAL_LOCKS="0")


# ---------------------------------------------------------------- helpers

def read_bytes(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return b""


def text_of(raw):
    """UTF-8 with any byte-order mark dropped. One web app's diagnostic script and
    one of KiT's modules begin with one, and `ast` refuses U+FEFF in a string: the
    first real run called six such files "python that does not parse"."""
    return raw.decode("utf-8-sig", "replace")


def read(path):
    return text_of(read_bytes(path))


def count_lines(raw):
    return raw.count(b"\n") + (1 if raw and not raw.endswith(b"\n") else 0)


def rel(root, path):
    try:
        return os.path.relpath(path, root).replace("\\", "/")
    except ValueError:
        return path.replace("\\", "/")


def _pj(*parts):
    """Join posix path pieces, ignoring empty ones ('' is the project root)."""
    return "/".join(p for p in parts if p)


def _line_index(text):
    """A function from a character offset to its 1-based line, by bisection -
    counting newlines per match is quadratic on a 700 KB file."""
    starts = [0] + [m.end() for m in re.finditer("\n", text)]
    return lambda pos: bisect_right(starts, pos)


def git(root, *args):
    """(ok, stdout). ok is False when git is absent or this is not a repo.
    GIT_OPTIONAL_LOCKS=0: reading a repository must never write its index."""
    try:
        p = subprocess.run(("git",) + args, cwd=root, capture_output=True,
                           timeout=60, env=_GIT_ENV)
        return p.returncode == 0, p.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return False, ""


def _kept(root):
    """The files git would keep here - tracked, or new and not ignored - or
    None outside a work tree (featuremap.py's rule: what git ignores differs
    per checkout, and an ignored file is not part of the project)."""
    ok, out = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    if not ok:
        return None
    return set(x for x in out.split("\0") if x)


def walk(root):
    """Every file under root that git keeps, skipping vendored and generated
    trees and dot-folders. Inside a repository git's own list is walked, so an
    ignored tree is never entered and a file is named as git spells it.
    Symlinks are never followed."""
    kept = _kept(root)
    if kept is not None:
        for r in sorted(kept):
            parts = r.split("/")
            if any(p in SKIP_DIRS or p.startswith(".") for p in parts[:-1]):
                continue
            p = os.path.join(root, *parts)
            if os.path.isfile(p) and not os.path.islink(p):
                yield r
        return
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")
                         and not os.path.islink(os.path.join(base, d)))
        for f in sorted(files):
            p = os.path.join(base, f)
            if not os.path.islink(p):
                yield rel(root, p)


def generated_reason(root, r, all_rel):
    """Why a file is build output rather than authored source, or None.
    featuremap.py's rule: a compiled .js beside its .jsx maps the same UI
    twice, and a minified bundle invents edges no human wrote."""
    base = posixpath.basename(r).lower()
    if ".min." in base or base.endswith((".bundle.js", ".chunk.js", ".map")):
        return "minified"
    parts = r.lower().split("/")
    if "vendor" in parts or "vendors" in parts or "third_party" in parts:
        return "vendored"
    if r.endswith(".js"):
        stem = r[:-3]
        for ext in COMPILES_TO_JS:
            if (stem + ext) in all_rel:
                return "build output of " + posixpath.basename(stem + ext)
    if r.endswith((".js", ".css", ".ts")):
        text = _DATA_URI.sub("data:", read(os.path.join(root, r)))
        if text and max((len(x) for x in text.split("\n")), default=0) > 2000:
            return "minified (a line over 2000 chars)"
    return None


def lang_of(r):
    low = r.lower()
    if low.endswith(PY_EXT):
        return "python"
    if low.endswith(JS_EXT):
        return "js"
    if low.endswith(MD_EXT):
        return "markdown"
    if low.endswith(HTML_EXT):
        return "html"
    if low.endswith((".css", ".scss")):
        return "css"
    return "data"


def is_node_file(r):
    return r.lower().endswith(NODE_EXT) or posixpath.splitext(posixpath.basename(r))[1] == ""


_TEST_CODE = (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")


def is_test(r):
    """A test or a test helper, by where it lives or what it is called. Code
    only: a fixture under tests/ (KiT's tests/fixtures/*.json) is data a test
    reads, and was once named among the tests to run."""
    parts = r.lower().split("/")
    base = parts[-1]
    if not base.endswith(_TEST_CODE):
        return False
    return (any(p in _TEST_DIRS for p in parts[:-1]) or base.startswith("test_")
            or base.endswith("_test.py") or ".test." in base or ".spec." in base
            or base == "conftest.py")


# ---------------------------------------------------------------- the graph

class Graph:
    def __init__(self, root):
        self.root = root
        self.nodes = {}        # id -> {"lang", "lines", "symbols", "ext", "runnable"}
        self.edges = {}        # (from, to, kind) -> {"symbols", "line", "inferred", "by_name"}
        self.unresolved = []   # {"file", "spec", "kind", "line", "reason"}
        self.stdlib = set()
        self.skipped = []      # {"file", "reason"}
        self.generated = {}    # rel -> reason
        self.all_rel = set()
        self.dirs = {""}
        self._lower = {}
        self._lower_dirs = {}
        self.stats = {}
        self.assets = 0
        self.templated = 0

    # -- files
    def set_files(self, files):
        self.all_rel = set(files)
        for f in files:
            d = posixpath.dirname(f)
            while d and d not in self.dirs:
                self.dirs.add(d)
                d = posixpath.dirname(d)
        if os.name == "nt":
            self._lower = {f.lower(): f for f in files}
            self._lower_dirs = {d.lower(): d for d in self.dirs}

    @staticmethod
    def _norm(r):
        r = posixpath.normpath(r.replace("\\", "/"))
        return "" if r == "." else r

    def find(self, r):
        """The canonical id of a kept file named r (case-insensitively on
        Windows), or None. A file on disk that git ignores is not found."""
        r = self._norm(r)
        if not r or r == ".." or r.startswith(("../", "/")):
            return None
        if r in self.all_rel:
            return r
        if os.name == "nt":
            return self._lower.get(r.lower())
        return None

    def is_dir(self, r):
        r = self._norm(r)
        if r == "":
            return True
        if r == ".." or r.startswith(("../", "/")):
            return False
        return r in self.dirs or (os.name == "nt" and r.lower() in self._lower_dirs)

    def target(self, r):
        """(id, None) for a node; (None, "asset") for an image, font or media
        file; (None, "generated") for a minified or vendored file; (None, None)
        when nothing is there. A compiled file resolves to its source."""
        f = self.find(r)
        if not f:
            return None, None
        gen = self.generated.get(f)
        if gen and gen.startswith("build output of "):
            src = self.find(_pj(posixpath.dirname(f), gen[len("build output of "):]))
            if src:
                return src, None
        if gen:
            return None, "generated"
        if not is_node_file(f):
            return None, "asset"
        return f, None

    def ref(self, src, cands, kind, line, dirs_ok=False):
        """Try each candidate path for a reference: add the edge, count the
        asset, name the generated file as external, or accept a folder link.
        False when none of them is there."""
        for c in cands:
            t, note = self.target(c)
            if t:
                if t != src:
                    self.add_edge(src, t, kind, None, line)
                return True
            if note == "asset":
                self.assets += 1
                return True
            if note == "generated":
                self.external(src, self._norm(c))
                return True
            if dirs_ok and self.is_dir(c):
                return True
        return False

    def add_node(self, r, lines=None):
        if r not in self.nodes:
            self.nodes[r] = {"lang": lang_of(r), "lines": 0, "symbols": [],
                             "ext": set(), "runnable": ""}
            if lines is None:   # reached only as a target: count its lines once
                lines = count_lines(read_bytes(os.path.join(self.root, r)))
        if lines is not None:
            self.nodes[r]["lines"] = lines

    def add_edge(self, src, dst, kind, symbol=None, line=0, inferred=False, by_name=False):
        if src == dst:
            return
        self.add_node(dst)
        e = self.edges.setdefault((src, dst, kind), {"symbols": set(), "line": line,
                                                     "inferred": inferred, "by_name": by_name})
        if symbol:
            e["symbols"].add(symbol)
        if line and (not e["line"] or line < e["line"]):
            e["line"] = line
        if not inferred:
            e["inferred"] = False
        if not by_name:
            e["by_name"] = False

    def miss(self, src, spec, kind, line, reason):
        self.unresolved.append({"file": src, "spec": spec, "kind": kind,
                                "line": line, "reason": reason})

    def external(self, src, name, stdlib=False):
        self.nodes[src]["ext"].add(name)
        if stdlib:
            self.stdlib.add(name)

    def externals(self):
        """{name: number of files that use it}."""
        c = Counter()
        for n in self.nodes.values():
            c.update(n["ext"])
        return c

    # -- views
    def edge_list(self, inferred=False, kinds=None):
        for key in sorted(self.edges):
            e = self.edges[key]
            if e["inferred"] and not inferred:
                continue
            if kinds is not None and key[2] not in kinds:
                continue
            yield key[0], key[1], key[2], e

    def adjacency(self, inferred=False, reverse=False, kinds=None):
        """{node: {neighbor: [(kind, symbols, line, inferred, by_name)]}} - sorted."""
        adj = {n: {} for n in self.nodes}
        for a, b, kind, e in self.edge_list(inferred, kinds):
            if reverse:
                a, b = b, a
            adj.setdefault(a, {}).setdefault(b, []).append(
                (kind, sorted(e["symbols"]), e["line"], e["inferred"], e.get("by_name", False)))
        return adj

    def degrees(self, inferred=False, kinds=None):
        """{node: (in, out)} counting distinct files, not edges."""
        ins, outs = Counter(), Counter()
        seen = set()
        for a, b, kind, e in self.edge_list(inferred, kinds):
            if (a, b) in seen:
                continue
            seen.add((a, b))
            outs[a] += 1
            ins[b] += 1
        return {n: (ins[n], outs[n]) for n in self.nodes}

    # -- export
    def to_json(self):
        ext = self.externals()
        return {
            "version": 2,
            "root": self.root.replace("\\", "/"),
            "stats": {k: self.stats[k] for k in sorted(self.stats)},
            "nodes": [{"id": n, "lang": d["lang"], "lines": d["lines"],
                       "symbols": d["symbols"], "externals": sorted(d["ext"]),
                       "runnable": d["runnable"]}
                      for n, d in sorted(self.nodes.items())],
            "edges": [{"from": a, "to": b, "kind": k, "symbols": sorted(e["symbols"]),
                       "line": e["line"], "inferred": e["inferred"],
                       "by_name": e.get("by_name", False)}
                      for a, b, k, e in self.edge_list(True)],
            "unresolved": sorted(self.unresolved, key=lambda u: (u["file"], u["line"], u["spec"])),
            "externals": {k: {"count": ext[k], "stdlib": k in self.stdlib}
                          for k in sorted(ext)},
            "skipped": sorted(self.skipped, key=lambda s: s["file"]),
        }

    @classmethod
    def from_json(cls, data):
        g = cls(data.get("root", "."))
        g.stats = dict(data.get("stats", {}))
        for n in data.get("nodes", []):
            g.nodes[n["id"]] = {"lang": n.get("lang", "data"), "lines": n.get("lines", 0),
                                "symbols": list(n.get("symbols", [])),
                                "ext": set(n.get("externals", [])),
                                "runnable": n.get("runnable", "")}
        for e in data.get("edges", []):
            g.edges[(e["from"], e["to"], e["kind"])] = {
                "symbols": set(e.get("symbols", [])), "line": e.get("line", 0),
                "inferred": bool(e.get("inferred")), "by_name": bool(e.get("by_name"))}
        g.unresolved = list(data.get("unresolved", []))
        for k, v in data.get("externals", {}).items():
            if v.get("stdlib"):
                g.stdlib.add(k)
        g.skipped = list(data.get("skipped", []))
        g.set_files(sorted(g.nodes))
        return g


# ---------------------------------------------------------------- python

def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _py_file(g, base, dotted):
    """The file for module `dotted` under folder `base` ('' is the root):
    base/a/b.py, then base/a/b/__init__.py. `dotted` '' is base's own package."""
    parts = [p for p in dotted.split(".") if p]
    p = _pj(base, *parts)
    if parts:
        f = g.find(p + ".py")
        if f:
            return f
    return g.find(_pj(p, "__init__.py"))


def _py_dir(g, base, dotted):
    """The folder a dotted name names under base, package or namespace, or None."""
    p = _pj(base, *[x for x in dotted.split(".") if x])
    return p if g.is_dir(p) else None


def _py_bases(file_dir):
    """Where an absolute import is looked for: the file's own folder (a
    script's sys.path[0]), the root, then a src/ layout."""
    out = []
    for b in (file_dir, "", "src"):
        if b not in out:
            out.append(b)
    return out


def _py_suffixes(r):
    """Every dotted name a .py file answers to from some sys.path entry:
    api/syms.py -> syms and api.syms."""
    parts = r[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return [".".join(parts[i:]) for i in range(len(parts))]


def _ambiguous(dotted, hits):
    return ("ambiguous: %d local files could be %s (%s); sys.path decides at run time"
            % (len(hits), dotted, ", ".join(hits)))


def _py_absolute(g, file_dir, dotted, pyidx):
    """(file, by_name, why) for `import dotted`. Found by the import system's
    own rules first; then, for a name no stdlib module has, the one local file
    of that dotted name anywhere in the tree. Two real projects put folders on
    sys.path by hand (one app adds its own package folder at start-up), and the first real
    run called 26 of their modules third-party. Two candidates: `why` says so.
    A local folder with no __init__.py is a namespace package: why is
    "namespace" - no file to point at, and not third-party either. It is
    checked after the stdlib, because a regular package anywhere on sys.path
    outranks a namespace portion."""
    bases = _py_bases(file_dir)
    for base in bases:
        f = _py_file(g, base, dotted)
        if f:
            return f, False, None
    if dotted.split(".")[0] in STDLIB:
        return None, False, None
    if any(_py_dir(g, base, dotted) for base in bases):
        return None, False, "namespace"
    hits = pyidx.get(dotted, [])
    if len(hits) == 1:
        return hits[0], True, None
    if len(hits) > 1:
        return None, False, _ambiguous(dotted, hits)
    return None, False, None


_PY_FILE_LIT = re.compile(r"^(?!\.)[\w][\w./\\-]*\.(?:html?|css|js|jsx|ts|tsx|mjs|json|md|txt|csv|ya?ml|toml|sql|ini|cfg|xml|svg)$")


def _joined_path(node):
    """A path built from parts - os.path.join(BASE, 'api', 'x.py'),
    ROOT / "site" / "index.astro", ROOT.joinpath("api", "x.py") - as
    'api/x.py', or None. Only one leading part may be unknown (BASE, ROOT,
    Path(__file__).parent); every part after it must be a string constant,
    because a variable in the middle leaves the folder unknown. One web app's tests
    read 187 source files this way, and KiT's 47."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        f = node.func
        if f.attr == "joinpath" or (f.attr == "join" and (_dotted(f.value) or "").split(".")[-1]
                                    in ("path", "posixpath", "ntpath")):
            parts = ([f.value] if f.attr == "joinpath" else []) + list(node.args)
        else:
            return None
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        parts = []
        while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            parts.insert(0, node.right)
            node = node.left
        parts.insert(0, node)
    else:
        return None
    lit = [isinstance(p, ast.Constant) and isinstance(p.value, str) for p in parts]
    if not lit[-1] or not all(lit[1:]):
        return None
    tail = [p.value for p in parts[0 if lit[0] else 1:]]
    if not all(tail) or any(len(t) > 200 or "\n" in t for t in tail):
        return None
    return "/".join(t.replace("\\", "/").strip("/") for t in tail)


def _is_main_guard(st):
    """`if __name__ == "__main__":` at module level, either way round."""
    if not isinstance(st, ast.If) or not isinstance(st.test, ast.Compare):
        return False
    t = st.test
    if len(t.ops) != 1 or not isinstance(t.ops[0], ast.Eq):
        return False
    sides = [t.left, t.comparators[0]]
    return (any(isinstance(s, ast.Name) and s.id == "__name__" for s in sides)
            and any(isinstance(s, ast.Constant) and s.value == "__main__" for s in sides))


def parse_python(g, r, raw, text, trees):
    try:
        tree = ast.parse(raw)       # bytes: the parser honors a BOM and a coding line
    except (SyntaxError, ValueError):
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError, RecursionError) as e:
            where = " (line %s: %s)" % (e.lineno, e.msg) if isinstance(e, SyntaxError) else ""
            g.skipped.append({"file": r, "reason": "python that does not parse" + where})
            return
    except RecursionError:
        g.skipped.append({"file": r, "reason": "python nested too deeply to parse"})
        return
    trees[r] = tree
    syms = []
    for st in tree.body:
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            syms.append("def " + st.name)
        elif isinstance(st, ast.ClassDef):
            syms.append("class " + st.name)
        elif _is_main_guard(st):
            g.nodes[r]["runnable"] = "__main__ guard"
    if posixpath.basename(r) == "__main__.py":
        g.nodes[r]["runnable"] = "__main__.py"
    elif not g.nodes[r]["runnable"] and text.startswith("#!"):
        g.nodes[r]["runnable"] = "shebang"
    g.nodes[r]["symbols"] = sorted(syms)


def _link_import_from(g, r, file_dir, node, pyidx, bound, stars):
    mod, level, line = node.module or "", node.level, node.lineno
    if level:
        base = file_dir
        for _ in range(level - 1):
            if not base:
                g.miss(r, "." * level + mod, "import", line, "above the project root")
                return
            base = posixpath.dirname(base)
        bases = [base]
    else:
        bases = _py_bases(file_dir)
    names = [a.name for a in node.names if a.name != "*"]
    modfile = moddir = None
    by_name = False
    for b in bases:
        mf, md = _py_file(g, b, mod), _py_dir(g, b, mod)
        # a folder with no __init__.py is a namespace package; an absolute
        # name that is only a folder counts when a name is a module in it
        if mf or (md is not None and (level or any(_py_file(g, md, n) for n in names))):
            modfile, moddir = mf, md
            break
    if modfile is None and moddir is None and not level and mod:
        if mod.split(".")[0] not in STDLIB:
            hits = pyidx.get(mod, [])
            if len(hits) == 1:
                modfile, by_name = hits[0], True
            elif len(hits) > 1:
                g.miss(r, mod, "import", line, _ambiguous(mod, hits))
                return
    if modfile is None and moddir is None:
        if level:
            g.miss(r, "." * level + mod, "import", line, "not found")
        else:
            top = mod.split(".")[0]
            g.external(r, top, top in STDLIB)
        return
    if moddir is None and modfile.endswith("__init__.py"):
        moddir = posixpath.dirname(modfile)
    for a in node.names:
        name = a.asname or a.name
        if a.name == "*":
            if modfile:
                g.add_edge(r, modfile, "import", "*", line, by_name=by_name)
                stars.append(modfile)
            continue
        sub = _py_file(g, moddir, a.name) if moddir is not None else None
        if sub:
            g.add_edge(r, sub, "import", a.name, line, by_name=by_name)
            bound[name] = (sub, None, by_name)
        elif modfile:
            g.add_edge(r, modfile, "import", a.name, line, by_name=by_name)
            bound[name] = (modfile, a.name, by_name)
        else:
            g.miss(r, "." * level + _pj(mod.replace(".", "/"), a.name).replace("/", "."),
                   "import", line, "not found")


def link_python(g, r, tree, def_where, pyidx):
    """Second pass, once every file's definitions are known."""
    file_dir = posixpath.dirname(r)
    bound = {}          # name or dotted -> (file, symbol or None, by_name)
    stars = []          # files imported with *
    imported = set()    # every name an import binds, local or not
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                top = a.name.split(".")[0]
                imported.add(a.asname or top)
                f, by_name, why = _py_absolute(g, file_dir, a.name, pyidx)
                if f:
                    g.add_edge(r, f, "import", a.asname or a.name, node.lineno, by_name=by_name)
                    bound[a.asname or a.name] = (f, None, by_name)
                    if not a.asname and top != a.name:
                        ft, bt, _ = _py_absolute(g, file_dir, top, pyidx)
                        if ft:
                            bound[top] = (ft, None, bt)
                elif why == "namespace":
                    pass    # a local folder, nothing to point at
                elif why:
                    g.miss(r, a.name, "import", node.lineno, why)
                else:
                    g.external(r, top, top in STDLIB)
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name != "*":
                    imported.add(a.asname or a.name)
            _link_import_from(g, r, file_dir, node, pyidx, bound, stars)
    local = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            local.add(node.id)
        elif isinstance(node, ast.arg):
            local.add(node.arg)
    star_defs = {f: set(s.split(" ", 1)[1] for s in g.nodes[f]["symbols"]) for f in stars}

    def resolve_name(dotted):
        """(file, symbol, inferred, by_name) through the bound names, a star
        import, or a unique definition elsewhere (inferred). A name any import
        binds - `from pathlib import Path` - is never matched by definition."""
        parts = dotted.split(".")
        for i in range(len(parts), 0, -1):
            prefix = ".".join(parts[:i])
            if prefix in bound:
                f, sym, bn = bound[prefix]
                rest = ".".join(parts[i:])
                return f, (sym + ("." + rest if rest else "")) if sym else (rest or prefix), False, bn
        head = parts[0]
        if head in local or head in BUILTINS or head in imported:
            return None, None, False, False
        for f in stars:
            if head in star_defs[f]:
                return f, head, False, False
        where = [f for f in def_where.get(head, ()) if f != r]
        if len(where) == 1:
            return where[0], head, True, False
        return None, None, False, False

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            d = _dotted(node.func)
            if d:
                f, sym, inf, bn = resolve_name(d)
                if f:
                    g.add_edge(r, f, "calls", sym, node.lineno, inf, bn)
        elif isinstance(node, ast.ClassDef):
            for b in node.bases:
                d = _dotted(b)
                if d:
                    f, sym, inf, bn = resolve_name(d)
                    if f:
                        g.add_edge(r, f, "inherits", sym, node.lineno, inf, bn)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and len(node.value) < 200 and _PY_FILE_LIT.match(node.value):
            v = node.value.replace("\\", "/")
            for base in (file_dir, "", "static", "templates"):
                t, note = g.target(_pj(base, v))
                if t:
                    if t != r:
                        g.add_edge(r, t, "references", None, node.lineno)
                    break
        if isinstance(node, (ast.Call, ast.BinOp)):
            v = _joined_path(node)
            if v:
                # the unknown head is a folder at or above this file: the
                # nearest one that has the rest of the path wins
                bases, b = [file_dir], file_dir
                while b and not v.startswith(".."):
                    b = posixpath.dirname(b)
                    bases.append(b)
                for base in bases:
                    t, note = g.target(_pj(base, v))
                    if t:
                        if t != r:
                            g.add_edge(r, t, "references", None, node.lineno)
                        break


# ---------------------------------------------------------------- js / ts

_JS_TOKENS = re.compile(r"""
    '(?:\\.|[^'\\\n])*'
  | "(?:\\.|[^"\\\n])*"
  | `(?:\\.|\$\{[^}]*\}|[^`\\])*`
  | //[^\n]*
  | /\*[\s\S]*?\*/
  | \bimport(?![\w$])\s*\(\s*(?P<q1>['"])(?P<dyn>[^'"\n]+)(?P=q1)\s*\)
  | \bimport(?![\w$])\s*(?:type\s+)?(?:[\w$]+\s*,?\s*)?(?:\*\s*as\s+[\w$]+\s*,?\s*)?
        (?:\{[^}]*\}\s*)?(?:from\s*)?(?P<q2>['"])(?P<imp>[^'"\n]+)(?P=q2)
  | \bexport(?![\w$])\s+(?:type\s+)?(?:\*(?:\s*as\s+[\w$]+)?|\{[^}]*\})\s*from\s*
        (?P<q3>['"])(?P<reexp>[^'"\n]+)(?P=q3)
  | \brequire\s*\(\s*(?P<q4>['"])(?P<req>[^'"\n]+)(?P=q4)\s*\)
""", re.X)
_JS_EXPORT = re.compile(r"^\s*export\s+(?:default\s+)?(?:async\s+)?"
                        r"(?:function\*?|class|const|let|var)\s+([\w$]+)", re.M)
_JS_ROUTE_DIRS = {"pages", "routes"}
# A whole string that is a file name: one web app's build script reads its
# JSX source through path.join(__dirname, 'static', 'app.jsx').
_JS_FILE_LIT = re.compile(r"^(?:\.{1,2}/)*[\w][\w./-]*\.(?:html?|css|js|jsx|ts|tsx|mjs|cjs|json|md|txt|csv|ya?ml|toml|sql|svg)$")


def _js_resolve(g, file_dir, spec):
    """(file, note, candidate) for a ./ ../ / @/ ~/ specifier. note is
    "asset", "generated" or "not found" when there is no file node."""
    spec = spec.split("?")[0].split("#")[0]
    if spec.startswith("/"):
        bases = ["", "src", "public", "static"]
        spec = spec[1:]
    elif spec.startswith(("@/", "~/")):
        bases = ["src", ""]
        spec = spec[2:]
    else:
        bases = [file_dir]
    for base in bases:
        p = posixpath.normpath(_pj(base, spec)) if (base or spec) else ""
        cands = [p] + [p + e for e in JS_RESOLVE_EXT]
        stem, ext = posixpath.splitext(p)
        for alt in JS_SWAP.get(ext, ()):
            cands.append(stem + alt)
        cands += [_pj(p, "index" + e) for e in JS_RESOLVE_EXT]
        for c in cands:
            t, note = g.target(c)
            if t:
                return t, None, c
            if note:
                return None, note, c
    return None, "not found", None


def _js_refs(g, r, text, offset=0):
    file_dir = posixpath.dirname(r)
    line_at = None
    for m in _JS_TOKENS.finditer(text):
        spec, kind = None, None
        if m.group("imp"):
            spec, kind = m.group("imp"), "import"
        elif m.group("reexp"):
            spec, kind = m.group("reexp"), "reexport"
        elif m.group("req"):
            spec, kind = m.group("req"), "require"
        elif m.group("dyn"):
            spec, kind = m.group("dyn"), "dynamic-import"
        if not spec:
            tok = m.group(0)
            if tok[:1] in ("'", '"') and 4 < len(tok) < 200 and _JS_FILE_LIT.match(tok[1:-1]):
                s = tok[1:-1]
                for base in ((file_dir,) if s.startswith(".") else
                             (file_dir, "", "static", "public", "src")):
                    t, note = g.target(_pj(base, s))
                    if t:
                        if t != r:
                            if line_at is None:
                                line_at = _line_index(text)
                            g.add_edge(r, t, "references", None, line_at(m.start()) + offset)
                        break
            continue
        if line_at is None:
            line_at = _line_index(text)
        line = line_at(m.start()) + offset
        if spec.startswith((".", "/", "@/", "~/")):
            t, note, cand = _js_resolve(g, file_dir, spec)
            if t:
                g.add_edge(r, t, kind, None, line)
            elif note == "asset":
                g.assets += 1
            elif note == "generated":
                g.external(r, g._norm(cand))
            else:
                g.miss(r, spec, kind, line, note)
        else:
            name = "/".join(spec.split("/")[:2]) if spec.startswith("@") else spec.split("/")[0]
            g.external(r, name.split("?")[0])


def parse_js(g, r, text):
    g.nodes[r]["symbols"] = sorted(set(_JS_EXPORT.findall(text)))
    if text.startswith("#!"):
        g.nodes[r]["runnable"] = "shebang"
    elif _JS_ROUTE_DIRS & set(r.lower().split("/")[:-1]):
        g.nodes[r]["runnable"] = "route"
    _js_refs(g, r, text)


# ---------------------------------------------------------------- markdown

_MD_FENCE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})[^\n]*\n[\s\S]*?^[ ]{0,3}\1[`~]*[ \t]*$", re.M)
_MD_COMMENT = re.compile(r"<!--[\s\S]*?-->")
_MD_CODE = re.compile(r"`[^`\n]*`")
_MD_LINK = re.compile(r"(?<!\!)\[[^\]\n]*\]\(\s*<?([^)\s>]+)>?(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'))?\s*\)")
_MD_REF = re.compile(r"^[ ]{0,3}\[(?!\^)[^\]\n]+\]:[ \t]*<?(\S+?)>?(?:[ \t]|$)", re.M)
_MD_WIKI = re.compile(r"\[\[([^\]|#\n]+)(?:#[^\]|\n]*)?(?:\|[^\]\n]*)?\]\]")
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def _blank(rx, text):
    """Remove what rx matches but keep its newlines, so every later line
    number is the file's own (the first real run numbered links after a code
    fence by the fence-less text)."""
    return rx.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def _host(spec):
    return re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*:/*", "", spec).split("/")[0]


def parse_markdown(g, r, text, md_index):
    file_dir = posixpath.dirname(r)
    clean = _MD_CODE.sub("", _blank(_MD_COMMENT, _blank(_MD_FENCE, text)))
    line_at = _line_index(clean)
    seen = set()
    for rx, wiki in ((_MD_LINK, False), (_MD_REF, False), (_MD_WIKI, True)):
        for m in rx.finditer(clean):
            spec = m.group(1).strip()
            if (spec, wiki) in seen:
                continue
            seen.add((spec, wiki))
            line = line_at(m.start())
            if not wiki:
                if spec.startswith("#"):
                    continue
                if _SCHEME.match(spec) or spec.startswith("//"):
                    g.external(r, _host(spec) or spec.split(":")[0])
                    continue
                path = unquote(spec.split("#")[0].split("?")[0])
                if not path:
                    continue
                cands = [path[1:]] if path.startswith("/") else [_pj(file_dir, path)]
            else:
                name = spec.strip()
                cands = [_pj(file_dir, name + ".md"), name + ".md", _pj(file_dir, name), name]
                hit = md_index.get(posixpath.basename(name).lower())
                if hit and len(hit) == 1:
                    cands.append(hit[0])
            if not g.ref(r, cands, "link", line, dirs_ok=True):
                g.miss(r, spec, "link", line, "not found")


# ---------------------------------------------------------------- html

_URL_FOR = re.compile(r"url_for\(\s*['\"]static['\"]\s*,\s*filename\s*=\s*['\"]([^'\"]+)['\"]")
_TEMPLATED = ("{{", "{%", "<%", "${")
_SCRIPT_TYPES = ("", "module", "text/javascript", "application/javascript",
                 "text/babel", "text/jsx")


class _Refs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found = []       # (spec, kind, line)
        self.scripts = []     # (first line, inline code)
        self._script = None

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "").strip() for k, v in attrs}
        line = self.getpos()[0]
        if tag == "script":
            if a.get("src"):
                self.found.append((a["src"], "script", line))
            elif a.get("type", "").lower() in _SCRIPT_TYPES:
                self._script = (line, [])
            return
        if tag in ("link", "a") and a.get("href"):
            self.found.append((a["href"], "link" if tag == "link" else "href", line))
        if a.get("src"):
            self.found.append((a["src"], "src", line))

    def handle_data(self, data):
        if self._script is not None:
            self._script[1].append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._script is not None:
            self.scripts.append((self._script[0], "".join(self._script[1])))
            self._script = None


def parse_html(g, r, text):
    file_dir = posixpath.dirname(r)
    p = _Refs()
    try:
        p.feed(text)
        p.close()
    except Exception:  # html.parser raises on some malformed input
        g.skipped.append({"file": r, "reason": "html that does not parse"})
        return
    g.nodes[r]["runnable"] = "page"
    seen = set()
    for spec, kind, line in p.found:
        if (spec, kind) in seen:
            continue
        seen.add((spec, kind))
        if any(t in spec for t in _TEMPLATED):
            m = _URL_FOR.search(spec)
            if not m:
                g.templated += 1
                continue
            x = m.group(1)
            cands = [_pj(posixpath.dirname(file_dir), "static", x),
                     _pj(file_dir, "static", x), _pj("static", x)]
            if not g.ref(r, cands, kind, line):
                g.miss(r, spec, kind, line, "not found")
            continue
        if spec.startswith("#") or spec.lower().startswith(
                ("javascript:", "mailto:", "tel:", "data:", "blob:")):
            continue
        if _SCHEME.match(spec) or spec.startswith("//"):
            g.external(r, _host(spec) or spec)
            continue
        path = unquote(spec.split("?")[0].split("#")[0])
        if not path:
            continue
        if path.startswith("/"):
            cands = [path[1:], _pj("static", path[1:]), _pj("public", path[1:])]
        else:
            # file-relative, then from the root: a server-rendered page is
            # served from "/", whatever folder its template sits in
            cands = [_pj(file_dir, path), path]
        if not g.ref(r, cands, kind, line, dirs_ok=True):
            if path.endswith("/") or not posixpath.splitext(path)[1]:
                continue    # a route, not a file
            g.miss(r, spec, kind, line, "not found")
    for line0, code in p.scripts:
        _js_refs(g, r, code, line0 - 1)


# ---------------------------------------------------------------- build

def build(root, want_time=False):
    t0 = time.perf_counter()
    g = Graph(root)
    files = sorted(set(walk(root)))
    g.set_files(files)
    parse = []
    for r in files:
        if not r.lower().endswith(PARSED_EXT):
            continue
        reason = generated_reason(root, r, g.all_rel)
        if reason:
            g.generated[r] = reason
            g.skipped.append({"file": r, "reason": reason})
            continue
        try:
            size = os.path.getsize(os.path.join(root, r))
        except OSError:
            size = 0
        if size > MAX_BYTES:
            g.skipped.append({"file": r, "reason": "over %d MB" % (MAX_BYTES // (1024 * 1024))})
            continue
        parse.append(r)
    raws, texts, md_index, pyidx = {}, {}, {}, {}
    for r in parse:
        raw = read_bytes(os.path.join(root, r))
        texts[r] = text_of(raw)
        g.add_node(r, count_lines(raw))
        lang = lang_of(r)
        if lang == "python":
            raws[r] = raw
            for s in _py_suffixes(r):
                pyidx.setdefault(s, []).append(r)
        elif lang == "markdown":
            md_index.setdefault(posixpath.splitext(posixpath.basename(r))[0].lower(), []).append(r)
    trees = {}
    for r in parse:
        if r in raws:
            parse_python(g, r, raws[r], texts[r], trees)
    def_where = {}
    for r in trees:
        for s in g.nodes[r]["symbols"]:
            def_where.setdefault(s.split(" ", 1)[1], []).append(r)
    for r in parse:
        lang = lang_of(r)
        if lang == "python":
            if r in trees:
                link_python(g, r, trees[r], def_where, pyidx)
        elif lang == "js":
            parse_js(g, r, texts[r])
        elif lang == "markdown":
            parse_markdown(g, r, texts[r], md_index)
        elif lang == "html":
            parse_html(g, r, texts[r])
    ok, head = git(root, "rev-parse", "--short", "HEAD")
    g.stats = {"files_walked": len(files), "files_parsed": len(parse),
               "nodes": len(g.nodes), "edges": len(g.edges),
               "edges_inferred": sum(1 for e in g.edges.values() if e["inferred"]),
               "edges_by_name": sum(1 for e in g.edges.values() if e["by_name"]),
               "unresolved": len(g.unresolved), "externals": len(g.externals()),
               "asset_refs": g.assets, "templated_refs": g.templated,
               "skipped": len(g.skipped), "git_head": head.strip() if ok else ""}
    if want_time:
        sys.stderr.write("built %d node(s), %d edge(s) from %d file(s) in %.2f s\n"
                         % (len(g.nodes), len(g.edges), len(parse), time.perf_counter() - t0))
    return g


def load_or_build(a):
    if a.graph:
        try:
            with open(a.graph, "r", encoding="utf-8") as fh:
                return Graph.from_json(json.load(fh))
        except (OSError, ValueError, KeyError) as e:
            print("REFUSED cannot read the graph file %s: %s" % (a.graph, e))
            return None
    return build(a.project, a.time)


def _is_abs(name):
    return os.path.isabs(name) and (os.name != "nt" or bool(os.path.splitdrive(name)[0]))


def locate(g, name):
    """A node for a path, a basename or a symbol - or (None, message)."""
    n = name.replace("\\", "/")
    if _is_abs(name):
        n = rel(g.root, name)
    while n.startswith("./"):
        n = n[2:]
    n = n.rstrip("/")
    if n in g.nodes:
        return n, None
    f = g.find(n)
    if f and f in g.nodes:
        return f, None
    by_base = sorted(x for x in g.nodes if x.endswith("/" + n) or posixpath.basename(x) == n)
    if len(by_base) == 1:
        return by_base[0], None
    if len(by_base) > 1:
        return None, "%s names %d files: %s" % (name, len(by_base), ", ".join(by_base))
    by_sym = sorted(x for x in g.nodes if any(s.split(" ", 1)[-1] == n for s in g.nodes[x]["symbols"]))
    if len(by_sym) == 1:
        return by_sym[0], "symbol %s is defined in %s" % (n, by_sym[0])
    if len(by_sym) > 1:
        return None, "symbol %s is defined in %d files: %s" % (n, len(by_sym), ", ".join(by_sym))
    return None, "%s is not in the graph (not a parsed file of this tree, or ignored)" % name


def _fmt_edge(kinds):
    """'import C, inherits C :5' from an adjacency entry."""
    bits = []
    for kind, syms, line, inf, bn in kinds:
        s = kind + (" " + ", ".join(syms[:4]) + ("..." if len(syms) > 4 else "") if syms else "")
        if inf:
            s += " [inferred]"
        if bn:
            s += " [by name]"
        bits.append(s)
    line = min((k[2] for k in kinds if k[2]), default=0)
    return ", ".join(bits) + (" :%d" % line if line else "")


# ---------------------------------------------------------------- commands

def cmd_explain(g, a):
    n, note = locate(g, a.name)
    if not n:
        print(note)
        print("RESULT: %s not explained" % a.name)
        return 2
    if note:
        print(note)
    out, inn = g.adjacency(a.inferred), g.adjacency(a.inferred, reverse=True)
    deg = g.degrees(a.inferred)
    d = g.nodes[n]
    print("%s  %s, %d line(s), in %d, out %d%s" % (
        n, d["lang"], d["lines"], deg[n][0], deg[n][1],
        ", runnable (%s)" % d["runnable"] if d["runnable"] and d["lang"] != "html" else ""))
    if d["symbols"]:
        print("  defines: " + ", ".join(d["symbols"][:30]) +
              (" (+%d)" % (len(d["symbols"]) - 30) if len(d["symbols"]) > 30 else ""))
    print("  imports (out): %d" % len(out.get(n, {})))
    for t in sorted(out.get(n, {})):
        print("    %s  %s" % (t, _fmt_edge(out[n][t])))
    print("  imported by (in): %d" % len(inn.get(n, {})))
    for t in sorted(inn.get(n, {})):
        print("    %s  %s%s" % (t, _fmt_edge(inn[n][t]), "  [test]" if is_test(t) else ""))
    ext = [x + (" (stdlib)" if x in g.stdlib else "") for x in sorted(d["ext"])]
    if ext:
        print("  external: " + ", ".join(ext))
    un = [u for u in g.unresolved if u["file"] == n]
    if un:
        print("  unresolved: %d" % len(un))
        for u in sorted(un, key=lambda u: (u["line"], u["spec"])):
            print("    %s  %s :%d  (%s)" % (u["spec"], u["kind"], u["line"], u["reason"]))
    print("RESULT: %s: %d out, %d in, %d external, %d unresolved" % (
        n, len(out.get(n, {})), len(inn.get(n, {})), len(ext), len(un)))
    return 0


def _bfs(adj, start, goal):
    prev = {start: None}
    q = deque([start])
    while q:
        v = q.popleft()
        if v == goal:
            break
        for w in sorted(adj.get(v, {})):
            if w not in prev:
                prev[w] = v
                q.append(w)
    if goal not in prev:
        return None
    path, v = [], goal
    while v is not None:
        path.append(v)
        v = prev[v]
    return path[::-1]


def cmd_path(g, a):
    src, n1 = locate(g, a.a)
    dst, n2 = locate(g, a.b)
    if not src or not dst:
        print(n1 if not src else n2)
        print("RESULT: no path computed")
        return 2
    adj = g.adjacency(a.inferred)
    p = _bfs(adj, src, dst)
    if p:
        print(p[0])
        for i in range(1, len(p)):
            print("  -> %s  (%s)" % (p[i], _fmt_edge(adj[p[i - 1]][p[i]])))
        print("RESULT: path of %d step(s) from %s to %s" % (len(p) - 1, src, dst))
        return 0
    q = _bfs(adj, dst, src)
    if q:
        print("no forward path (%s does not depend on %s); the reverse path, %s depends on %s:"
              % (src, dst, dst, src))
        print(q[0])
        for i in range(1, len(q)):
            print("  -> %s  (%s)" % (q[i], _fmt_edge(adj[q[i - 1]][q[i]])))
        print("RESULT: reverse path of %d step(s) from %s to %s" % (len(q) - 1, dst, src))
        return 0
    print("RESULT: no path between %s and %s in either direction" % (src, dst))
    return 1


def _changed_since(g, ref):
    """The files that differ from ref - committed, staged, unstaged or new -
    as git spells them (-z: no octal quoting of a non-ASCII name). Renames are
    split, so the old name shows up as deleted. None when git cannot answer."""
    ok, _ = git(g.root, "rev-parse", "--verify", "--quiet", ref + "^{commit}")
    if not ok:
        return None
    ok, out = git(g.root, "diff", "--name-only", "--no-renames", "-z", "--relative", ref, "--", ".")
    if not ok:
        return None
    names = set(x.replace("\\", "/") for x in out.split("\0") if x.strip())
    ok, out = git(g.root, "ls-files", "--others", "--exclude-standard", "-z")
    if ok:
        names |= set(x.replace("\\", "/") for x in out.split("\0") if x.strip())
    return sorted(names)


def cmd_affected(g, a):
    changed, outside, deleted = [], [], []
    if a.since:
        names = _changed_since(g, a.since)
        if names is None:
            print("REFUSED: git could not diff against %s (not a repository, or no such ref)" % a.since)
            print("RESULT: affected not computed")
            return 2
        for n in names:
            f = g.find(n)
            if f and f in g.nodes:
                changed.append(f)
            elif not os.path.exists(os.path.join(g.root, n)):
                deleted.append(n)
            else:
                outside.append(n)
    for name in a.files:
        n, note = locate(g, name)
        if not n:
            print(note)
            print("RESULT: affected not computed")
            return 2
        changed.append(n)
    changed = sorted(set(changed))
    if deleted:
        print("deleted: " + ", ".join(deleted) +
              "  (no longer in the tree, so what imported them is not traced here;"
              " their importers now show them as unresolved or external)")
    if outside:
        print("changed but not in the graph: " + ", ".join(outside))
    if not changed:
        print("RESULT: nothing changed in the graph%s" % (" since " + a.since if a.since else ""))
        return 0
    rev = g.adjacency(a.inferred, reverse=True)
    depth, via = {c: 0 for c in changed}, {}
    q = deque(changed)
    while q:
        v = q.popleft()
        if a.max_depth and depth[v] >= a.max_depth:
            continue
        for w in sorted(rev.get(v, {})):
            if w not in depth:
                depth[w] = depth[v] + 1
                via[w] = v
                q.append(w)
    print("changed: " + ", ".join(changed))
    hits = sorted((d, n) for n, d in depth.items() if d > 0)
    for d, n in hits:
        v = via[n]
        print("  %d  %s  %s%s%s" % (d, n, _fmt_edge(rev[v][n]),
                                    "  (via %s)" % v if d > 1 else "",
                                    "  [test]" if is_test(n) else ""))
    # a test that changed is run too: it is not "affected" by itself, and
    # an --since run on KiT left out the two tests that had changed
    tests = sorted(set(n for _, n in hits if is_test(n)) | set(c for c in changed if is_test(c)))
    if tests:
        print("tests to run: " + ", ".join(tests))
    print("RESULT: %d file(s) affected by %d changed file(s), max depth %d; %d test(s) to run"
          % (len(hits), len(changed), max((d for d, _ in hits), default=0), len(tests)))
    return 0


def cmd_hubs(g, a):
    deg = g.degrees(a.inferred)
    rev = g.adjacency(a.inferred, reverse=True)
    rows = sorted(g.nodes, key=lambda n: (-deg[n][0], -deg[n][1], n))
    rows = [n for n in rows if deg[n][0] > 0][:a.top]
    if rows:
        print("  in  out  tests  file")
    for n in rows:
        who = sorted(rev.get(n, {}))
        non_test = [w for w in who if not is_test(w)] + [w for w in who if is_test(w)]
        print("%4d %4d  %5d  %s  <- %s%s" % (
            deg[n][0], deg[n][1], sum(1 for w in who if is_test(w)), n,
            ", ".join(non_test[:4]), " (+%d)" % (len(who) - 4) if len(who) > 4 else ""))
    top = rows[0] if rows else None
    print("RESULT: %d hub(s) shown of %d file(s)%s" % (
        len(rows), len(g.nodes),
        ", top in-degree %d (%s)" % (deg[top][0], top) if top else ""))
    return 0


def _sccs(adj, nodes):
    """Tarjan, iterative - a repository with a long import chain must not
    hit the recursion limit."""
    index, low, on, stack, result, counter = {}, {}, set(), [], [], 0
    for root in nodes:
        if root in index:
            continue
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on.add(root)
        work = [(root, iter(sorted(adj.get(root, {}))))]
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(sorted(adj.get(w, {})))))
                    advanced = True
                    break
                elif w in on:
                    low[v] = min(low[v], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                u = work[-1][0]
                low[u] = min(low[u], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                result.append(sorted(comp))
    return result


def cmd_cycles(g, a):
    kinds = None if a.links else CODE_KINDS
    adj = g.adjacency(a.inferred, kinds=kinds)
    comps = [c for c in _sccs(adj, sorted(g.nodes)) if len(c) > 1]
    comps.sort(key=lambda c: (-len(c), c[0]))
    total = 0
    for i, c in enumerate(comps, 1):
        members = set(c)
        print("cycle %d: %d file(s)" % (i, len(c)))
        for v in c:
            for w in sorted(adj.get(v, {})):
                if w in members:
                    print("  %s -> %s  (%s)" % (v, w, _fmt_edge(adj[v][w])))
        total += len(c)
    # "0 cycle(s) among 0 file(s)" read as an empty graph on a clean tree (the
    # pack's reviewer, 2026-09-30): with no cycle, say what the graph holds.
    print("RESULT: %s%s" % (
        "%d cycle(s) among %d file(s)" % (len(comps), total) if comps
        else "0 cycle(s), %d file(s) in the graph" % len(g.nodes),
        "" if a.links else " (code edges; --links adds doc links and references)"))
    return 1 if comps and a.fail_on_cycles else 0


def _undirected(g, inferred):
    und = {n: Counter() for n in g.nodes}
    for a, b, kind, e in g.edge_list(inferred):
        und[a][b] += 1
        und[b][a] += 1
    return und


def _louvain(nodes, und, resolution=1.0):
    """Community by modularity, local moves then aggregation, in a fixed
    node order so the answer is the same every run. Community ids are the
    smallest member's id, so names are stable too."""
    comm = {n: n for n in nodes}
    graph = {n: dict(und[n]) for n in nodes}
    level_nodes = list(nodes)
    while True:
        m2 = sum(sum(w for w in graph[n].values()) for n in level_nodes)
        if m2 == 0:
            break
        k = {n: sum(graph[n].values()) for n in level_nodes}
        cur = {n: n for n in level_nodes}
        tot = {n: k[n] for n in level_nodes}
        moved_any = False
        for _ in range(40):
            moved = False
            for n in level_nodes:
                c0 = cur[n]
                wc = Counter()
                for mm, w in graph[n].items():
                    if mm != n:
                        wc[cur[mm]] += w
                tot[c0] -= k[n]
                best, gain = c0, wc.get(c0, 0) - resolution * tot[c0] * k[n] / m2
                for c in sorted(wc):
                    gg = wc[c] - resolution * tot[c] * k[n] / m2
                    if gg > gain + 1e-12:
                        best, gain = c, gg
                cur[n] = best
                tot[best] += k[n]
                if best != c0:
                    moved = moved_any = True
            if not moved:
                break
        if not moved_any:
            break
        # rename each community after its smallest member, then aggregate
        members = {}
        for n in level_nodes:
            members.setdefault(cur[n], []).append(n)
        rename = {c: min(ms) for c, ms in members.items()}
        for n in nodes:
            comm[n] = rename[cur[comm[n]]]
        new_nodes = sorted(set(rename.values()))
        agg = {c: Counter() for c in new_nodes}
        for n in level_nodes:
            for mm, w in graph[n].items():
                agg[rename[cur[n]]][rename[cur[mm]]] += w
        graph = {c: dict(agg[c]) for c in new_nodes}
        if len(new_nodes) == len(level_nodes):
            break
        level_nodes = new_nodes
    return comm


def clusters_of(g, inferred):
    """([(members, hub)], unconnected) - a file with no edge at all is not a
    cluster of one; it is listed once, with the others like it."""
    nodes = sorted(g.nodes)
    und = _undirected(g, inferred)
    lonely = [n for n in nodes if not und[n]]
    comm = _louvain(nodes, und)
    deg = g.degrees(inferred)
    groups = {}
    for n in nodes:
        if und[n]:
            groups.setdefault(comm[n], []).append(n)
    out = []
    for c, ms in groups.items():
        hub = sorted(ms, key=lambda n: (-deg[n][0], -deg[n][1], n))[0]
        out.append((sorted(ms), hub))
    out.sort(key=lambda t: (-len(t[0]), t[1]))
    return out, lonely


def cmd_clusters(g, a):
    cl, lonely = clusters_of(g, a.inferred)
    for i, (ms, hub) in enumerate(cl, 1):
        print("cluster %d: %d file(s), hub %s" % (i, len(ms), hub))
        for n in ms:
            print("  " + n)
    if lonely:
        print("unconnected: %d file(s) with no edge to any other" % len(lonely))
        for n in lonely:
            print("  " + n)
    print("RESULT: %d cluster(s) over %d file(s), %d unconnected" % (
        len(cl), len(g.nodes) - len(lonely), len(lonely)))
    return 0


_READ_FIRST = ("readme.md", "readme.markdown", "readme")
_TOUR_LANGS = ("python", "js", "markdown", "html")
_TOUR_KINDS = CODE_KINDS + ("references", "script", "href", "src")
_ENTRY_TIER = {"__main__ guard": 0, "__main__.py": 0, "shebang": 0, "page": 1, "route": 1}


def tour_of(g, inferred, steps):
    """README; then each entry point by how much it reaches (programs, then
    pages and routes, then roots no non-test file depends on, on a tie), each
    followed by what it reaches, nearest and most depended-on first; then
    what no entry reaches; tests last. Markdown links are not followed, so
    documentation does not crowd out the code it describes.

    A driver comes after the program it runs: an entry whose reach is at
    least half carried by a runnable program it imports is read after that
    program. One web app's end-to-end driver imports app.py and reached one file more,
    and opened the tour ahead of it. Half, so that a library module with its
    own __main__ self-test block never jumps ahead of the app that imports it."""
    deg = g.degrees(inferred)
    adj = g.adjacency(inferred, kinds=_TOUR_KINDS)
    walkable = [n for n in sorted(g.nodes) if g.nodes[n]["lang"] in _TOUR_LANGS]
    code = [n for n in walkable if not is_test(n)]
    code_set = set(code)
    feeds = Counter()          # non-test files that depend on each file
    for a_, b_, k_, e_ in g.edge_list(inferred, _TOUR_KINDS):
        if a_ in code_set:
            feeds[b_] += 1

    def reach(start):
        depth, parent = {start: 0}, {start: None}
        q = deque([start])
        while q:
            v = q.popleft()
            for w in sorted(adj.get(v, {})):
                if w not in depth and w in code_set:
                    depth[w] = depth[v] + 1
                    parent[w] = v
                    q.append(w)
        return depth, parent

    readme = [n for n in walkable if n.lower() in _READ_FIRST]
    cand = [n for n in code if n not in readme and g.nodes[n]["lang"] != "markdown"
            and (g.nodes[n]["runnable"] or (feeds[n] == 0 and adj.get(n)))]
    reached = {n: reach(n) for n in cand}
    size = {n: len(reached[n][0]) - 1 for n in cand}
    entries = sorted(cand, key=lambda n: (-size[n], _ENTRY_TIER.get(g.nodes[n]["runnable"], 2), n))
    order, why = [], {}
    for n in readme:
        order.append(n)
        why[n] = "read first: the front door"

    def emit(e, busy):
        if e in why or e in busy:
            return
        busy.add(e)
        depth, parent = reached[e]
        for p in entries:       # the program this entry drives, read first
            if p != e and depth.get(p, 0) > 0 and _ENTRY_TIER.get(g.nodes[p]["runnable"]) == 0 \
                    and size[p] * 2 >= size[e]:
                emit(p, busy)
        busy.discard(e)
        if e in why:
            return
        rn = g.nodes[e]["runnable"]
        order.append(e)
        why[e] = ("entry point: runs as a program (%s)" % rn if _ENTRY_TIER.get(rn) == 0 else
                  "entry point: a %s" % rn if rn else
                  "entry point: no non-test file depends on it") + \
            "; reaches %d file(s)" % size[e]
        for n in sorted((x for x in depth if depth[x] > 0 and x not in why),
                        key=lambda x: (depth[x], -deg[x][0], x)):
            order.append(n)
            why[n] = "depth %d from %s (via %s); in %d, out %d" % (
                depth[n], e, parent[n], deg[n][0], deg[n][1])

    for e in entries:
        emit(e, set())
    rest = [n for n in code if n not in why]
    for n in sorted(rest, key=lambda n: (g.nodes[n]["lang"] == "markdown", -deg[n][0], n)):
        order.append(n)
        why[n] = "not reached from an entry point; in %d, out %d" % (deg[n][0], deg[n][1])
    for n in walkable:
        if n not in why:
            order.append(n)
            why[n] = "test; depends on %d file(s)" % deg[n][1]
    shown = order[:steps] if steps else order
    return shown, why, len(order) - len(shown), g.adjacency(inferred)


def cmd_tour(g, a):
    shown, why, left, adj = tour_of(g, a.inferred, a.steps)
    for i, n in enumerate(shown, 1):
        leads = sorted(adj.get(n, {}))
        print("%3d. %s  %s%s" % (i, n, why[n],
                                 ("  -> " + ", ".join(leads[:3]) + (" (+%d)" % (len(leads) - 3) if len(leads) > 3 else ""))
                                 if leads else ""))
    if left:
        print("... and %d more file(s) not on the tour (--steps to widen, --steps 0 for all)" % left)
    print("RESULT: tour of %d step(s) over %d file(s)" % (len(shown), len(g.nodes)))
    return 0


def cmd_json(g, a):
    text = json.dumps(g.to_json(), indent=1, sort_keys=False, ensure_ascii=False) + "\n"
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print("RESULT: graph of %d node(s), %d edge(s) written to %s (%d bytes)"
              % (len(g.nodes), len(g.edges), a.out, len(text.encode("utf-8"))))
    else:
        sys.stdout.write(text)
        print("RESULT: graph of %d node(s), %d edge(s) on stdout" % (len(g.nodes), len(g.edges)))
    return 0


# ---------------------------------------------------------------- html view

_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dependency graph</title>
<style>
:root{--bg:#ffffff;--fg:#1b1f24;--muted:#5c6470;--line:#c9ced6;--panel:#f3f5f8;--accent:#2f6fed;--in:#c2410c;--dim:0.18}
@media (prefers-color-scheme: dark){:root{--bg:#14171c;--fg:#e6e9ee;--muted:#9aa3b0;--line:#3a414c;--panel:#1d2229;--accent:#7aa2ff;--in:#fb923c}}
*{box-sizing:border-box}
html,body{max-width:100%;overflow-x:hidden}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{padding:12px 16px;border-bottom:1px solid var(--line)}
header h1{font-size:16px;margin:0 0 4px}
header p{margin:0;color:var(--muted);font-size:12px;overflow-wrap:anywhere}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:8px 16px;border-bottom:1px solid var(--line)}
.bar input[type=search]{flex:1 1 160px;min-width:0;padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
.bar button{min-width:36px;min-height:32px;padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--fg);cursor:pointer}
.bar label{color:var(--muted);font-size:12px}
main{display:grid;grid-template-columns:minmax(0,1fr) 340px;min-height:60vh}
#view{width:100%;height:calc(100vh - 150px);min-height:320px;display:block;touch-action:none;cursor:grab;background:var(--bg)}
aside{border-left:1px solid var(--line);background:var(--panel);padding:12px 16px;overflow:auto;max-height:calc(100vh - 150px)}
aside h2{font-size:13px;margin:0 0 6px;overflow-wrap:anywhere}
aside h3{font-size:12px;color:var(--muted);margin:12px 0 4px;text-transform:uppercase;letter-spacing:.04em}
aside ul{margin:0;padding-left:16px}
aside li{overflow-wrap:anywhere}
aside li a{color:var(--accent);cursor:pointer;text-decoration:none}
.legend{display:flex;flex-wrap:wrap;gap:6px 12px;padding:8px 16px;border-bottom:1px solid var(--line);font-size:12px}
.legend span{display:inline-flex;align-items:center;gap:5px;overflow-wrap:anywhere}
.legend i{width:10px;height:10px;border-radius:50%;display:inline-block;flex:none}
line{stroke:var(--line);stroke-width:1;opacity:.75}
line.hi{stroke:var(--accent);stroke-width:2;opacity:1}
line.in{stroke:var(--in);stroke-width:2;opacity:1}
circle{stroke:var(--bg);stroke-width:1.2;cursor:pointer}
text{font-size:11px;fill:var(--fg);pointer-events:none;paint-order:stroke;stroke:var(--bg);stroke-width:3px;stroke-linejoin:round}
.dim{opacity:var(--dim)}
@media (max-width:720px){main{grid-template-columns:minmax(0,1fr)}#view{height:60vh}aside{border-left:0;border-top:1px solid var(--line);max-height:none}}
</style>
</head>
<body>
<header><h1>Dependency graph</h1><p id="meta"></p></header>
<div class="bar"><input id="q" type="search" placeholder="filter files (substring)" aria-label="filter files"><button id="zin" aria-label="zoom in">+</button><button id="zout" aria-label="zoom out">&minus;</button><button id="fit">fit</button><label><input id="lbl" type="checkbox"> all labels</label></div>
<div class="legend" id="legend"></div>
<main>
<svg id="view" role="img" aria-label="dependency graph"><g id="edges"></g><g id="nodes"></g><g id="labels"></g></svg>
<aside id="side"><h2>Click a file</h2><p style="color:var(--muted)">Size is in-degree (how many files depend on it). Color is the cluster; gray is a smaller cluster or a file with no edges. Blue lines lead to what it imports, orange lines come from what imports it.</p></aside>
</main>
<script>
var D = __DATA__;
var PAL = ["#4c78a8","#f58518","#54a24b","#e45756","#b279a2","#ff9da6","#9d755d","#72b7b2","#eeca3b","#bab0ac"], GRAY = "#8a8f98";
function color(c){ return c >= 0 && c < PAL.length ? PAL[c] : GRAY; }
var N = D.nodes, E = D.edges, n = N.length;
var svg = document.getElementById("view"), NS = svg.namespaceURI, gE = document.getElementById("edges"), gN = document.getElementById("nodes"), gL = document.getElementById("labels");
var W = 1000, H = 700;
document.getElementById("meta").textContent = D.root + " - " + n + " files, " + E.length + " edges, " + D.clusters.length + " clusters, " + D.lonely + " unconnected" + (D.head ? " @ " + D.head : "");
var leg = document.getElementById("legend");
function legendItem(col, text){ var s = document.createElement("span"); var dot = document.createElement("i"); dot.style.background = col; s.appendChild(dot); s.appendChild(document.createTextNode(text)); leg.appendChild(s); }
D.clusters.slice(0, PAL.length).forEach(function(c, i){ legendItem(PAL[i], c.hub + " (" + c.size + ")"); });
if (D.clusters.length > PAL.length) legendItem(GRAY, (D.clusters.length - PAL.length) + " smaller clusters");
if (D.lonely) legendItem(GRAY, D.lonely + " unconnected");
var adjOut = [], adjIn = [];
for (var i = 0; i < n; i++) { adjOut.push([]); adjIn.push([]); }
E.forEach(function(e){ adjOut[e[0]].push(e); adjIn[e[1]].push(e); });
// initial positions: each cluster on its own ring segment
var byC = {};
N.forEach(function(d, i){ (byC[d.c] = byC[d.c] || []).push(i); });
var keys = Object.keys(byC);
keys.forEach(function(k, ci){ var arr = byC[k]; var a0 = ci / keys.length * Math.PI * 2; var R = Math.min(W, H) * 0.32; var cx = W/2 + Math.cos(a0) * R * (keys.length > 1 ? 1 : 0), cy = H/2 + Math.sin(a0) * R * (keys.length > 1 ? 1 : 0); arr.forEach(function(i, j){ var a = j / arr.length * Math.PI * 2; var r = 20 + Math.sqrt(arr.length) * 12; N[i].x = cx + Math.cos(a) * r; N[i].y = cy + Math.sin(a) * r; N[i].vx = 0; N[i].vy = 0; }); });
function radius(d){ return 4 + Math.sqrt(d.i) * 2.2; }
var els = [], lbl = [], lines = [];
N.forEach(function(d, i){ var c = document.createElementNS(NS, "circle"); c.setAttribute("r", radius(d)); c.setAttribute("fill", color(d.c)); c.addEventListener("click", function(ev){ ev.stopPropagation(); select(i); }); var t = document.createElementNS(NS, "title"); t.textContent = d.id; c.appendChild(t); gN.appendChild(c); els.push(c); var l = document.createElementNS(NS, "text"); l.textContent = d.id.split("/").pop(); l.style.display = d.i >= D.labelAt ? "" : "none"; gL.appendChild(l); lbl.push(l); });
E.forEach(function(e){ var l = document.createElementNS(NS, "line"); gE.appendChild(l); lines.push(l); });
// The layout is computed before the first paint, not animated: requestAnimationFrame
// never runs in a hidden tab or a preview, where the graph stayed at its start.
var alpha = 1, ticks = 0, maxTicks = n > 600 ? 120 : 260, CELL = 300;
function layout(){ var t0 = Date.now(); while (ticks < maxTicks && Date.now() - t0 < 2000) { step(); ticks++; } draw(); fit(); }
function step(){
  var k = 0.02, rep = n > 400 ? 900 : 1600, grid = {};
  for (var i = 0; i < n; i++) { var a = N[i]; a.vx += (W/2 - a.x) * 0.002; a.vy += (H/2 - a.y) * 0.002; var key = Math.floor(a.x / CELL) + "," + Math.floor(a.y / CELL); (grid[key] = grid[key] || []).push(i); }
  // repulsion only between nodes in neighboring cells: a pair further apart than CELL is skipped anyway, and a big repo stays smooth
  for (var i = 0; i < n; i++) { var a = N[i], gx = Math.floor(a.x / CELL), gy = Math.floor(a.y / CELL);
    for (var x = gx - 1; x <= gx + 1; x++) for (var y = gy - 1; y <= gy + 1; y++) { var cell = grid[x + "," + y]; if (!cell) continue;
      for (var t = 0; t < cell.length; t++) { var j = cell[t]; if (j <= i) continue; var b = N[j]; var dx = a.x - b.x, dy = a.y - b.y; var d2 = Math.max(dx*dx + dy*dy, 100); if (d2 > CELL * CELL) continue; var d = Math.sqrt(d2), f = rep / d2; var fx = dx / d * f, fy = dy / d * f; a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy; } } }
  for (var q = 0; q < E.length; q++) { var e = E[q], a = N[e[0]], b = N[e[1]]; var dx = b.x - a.x, dy = b.y - a.y; var d = Math.sqrt(dx*dx + dy*dy) + 0.01; var want = 60 + (a.c === b.c ? 0 : 60); var f = (d - want) * k; var fx = dx / d * f, fy = dy / d * f; a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy; }
  // two nodes that pass within a pixel must not fling one off the page: distance is
  // floored at 10 above and speed capped here, or fit() frames one outlier (one web app, 2026-09-29)
  for (var i = 0; i < n; i++) { var a = N[i]; a.vx *= 0.6; a.vy *= 0.6; var sp = Math.sqrt(a.vx*a.vx + a.vy*a.vy); if (sp > 40) { a.vx *= 40 / sp; a.vy *= 40 / sp; } a.x += a.vx * alpha; a.y += a.vy * alpha; }
  alpha = Math.max(0.02, alpha * 0.985);
}
function draw(){ for (var i = 0; i < n; i++) { els[i].setAttribute("cx", N[i].x); els[i].setAttribute("cy", N[i].y); lbl[i].setAttribute("x", N[i].x + radius(N[i]) + 2); lbl[i].setAttribute("y", N[i].y + 4); } for (var q = 0; q < E.length; q++) { var e = E[q]; lines[q].setAttribute("x1", N[e[0]].x); lines[q].setAttribute("y1", N[e[0]].y); lines[q].setAttribute("x2", N[e[1]].x); lines[q].setAttribute("y2", N[e[1]].y); } }
var vb = {x:0, y:0, w:W, h:H};
function setVB(){ svg.setAttribute("viewBox", vb.x + " " + vb.y + " " + vb.w + " " + vb.h); }
function fit(){ if (!n) { setVB(); return; } var x0=1e9,y0=1e9,x1=-1e9,y1=-1e9; N.forEach(function(d){ x0=Math.min(x0,d.x); y0=Math.min(y0,d.y); x1=Math.max(x1,d.x); y1=Math.max(y1,d.y); }); var pad = 60; vb = {x:x0-pad, y:y0-pad, w:Math.max(200, x1-x0+pad*2), h:Math.max(200, y1-y0+pad*2)}; setVB(); }
function zoom(f){ var cx = vb.x + vb.w/2, cy = vb.y + vb.h/2; vb.w *= f; vb.h *= f; vb.x = cx - vb.w/2; vb.y = cy - vb.h/2; setVB(); }
document.getElementById("zin").onclick = function(){ zoom(0.8); };
document.getElementById("zout").onclick = function(){ zoom(1.25); };
document.getElementById("fit").onclick = fit;
svg.addEventListener("wheel", function(ev){ ev.preventDefault(); zoom(ev.deltaY > 0 ? 1.1 : 0.9); }, {passive:false});
var drag = null;
svg.addEventListener("pointerdown", function(ev){ drag = {x: ev.clientX, y: ev.clientY, vx: vb.x, vy: vb.y, moved: false}; });
svg.addEventListener("pointermove", function(ev){ if (!drag) return; if (Math.abs(ev.clientX - drag.x) + Math.abs(ev.clientY - drag.y) > 4) drag.moved = true; if (!drag.moved) return; var r = svg.getBoundingClientRect(); var sx = vb.w / r.width, sy = vb.h / r.height; vb.x = drag.vx - (ev.clientX - drag.x) * sx; vb.y = drag.vy - (ev.clientY - drag.y) * sy; setVB(); });
svg.addEventListener("pointerup", function(){ setTimeout(function(){ drag = null; }, 0); });
svg.addEventListener("click", function(){ if (!drag || !drag.moved) select(-1); });
var side = document.getElementById("side");
function esc(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
function list(title, items, which){ if (!items.length) return ""; var h = "<h3>" + title + " (" + items.length + ")</h3><ul>"; items.forEach(function(e){ var j = which === 0 ? e[1] : e[0]; h += "<li><a data-i=\"" + j + "\">" + esc(N[j].id) + "</a> <span style=\"color:var(--muted)\">" + esc(e[2]) + "</span></li>"; }); return h + "</ul>"; }
function select(i){
  var near = {};
  if (i >= 0) { near[i] = 1; adjOut[i].forEach(function(e){ near[e[1]] = 1; }); adjIn[i].forEach(function(e){ near[e[0]] = 1; }); }
  for (var k = 0; k < n; k++) { els[k].classList.toggle("dim", i >= 0 && !near[k]); lbl[k].style.display = (i >= 0 && near[k]) || N[k].i >= D.labelAt || document.getElementById("lbl").checked ? "" : "none"; lbl[k].classList.toggle("dim", i >= 0 && !near[k]); }
  for (var q = 0; q < E.length; q++) { var e = E[q]; lines[q].classList.toggle("hi", i >= 0 && e[0] === i); lines[q].classList.toggle("in", i >= 0 && e[1] === i); lines[q].classList.toggle("dim", i >= 0 && e[0] !== i && e[1] !== i); }
  if (i < 0) { side.innerHTML = "<h2>Click a file</h2>"; return; }
  var d = N[i];
  var h = "<h2>" + esc(d.id) + "</h2><p style=\"color:var(--muted)\">" + esc(d.lang) + ", " + d.lines + " lines, in " + d.i + ", out " + d.o + ", " + (d.c >= 0 ? "cluster " + esc(D.clusters[d.c].hub) : "no edges") + "</p>";
  if (d.s.length) h += "<h3>defines</h3><p>" + esc(d.s.slice(0, 40).join(", ")) + (d.s.length > 40 ? " ..." : "") + "</p>";
  h += list("imports", adjOut[i].slice().sort(function(a,b){ return N[a[1]].id < N[b[1]].id ? -1 : 1; }), 0);
  h += list("imported by", adjIn[i].slice().sort(function(a,b){ return N[a[0]].id < N[b[0]].id ? -1 : 1; }), 1);
  side.innerHTML = h;
  side.querySelectorAll("a[data-i]").forEach(function(a){ a.onclick = function(){ select(+a.getAttribute("data-i")); }; });
}
document.getElementById("q").addEventListener("input", function(ev){ var v = ev.target.value.toLowerCase(); for (var k = 0; k < n; k++) { var hit = !v || N[k].id.toLowerCase().indexOf(v) >= 0; els[k].classList.toggle("dim", !hit); lbl[k].style.display = hit && v ? "" : (N[k].i >= D.labelAt ? "" : "none"); } });
document.getElementById("lbl").addEventListener("change", function(){ select(-1); });
setVB();
if (n) layout(); else document.getElementById("meta").textContent += " - nothing to draw";
</script>
</body>
</html>
"""


def cmd_html(g, a):
    cl, lonely = clusters_of(g, a.inferred)
    cidx = {n: -1 for n in lonely}
    for i, (ms, hub) in enumerate(cl):
        for n in ms:
            cidx[n] = i
    nodes = sorted(g.nodes)
    idx = {n: i for i, n in enumerate(nodes)}
    deg = g.degrees(a.inferred)
    data = {
        "root": posixpath.basename(g.root.replace("\\", "/").rstrip("/")) or g.root,
        "head": g.stats.get("git_head", ""),
        "labelAt": max(3, sorted((deg[n][0] for n in nodes), reverse=True)[min(len(nodes), 12) - 1]) if nodes else 3,
        "clusters": [{"hub": hub, "size": len(ms)} for ms, hub in cl],
        "lonely": len(lonely),
        "nodes": [{"id": n, "lang": g.nodes[n]["lang"], "lines": g.nodes[n]["lines"],
                   "i": deg[n][0], "o": deg[n][1], "c": cidx.get(n, -1),
                   "s": g.nodes[n]["symbols"][:60]} for n in nodes],
        "edges": [[idx[x], idx[y], k + (" [inferred]" if e["inferred"] else "")
                   + (" [by name]" if e.get("by_name") else "")]
                  for x, y, k, e in g.edge_list(a.inferred)],
    }
    # "<" as \u003c: no file name can close the script element or open a comment
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    page = _HTML.replace("__DATA__", blob)
    if a.out:
        d = os.path.dirname(os.path.abspath(a.out))
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(page)
        print("RESULT: page of %d node(s), %d edge(s) written to %s (%d bytes, self-contained)"
              % (len(nodes), len(data["edges"]), a.out, len(page.encode("utf-8"))))
    else:
        sys.stdout.write(page)
        print("RESULT: page of %d node(s), %d edge(s) on stdout" % (len(nodes), len(data["edges"])))
    return 0


# ---------------------------------------------------------------- main

def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", default=".", help="the folder to read (default .)")
    common.add_argument("--graph", help="answer from a json export instead of re-reading the tree")
    common.add_argument("--inferred", action="store_true",
                        help="count inferred edges (bare calls matched by a unique definition)")
    common.add_argument("--time", action="store_true", help="print the build time to stderr")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("explain", parents=[common], help="what a file imports and who imports it")
    p.add_argument("name")
    p = sub.add_parser("path", parents=[common], help="the shortest dependency path")
    p.add_argument("a")
    p.add_argument("b")
    p = sub.add_parser("affected", parents=[common], help="what could break if these files change")
    p.add_argument("files", nargs="*")
    p.add_argument("--since", metavar="REF", help="take the changed files from git diff REF")
    p.add_argument("--max-depth", type=int, default=0)
    p = sub.add_parser("hubs", parents=[common], help="the most depended-on files")
    p.add_argument("--top", type=int, default=15)
    p = sub.add_parser("cycles", parents=[common], help="import cycles")
    p.add_argument("--links", action="store_true",
                   help="count doc links, hrefs and file-name references too")
    p.add_argument("--fail-on-cycles", action="store_true")
    sub.add_parser("clusters", parents=[common], help="communities of files")
    p = sub.add_parser("tour", parents=[common], help="an ordered reading path")
    p.add_argument("--steps", type=int, default=20)
    p = sub.add_parser("html", parents=[common], help="one self-contained page")
    p.add_argument("--out")
    p = sub.add_parser("json", parents=[common], help="the graph as json")
    p.add_argument("--out")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        print("RESULT: could not run (no command)")
        return 2
    a.project = os.path.abspath(a.project)
    if not os.path.isdir(a.project):
        print("no such project directory: %s" % a.project)
        print("RESULT: could not run")
        return 2
    if a.cmd == "affected" and not a.files and not a.since:
        print("affected needs one or more files, or --since REF")
        print("RESULT: could not run")
        return 2
    g = load_or_build(a)
    if g is None:
        print("RESULT: could not run")
        return 2
    return {"explain": cmd_explain, "path": cmd_path, "affected": cmd_affected,
            "hubs": cmd_hubs, "cycles": cmd_cycles, "clusters": cmd_clusters,
            "tour": cmd_tour, "html": cmd_html, "json": cmd_json}[a.cmd](g, a)


if __name__ == "__main__":
    sys.exit(main())
