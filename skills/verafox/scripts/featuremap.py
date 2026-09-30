# -*- coding: utf-8 -*-
"""featuremap.py - maintain a project's FEATURE-MAP.md and its proof store.

WHAT IT DOES
    --init      scaffold FEATURE-MAP.md and .verify/ for a project that has none.
    --check     report drift and stale proof. Exits 1 when either is found, so a
                hook or a CI step can refuse on it. Reports, never repairs.
    --write     regenerate ONLY the DERIVED block of the map from the code.
    --reaim     move each hand-mapped `code:` or `entry:` range whose lines
                moved (code added or removed above it) to where those lines
                are now, stamped `@ <commit>` - the commit whose lines it is
                in - and name each range it leaves, with why.
    --record    append one capture record to the proof store and print the
                analysis against the previous capture for that feature.
    --ratchet   lower every recorded ceiling to the count present. Never raises.
    --list      print every capability with its face (user / dev) and grade;
                read-only, needs no map. --ref R reads it as it stood at R.
    --compare A [B]
                what changed between two refs, or a ref and the working tree:
                capabilities added, removed, re-faced or moved, and entries
                regraded. Refs are read out of git, never checked out.
    --live      ask production what it serves: GET the declared probe paths and
                a fingerprint file, place that file's version in git, and list
                what the working tree has that production cannot. Only paths an
                entry declares are requested; redirects are never followed.
    --judge     ask Jev, in one request, whether each entry's observable is
                evidence of its intent - the Intended bar no test suite checks.
                A reading, never a failure; needs the levjev skill installed
                beside this one, and TYPESAFE_API_KEY.

WHAT IT WILL NEVER DO
    Touch the AUTHORED half of a map, beyond --reaim moving a `code:` or
    `entry:` pointer's numbers to where git measures its unchanged lines now,
    stamped with the commit they are in - the judgment fields (what a feature is for,
    its observable, its negative contract, the operator's intent, the evidence
    grade) are written by a human or by an agent exercising judgment, and a
    generator that can overwrite them is the reason people stop keeping maps.
    Invent a grade. Decide that an unparsed stack is absent: it reports UNPARSED
    and fails --check instead, because a scanner that skips what it cannot read
    reports a clean map over an unmapped app.

USAGE
    python featuremap.py --check   --project C:\\path\\to\\project
    python featuremap.py --write   --project .
    python featuremap.py --record  --project . --feature checkout.submit \\
        --grade DRIVEN --result pass --observable "order row 8841; cart 0" \\
        --how "clicked [data-testid=checkout]" --bound "one item, Chrome 1920" \\
        --metric duration_ms=812 --metric console_errors=0
"""
import argparse
import collections
import json
import os
import re
import shutil
import subprocess
import sys
import datetime

MAP_NAME = "FEATURE-MAP.md"
STORE = ".verify"
D_BEGIN, D_END = "<!-- DERIVED:BEGIN -->", "<!-- DERIVED:END -->"
A_BEGIN, A_END = "<!-- AUTHORED:BEGIN -->", "<!-- AUTHORED:END -->"
GRADES = ("DRIVEN", "TESTED", "ASSERTED", "UNKNOWN")

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".next", "dist", "build",
             ".venv", "venv", "site-packages", ".verify", "Archives", ".cursor"}

# Source extensions that compile down to .js - when a sibling of the same stem
# exists, the .js is build output and the .jsx/.ts is what a human edits.
COMPILES_TO_JS = (".jsx", ".ts", ".tsx", ".coffee", ".svelte", ".vue")
# An inlined image is one long token, not minification. One web app's hand-written
# stylesheet carries two 37,907-character SVG data URIs, and measuring them as
# lines excluded the whole file - so a rule written over its CSS reported zero.
_DATA_URI = re.compile(r"([\"'])data:[^\"']*\1|url\(\s*data:[^)]*\)")


def generated_reason(root, path, all_rel):
    """Why this file is a build artifact rather than authored source, or None.

    Extracting from minified or compiled output invents features that do not
    exist: the first real run of this against a Flask app mapped `__esModule`
    and `default` as keyboard shortcuts out of babel.min.js, and mapped the same
    UI twice because the compiled .js sat beside its .jsx. A junk entry is worse
    than a gap, because a gap is visible and a junk entry looks like coverage.

    These are REPORTED with their reason, never silently dropped. Silently
    skipping the only source file in a project yields a clean map over an
    unmapped app, which is the failure this whole script exists to prevent."""
    r = rel(root, path)
    base = os.path.basename(r).lower()
    if ".min." in base or base.endswith((".bundle.js", ".chunk.js", ".map")):
        return "minified or bundled"
    parts = r.lower().split("/")
    if "vendor" in parts or "vendors" in parts or "third_party" in parts:
        return "vendored third-party code"
    if r.endswith(".js"):
        stem = r[:-3]
        for ext in COMPILES_TO_JS:
            if (stem + ext) in all_rel:
                return "build output of " + os.path.basename(stem + ext)
    if r.endswith((".js", ".css", ".ts")):
        # A file whose longest line runs into the thousands is minified whatever
        # it is named. Cheap to measure, and it catches the ones named plainly.
        text = _DATA_URI.sub("data:", read(path) or "")
        if text and max((len(x) for x in text.split("\n")), default=0) > 2000:
            return "minified (a line over 2000 chars)"
    return None


# ---------------------------------------------------------------- helpers

def read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def write(path, text):
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


_KEPT = {}


def _kept(root):
    """The files git would keep here - tracked, or new and not ignored - or None
    outside a work tree. What git ignores (logs, snapshots, .env, local builds)
    differs per checkout: one web app's single commit read 661, 500 and 301 files in
    three of them."""
    if root not in _KEPT:
        try:
            p = subprocess.run(("git", "ls-files", "--cached", "--others",
                                "--exclude-standard", "-z"), cwd=root,
                               capture_output=True, timeout=60)
            _KEPT[root] = (set(x.decode("utf-8", "replace") for x in
                               p.stdout.split(b"\0") if x)
                           if p.returncode == 0 else None)
        except (OSError, subprocess.SubprocessError):
            _KEPT[root] = None
    return _KEPT[root]


def walk(root):
    """Every candidate source file, skipping vendored and generated trees and,
    in a git work tree, whatever git ignores."""
    kept = _kept(root)
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            p = os.path.join(base, f)
            if kept is None or rel(root, p) in kept:
                yield p


def rel(root, path):
    try:
        return os.path.relpath(path, root).replace("\\", "/")
    except ValueError:
        return path.replace("\\", "/")


def git(root, *args):
    """(ok, stdout). ok is False when git is absent or this is not a repo -
    every caller must degrade and say so rather than assume a clean answer."""
    try:
        p = subprocess.run(("git",) + args, cwd=root, capture_output=True,
                           timeout=30)
        return p.returncode == 0, p.stdout.decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError):
        return False, ""


def slug(text):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return s or "unnamed"


# ---------------------------------------------------------------- extractors
# Each returns [(id, surface, code, note)] and each declares the files it
# claimed, so anything left over can be reported UNPARSED.

def _route_slug(path):
    """The id part for a route path. `/` is the site's root and is named so: it
    used to slug to `unnamed`, the id that one web app's dashboard, its most
    important page, carried."""
    return "root" if not path.strip().strip("/") else slug(path)


def _page_route(stem):
    """A page file's route: `index` is the directory's own page, and only when
    it is the whole last segment - `reindex` is not `re`."""
    return "/" + re.sub(r"(?:^|/)index$", "", stem).rstrip("/")

def ex_next_app(root, files):
    out, claimed = [], []
    for p in files:
        r = rel(root, p)
        m = re.search(r"(?:^|/)app/(.*/)?page\.(tsx|jsx|ts|js)$", r)
        if not m:
            continue
        claimed.append(r)
        route = "/" + (m.group(1) or "").rstrip("/")
        out.append(("route." + _route_slug(route), "web-ui", r + ":1",
                    "next app route " + route))
    return out, claimed


def ex_next_pages(root, files):
    out, claimed = [], []
    for p in files:
        r = rel(root, p)
        m = re.search(r"(?:^|/)pages/(.+)\.(tsx|jsx|ts|js)$", r)
        if not m or "/api/" in r:
            continue
        claimed.append(r)
        route = _page_route(m.group(1))
        out.append(("route." + _route_slug(route), "web-ui", r + ":1",
                    "next pages route " + route))
    return out, claimed


def ex_astro(root, files):
    out, claimed = [], []
    for p in files:
        r = rel(root, p)
        m = re.search(r"(?:^|/)src/pages/(.+)\.astro$", r)
        if not m:
            continue
        claimed.append(r)
        route = _page_route(m.group(1))
        out.append(("route." + _route_slug(route), "web-ui", r + ":1",
                    "astro page " + route))
    return out, claimed


_PY_ROUTE = re.compile(
    r"@(?:\w+)\.(?:route|get|post|put|patch|delete)\(\s*[\"']([^\"']+)[\"']")
_ROUTE_VERBS = ("route", "get", "post", "put", "patch", "delete")
# A route that hands back an HTML file is a page, whatever helper it uses.
# One web app serves its dashboard and its landing page by reading index.html and
# welcome.html itself, so `render_template` alone called both of them an API.
_SERVES_HTML = re.compile(r"render_template|HTMLResponse|text/html"
                          r"|[\"'][^\"'\n]*\.html?[\"']")


def _py_routes(text):
    """[(line, path, body)] for route decorators in real code, read from the
    syntax tree - so a decorator inside a string is not a route. This skill's
    own map carried `endpoint.health`, `.orders` and `.refund` for a year of
    fixture strings in its test harness. None when the file does not parse."""
    import ast
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    lines, found = text.split("\n"), []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr in _ROUTE_VERBS and dec.args
                    and isinstance(dec.args[0], ast.Constant)
                    and isinstance(dec.args[0].value, str)):
                end = getattr(node, "end_lineno", None) or node.lineno + 20
                found.append((dec.lineno, dec.args[0].value,
                              "\n".join(lines[node.lineno - 1:end])))
    return sorted(found)


def ex_python_routes(root, files):
    """Flask and FastAPI decorators - the surface is api unless it renders."""
    out, claimed = [], []
    for p in files:
        if not p.endswith(".py"):
            continue
        text = read(p)
        if "@" not in text:
            continue
        r = rel(root, p)
        hit = False
        routes = _py_routes(text)
        if routes is None:
            # A file that does not parse (Python 2, a template) is still read,
            # by the pattern, rather than skipped.
            routes = [(text.count("\n", 0, m.start()) + 1, m.group(1),
                       text[m.end():m.end() + 400])
                      for m in _PY_ROUTE.finditer(text)]
        for line, path, body in routes:
            hit = True
            surface = "web-ui" if _SERVES_HTML.search(body) else "api"
            out.append(("endpoint." + _route_slug(path), surface,
                        "%s:%d" % (r, line), "python route " + path))
        if hit:
            claimed.append(r)
    return out, claimed


_JS_ROUTE = re.compile(
    r"\b(?:app|router)\.(get|post|put|patch|delete)\(\s*[\"'`]([^\"'`]+)[\"'`]")


def ex_express(root, files):
    out, claimed = [], []
    for p in files:
        if not p.endswith((".js", ".ts", ".mjs", ".cjs")):
            continue
        text = read(p)
        r = rel(root, p)
        hit = False
        for m in _JS_ROUTE.finditer(text):
            hit = True
            line = text.count("\n", 0, m.start()) + 1
            out.append(("endpoint." + _route_slug(m.group(2)), "api",
                        "%s:%d" % (r, line),
                        "%s %s" % (m.group(1).upper(), m.group(2))))
        if hit:
            claimed.append(r)
    return out, claimed


_LABEL_ATTR = re.compile(r"\b(data-testid|aria-label)=(\"[^\"]*\"|'[^']*'|\{)")


# A label is not always a quoted string. JSX also writes it as a template
# (aria-label={`Unpin ${title}`}) or as any expression ({locked ? 'Unlock all' :
# 'Lock all'}). Reading only the quoted form dropped five real controls on
# a web app without a word, because the file was already claimed by the labels it
# could read - a gap that reports as coverage. These read an expression to its
# matching brace, skipping strings and templates so a brace inside one does not
# count.

def _skip_quoted(s, j):
    """s[j] opens a '...' or "..." string: the index of its closing quote, or -1."""
    q, k = s[j], j + 1
    while k < len(s):
        if s[k] == "\\":
            k += 2
            continue
        if s[k] == q:
            return k
        if s[k] == "\n":
            return -1
        k += 1
    return -1


def _skip_template(s, j):
    """s[j] opens a `...` template: the index of its closing backtick, or -1."""
    k = j + 1
    while k < len(s):
        c = s[k]
        if c == "\\":
            k += 2
            continue
        if c == "`":
            return k
        if c == "$" and s[k + 1:k + 2] == "{":
            k = _match_brace(s, k + 1)
            if k < 0:
                return -1
        k += 1
    return -1


def _match_brace(s, i, opening="{", closing="}"):
    """s[i] is '{' (or `opening`): the index of the bracket that closes it, or -1."""
    depth, k = 0, i
    while k < len(s):
        c = s[k]
        if c in "'\"":
            k = _skip_quoted(s, k)
        elif c == "`":
            k = _skip_template(s, k)
        elif c == opening:
            depth += 1
        elif c == closing:
            depth -= 1
            if depth == 0:
                return k
        if k < 0:
            return -1
        k += 1
    return -1


def _template_words(tpl):
    """`Move ${id} up` -> ("Move   up", "Move ${…} up"): the words a reader
    always sees, and the template as it reads with the variable parts elided."""
    fixed, shown, k = [], [], 1
    while k < len(tpl) - 1:
        c = tpl[k]
        if c == "\\":
            fixed.append(tpl[k + 1:k + 2])
            shown.append(tpl[k:k + 2])
            k += 2
            continue
        if c == "$" and tpl[k + 1:k + 2] == "{":
            end = _match_brace(tpl, k + 1)
            if end < 0:
                break
            fixed.append(" ")
            shown.append("${…}")
            k = end + 1
            continue
        fixed.append(c)
        shown.append(c)
        k += 1
    return "".join(fixed), "".join(shown)


def _first_literal(expr):
    """The first string or template inside an expression that carries words:
    {locked ? 'Unlock all panels' : 'Lock all panels'} -> 'Unlock all panels'."""
    k = 0
    while k < len(expr):
        c = expr[k]
        if c in "'\"":
            end = _skip_quoted(expr, k)
            if end < 0:
                return None
            if re.search(r"[A-Za-z0-9]", expr[k + 1:end]):
                return expr[k + 1:end]
            k = end
        elif c == "`":
            end = _skip_template(expr, k)
            if end < 0:
                return None
            words, _ = _template_words(expr[k:end + 1])
            if re.search(r"[A-Za-z0-9]", words):
                return words
            k = end
        k += 1
    return None


def _label_value(text, m):
    """(id_source, found_as) for one data-testid / aria-label match. id_source
    is None when the value has no fixed words to name it by."""
    v = m.group(2)
    if v != "{":
        return v[1:-1], "=" + v[1:-1]
    end = _match_brace(text, m.end() - 1)
    if end < 0:
        return None, "={... (no closing brace found)"
    expr = text[m.end():end].strip()
    if expr.startswith("`") and _skip_template(expr, 0) == len(expr) - 1:
        words, shown = _template_words(expr)
        return words, "=`%s` (template; id from its fixed words)" % shown
    lit = _first_literal(expr)
    if lit:
        return lit, "={…} (computed; id from its literal \"%s\")" % lit
    short = re.sub(r"\s+", " ", expr).replace("`", "'")
    return None, "={%s}" % ((short[:57] + "...") if len(short) > 60 else short)


# What an element IS decides what its label names. A label on a button names a
# control; a label on an <aside> or a role="group" names a region of the page,
# which is a feature too; a label on an image names neither. This used to be
# guessed from any handler within 300 characters of the label, which dropped
# a web app's labelled Explain drawer (its buttons sat further down) and minted a
# "control" out of whatever labelled thing sat beside a button. The element's
# own opening tag is read instead.
_TAG_OPEN = re.compile(r"<([A-Za-z][\w.:-]*)")
_ATTR_NAME = re.compile(r"[^\s=>/{}\"']+")
_UNQUOTED = re.compile(r"[^\s>]+")
_TAG_CLOSE = re.compile(r"</([A-Za-z][\w.:-]*)\s*>")
_NATIVE_CONTROLS = {"button", "input", "select", "textarea", "summary", "option"}
_CONTROL_ROLES = {"button", "link", "tab", "menuitem", "menuitemcheckbox",
                  "menuitemradio", "checkbox", "radio", "switch", "option",
                  "combobox", "slider", "spinbutton", "textbox", "searchbox",
                  "treeitem"}
_REGION_TAGS = {"aside", "nav", "section", "dialog", "form", "header", "footer",
                "main", "search", "fieldset"}
_REGION_ROLES = {"region", "dialog", "alertdialog", "navigation", "complementary",
                 "search", "banner", "contentinfo", "main", "form", "toolbar",
                 "tablist", "tabpanel", "menu", "menubar", "group", "radiogroup",
                 "listbox", "tree", "grid", "status", "log", "alert"}
# A handler makes an element operable - except the ones a resource fires on its
# own, which no user ever triggers.
_HANDLER = re.compile(r"^(?:on[A-Z]\w*|on(?:click|dblclick|change|input|submit|"
                      r"key\w+|mouse\w+|pointer\w+|touch\w+|focus|blur|select|"
                      r"toggle|drag\w*|drop|wheel|contextmenu)|@\w+|v-on:\w+|"
                      r"on:\w+)$")
_NOT_USER = re.compile(r"^on(?:Load|Error|Animation\w*|Transition\w*)$")


def _parse_tag(text, m):
    """`<name attr=... >` from a _TAG_OPEN match: (name, attrs, end) or None.
    Values are read whole - a `>` inside {() => go()} does not end the tag."""
    attrs, j, n = {}, m.end(), len(text)
    while j < n and j - m.start() < 20000:
        while j < n and text[j].isspace():
            j += 1
        if j >= n:
            return None
        if text[j] == ">":
            return m.group(1), attrs, j + 1
        if text.startswith("/>", j):
            return m.group(1), attrs, j + 2
        if text[j] == "{":                      # a JSX spread, {...props}
            e = _match_brace(text, j)
            if e < 0:
                return None
            j = e + 1
            continue
        a = _ATTR_NAME.match(text, j)
        if not a:
            return None
        name, j = a.group(0), a.end()
        while j < n and text[j] in " \t":
            j += 1
        if j < n and text[j] == "=":
            j += 1
            while j < n and text[j].isspace():
                j += 1
            if j >= n:
                return None
            if text[j] in "\"'":
                e = text.find(text[j], j + 1)
            elif text[j] == "{":
                e = _match_brace(text, j)
            else:
                u = _UNQUOTED.match(text, j)
                e = u.end() - 1 if u else -1
            if e < 0:
                return None
            attrs[name] = text[j:e + 1]
            j = e + 1
        else:
            attrs[name] = ""
    return None


def _open_tag(text, pos):
    """(name, attrs, end) of the opening tag containing text[pos], or None. Walks
    back to each `<name` and keeps the first whose parsed extent covers pos, so
    a tag nested inside an attribute ({<Icon />}) is stepped over."""
    k = pos
    for _ in range(60):
        k = text.rfind("<", 0, k)
        if k < 0:
            return None
        m = _TAG_OPEN.match(text, k)
        if not m:
            continue
        tag = _parse_tag(text, m)
        if tag and k < pos < tag[2]:
            return tag
    return None


def _attr_word(raw):
    """role="dialog", role={'dialog'} and role={open ? 'dialog' : null} -> dialog."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    if raw[0] in "\"'":
        return raw[1:-1].strip().lower()
    if raw[0] == "{":
        return (_first_literal(raw[1:-1]) or "").strip().lower()
    return raw.lower()


def _element_kind(name, attrs):
    """'region', 'control', or None for a label on anything else."""
    low, role = name.lower(), _attr_word(attrs.get("role"))
    if low in _REGION_TAGS or role in _REGION_ROLES:
        return "region"
    if low in _NATIVE_CONTROLS or role in _CONTROL_ROLES:
        return "control"
    if low == "a" and "href" in attrs:
        return "control"
    if _attr_word(attrs.get("type")) == "submit":
        return "control"
    if any(_HANDLER.match(a) and not _NOT_USER.match(a) for a in attrs):
        return "control"
    return None


def _holds_control(text, name, start):
    """Whether the element whose content begins at `start` holds a control
    before it closes. A plain <div aria-label="Account"> wrapped round the
    sign-in buttons names a real area of the page; on one web app, reading the
    element's own tag alone dropped it without a word."""
    depth, j, stop = 1, start, min(len(text), start + 30000)
    while j < stop:
        k = text.find("<", j, stop)
        if k < 0:
            return False
        c = _TAG_CLOSE.match(text, k)
        if c:
            if c.group(1) == name:
                depth -= 1
                if depth == 0:
                    return False
            j = c.end()
            continue
        m = _TAG_OPEN.match(text, k)
        tag = _parse_tag(text, m) if m else None
        if not tag:
            j = k + 1
            continue
        if _element_kind(tag[0], tag[1]) == "control":
            return True
        if tag[0] == name and not text.startswith("/>", tag[2] - 2):
            depth += 1
        j = tag[2]
    return False


def ex_controls(root, files):
    """Controls and labelled regions that carry a durable selector. An onClick
    with no testid and no aria-label is deliberately NOT emitted as a feature: a
    CSS path would rot on the next refactor and a map built on rotting selectors
    is worse than a gap, because the gap is visible."""
    out, claimed = [], []
    for p in files:
        if not p.endswith((".tsx", ".jsx", ".astro", ".vue", ".html")):
            continue
        text = read(p)
        if "aria-label" not in text and "data-testid" not in text:
            continue
        r = rel(root, p)
        hit = False
        for m in _LABEL_ATTR.finditer(text):
            tag = _open_tag(text, m.start())
            kind = _element_kind(tag[0], tag[1]) if tag else None
            holds = False
            if not kind and tag and not _attr_word(tag[1].get("role")) \
                    and not text.startswith("/>", tag[2] - 2):
                # No role and no handler, but a name: a region if it holds
                # controls. An explicit other role (img, tooltip) is not one.
                holds = _holds_control(text, tag[0], tag[2])
                kind = "region" if holds else None
            if not kind:
                continue
            hit = True
            src, found_as = _label_value(text, m)
            loc = "%s:%d" % (r, text.count("\n", 0, m.start()) + 1)
            note = m.group(1) + found_as
            if kind == "region":
                role = _attr_word(tag[1].get("role"))
                note = "%s%s: %s" % (tag[0], " role=" + role if role else
                                     " holding controls" if holds else "", note)
            if src and re.search(r"[A-Za-z0-9]", src):
                out.append((kind + "." + slug(src), "web-ui", loc, note))
            else:
                # Real, but nothing fixed in the code names it. An id of None
                # is how an extractor says "found, cannot address" - derive()
                # lists it by location instead of letting it vanish.
                out.append((None, "web-ui", loc, note))
        if hit:
            claimed.append(r)
    return out, claimed


# One key test: `e.key === 'Escape'`, and the guard form `e.key !== 'Escape')
# return`, which means the same key. One web app's settings panel closes on Escape
# through exactly that guard, and the equality-only reading never saw it.
_KEY_TEST = re.compile(r"\b(key|code)\s*(===?|!==?)\s*([\"'])((?:(?!\3).){1,12})\3")

# Keys whose literal slugs to nothing useful. A shortcut named `key.unnamed` is
# unsearchable, and the map is an addressing system before it is a document.
KEY_NAMES = {" ": "space", "": "empty", "+": "plus", "-": "minus", "/": "slash",
             "?": "question", ".": "period", ",": "comma", "[": "bracket-left",
             "]": "bracket-right", "\\": "backslash", "=": "equals"}


# A shortcut is the keys tested in ONE condition plus the modifiers it demands.
# Reading each literal alone mapped one web app's Alt+P twice, as `key.p` and
# `key.keyp`, and without its Alt. Where the test sits decides what it is: in a
# window or document listener it is a global shortcut; in an element's own
# onKeyDown it operates that element - and Enter or Space there, on something
# button-like, is the element's keyboard activation, not a shortcut at all.
_LISTEN = re.compile(r"\.addEventListener\(\s*([\"'])key(?:down|up|press)\1\s*,\s*")
_ONKEY_ATTR = re.compile(r"\bon[Kk]ey(?:[Dd]own|[Uu]p|[Pp]ress)\s*=\s*")
_SAME_CONDITION = re.compile(r"^[\s()|&!]*(?:[\w$]+\.)*$")
_PLAUSIBLE_KEY = re.compile(
    r"^(?:.|Enter|Escape|Esc|Tab|Backspace|Delete|Insert|Home|End|PageUp|"
    r"PageDown|Arrow(?:Up|Down|Left|Right)|F\d{1,2}|Key[A-Z]|Digit\d|"
    r"Numpad\w+|Space|Spacebar)$")
_MOD_GUARD = re.compile(r"!\s*[\w$]+\.(ctrl|alt|shift|meta)Key\s*\)\s*return\b")
# `!e.altKey &&` rules Alt out. Read as `e.altKey &&`, KiT's Ctrl+Shift+D was
# minted as Ctrl+Alt+Shift+D.
_MOD_AND = re.compile(r"(?<![\w$!])(?<!!\s)[\w$]+\.(ctrl|alt|shift|meta)Key\s*\)?\s*&&")
_MOD_EITHER = re.compile(r"[\w$]+\.(?:ctrl|meta)Key\s*\|\|\s*[\w$]+\.(?:ctrl|meta)Key")
# A key read into a local first - `const k = e.key.toLowerCase()` - and then
# tested by that name. KiT's landing page dispatches every shortcut that way,
# and not one was derived. Followed only inside the listener that defines it,
# from the definition on: a `k` anywhere else in the file is not that key.
_KEY_ALIAS = re.compile(r"\b(?:const|let|var)\s+([\w$]+)\s*=\s*[\w$]+\.(?:key|code)\b"
                        r"(?:\s*\.\s*to(?:Lower|Upper)Case\(\s*\))?\s*(?:;|\n)")
_ACTIVATABLE_ROLES = {"button", "link", "checkbox", "switch", "tab", "menuitem",
                      "menuitemcheckbox", "menuitemradio", "option", "radio",
                      "treeitem"}


def _fn_body(text, j, is_function=False):
    """(start, end) of the function written at text[j:] - an arrow's block or
    expression, or a `function`'s block. A wrapper such as useCallback((e) =>
    {...}) is stepped through. None when it cannot be read."""
    k = j
    while k < len(text) and text[k].isspace():
        k += 1
    f = re.compile(r"(?:async\s+)?function\b[^(]*").match(text, k)
    if f or is_function:
        p = f.end() if f else k
        q = _match_brace(text, p, "(", ")") if text[p:p + 1] == "(" else -1
        b = text.find("{", q) if q >= 0 else -1
        e = _match_brace(text, b) if b >= 0 else -1
        return (b, e) if e > 0 else None
    a = text.find("=>", k, k + 400)
    if a < 0:
        return None
    b = a + 2
    while b < len(text) and text[b].isspace():
        b += 1
    if text[b:b + 1] == "{":
        e = _match_brace(text, b)
        return (b, e) if e > 0 else None
    e = text.find("\n", b)
    return (b, e if e > 0 else len(text))


def _named_body(text, name, before):
    """Body of the nearest definition of `name` above `before`. One file can
    define `onKey` in three components; the listener registered in each means
    the one written just above it."""
    best = None
    for d in re.finditer(r"\b(?:(?:const|let|var)\s+%s\s*=|function\s+%s\s*(?=\())"
                         % (re.escape(name), re.escape(name)), text[:before]):
        best = d
    if not best:
        return None
    return _fn_body(text, best.end(), best.group(0).startswith("function"))


def _key_scopes(text):
    """[(start, end, kind, detail)] for every keyboard listener body in a file:
    kind is "global" (detail: what it listens on) or "element" (detail: the
    element's parsed opening tag, or None)."""
    scopes = []
    for m in _LISTEN.finditer(text):
        who = re.search(r"([\w$.]+)$", text[max(0, m.start() - 60):m.start()])
        n = re.match(r"([\w$]+)\s*[,)]", text[m.end():m.end() + 80])
        body = (_named_body(text, n.group(1), m.start()) if n
                else _fn_body(text, m.end()))
        if body:
            scopes.append((body[0], body[1], "global",
                           who.group(1) if who else "an element"))
    for m in _ONKEY_ATTR.finditer(text):
        j = m.end()
        tag = _open_tag(text, m.start())
        if text[j:j + 1] == "{":
            e = _match_brace(text, j)
            if e < 0:
                continue
            inner = text[j + 1:e].strip()
            if re.match(r"^[\w$.]+$", inner):
                body = _named_body(text, inner.split(".")[-1], m.start())
                if body:
                    scopes.append((body[0], body[1], "element", tag))
            else:
                scopes.append((j, e, "element", tag))
        elif text[j:j + 1] in "\"'":
            e = text.find(text[j], j + 1)
            if e > 0:
                scopes.append((j, e, "element", tag))
    return scopes


def _key_name(k):
    m = re.match(r"^Key([A-Z])$", k) or re.match(r"^Digit(\d)$", k)
    if m:
        return m.group(1).lower()
    if len(k) == 1 and k.isalpha():
        return k.lower()
    if k.lower() in ("esc", "escape"):
        return "escape"
    if k in (" ", "Spacebar", "Space"):
        return "space"
    return KEY_NAMES.get(k, slug(k))


def _branch_block(text, g):
    """(start, end) of the block opened by the `if` whose condition holds the
    key test g, or None. A key tested again inside that block picks a branch
    of the same shortcut: KiT's `set(k === "d" ? "light" : "night")` inside its
    Ctrl+Shift+D/K block was minted as a bare D that does not exist."""
    s = g[0].start()
    b = max(text.rfind(";", 0, s), text.rfind("{", 0, s), text.rfind("}", 0, s))
    ifs = list(re.finditer(r"\bif\s*\(", text[b + 1:s]))
    if not ifs:
        return None
    q = _match_brace(text, b + ifs[-1].end(), "(", ")")
    o = re.match(r"\s*\{", text[q + 1:q + 40]) if q >= g[-1].end() else None
    if not o:
        return None
    e = _match_brace(text, q + o.end())
    return (q + o.end(), e) if e > 0 else None


def _modifiers(guard_ctx, condition):
    """Modifiers a shortcut demands: a guard earlier in its handler
    (`if (!e.altKey) return`) or a conjunction in its own condition
    (`e.altKey && ...`). `(e.ctrlKey || e.metaKey)` is `mod` - Ctrl on
    Windows, Cmd on a Mac. Anything subtler is not guessed at."""
    mods = set(m.group(1) for m in _MOD_GUARD.finditer(guard_ctx))
    mods.update(m.group(1) for m in _MOD_AND.finditer(condition))
    if _MOD_EITHER.search(condition) or _MOD_EITHER.search(guard_ctx):
        mods = (mods - {"ctrl", "meta"}) | {"mod"}
    return [x for x in ("mod", "ctrl", "alt", "shift", "meta") if x in mods]


def ex_keyboard(root, files):
    out, claimed = [], []
    for p in files:
        if not p.endswith((".tsx", ".jsx", ".ts", ".js", ".vue", ".astro", ".html")):
            continue
        text = read(p)
        if not re.search(r"key(?:down|up|press)", text, re.I):
            continue
        r = rel(root, p)
        scopes = _key_scopes(text)
        tests = list(_KEY_TEST.finditer(text))
        for s in scopes:
            for a in _KEY_ALIAS.finditer(text, s[0], s[1]):
                if a.group(1) in ("key", "code"):
                    continue                        # _KEY_TEST reads these
                rx = re.compile(r"(?<![\w$.])(%s)\s*(===?|!==?)\s*([\"'])"
                                r"((?:(?!\3).){1,12})\3" % re.escape(a.group(1)))
                tests += rx.finditer(text, a.end(), s[1])
        seen = set()
        tests = [m for m in sorted(tests, key=lambda m: m.start())
                 if not (m.start() in seen or seen.add(m.start()))]
        groups = []
        for m in tests:
            # `key !== 'Tab'` outside a guard means "any other key": no key.
            if m.group(2).startswith("!") and not re.match(
                    r"\s*\)\s*return\b", text[m.end():m.end() + 30]):
                continue
            if groups and _SAME_CONDITION.match(text[groups[-1][-1].end():m.start()]):
                groups[-1].append(m)
            else:
                groups.append([m])
        found, minted = False, []
        for g in groups:
            start, end = g[0].start(), g[-1].end()
            inside = [s for s in scopes if s[0] <= start < s[1]]
            scope = min(inside, key=lambda s: s[1] - s[0]) if inside else None
            raw = [m.group(4) for m in g]
            if not scope and not all(_PLAUSIBLE_KEY.match(k) for k in raw):
                continue  # `tab.key === 'fundamentals'` is data, not a keyboard
            names = []
            for k in raw:
                if _key_name(k) not in names:
                    names.append(_key_name(k))
            if any(blk and blk[0] < start < blk[1] and set(names) <= nm
                   and sc == scope for blk, nm, sc in minted):
                continue  # a branch of the shortcut whose block this is in
            found = True
            b = max(text.rfind(";", 0, start), text.rfind("{", 0, start),
                    text.rfind("}", 0, start))
            mods = _modifiers(text[scope[0]:start] if scope else "",
                              text[b + 1:end])
            if scope and scope[2] == "element" and set(names) <= {"enter", "space"} \
                    and scope[3] and (_attr_word(scope[3][1].get("role"))
                                      in _ACTIVATABLE_ROLES
                                      or scope[3][0].lower() in ("button", "a", "summary")):
                continue  # the element's own keyboard activation, not a shortcut
            fid = "key." + "-".join(mods + ["-or-".join(names)])
            keys = " / ".join(repr(k) for k in raw) + (
                " with " + "+".join(mods) if mods else "") + "".join(
                sorted(set(" (tested as %s)" % m.group(1) for m in g
                           if m.group(1) not in ("key", "code"))))
            if scope and scope[2] == "global":
                how = "global shortcut (%s keydown listener): %s" % (scope[3], keys)
            elif scope:
                t = scope[3]
                role = _attr_word(t[1].get("role")) if t else ""
                how = "on a focused element (onKeyDown of %s%s): %s" % (
                    t[0] if t else "an element", " role=" + role if role else "",
                    keys)
            else:
                how = "key test outside any listener this can follow: %s" % keys
            line = text.count("\n", 0, start) + 1
            out.append((fid, "web-ui", "%s:%d" % (r, line), how))
            minted.append((_branch_block(text, g), set(names), scope))
        if found:
            claimed.append(r)
    return out, claimed


def ex_cli(root, files):
    out, claimed = [], []
    for p in files:
        if not p.endswith(".py"):
            continue
        text = read(p)
        if "add_argument" not in text and "@click.command" not in text:
            continue
        r = rel(root, p)
        claimed.append(r)
        flags = _py_flags(text)
        if flags is None:
            flags = [(text.count("\n", 0, m.start()) + 1, m.group(1)) for m in
                     re.finditer(r"add_argument\(\s*[\"'](--[a-zA-Z0-9-]+)[\"']",
                                 text)]
        for line, flag in flags:
            out.append(("cli." + slug(flag), "cli", "%s:%d" % (r, line),
                        "flag " + flag))
    return out, claimed


def _py_flags(text):
    """[(line, --flag)] for argparse flags in real code, from the syntax tree -
    this skill's own map carried `cli.verbose` out of a fixture string in its
    test harness. None when the file will not parse, and the pattern reads it."""
    import ast
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            for a in node.args:
                if (isinstance(a, ast.Constant) and isinstance(a.value, str)
                        and re.match(r"^--[a-zA-Z0-9-]+$", a.value)):
                    found.append((node.lineno, a.value))
                    break
    return sorted(found)


def ex_pkg_scripts(root, files):
    out, claimed = [], []
    for p in files:
        if os.path.basename(p) != "package.json":
            continue
        r = rel(root, p)
        if r.count("/") > 1:
            continue
        try:
            data = json.loads(read(p) or "{}")
        except ValueError:
            continue
        claimed.append(r)
        for name in (data.get("scripts") or {}):
            out.append(("script." + slug(name), "cli", r + ":1",
                        "npm script " + name))
    return out, claimed


# ---------------------------------------------------------------- the dev face
# What a developer or operator reaches without opening a screen: the settings a
# process reads from its environment, the services a deploy config declares,
# and the workflows CI runs. NAMES ONLY. A value is never read, printed or
# stored - the value of a key is the secret, and a map is a tracked file.

_ENV_JS = (
    (re.compile(r"\bprocess\.env\.([A-Za-z_][A-Za-z0-9_]*)"), "node process.env"),
    (re.compile(r"\bprocess\.env\[\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']\s*\]"),
     "node process.env"),
    (re.compile(r"\bimport\.meta\.env\.([A-Za-z_][A-Za-z0-9_]*)"),
     "vite import.meta.env"),
)
_ENV_PY = re.compile(
    r"\b(?:environ\.get|getenv|environ\.setdefault)\(\s*[\"']([A-Za-z_]\w*)[\"']"
    r"|\benviron\[\s*[\"']([A-Za-z_]\w*)[\"']\s*\]")


def _py_env_reads(text):
    """[(line, NAME)] for environment reads in real code, from the syntax tree:
    `os.environ.get("X")`, `os.getenv("X")`, `os.environ["X"]`,
    `environ.setdefault("X", ...)`. A read inside a string is not a read - the
    same lesson as routes in fixture strings. None when the file will not parse."""
    import ast
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None

    def environ(node):
        return ((isinstance(node, ast.Attribute) and node.attr == "environ")
                or (isinstance(node, ast.Name) and node.id == "environ"))
    # A name read through a module constant - `KEY_ENV = "TYPESAFE_API_KEY"`,
    # then `os.environ.get(KEY_ENV)` - is still that name. This skill's own Jev
    # client read its key that way and the dev face did not list it. A name
    # assigned more than once is not resolved: which one is read is not fixed.
    consts, seen = {}, {}
    for st in tree.body:
        if isinstance(st, ast.Assign):
            pairs = []
            for t in st.targets:
                if isinstance(t, ast.Name):
                    pairs.append((t.id, st.value))
                elif isinstance(t, ast.Tuple) and isinstance(st.value, ast.Tuple) \
                        and len(t.elts) == len(st.value.elts):
                    pairs += [(e.id, v) for e, v in zip(t.elts, st.value.elts)
                              if isinstance(e, ast.Name)]
            for name, v in pairs:
                seen[name] = seen.get(name, 0) + 1
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    consts[name] = v.value
    consts = {k: v for k, v in consts.items() if seen[k] == 1}
    found = []
    for node in ast.walk(tree):
        arg = None
        if isinstance(node, ast.Call) and node.args:
            f = node.func
            if (isinstance(f, ast.Attribute) and f.attr in ("get", "setdefault")
                    and environ(f.value)) \
                    or (isinstance(f, ast.Attribute) and f.attr == "getenv") \
                    or (isinstance(f, ast.Name) and f.id == "getenv"):
                arg = node.args[0]
        elif isinstance(node, ast.Subscript) and environ(node.value):
            arg = node.slice
            if not isinstance(arg, ast.Constant):      # Python 3.8 wraps it
                arg = getattr(arg, "value", arg)
        via = ""
        if isinstance(arg, ast.Name) and arg.id in consts:
            via, arg = arg.id, ast.Constant(value=consts[arg.id])
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                and re.match(r"^[A-Za-z_]\w*$", arg.value):
            found.append((node.lineno, arg.value, via))
    return sorted(found)


def ex_env(root, files):
    """Environment variables the code reads, by name. Tests are skipped: a
    variable a test sets for itself is the test's configuration, not the app's."""
    out = []
    for p in files:
        r = rel(root, p)
        if _TEST_PATH.search(r):
            continue
        if p.endswith(".py"):
            text = read(p)
            if "environ" not in text and "getenv" not in text:
                continue
            reads = _py_env_reads(text)
            if reads is None:
                reads = [(text.count("\n", 0, m.start()) + 1,
                          m.group(1) or m.group(2), "") for m in _ENV_PY.finditer(text)]
            for line, name, via in reads:
                out.append(("env." + slug(name), "config", "%s:%d" % (r, line),
                            "python environ " + name + (" (via %s)" % via if via else "")))
        elif p.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue",
                         ".svelte", ".astro")):
            text = read(p)
            if ".env" not in text:
                continue
            for rx, how in _ENV_JS:
                for m in rx.finditer(text):
                    line = text.count("\n", 0, m.start()) + 1
                    out.append(("env." + slug(m.group(1)), "config",
                                "%s:%d" % (r, line), "%s %s" % (how, m.group(1))))
    return out, []


_TOP = {}   # project root -> repository top; also set for a tree taken from a ref


def _toplevel(root):
    key = os.path.normcase(os.path.abspath(root))
    if key not in _TOP:
        ok, top = git(root, "rev-parse", "--show-toplevel")
        _TOP[key] = os.path.normpath(top) if ok and top else root
    return _TOP[key]


def _render_services(text):
    """[(line, name, type, {field: value}, [env key names])] from a render.yaml,
    read by indentation - enough for its fixed shape, with no YAML parser to
    install. `value:` lines are never read, so no secret passes through here."""
    out, cur, item_indent, in_services = [], None, None, False
    for i, raw in enumerate(text.split("\n"), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent == 0:
            in_services = bool(re.match(r"^services\s*:", raw))
            continue
        if not in_services:
            continue
        m = re.match(r"^(\s*)-\s*([A-Za-z]+)\s*:\s*(.*)$", raw)
        if m and (item_indent is None or len(m.group(1)) == item_indent):
            item_indent = len(m.group(1))
            cur = [i, "", "", {}, []]
            out.append(cur)
        if cur is None:
            continue
        k = re.match(r"^\s*(?:-\s*)?([A-Za-z]+)\s*:\s*(.*?)\s*$", raw)
        if not k:
            continue
        key = k.group(1)
        val = re.sub(r"\s+#.*$", "", k.group(2)).strip().strip("'\"")
        if key == "key" and indent > item_indent:
            cur[4].append(val)
        elif key == "name" and not cur[1]:
            cur[1] = val
        elif key == "type" and not cur[2]:
            cur[2] = val
        elif key in ("rootDir", "healthCheckPath", "branch", "autoDeploy",
                     "runtime", "plan"):
            cur[3][key] = val
    return [tuple(s) for s in out if s[1]]


def _deploy_configs(root):
    """[(path, kind, text)] for the deploy and CI files that govern this
    project: its own, and the repository's when the project is a folder inside
    one (one web app's render.yaml sits at the repository root and names the project
    folder as its rootDir)."""
    top = _toplevel(root)
    seen, found = set(), []
    for base in ([root] + ([top] if os.path.normcase(top) != os.path.normcase(root)
                           else [])):
        for name, kind in (("render.yaml", "render"), ("Procfile", "procfile"),
                           ("Dockerfile", "docker")):
            p = os.path.join(base, name)
            if os.path.isfile(p) and os.path.normcase(p) not in seen:
                seen.add(os.path.normcase(p))
                found.append((p, kind, read(p)))
        wf = os.path.join(base, ".github", "workflows")
        if os.path.isdir(wf):
            for f in sorted(os.listdir(wf)):
                p = os.path.join(wf, f)
                if f.endswith((".yml", ".yaml")) and os.path.normcase(p) not in seen:
                    seen.add(os.path.normcase(p))
                    found.append((p, "workflow", read(p)))
    return found


def _mine(root, service):
    """Does this render.yaml service deploy this project folder?"""
    top = _toplevel(root)
    here = rel(top, root).strip("./")
    there = service[3].get("rootDir", "").replace("\\", "/").strip("./")
    return here == there


def ex_deploy(root, files):
    out = []
    for p, kind, text in _deploy_configs(root):
        r = rel(root, p)
        if kind == "render":
            for line, name, typ, fields, keys in _render_services(text):
                if not _mine(root, (line, name, typ, fields, keys)):
                    continue
                bits = ["%s %s" % (k, fields[k]) for k in
                        ("rootDir", "healthCheckPath", "branch") if fields.get(k)]
                out.append(("deploy." + slug(name), "deploy", "%s:%d" % (r, line),
                            "render %s service %s%s; declares %d env var(s)"
                            % (typ or "?", name,
                               (" (" + ", ".join(bits) + ")") if bits else "",
                               len(keys))))
        elif kind == "procfile":
            for i, raw in enumerate(text.split("\n"), 1):
                m = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(\S+)", raw)
                if m:
                    out.append(("deploy." + slug(m.group(1)), "deploy",
                                "%s:%d" % (r, i),
                                "Procfile process %s runs %s" % (m.group(1),
                                                                 m.group(2))))
        elif kind == "docker":
            ports = re.findall(r"^\s*EXPOSE\s+([^\n#]+)", text, re.M | re.I)
            out.append(("deploy.dockerfile", "deploy", r + ":1", "Dockerfile"
                        + (" exposing " + ", ".join(x.strip() for x in ports)
                           if ports else "")))
        else:
            m = re.search(r"^name\s*:\s*(.+)$", text, re.M)
            stem = os.path.splitext(os.path.basename(p))[0]
            on = re.search(r"^on\s*:\s*(.*)$", text, re.M)
            out.append(("ci." + slug(stem), "ci", r + ":1",
                        "GitHub workflow %s%s" % (
                            (m.group(1).strip().strip("'\"") if m else stem),
                            (" on " + on.group(1).strip()) if on and
                            on.group(1).strip() else "")))
    return out, []


def _declared_env(root):
    """{NAME: service} for every env key a deploy config of this project names."""
    names = {}
    for p, kind, text in _deploy_configs(root):
        if kind != "render":
            continue
        for s in _render_services(text):
            if _mine(root, s):
                for k in s[4]:
                    names.setdefault(k, s[1])
    return names


def _cross_env(root, feats):
    """Say, per variable, whether the deploy config declares it, and per
    service which declared names no code reads. A variable the config does not
    declare may still be set in the host's dashboard - so this reports what the
    files say, and the row says which file it read."""
    declared = _declared_env(root)
    if not declared:
        return
    read_names = set()
    for fid, f in list(feats.items()):
        if fid.startswith("env."):
            name = f[3].split(" — ")[0].split()[-1]
            read_names.add(name)
            feats[fid] = f[:3] + (f[3] + " — " + (
                "declared in render.yaml (service %s)" % declared[name]
                if name in declared else "not declared in render.yaml"),) + f[4:]
    for fid, f in list(feats.items()):
        if fid.startswith("deploy.") and f[3].startswith("render "):
            unread = sorted(k for k, s in declared.items()
                            if "deploy." + slug(s) == fid and k not in read_names)
            if unread:
                feats[fid] = f[:3] + (f[3] + " — declared but read by no "
                                      "code: " + ", ".join(unread),) + f[4:]


EXTRACTORS = (ex_next_app, ex_next_pages, ex_astro, ex_python_routes,
              ex_express, ex_controls, ex_keyboard, ex_cli, ex_pkg_scripts,
              ex_env, ex_deploy)
ROUTE_EXTRACTORS = (ex_python_routes, ex_express)

# ---------------------------------------------------------------- faces
# The requirement, 2026-09-23: map everything from both the user's face and the
# development face. A user reaches pages, controls, regions and keys, and whatever API the
# user's own screens call. A developer or operator reaches the command line,
# the scripts, and the endpoints no screen calls. For an API endpoint the face
# is measured, not guessed: a client file that calls its path is the evidence,
# and the row says which file and line.
USER_PREFIXES = ("route.", "control.", "region.", "key.")
DEV_PREFIXES = ("cli.", "script.", "env.", "deploy.", "ci.")
CLIENT_EXT = (".jsx", ".tsx", ".js", ".ts", ".mjs", ".vue", ".svelte", ".astro",
              ".html", ".hbs", ".ejs")
_TEST_PATH = re.compile(r"(?:^|/)(?:tests?|__tests__|spec)/|\.(?:test|spec)\.\w+$")


def _fixed_part(path):
    """The longest piece of a route path that holds no parameter. One web app's UI
    calls `/<path:ticker>/frame/today` as `/${enc}/frame/today`, so the piece
    worth looking for is the one after the parameter, not the `/` before it."""
    return max(re.split(r"<[^>]*>|\{[^}]*\}|:[A-Za-z_]\w*", path), key=len)


def _caller(path, client):
    """(face, why) for an API endpoint: `user` when a client file calls its
    path, `dev` when none does, and `unclassified` when the path has no fixed
    part to look for - `/<ticker>` matches every string that starts a path."""
    fixed = _fixed_part(path)
    if len(fixed.strip("/")) < 2:
        return "unclassified", "no fixed path to look for in client code"
    if path.endswith(fixed):
        # The path ends here, so the string in the caller must end here too:
        # `/chat` is not a call to `/chatroom`.
        rx = re.compile(r"[\"'`}]" + re.escape(fixed.rstrip("/"))
                        + r"(?:[\"'`?#]|/[\"'`]|\$\{)")
    else:
        rx = re.compile(r"[\"'`}]" + re.escape(fixed))
    for r, text in client:
        m = rx.search(text)
        if m:
            return "user", "called from %s:%d" % (
                r, text.count("\n", 0, m.start()) + 1)
    return "dev", "no client file calls it"


def _face(fid, surface, note, client):
    if fid.startswith(USER_PREFIXES) or (fid.startswith("endpoint.")
                                         and surface == "web-ui"):
        return "user", ""
    if fid.startswith(DEV_PREFIXES):
        return "dev", ""
    if fid.startswith("endpoint."):
        m = re.search(r"\s(/\S*)", note)
        if m:
            return _caller(m.group(1), client())
    return "unclassified", ""


def face_counts(feats):
    n = {}
    for f in feats.values():
        n[f[4]] = n.get(f[4], 0) + 1
    return ", ".join("%s %d" % (k, n[k]) for k in ("user", "dev", "unclassified")
                     if k in n) or "none"

# Files that look like a user surface. Anything here that no extractor claimed
# is reported UNPARSED - the honest output when a stack is not understood.
SURFACE_EXT = (".tsx", ".jsx", ".astro", ".vue", ".svelte", ".html", ".hbs",
               ".ejs", ".razor", ".blade.php")

# A desktop GUI is a user surface too. KiT's Windows app - a Tk control bar, a
# pystray tray menu, RegisterHotKey chords - derived nothing, and --check said
# every surface file parsed. No extractor reads these, so a file that uses one
# is UNPARSED whatever else in it was read: a file claimed for its argparse
# flags has not had its window read. An extractor that learns to read them
# must take its files out of this rule, or it will never be able to close one.
_DESKTOP_MODULES = ("tkinter", "pystray")
_DESKTOP_CALLS = ("RegisterHotKey",)
_DESKTOP_RX = re.compile(r"^\s*(?:import|from)\s+(tkinter|pystray)\b"
                         r"|\b(RegisterHotKey)\s*\(", re.M)


def _desktop_gui(text):
    """Why a Python file is a desktop GUI ("imports tkinter at line 10"), or
    None. From the syntax tree, so a docstring naming RegisterHotKey is not a
    call; by pattern only when the file will not parse."""
    if not any(w in text for w in _DESKTOP_MODULES + _DESKTOP_CALLS):
        return None
    import ast
    found = {}

    def hit(what, line):                    # the first line each one is at
        found[what] = min(found.get(what, line), line)
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        for m in _DESKTOP_RX.finditer(text):
            hit(("imports " + m.group(1)) if m.group(1) else ("calls " + m.group(2)),
                text.count("\n", 0, m.start()) + 1)
        tree = None
    for node in (ast.walk(tree) if tree else ()):
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            mods = [node.module]
        for mod in mods:
            if mod.split(".")[0] in _DESKTOP_MODULES:
                hit("imports " + mod.split(".")[0], node.lineno)
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else \
                getattr(f, "id", None)
            if name in _DESKTOP_CALLS:
                hit("calls " + name, node.lineno)
    return "; ".join("%s at line %d" % (w, n) for w, n in
                     sorted(found.items(), key=lambda x: x[1])) or None


def derive(root):
    every = [p for p in walk(root)]
    all_rel = set(rel(root, p) for p in every)
    generated, files = {}, []
    for p in every:
        why = generated_reason(root, p, all_rel)
        if why:
            generated[rel(root, p)] = why
        else:
            files.append(p)
    feats, claimed, unaddressed, also, server = {}, set(), [], {}, set()
    for fn in EXTRACTORS:
        got, cl = fn(root, files)
        if fn in ROUTE_EXTRACTORS:
            server.update(cl)
        for fid, surface, code, note in got:
            if fid is None:
                unaddressed.append((code, note))
                continue
            if fid in feats:
                # One id, several places. Keeping only the first hid one web app's
                # two global Escape handlers behind its look-up's Escape. Every
                # place is listed, so the entry for the id can cover them all.
                if code != feats[fid][2] and code not in also.setdefault(fid, []):
                    also[fid].append(code)
                continue
            feats[fid] = (fid, surface, code, note)
        claimed.update(cl)
    for fid, locs in also.items():
        if locs:
            f = feats[fid]
            feats[fid] = f[:3] + (f[3] + " \u2014 also at " + ", ".join(locs[:5])
                                  + (" and %d more" % (len(locs) - 5)
                                     if len(locs) > 5 else ""),)
    cache = []

    def client():
        # Read once, and only when an API endpoint needs its face measured. A
        # file that serves routes is not a caller of them, and neither is a test.
        if not cache:
            cache.append([(rel(root, p), read(p)) for p in files
                          if p.endswith(CLIENT_EXT) and rel(root, p) not in server
                          and not _TEST_PATH.search(rel(root, p))])
        return cache[0]
    for fid in list(feats):
        f = feats[fid]
        face, why = _face(fid, f[1], f[3], client)
        feats[fid] = f[:3] + ((f[3] + " \u2014 " + why) if why else f[3], face)
    _cross_env(root, feats)
    unparsed = []                           # (path, why - "" for a page file)
    for p in files:
        r = rel(root, p)
        if r.endswith(SURFACE_EXT):
            if r not in claimed:
                unparsed.append((r, ""))
        elif r.endswith((".py", ".pyw")) and not _TEST_PATH.search(r):
            why = _desktop_gui(read(p))
            if why:
                unparsed.append((r, "desktop GUI: " + why))
    return feats, sorted(unparsed), len(files), generated, unaddressed


# ---------------------------------------------------------------- the map

def parse_map(text):
    """(derived_ids, authored) - authored is {id: {field: value}}."""
    derived_ids = set()
    dblock = _between(text, D_BEGIN, D_END)
    for m in re.finditer(r"^\|\s*`([^`]+)`\s*\|", dblock, re.M):
        derived_ids.add(m.group(1))
    authored = {}
    ablock = _between(text, A_BEGIN, A_END)
    for sec in re.split(r"^###\s+", ablock, flags=re.M)[1:]:
        head, _, body = sec.partition("\n")
        head = head.strip().strip("`")
        if head.lower().startswith("pattern:"):
            # `### pattern: no-direct-db` and `### pattern:no-direct-db` are the
            # same rule. Two spellings of one id is a drift generator.
            fid = "pattern:" + head[len("pattern:"):].strip().split()[0] \
                if head[len("pattern:"):].strip() else ""
        else:
            fid = head.split()[0] if head else ""
        if not fid:
            continue
        # Values may wrap. An indented line that does not start a new `- key:`
        # continues the previous one - otherwise a rule written across two lines
        # silently loses its second half, and the rule text is the whole reason
        # a reader with no context can act on it at all.
        fields, key = {}, None
        for raw in body.split("\n"):
            m = re.match(r"^-\s*([a-z_]+)\s*:\s*(.*)$", raw)
            if m:
                key = m.group(1)
                fields[key] = m.group(2).strip()
            elif key and raw.strip() and raw[:1] in (" ", "\t"):
                fields[key] = (fields[key] + " " + raw.strip()).strip()
            elif not raw.strip():
                key = None
        authored[fid] = fields
    return derived_ids, authored


def _between(text, a, b):
    i, j = text.find(a), text.find(b)
    return text[i + len(a):j] if (i >= 0 and j > i) else ""


# ------------------------------------------------------- pattern conformance
# An agent with no context copies the nearest example. That makes a codebase its
# own memory, and it makes an anti-pattern contagious: one bad neighbour becomes
# the template for everything written next to it. The ratchet below is what
# makes "do it the right way" the cheapest path rather than the virtuous one -
# existing violations are grandfathered at a recorded ceiling, and any NEW
# occurrence fails by name and location. You never have to reach zero to be
# protected; you only have to never grow.

SOURCE_EXT = (".py", ".js", ".jsx", ".ts", ".tsx", ".astro", ".vue", ".svelte",
              ".html", ".css", ".sql", ".sh", ".rb", ".go", ".java", ".cs",
              ".php", ".rs", ".md", ".yml", ".yaml", ".json", ".toml")


def pattern_hits(root, pat, files, mode="antipattern"):
    """[(relpath, line, text)] for every violation of this rule.

    Two modes, because a pattern fails in two directions and only one of them
    is the obvious one:

    `antipattern` - the WRONG way, counted wherever it appears inside `files`.
    This is contagion: one bad neighbour becomes the template for what gets
    written next to it.

    `spread` - the RIGHT way, counted wherever it appears OUTSIDE `only_in`.
    A good pattern applied where it was never designed to go is damage too, and
    it is the harder one to see, because every individual occurrence looks like
    someone following the rules."""
    if mode == "spread":
        src, scope, invert = pat.get("signature", ""), pat.get("only_in", ""), True
        if not src or not scope:
            return []
    else:
        src, scope, invert = pat.get("antipattern", ""), pat.get("files", ""), False
        if not src:
            return []
    try:
        # MULTILINE is not optional here. A rule is almost always written
        # line-anchored (`^\s*except\s*:`), and without re.M the `^` binds to the
        # start of the FILE and the rule silently measures zero. That is the
        # worst failure this script can have: a rule that looks enforced, reports
        # clean, and is not running. Caught on the first real tree it was pointed
        # at, where it found 0 of 3 occurrences grep could see.
        rx = re.compile(src, re.M)
    except re.error:
        return None  # a broken regex is reported, never treated as zero hits
    scope = scope.strip()
    hits = []
    for p in files:
        r = rel(root, p)
        if not r.endswith(SOURCE_EXT):
            continue
        if r == MAP_NAME:
            # The rules are written in the map, so every rule matches its own
            # definition there: a `signature` read as drift, a plain-word
            # `antipattern` as spread, on a tree with no violation at all.
            continue
        if scope and (_scope_match(r, scope) == invert):
            continue
        text = read(p)
        if not text:
            continue
        for m in rx.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            body = text.split("\n")[line - 1].strip()
            hits.append((r, line, body[:100]))
    return hits


def _scope_match(relpath, scope):
    """Comma-separated globs; `**/` means any depth. Kept deliberately small -
    a scope nobody can predict is a scope that silently excludes real code."""
    import fnmatch
    for g in (x.strip() for x in scope.split(",") if x.strip()):
        if fnmatch.fnmatch(relpath, g) or fnmatch.fnmatch(relpath, "*/" + g) \
                or fnmatch.fnmatch("/" + relpath, g):
            return True
    return False


def parse_patterns(authored):
    """Authored entries whose id begins with `pattern:` are conformance rules,
    not features. Same section syntax so there is one thing to learn."""
    pats = {}
    for fid, fields in authored.items():
        if fid.startswith("pattern:"):
            pats[fid[len("pattern:"):]] = fields
    return pats


def derived_block(feats, unparsed, nfiles, stamp, generated, unaddressed=()):
    rows = ["| id | face | surface | code | found as |", "|---|---|---|---|---|"]
    for fid in sorted(feats):
        _, surface, code, note, face = feats[fid]
        rows.append("| `%s` | %s | %s | `%s` | %s |"
                    % (fid, face, surface, code, note))
    body = [
        "",
        "_Generated by `featuremap.py --write` at %s from %d file(s). "
        "Do not hand-edit: the next `--write` overwrites it. Judgment fields "
        "live in the AUTHORED half below._" % (stamp, nfiles),
        "",
        "**%d capability/capabilities found in code - by face: %s.**"
        % (len(feats), face_counts(feats)),
        "",
    ] + rows + [""]
    if unparsed:
        body += [
            "**UNPARSED - %d user-surface file(s) no extractor understood.** These are "
            "NOT absent features; they are unmeasured ones, and `--check` fails while "
            "any remain. Either add an extractor or map them by hand and list them in "
            "`unparsed_accepted` in the authored half." % len(unparsed),
            "",
        ] + ["- `%s`%s" % (u, " — " + why if why else "")
             for u, why in unparsed] + [""]
    if unaddressed:
        body += [
            "**NO FIXED NAME - %d control(s) or region(s) whose label exists only "
            "at runtime.** "
            "Found and real, but nothing in the code names them, so no id can be "
            "derived. Listed rather than dropped: `--check` prints them and its PASS "
            "states that it does not cover them. Map one by hand when you touch it."
            % len(unaddressed),
            "",
        ] + ["- `%s` — %s" % (loc, note.replace("`", "'"))
             for loc, note in unaddressed] + [""]
    if generated:
        body += [
            "**EXCLUDED as build artifacts - %d file(s), each with its reason.** Listed "
            "rather than silently skipped: a quiet exclusion of the only source file in a "
            "project produces a clean map over an unmapped app. Extracting from minified "
            "or compiled output invents features that do not exist." % len(generated),
            "",
        ] + ["- `%s` — %s" % (g, generated[g])
             for g in sorted(generated)] + [""]
    # Every list whole, as --check's are since 1.3.1: "...and N more" reads as
    # the end of a list to anyone who does not count.
    return "\n".join(body)


# ---------------------------------------------------------------- commands

def cmd_write(root, mp):
    if not os.path.exists(mp):
        print("no %s - run --init first" % MAP_NAME)
        return 1
    text = read(mp)
    if D_BEGIN not in text or D_END not in text:
        print("map is missing the %s / %s markers - refusing to guess where the "
              "generated half belongs" % (D_BEGIN, D_END))
        return 1
    feats, unparsed, nfiles, generated, unaddressed = derive(root)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    new = (text[:text.find(D_BEGIN) + len(D_BEGIN)]
           + "\n" + derived_block(feats, unparsed, nfiles, stamp, generated,
                                  unaddressed)
           + text[text.find(D_END):])
    write(mp, new)
    print("wrote DERIVED block: %d capability/capabilities, %d unparsed file(s), "
          "%d build artifact(s) excluded by name"
          % (len(feats), len(unparsed), len(generated)))
    return 0


# Ids the extractors mint. An authored entry under one of these prefixes that
# the code no longer derives maps something that is gone, or is there under a
# new name - and the file it points at still existing proves nothing, because a
# route renamed inside a file leaves the file. Hand-mapped features take their
# own prefixes (ui., setting.) and are never judged by this.
DERIVED_PREFIXES = ("endpoint.", "route.", "control.", "region.", "key.", "cli.",
                    "script.", "env.", "deploy.", "ci.")
KNOWN_RENAMES = {"endpoint.unnamed": "endpoint.root", "route.unnamed": "route.root"}


def _successor(fid, entry, feats, authored_ids):
    """The derived id an orphaned entry most likely became, or None."""
    free = [i for i in sorted(feats) if i not in authored_ids]
    if KNOWN_RENAMES.get(fid) in free:
        return KNOWN_RENAMES[fid]
    pre, _, rest = fid.partition(".")
    same = [i for i in free if i.partition(".")[2] == rest]
    if same:
        return same[0]                              # control.x -> region.x
    if pre == "key":
        bare = re.sub(r"^(?:key|digit)([a-z0-9])$", r"\1", rest)
        grown = [i for i in free if i.startswith("key.")
                 and bare in i[4:].split("-")]
        if len(grown) == 1:
            return grown[0]                         # key.p -> key.alt-p
    m = re.match(r"^`?([^:`]+):(\d+)", entry.get("code", "").strip())
    if m:
        near = [(abs(int(feats[i][2].rsplit(":", 1)[1]) - int(m.group(2))), i)
                for i in free if feats[i][2].rsplit(":", 1)[0] == m.group(1)
                and feats[i][2].rsplit(":", 1)[1].isdigit()]
        near = [x for x in near if x[0] <= 5]
        if near:
            return min(near)[1]                     # same place, new words
    return None


# How far either side of a feature's `code:` line a change still counts as a
# change to that feature, when the entry names one line instead of a range.
REGION_LINES = 30


def _span(ptr):
    """The region a pointer names: `path:120-180` -> (120, 180); `path:120`
    -> (90, 150), REGION_LINES either side of the one line."""
    if ptr.dash:
        return ptr.lo, ptr.hi
    return max(1, ptr.lo - REGION_LINES), ptr.lo + REGION_LINES


def _hunks(root, commit, path, to=None):
    """[(old_start, old_len, new_start, new_len)] for every change to `path`
    between `commit` and the working tree - or the commit `to` - or None when
    git cannot say. The working tree, not HEAD: the proof is about the code as
    it stands now."""
    ok, out = git(root, "diff", "-U0", "--no-color", "--no-ext-diff", commit,
                  *([to] if to else []), "--", path)
    if not ok:
        return None
    return [tuple(int(x) if x is not None else 1 for x in m.groups())
            for m in re.finditer(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@",
                                 out, re.M)]


def _carry(hunks, lo, hi):
    """Where lines lo-hi of the older side sit now, or None when a change falls
    inside them (then the code itself moved, which is stale proof, not a moved
    pointer). An insertion hunk (old length 0) lands after its old start line."""
    shift = 0
    for a, b, c, d in hunks:
        end = a if b == 0 else a + b - 1
        if (b == 0 and a < lo) or (b and end < lo):
            shift += d - b
        elif a <= hi and not (b == 0 and a >= hi):
            return None
    return lo + shift, hi + shift


def _translate(hunks, lo, hi):
    """Lines lo-hi of a diff's older side, in its newer side's numbers. An end
    that falls in a changed hunk takes that hunk's whole newer side - the lines
    either side of it when it has none - so the region may widen here but never
    drops a change."""
    def at(x, last):
        shift = 0
        for a, b, c, d in hunks:
            if b and a <= x <= a + b - 1:
                return (c + d - 1 if last else c) if d else max(1, c + last)
            if (b == 0 and a < x) or (b and a + b - 1 < x):
                shift += d - b
        return x + shift
    lo = at(lo, False)
    return lo, max(lo, at(hi, True))


# A pointer is `path:N` or `path:N-M` inside a `code:` or `entry:` field - any
# number of them in one field, alone or in prose - and it may carry
# ` @ <commit>`, the commit whose lines its numbers are in. --reaim writes that
# stamp on each range it moves while the file is clean at HEAD, and it is read
# before git blame: nine ranges re-aimed at one commit and left uncommitted were
# read in today's lines by blame alone, one short each, under a PASS, and four
# pointers in prose or in an `entry:` were never read at all (a static site,
# 2026-09-30). A host:port or a URL is not pointer-shaped; a bare file name that
# resolves to nothing is, and --check names it.
POINTER_FIELDS = ("code", "entry")
_POINTER = re.compile(
    r"(?<![\w./@:-])([\w.-]+(?:/[\w.-]+)*):(\d+)(?:(\s*-\s*)(\d+))?(`?)"
    r"(?:\s*@\s*([0-9a-fA-F]{7,40})\b)?(?![\w/-])")
_PATHLIKE = re.compile(r"/|\.[A-Za-z]\w*$")
Ptr = collections.namedtuple(
    "Ptr", "line fid field path lo hi dash tick stamp start end blame exists")
Move = collections.namedtuple("Move", "ptr base via now reason")


def _scan_pointers(root, text):
    """Every pointer in the authored half's `code:` and `entry:` fields, in
    map order, blame not yet read (None). A field runs to the next `- key:` or
    a blank line, as parse_map reads it, so a pointer on a wrapped line counts.
    A token that is not pointer-shaped (localhost:3000) is left out; one that
    is and names no file is kept with exists=False, for --check to name."""
    found, fid, field, inside = [], None, None, False
    for i, ln in enumerate(text.split("\n")):
        if A_BEGIN in ln:
            inside = True
        elif A_END in ln:
            inside = False
        if not inside:
            continue
        ln = ln.rstrip("\r")
        m = re.match(r"^###\s+`?([^`\s]+)", ln)
        if m:
            fid, field = m.group(1), None
            continue
        m = re.match(r"^-\s*([a-z_]+)\s*:", ln)
        if m:
            field = m.group(1)
        elif not (ln.strip() and ln[:1] in (" ", "\t")):
            field = None
        if not fid or field not in POINTER_FIELDS:
            continue
        for p in _POINTER.finditer(ln):
            exists = os.path.exists(os.path.join(root, p.group(1)))
            if not exists and not _PATHLIKE.search(p.group(1)):
                continue
            lo = int(p.group(2))
            hi = int(p.group(4)) if p.group(4) else lo
            found.append(Ptr(i, fid, field, p.group(1), lo, max(lo, hi),
                             p.group(3), p.group(5), p.group(6), p.start(),
                             p.end(), None, exists))
    return found


def _pointers(root, mp, text):
    """_scan_pointers, each with its blame: the commit that last wrote its map
    line, None while that line is not committed. None when git cannot blame
    the map - the lines are then unknown."""
    ok, out = git(root, "blame", "-l", "-s", "--", rel(root, mp))
    if not ok:
        return None
    shas = [ln.split(" ", 1)[0].lstrip("^") for ln in out.split("\n")]
    found = []
    for p in _scan_pointers(root, text):
        sha = shas[p.line] if p.line < len(shas) else ""
        found.append(p._replace(blame=sha if sha.strip("0") else None))
    return found


def _base(root, ptr, known):
    """(commit, dangling): the commit whose lines a pointer's numbers are in -
    its `@ commit` stamp when this repository has it, else the commit that
    last wrote its map line, else None: not committed and unstamped, so read
    in today's lines. `dangling` says the stamp named no commit here."""
    if ptr.stamp:
        if ptr.stamp not in known:
            known[ptr.stamp] = git(root, "rev-parse", "--verify", "--quiet",
                                   ptr.stamp + "^{commit}")[0]
        if known[ptr.stamp]:
            return ptr.stamp, False
        return ptr.blame, True
    return ptr.blame, False


def _ptr_text(ptr, span=None, write=False):
    """`path:lo-hi`, or `path:lo` for a one-line pointer, at `span` or as
    written. For writing back, the separator is kept as the author spaced it."""
    lo, hi = span or (ptr.lo, ptr.hi)
    sep = (ptr.dash if write else "-") if ptr.dash else None
    return "%s:%d%s" % (ptr.path, lo, "%s%d" % (sep, hi) if sep else "")


def _said(mv, span):
    """`fid: path:lo-hi -> path:lo'-hi'`, the printed form of a move."""
    return "%s: %s -> %s" % (mv.ptr.fid, _ptr_text(mv.ptr), _ptr_text(mv.ptr, span))


def _moved_pointers(root, mp, text):
    """(moved, declined, dangling, unplaced). `moved`: every pointer whose
    lines moved since the commit its numbers are in (_base), where the code in
    the range did not change since - or a later DRIVEN/TESTED proof covers the
    change - so --reaim can carry it. `declined`: a range that moved with a
    change inside it no proof covers, with git's best reading of where it sits
    now and the reason it stays; unsaid, that drift hid behind the stale proof
    (a static site's ui.vista, 2026-09-30). `dangling`: a stamp naming no
    commit here, read by blame instead. `unplaced`: not committed and
    unstamped, read in today's lines - right when written, wrong once HEAD
    moves past commits touching the file, which --check says."""
    # A graded proof taken after the map line was written covers every change
    # made in between, so a change inside the range before the proof is no
    # reason to leave it pointing at the wrong lines: carry it through the
    # proof's commit. A static site's ui.workshop-plates, 2026-09-29.
    proofs = {}
    for fid, f in parse_map(text)[1].items():
        m = re.search(r"@\s*([0-9a-fA-F]{7,40})\b", f.get("verified_at", ""))
        if m and (f.get("grade") or "").strip().upper() in ("DRIVEN", "TESTED"):
            proofs[fid] = m.group(1)
    moved, declined, dangling, unplaced, cache, known = [], [], [], [], {}, {}

    def diff(*key):
        if key not in cache:
            cache[key] = _hunks(root, *key)
        return cache[key]
    for ptr in _pointers(root, mp, text) or []:
        if not ptr.exists:
            continue
        base, lost = _base(root, ptr, known)
        if lost:
            dangling.append(ptr)
        if base is None:
            unplaced.append(ptr)
            continue
        hunks = diff(base, ptr.path)
        if not hunks:
            continue
        now, via, why = _carry(hunks, ptr.lo, ptr.hi), "", ""
        proof = proofs.get(ptr.fid)
        if now is None and proof:
            why = "a change inside it postdates its proof @ %s" % proof
            if not (base.startswith(proof) or proof.startswith(base)) and git(
                    root, "merge-base", "--is-ancestor", base, proof)[0]:
                between, after = diff(base, ptr.path, proof), diff(proof, ptr.path)
                if between is not None and after is not None:
                    now = _carry(after, *_translate(between, ptr.lo, ptr.hi))
                    via = ", carried through its proof @ %s, which covers the " \
                          "change inside it" % proof
                else:
                    why = "git could not carry it through its proof @ %s" % proof
        elif now is None:
            why = "a change inside it, and no DRIVEN or TESTED proof names a " \
                  "commit that covers it"
        if now is None:
            best = _translate(hunks, ptr.lo, ptr.hi)
            if _ptr_text(ptr, best) != _ptr_text(ptr):
                declined.append(Move(ptr, base, "", best, why))
            continue
        # A one-line pointer prints only its start: carried to a region that
        # starts on its own line, it would be "moved" to the text it already
        # holds, forever - blame keeps naming the old commit (KiT, K92.1).
        if _ptr_text(ptr, now) != _ptr_text(ptr):
            moved.append(Move(ptr, base, via, now, ""))
    return moved, declined, dangling, unplaced


def _stamp(root, path, known):
    """HEAD's short sha while `path` is the same in HEAD and the working tree:
    HEAD's lines are then today's, and a range moved into them can say so.
    None while the file carries changes not in HEAD - today's lines are in no
    commit yet."""
    if path not in known:
        ok, sha = git(root, "rev-parse", "--short", "HEAD")
        known[path] = sha.strip() if ok and _hunks(root, "HEAD", path) == [] \
            else None
    return known[path]


def _rewrite(text, edits):
    """The map with each (line, start, end, replacement) applied - right to
    left within a line, so earlier spans keep their offsets; a CR is kept."""
    lines, by_line = text.split("\n"), {}
    for i, s, e, rep in edits:
        by_line.setdefault(i, []).append((s, e, rep))
    for i, reps in by_line.items():
        cr = "\r" if lines[i].endswith("\r") else ""
        ln = lines[i].rstrip("\r")
        for s, e, rep in sorted(reps, reverse=True):
            ln = ln[:s] + rep + ln[e:]
        lines[i] = ln + cr
    return "\n".join(lines)


def _say_dangling(dangling):
    for ptr in dangling:
        print("NOTE %s: %s @ %s names no commit this repository has - read by "
              "blame instead" % (ptr.fid, _ptr_text(ptr), ptr.stamp))


def _lines(start, n, empty):
    return empty % start if n == 0 else (
        "%d" % start if n == 1 else "%d-%d" % (start, start + n - 1))


def _touches(hunk, span, side=None):
    """A hunk touches the region on the side of the diff the region is
    numbered in - 0 the proof's commit, 1 the working tree - and on that side
    alone: read against the other side too, a range collides by number with
    code it is not (a static site, 2026-09-29). A pure addition or removal
    also touches the line it follows there, as its empty side does on the
    other. `side` None - the lines the range was written in are unknown - tries
    both sides."""
    if span is None:
        return True
    lo, hi = span
    a, b, c, d = hunk
    if side is None:
        return any(x <= hi and x + max(n, 1) - 1 >= lo
                   for x, n in ((a, b), (c, d)))
    x, n, other = (a, b, d) if side == 0 else (c, d, b)
    if n and not other:
        x, n = x - 1, n + 1
    return x <= hi and x + max(n, 1) - 1 >= lo


def cmd_reaim(root, mp):
    """Move each `code:` or `entry:` range whose lines moved to where they are
    now, stamped `@ <commit>` - the commit whose lines it is in - while its
    file is clean at HEAD. Only the numbers and that stamp change, and only
    where no change fell inside the range that its proof does not cover: that
    is a fact git measures, not a judgment, so it is the one edit this script
    makes to the authored half. A range it leaves is named, with where git
    reads it now and why it stays."""
    if not os.path.exists(mp):
        print("no %s - run --init first" % MAP_NAME)
        return 1
    text = read(mp)
    moved, declined, dangling, _ = _moved_pointers(root, mp, text)
    _say_dangling(dangling)
    if not moved and not declined:
        print("no code range has moved under its pointer")
        return 0
    edits, known, unstamped = [], {}, []
    for mv in moved:
        stamp = _stamp(root, mv.ptr.path, known)
        if not stamp and mv.ptr.path not in unstamped:
            unstamped.append(mv.ptr.path)
        edits.append((mv.ptr.line, mv.ptr.start, mv.ptr.end,
                      _ptr_text(mv.ptr, mv.now, write=True) + mv.ptr.tick
                      + (" @ %s" % stamp if stamp else "")))
        print("  " + _said(mv, mv.now))
    if moved:
        write(mp, _rewrite(text, edits))
    for mv in declined:
        print("  %s not moved: %s; re-drive it, then --reaim"
              % (_said(mv, mv.now), mv.reason))
    for path in unstamped:
        print("NOTE %s has changes not in HEAD, so the range(s) moved in it carry "
              "no `@ commit` and are read in today's lines - commit it with the "
              "map" % path)
    if moved:
        stamped = [s for s in known.values() if s]
        print("re-aimed %d code range(s); the proof on each still holds - the lines "
              "moved, and the code in them did not change after its proof%s"
              % (len(moved), ", each stamped `@ %s`, the commit whose lines it "
                 "is in" % stamped[0] if stamped and not unstamped else ""))
    if declined:
        print("%s%d range(s) left as written (named above): a change inside each "
              "is not covered by its proof - re-drive it, then --reaim, or set it "
              "by hand" % ("" if moved else "no code range was re-aimed; ",
                           len(declined)))
    return 0


def cmd_check(root, mp):
    if not os.path.exists(mp):
        print("FAIL no %s at %s - this project has no feature map, so nothing "
              "about it has been verified. Run --init." % (MAP_NAME, root))
        return 1
    text = read(mp)
    _, all_authored = parse_map(text)
    patterns = parse_patterns(all_authored)
    authored = dict((k, v) for k, v in all_authored.items()
                    if not k.startswith("pattern:"))
    feats, unparsed, nfiles, generated, unaddressed = derive(root)
    accepted = set()
    for f in authored.values():
        accepted.update(x.strip().strip("`") for x in
                        (f.get("unparsed_accepted", "").split(",")) if x.strip())

    problems = []

    # Unmapped capabilities ratchet exactly like anti-patterns do, and for the
    # same reason. An existing codebase adopts this with dozens unmapped; a check
    # that cannot go green until every one is authored does not get satisfied, it
    # gets switched off - and a disabled check is worse than a lenient one,
    # because it reports nothing at all. So: grandfather the count present at
    # adoption, and fail when it GROWS. New work must be mapped; the backlog is
    # paid down by lowering the ceiling, which `--ratchet` does automatically as
    # entries get authored.
    new = sorted(set(feats) - set(authored))
    unmapped_ceiling, loosen_unmapped = None, None
    for f in all_authored.values():
        if f.get("unmapped_ceiling", "").strip().isdigit():
            unmapped_ceiling = int(f["unmapped_ceiling"].strip())
            break
    if new and (unmapped_ceiling is None or len(new) > unmapped_ceiling):
        headroom = ("" if unmapped_ceiling is None else
                    " against a grandfathered ceiling of %d" % unmapped_ceiling)
        problems.append(
            "%d capability/capabilities exist in code with no authored entry%s - "
            "unmapped means unverified:\n" % (len(new), headroom)
            + "\n".join("    %s  [%s] (%s)" % (i, feats[i][4], feats[i][2])
                        for i in new)  # every one: a cut list reads as the whole
            + ("\n    Adopting this on an existing codebase? Record "
               "`- unmapped_ceiling: %d` on any authored entry to grandfather what "
               "is here now. New capabilities then fail while the backlog does not, "
               "and --ratchet lowers it as you author them." % len(new)
               if unmapped_ceiling is None else ""))
    elif unmapped_ceiling is not None and len(new) < unmapped_ceiling:
        loosen_unmapped = (len(new), unmapped_ceiling)

    # Every pointer, not the first path of the `code:` field alone: a bare
    # `BaseLayout.astro:138` in an entry named no file and passed for days
    # (a static site, 2026-09-30).
    ptrs = _scan_pointers(root, text)
    gone = []
    for fid, f in authored.items():
        code = f.get("code", "").split(":")[0].strip().strip("`")
        if code and not any(p.fid == fid and p.field == "code" for p in ptrs) \
                and not os.path.exists(os.path.join(root, code)):
            gone.append("%s -> %s" % (fid, code))
    for p in ptrs:
        if not p.exists:
            gone.append("%s -> %s (in its %s field)" % (p.fid, _ptr_text(p), p.field))
    if gone:
        problems.append(
            "%d authored pointer(s) name code that does not exist - no such file "
            "under the project (a bare name, a moved file, a typo), and a pointer "
            "no reader can follow verifies nothing:\n"
            % len(gone) + "\n".join("    " + g for g in gone))

    orphans = [(fid, _successor(fid, f, feats, set(authored)))
               for fid, f in sorted(authored.items())
               if fid.startswith(DERIVED_PREFIXES) and fid not in feats]
    if orphans:
        problems.append(
            "%d authored entry/entries name a capability the code no longer "
            "derives - renamed or removed. Rename the entry to its new id and move "
            "its proof folder under .verify/proof/ with it, or delete it. A "
            "feature mapped by hand belongs outside the derived prefixes (ui., "
            "setting.):\n" % len(orphans)
            + "\n".join("    %s -> now %s?" % (i, s) if s else
                        "    %s  (no likely successor found)" % i
                        for i, s in orphans))

    # The generated half is what a reader of the map sees. KiT's was four days
    # old - 20 capabilities where the code had 24, no UNPARSED list - under a
    # PASS, because this check derived afresh and never looked at it.
    def _norm(block):
        # The stamp and the file count say when and over what it was written,
        # not what the app is; the count also moved with each checkout until
        # 1.3.2, so comparing it would redden every older map for nothing.
        block = re.sub(r"(`featuremap\.py --write` at )[^\n]*? from \d+ file",
                       r"\1- from - file", block.replace("\r\n", "\n"))
        return "\n".join(x.rstrip() for x in block.strip().split("\n"))
    stored = _between(text.replace("\r\n", "\n"), D_BEGIN, D_END)
    fresh = derived_block(feats, unparsed, nfiles, "-", generated, unaddressed)
    # Masked above so it cannot fail, but still a claim the map makes: mk1made-
    # site's said 77 files over 93 and nothing said so.
    said = re.search(r"`featuremap\.py --write` at [^\n]*? from (\d+) file", stored)
    if said and int(said.group(1)) != nfiles:
        print("NOTE the map says %s file(s) and the code has %d now - --write "
              "refreshes it. A count, not a capability, so this is not a failure"
              % (said.group(1), nfiles))
    if _norm(stored) != _norm(fresh):
        ids = lambda b: set(re.findall(r"^\| `([^`]+)` \|", b, re.M))
        s_old, s_new = _norm(stored).split("\n"), _norm(fresh).split("\n")
        lacks, extra = sorted(ids(fresh) - ids(stored)), sorted(ids(stored) - ids(fresh))
        problems.append(
            "the DERIVED half of the map is stale - it is not what the code "
            "derives now, so a reader of the map sees an older app. Run --write "
            "(it touches only that half), then --check again:\n"
            + ("    in the code, missing from it: %s\n" % ", ".join(lacks) if lacks else "")
            + ("    in it, gone from the code: %s\n" % ", ".join(extra) if extra else "")
            + "    every line that differs (- in the map, + from the code):\n"
            + "\n".join("      %s %s" % (sign, x) for sign, lines, other in
                        (("-", s_old, s_new), ("+", s_new, s_old))
                        for x in lines if x not in other))

    # Every one, as with each list below: `unparsed_accepted` needs each name,
    # and a list that stops early reads as the whole of it.
    left = [(u, why) for u, why in unparsed if u not in accepted]
    if left:
        problems.append(
            "%d user-surface file(s) no extractor understood and no entry "
            "accepted:\n" % len(left)
            + "\n".join("    %s%s" % (u, "  (%s)" % why if why else "")
                        for u, why in left))

    bad = [(i, f.get("grade")) for i, f in authored.items()
           if f.get("grade") and f["grade"].strip().upper() not in GRADES]
    if bad:
        problems.append("%d entry/entries carry a grade that is not one of %s:\n"
                        % (len(bad), "/".join(GRADES))
                        + "\n".join("    %s: %r" % b for b in bad))

    # Stale proof: evidence older than the code it certifies is not evidence.
    # Measured per commit and per region. The `@ <commit>` in verified_at names
    # the code the proof was taken against, and only a change near the feature
    # stales it. By day and by file, a web app's single 15,500-line file staled every
    # web-ui entry on each round's commit, while a change made the same day as
    # its proof was not seen at all.
    ok_git, _ = git(root, "rev-parse", "--git-dir")
    stale, ungraded, by_region, by_day = [], [], 0, []
    # A region's numbers are in the lines of the commit stamped on it, else
    # the commit that last wrote its map line (git blame), so that is the side
    # of the diff it is held against. Where neither can say, both sides are
    # tried. Each `code:` pointer is a region of its own file - the field's
    # last numbers held against its first path put one file's range on
    # another's diff (a static site's region.primary, 2026-09-30).
    placed = (_pointers(root, mp, text) if ok_git else None) or []
    moved, declined, dangling, unplaced = _moved_pointers(root, mp, text) \
        if ok_git else ([], [], [], [])
    left = dict(((mv.ptr.line, mv.ptr.start), mv) for mv in declined)
    diffs, known = {}, {}

    def diff(*key):
        if key not in diffs:
            diffs[key] = _hunks(root, *key)
        return diffs[key]
    for fid, f in sorted(authored.items()):
        grade = (f.get("grade") or "UNKNOWN").strip().upper()
        if grade in ("UNKNOWN", "ASSERTED"):
            ungraded.append((fid, grade))
            continue
        code_field = f.get("code", "").strip().strip("`")
        code = code_field.split(":")[0].strip()
        when = f.get("verified_at", "").strip()
        if not code or not when:
            continue
        if not ok_git:
            continue
        sha = re.search(r"@\s*([0-9a-fA-F]{7,40})\b", when)
        regions = [(p, p.path, _span(p)) for p in placed
                   if p.fid == fid and p.field == "code" and p.exists] \
            or [(None, code, None)]
        hunks = {}
        if sha and git(root, "rev-parse", "--verify", "--quiet",
                       sha.group(1) + "^{commit}")[0]:
            hunks = dict((path, _hunks(root, sha.group(1), path))
                         for _, path, _ in regions)
        if hunks and all(h is not None for h in hunks.values()):
            by_region += 1
            for p, path, span in regions:
                mapped, side, w = span, None, None
                if span and p is not None:
                    w = _base(root, p, known)[0]
                    if w is None or diff(w, path) == []:
                        side = 1                    # today's lines
                    elif diff(w, path, sha.group(1)) is not None:
                        side = 0                    # carried into the proof's
                        mapped = _translate(diff(w, path, sha.group(1)), *span)
                hit = [h for h in hunks[path] if _touches(h, mapped, side)]
                if not hit:
                    continue
                # Both sides, each named: one side's numbers printed as the
                # other's put a change "inside" a region it was 10 lines away
                # from. The region says which side it is on.
                was = ", ".join(_lines(h[0], h[1], "after %d") for h in hit)
                now = ", ".join(_lines(h[2], h[3], "gone after %d") for h in hit)
                where = "%d-%d" % mapped if span else "(the whole file)"
                if side == 1:
                    where += " now"
                elif side == 0:
                    where += " at %s" % sha.group(1) + (
                        " (%d-%d as written @ %s)" % (span + (w[:7],))
                        if mapped != span else "")
                line = ("%s: verified @ %s, then %s changed at line(s) %s at %s "
                        "(%s now), touching its region %s"
                        % (fid, sha.group(1), path, was, sha.group(1), now, where))
                # The drift beside the stale proof, never instead of it: a
                # range that moved with a change inside stayed unsaid while its
                # proof was stale (a static site's ui.vista, 2026-09-30).
                mv = left.get((p.line, p.start)) if p is not None else None
                if mv:
                    line += ("; and it has moved: %s (written @ %s) -> %s, not "
                             "re-aimed until re-driven"
                             % (_ptr_text(p), mv.base[:7], _ptr_text(p, mv.now)))
                stale.append(line)
            continue
        by_day.append(fid)
        got, out = git(root, "log", "-1", "--format=%cI", "--", code)
        if not got or not out:
            continue
        cdate = out[:10]
        vdate = (re.search(r"\d{4}-\d{2}-\d{2}", when) or [None])
        vdate = vdate.group(0) if hasattr(vdate, "group") else None
        if vdate and cdate > vdate:
            stale.append("%s: verified %s, code changed %s - by day only: "
                         "verified_at names no commit this repository has"
                         % (fid, vdate, cdate))
    if stale:
        problems.append(
            "%d feature(s) carry proof OLDER than the code it certifies - the "
            "implementation moved after the evidence was taken, so the grade is "
            "UNKNOWN again until re-driven:\n" % len(stale)
            + "\n".join("    " + s for s in stale))

    # A pointer whose lines moved. From a static site, 2026-09-28: lines added
    # above three hand-mapped ranges left each naming other code - a script, a
    # section's close - while every check passed. Every entry, graded or not:
    # a pointer is a claim about where the code is, whatever its proof.
    if moved or declined:
        rows = [((mv.ptr.line, mv.ptr.start), "    %s: %s (written @ %s%s) -> %s"
                 % (mv.ptr.fid, _ptr_text(mv.ptr), mv.base[:7], mv.via,
                    _ptr_text(mv.ptr, mv.now))) for mv in moved]
        rows += [((mv.ptr.line, mv.ptr.start), "    %s: %s (written @ %s) -> %s NOT "
                  "re-aimed: %s - re-drive it, then --reaim, or set it by hand"
                  % (mv.ptr.fid, _ptr_text(mv.ptr), mv.base[:7],
                     _ptr_text(mv.ptr, mv.now), mv.reason)) for mv in declined]
        problems.append(
            "%d hand-mapped code range(s) name lines that have moved - code was "
            "added or removed above them after the pointer was written, so those "
            "numbers now hold other code. The code in a range --reaim can move "
            "did not change after its proof, so no proof is staled by that: run "
            "--reaim, or set each by hand. One marked NOT re-aimed has a change "
            "inside it that no proof covers, so --reaim leaves it:\n"
            % (len(moved) + len(declined))
            + "\n".join(row for _, row in sorted(rows)))
    _say_dangling(dangling)
    # A pointer neither committed nor stamped is read in today's lines: right
    # at the moment it is written, wrong once HEAD moves past commits touching
    # its file. --check cannot tell which, so the PASS says the bound.
    unplaced_bound = ""
    if unplaced:
        ok, last = git(root, "log", "-1", "--format=%h", "--", rel(root, mp))
        last, since, ahead = (last.strip() if ok else ""), {}, []
        for ptr in unplaced:
            if ptr.path not in since:
                ok, out = (git(root, "log", "--format=%h", "%s..HEAD" % last, "--",
                               ptr.path) if last else (False, ""))
                since[ptr.path] = len(out.split()) if ok else 0
            if since[ptr.path]:
                ahead.append("%s %s (%s, %d commit(s))"
                             % (ptr.fid, _ptr_text(ptr), ptr.path, since[ptr.path]))
        if ahead:
            unplaced_bound = (
                "%d pointer(s) not yet committed carry no `@ commit`, so their "
                "numbers are read in today's lines, though their file changed at "
                "commit(s) since the map's last commit (%s) - written before those, "
                "a move under them is not seen: --reaim stamps what it moves; stamp "
                "a hand-written one `path:N-M @ <commit>`, or commit the map soon "
                "after writing it: %s" % (len(ahead), last, "; ".join(ahead)))
            print("NOTE " + unplaced_bound)
    if by_day:
        print("NOTE %d proof(s) measured by day only - their verified_at names no "
              "commit this repository has, so a change on the day of the proof "
              "is not seen: %s" % (len(by_day), ", ".join(by_day)))
    if not ok_git:
        print("NOTE git unavailable or not a repository here - staleness of proof "
              "could NOT be measured, so a clean result below does not cover it")

    # The ratchet. An agent copies its nearest neighbour, so an anti-pattern
    # spreads by being present. Grandfather what exists, refuse what is added.
    src_files = [p for p in walk(root)
                 if not generated_reason(root, p, set())]
    loosen, tighten = [], []
    for pid, pat in sorted(patterns.items()):
        hits = pattern_hits(root, pat, src_files)
        if hits is None:
            problems.append(
                "pattern `%s` has an anti-pattern regex that does not compile, so it "
                "measured NOTHING. A rule that cannot run is not a rule in force:\n"
                "    %s" % (pid, pat.get("antipattern", "")))
            continue
        try:
            ceiling = int(pat.get("ceiling", "0"))
        except ValueError:
            ceiling = 0
        n = len(hits)
        if n > ceiling:
            new = hits[ceiling:] if ceiling else hits
            problems.append(
                "pattern `%s` SPREAD: %d occurrence(s) against a ceiling of %d.\n"
                "    rule: %s\n"
                "    copy this instead: %s\n"
                "    every occurrence, so you can see which are new:\n%s"
                % (pid, n, ceiling, pat.get("rule", "(no rule written)"),
                   pat.get("canonical", "(no canonical example named - write one, "
                           "or the right way is not the reachable way)"),
                   "\n".join("      %s:%d  %s" % h for h in hits)))
        elif n < ceiling:
            loosen.append((pid, n, ceiling))
        # The other direction: this pattern used where it was never designed to
        # go. Every occurrence looks correct on its own, which is why it needs a
        # machine to notice.
        out_of_scope = pattern_hits(root, pat, src_files, mode="spread")
        if out_of_scope is None:
            problems.append(
                "pattern `%s` has a `signature` regex that does not compile, so its "
                "scope was NOT measured:\n    %s" % (pid, pat.get("signature", "")))
        elif out_of_scope:
            problems.append(
                "pattern `%s` DRIFTED out of scope: %d use(s) outside `%s`.\n"
                "    This pattern was designed for that scope and nowhere else. Each "
                "of these looks correct in isolation, which is how it spread:\n%s"
                % (pid, len(out_of_scope), pat.get("only_in", ""),
                   "\n".join("      %s:%d  %s" % h for h in out_of_scope)))

        if pat.get("canonical"):
            cpath = pat["canonical"].split(":")[0].strip().strip("`")
            if cpath and not os.path.exists(os.path.join(root, cpath)):
                tighten.append((pid, cpath))
    if loosen or loosen_unmapped:
        print("ratchet can tighten - fewer occurrences than the recorded ceiling. "
              "Run --ratchet to lower it, or the headroom becomes room to regrow:")
        for pid, n, c in loosen:
            print("    %-36s %d now, ceiling %d" % (pid, n, c))
        if loosen_unmapped:
            print("    %-36s %d now, ceiling %d"
                  % ("(unmapped capabilities)", loosen_unmapped[0],
                     loosen_unmapped[1]))
    for pid, cpath in tighten:
        problems.append(
            "pattern `%s` points at a canonical example that no longer exists: %s\n"
            "    An agent told to copy a file that is gone will copy something else, "
            "and what it copies is whatever is nearest." % (pid, cpath))

    print("map: %d authored, %d derived (%s) from %d source file(s); %d build "
          "artifact(s) excluded by name"
          % (len(authored), len(feats), face_counts(feats), nfiles,
             len(generated)))
    if unaddressed:
        print("NOTE %d control(s) or region(s) carry a label computed at runtime "
              "and have no derived id, so nothing below covers them:"
              % len(unaddressed))
        for loc, note in unaddressed:
            print("    %s  %s" % (loc, note))
    if ungraded:
        counts = {}
        for _, g in ungraded:
            counts[g] = counts.get(g, 0) + 1
        print("unverified: " + ", ".join("%s %d" % (g, n)
                                         for g, n in sorted(counts.items()))
              + " - listed by name, never rounded into a percentage:")
        # Every one. The list is bounded by what people authored, and a cap
        # here cut five of KiT's 45 without a word.
        for fid, g in ungraded:
            print("    %-40s %s" % (fid, g))
    if problems:
        print("\nFAIL %d problem class(es):\n" % len(problems))
        for p in problems:
            print("  - " + p + "\n")
        return 1
    # A file accepted by hand was not parsed, and the PASS says so by name:
    # KiT's whole Windows app would otherwise sit under "every file parsed".
    by_hand = [u for u, _ in unparsed if u in accepted]
    bounds = ["%d element(s) with a runtime-only label are not covered (listed "
              "above)" % len(unaddressed)] if unaddressed else []
    if by_hand:
        bounds.append("%d surface file(s) are mapped by hand, not parsed "
                      "(unparsed_accepted): %s" % (len(by_hand), ", ".join(by_hand)))
    if unplaced_bound:
        bounds.append(unplaced_bound)
    print("PASS no drift, no stale proof, "
          + ("every surface file parsed or accepted" if by_hand
             else "every surface file parsed")
          + (" - bound: " + "; ".join(bounds) if bounds else ""))
    return 0


def _new_proof(d, stamp, commit, body):
    """Write one capture under a name of its own and return the name. The name
    is taken to the second, and two captures inside one second shared it: the
    later one silently replaced the earlier (the pack's reviewer, 2026-09-30).
    The file is created exclusively, so a same-second sibling - or a parallel
    run - gets ~2, ~3, ... after the commit, which still sorts after it."""
    if not os.path.isdir(d):
        os.makedirs(d)
    n = 1
    while True:
        name = "%s-%s%s.json" % (stamp, commit, "" if n == 1 else "~%d" % n)
        try:
            fd = os.open(os.path.join(d, name), os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, "O_BINARY", 0))
        except FileExistsError:
            n += 1
            continue
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(body)
        return name


def _say_verified_at(root, fid, commit):
    """The map line a passing capture asks for. A work label (K82.1) where the
    commit belongs is read by day and by whole file: any change to the file on
    a later day stales it, one later that day is missed (KiT, 2026-09-30)."""
    want = "%s @ %s" % (datetime.date.today(), commit)
    mp = os.path.join(root, MAP_NAME)
    have = parse_map(read(mp))[1].get(fid, {}).get("verified_at", "").strip() \
        if os.path.exists(mp) else ""
    if have == want:
        return
    sha = re.search(r"@\s*([0-9a-fA-F]{7,40})\b", have)
    if have and not (sha and git(root, "rev-parse", "--verify", "--quiet",
                                 sha.group(1) + "^{commit}")[0]):
        print("WARN %s's verified_at (%s) names no commit, so --check reads it by "
              "day only and over the whole file - a change later that day is "
              "missed, any change on a later day stales it" % (fid, have))
    print("map: set %s's verified_at to `%s` (this capture's commit)" % (fid, want))


def cmd_record(root, args):
    if not args.feature or not args.grade or not args.result:
        print("--record needs --feature, --grade and --result")
        return 1
    if args.grade.upper() not in GRADES:
        print("grade must be one of %s" % "/".join(GRADES))
        return 1
    if args.grade.upper() in ("DRIVEN", "TESTED") and not args.observable:
        print("a %s grade without --observable is an opinion, not a capture - "
              "name what you read back" % args.grade.upper())
        return 1
    metrics = {}
    for kv in (args.metric or []):
        k, _, v = kv.partition("=")
        try:
            metrics[k.strip()] = float(v) if "." in v else int(v)
        except ValueError:
            metrics[k.strip()] = v.strip()
    ok_git, commit = git(root, "rev-parse", "--short", "HEAD")
    now = datetime.datetime.now(datetime.timezone.utc)
    rec = {
        "feature": args.feature,
        "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": commit if ok_git else "unknown",
        "grade": args.grade.upper(),
        "how": args.how or "",
        "observable": args.observable or "",
        "result": args.result,
        "bound": args.bound or "",
        "metrics": metrics,
        "artifacts": args.artifact or [],
        "conditions": args.conditions or "",
    }
    if rec["grade"] in ("DRIVEN", "TESTED") and rec["result"] == "pass":
        rec["judged"] = _judge_record(root, args.feature, rec["observable"])
    d = os.path.join(root, STORE, "proof", args.feature)
    latest = os.path.join(d, "latest.json")
    prev = None
    if os.path.exists(latest):
        try:
            prev = json.loads(read(latest))
        except ValueError:
            prev = None
    body = json.dumps(rec, indent=2, sort_keys=True) + "\n"
    name = _new_proof(d, now.strftime("%Y%m%dT%H%M%SZ"), rec["commit"], body)
    write(latest, body)
    print("recorded %s" % rel(root, os.path.join(d, name)))
    if ok_git and rec["grade"] in ("DRIVEN", "TESTED") and rec["result"] == "pass":
        _say_verified_at(root, args.feature, commit)

    if not prev:
        print("first capture for this feature - nothing to compare yet")
        return 0
    print("analysis against %s (%s):" % (prev.get("at"), prev.get("commit")))
    if prev.get("result") != rec["result"]:
        print("  RESULT %s -> %s%s" % (prev.get("result"), rec["result"],
              "   <-- REGRESSION, do not report this as working"
              if rec["result"] != "pass" else "   (fixed)"))
    else:
        print("  result unchanged: %s" % rec["result"])
    for k in sorted(set(metrics) | set(prev.get("metrics") or {})):
        a, b = (prev.get("metrics") or {}).get(k), metrics.get(k)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            delta = b - a
            pct = (" %+.0f%%" % (100.0 * delta / a)) if a else ""
            flag = "   <-- worth a look" if (a and abs(delta) / max(a, 1) > 0.25) \
                else ""
            print("  %-18s %s -> %s (%+g%s)%s" % (k, a, b, delta, pct, flag))
        else:
            print("  %-18s %s -> %s" % (k, a, b))
    pb, nb = (prev.get("bound") or ""), (rec["bound"] or "")
    if pb and nb and len(nb) < len(pb) * 0.6:
        print("  BOUND SHRANK - this run covered materially less than the last "
              "one while holding the same grade")
    return 0


def cmd_ratchet(root, mp):
    """Lower every ceiling to the count actually present. NEVER raises one.

    This is the single narrow exception to `no script writes the authored half`,
    and it is safe in exactly one direction: tightening a rule cannot make the
    map claim more safety than reality, while loosening one can. Raising a
    ceiling stays a human edit with a reason attached, because that is a
    decision to tolerate something, and a tolerance nobody argued for is how a
    rule dies quietly."""
    if not os.path.exists(mp):
        print("no %s - run --init first" % MAP_NAME)
        return 1
    text = read(mp)
    _, all_authored = parse_map(text)
    patterns = parse_patterns(all_authored)
    feats, _, _, generated, _ = derive(root)
    src = [p for p in walk(root) if not generated_reason(root, p, set())]
    changed, blocked = [], []

    # The unmapped-capability ceiling tightens the same way, so authoring an
    # entry permanently lowers the bar rather than just buying slack.
    authored_feats = set(k for k in all_authored if not k.startswith("pattern:"))
    n_unmapped = len(set(feats) - authored_feats)
    m = re.search(r"^-\s*unmapped_ceiling\s*:\s*(\d+)\s*$", text, re.M)
    if m:
        cur = int(m.group(1))
        if n_unmapped > cur:
            blocked.append(("(unmapped capabilities)",
                            "%d unmapped against a ceiling of %d - author them, or "
                            "raise it by hand with a reason" % (n_unmapped, cur)))
        elif n_unmapped < cur:
            text = text[:m.start()] + "- unmapped_ceiling: %d" % n_unmapped \
                + text[m.end():]
            changed.append(("(unmapped capabilities)", cur, n_unmapped))

    if not patterns and not m:
        print("no patterns and no unmapped ceiling declared - nothing to ratchet")
        return 0
    for pid, pat in sorted(patterns.items()):
        hits = pattern_hits(root, pat, src)
        if hits is None:
            blocked.append((pid, "anti-pattern regex does not compile"))
            continue
        try:
            ceiling = int(pat.get("ceiling", "0"))
        except ValueError:
            ceiling = 0
        n = len(hits)
        if n > ceiling:
            blocked.append((pid, "%d occurrence(s) against a ceiling of %d - fix "
                            "the code, or raise the ceiling by hand with a reason"
                            % (n, ceiling)))
        elif n < ceiling:
            # Rewrite this pattern's ceiling line and nothing else in the file.
            head = re.compile(r"(^###\s+`?pattern:\s*%s`?\s*$)" % re.escape(pid),
                              re.M | re.I)
            m = head.search(text)
            if not m:
                blocked.append((pid, "could not locate its section to edit"))
                continue
            seg_start = m.end()
            nxt = re.search(r"^###\s+", text[seg_start:], re.M)
            seg_end = seg_start + (nxt.start() if nxt else len(text) - seg_start)
            seg = text[seg_start:seg_end]
            new_seg, cnt = re.subn(r"^-\s*ceiling\s*:.*$",
                                   "- ceiling: %d" % n, seg, count=1, flags=re.M)
            if not cnt:
                blocked.append((pid, "has no `- ceiling:` line to lower"))
                continue
            text = text[:seg_start] + new_seg + text[seg_end:]
            changed.append((pid, ceiling, n))
    if changed:
        write(mp, text)
    for pid, was, now in changed:
        print("tightened %-34s %d -> %d" % (pid, was, now))
    for pid, why in blocked:
        print("NOT changed %-31s %s" % (pid, why))
    if not changed and not blocked:
        print("every ceiling already equals the count present - nothing to do")
    return 1 if blocked else 0


def cmd_init(root, mp):
    if os.path.exists(mp):
        print("%s already exists - refusing to overwrite a map that may carry "
              "authored judgment" % MAP_NAME)
        return 1
    here = os.path.dirname(os.path.abspath(__file__))
    tpl = os.path.join(here, "..", "templates", MAP_NAME)
    text = read(tpl)
    if not text:
        print("template missing at %s" % tpl)
        return 1
    name = os.path.basename(os.path.abspath(root))
    text = text.replace("{{PROJECT}}", name).replace(
        "{{CREATED}}", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    write(mp, text)
    for sub in ("proof", "artifacts"):
        d = os.path.join(root, STORE, sub)
        if not os.path.isdir(d):
            os.makedirs(d)
    print("created %s and %s/" % (MAP_NAME, STORE))
    return cmd_write(root, mp)


# ------------------------------------------------ any branch, any commit
# The requirement, 2026-09-23: map it retroactively and as live, and across any
# branches that exist, for comparison's sake. A ref is read out
# of git into a temporary folder - never checked out, so the working tree, the
# index and whatever another session has open stay untouched - and measured with
# THIS extractor, so two refs differ only where their code differs.

class RefError(Exception):
    pass


def materialize(root, ref):
    """(temp_dir, project_dir_inside_it, short_sha, date) for this project as
    it stood at `ref`. The caller removes temp_dir."""
    import tarfile
    import tempfile
    if not git(root, "rev-parse", "--git-dir")[0]:
        raise RefError("not a git repository, so there is no history to read")
    ok, sha = git(root, "rev-parse", "--verify", "--quiet", ref + "^{commit}")
    if not ok or not sha:
        raise RefError("no such commit, branch or tag here: %s" % ref)
    top = _toplevel(root)
    prefix = rel(top, root)
    prefix = "" if prefix == "." else prefix
    paths = [prefix or "."]
    if prefix:
        # The repository's own deploy files govern a project that is a folder
        # inside it, so they come along (one web app's render.yaml, at the top).
        ok, names = git(top, "ls-tree", "--name-only", sha, "--", "render.yaml",
                        "Procfile", "Dockerfile", ".github")
        paths += [n for n in names.split("\n") if n.strip()] if ok else []
    tmp = tempfile.mkdtemp(prefix="verafox-ref-")
    tar = os.path.join(tmp, ".ref.tar")
    try:
        p = subprocess.run(["git", "archive", "--format=tar", "-o", tar, sha, "--"]
                           + paths, cwd=top, capture_output=True, timeout=300)
        if p.returncode != 0:
            raise RefError("git archive failed: %s"
                           % p.stderr.decode("utf-8", "replace").strip()[:200])
        with tarfile.open(tar) as tf:
            if hasattr(tarfile, "data_filter"):
                tf.extractall(tmp, filter="data")
            else:
                tf.extractall(tmp, members=[
                    m for m in tf.getmembers() if m.isfile() or m.isdir()
                    if not m.name.startswith("/") and ".." not in m.name.split("/")])
        os.remove(tar)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    # git archive leaves out what .gitattributes marks export-ignore, and a
    # submodule's contents. Measured 2026-09-23: a route in such a file vanished
    # from --ref without a word. Unmeasured is said by name, never implied.
    ok, listed = git(top, "ls-tree", "-r", "-z", "--name-only", sha, "--", *paths)
    gone = [n for n in (listed.split("\0") if ok else []) if n.strip()
            and not os.path.lexists(os.path.join(tmp, n.replace("/", os.sep)))]
    if gone:
        sys.stderr.write("NOTE %d file(s) in %s were not exported by git archive "
                         "(export-ignore, or a submodule) and are not measured: %s%s\n"
                         % (len(gone), ref, ", ".join(gone[:8]),
                            " ..." if len(gone) > 8 else ""))
    tree = os.path.join(tmp, prefix) if prefix else tmp
    _TOP[os.path.normcase(os.path.abspath(tree))] = tmp
    ok, date = git(root, "log", "-1", "--format=%cI", sha)
    return tmp, tree, sha[:10], (date[:16].replace("T", " ") if ok else "")


def snapshot(root, ref=None):
    """The derived capabilities and the authored entries of the working tree
    (ref None) or of a ref."""
    if not ref:
        mp = os.path.join(root, MAP_NAME)
        ok, sha = git(root, "rev-parse", "--short=10", "HEAD")
        return {"label": "working tree", "sha": sha if ok else "", "date": "",
                "feats": derive(root)[0],
                "authored": parse_map(read(mp))[1] if os.path.exists(mp) else {}}
    tmp, tree, sha, date = materialize(root, ref)
    try:
        mp = os.path.join(tree, MAP_NAME)
        feats = derive(tree)[0]
        authored = parse_map(read(mp))[1] if os.path.exists(mp) else {}
    finally:
        _TOP.pop(os.path.normcase(os.path.abspath(tree)), None)
        shutil.rmtree(tmp, ignore_errors=True)
    return {"label": ref, "sha": sha, "date": date, "feats": feats,
            "authored": authored}


_FACE_ORDER = {"user": 0, "dev": 1}
_FACES = ("user", "dev", "unclassified")


def _authored_face(value):
    """The face an author wrote - user, dev or unclassified, its reason allowed
    after a dash or in brackets - or None. Anything else is not a face: the
    template's hint line (`user · dev — only to overrule ...`) was taken as
    written and --list printed it as a bucket (the pack's reviewer, 2026-09-30)."""
    v = re.split(r"\s+[-–—]+\s+|\s*[(:]", (value or "").strip().lower(), 1)[0].strip()
    return v if v in _FACES else None


def entries(snap):
    """Every capability with its face and its evidence grade - derived ones,
    and the ones only a person mapped (ui., setting.). An authored `face:`
    wins over the measured one: it is a judgment the code cannot make."""
    rows, authored = [], dict((k, v) for k, v in snap["authored"].items()
                              if not k.startswith("pattern:"))
    for fid in sorted(set(snap["feats"]) | set(authored)):
        a = authored.get(fid, {})
        if fid in snap["feats"]:
            _, surface, code, note, face = snap["feats"][fid]
        else:
            surface, code = a.get("surface", ""), a.get("code", "").strip("`")
            note, face = "mapped by hand", "unclassified"
        rows.append({"id": fid, "face": _authored_face(a.get("face")) or face,
                     "surface": surface, "code": code, "note": note,
                     "grade": (a.get("grade") or "").strip().upper() or None})
    rows.sort(key=lambda r: (_FACE_ORDER.get(r["face"], 2), r["id"]))
    return rows


def _counts(rows):
    n = {}
    for r in rows:
        n[r["face"]] = n.get(r["face"], 0) + 1
    return n


def _label(snap):
    bits = [x for x in (snap["sha"], snap["date"]) if x]
    return snap["label"] + (" (%s)" % ", ".join(bits) if bits else "")


def cmd_list(root, ref, face, as_json):
    try:
        snap = snapshot(root, ref)
    except RefError as e:
        print("REFUSED %s" % e)
        return 2
    rows = [r for r in entries(snap) if not face or r["face"] == face]
    counts = _counts(rows)
    if as_json:
        print(json.dumps({"ref": snap["label"], "commit": snap["sha"],
                          "date": snap["date"], "counts": counts,
                          "capabilities": rows}, indent=2, sort_keys=True))
        return 0
    print("%s: %d capability/capabilities - %s" % (
        _label(snap), len(rows), ", ".join(
            "%s %d" % (k, counts[k]) for k in sorted(counts, key=lambda k:
                                                     (_FACE_ORDER.get(k, 2), k)))
        or "none"))
    for r in rows:
        print("  %-12s %-40s %-9s %s  %s" % (r["face"], r["id"],
                                            r["grade"] or "unmapped", r["code"],
                                            r["note"][:100]))
    return 0


def cmd_compare(root, refs, as_json):
    if len(refs) > 2:
        print("REFUSED --compare takes one ref (against the working tree) or two")
        return 2
    try:
        a = snapshot(root, refs[0])
        b = snapshot(root, refs[1] if len(refs) > 1 else None)
    except RefError as e:
        print("REFUSED %s" % e)
        return 2
    fa, fb = a["feats"], b["feats"]
    added, removed = sorted(set(fb) - set(fa)), sorted(set(fa) - set(fb))
    changed, moved = [], []
    for i in sorted(set(fa) & set(fb)):
        x, y = fa[i], fb[i]
        if x[4] != y[4]:
            changed.append((i, "face %s -> %s" % (x[4], y[4])))
        if x[1] != y[1]:
            changed.append((i, "surface %s -> %s" % (x[1], y[1])))
        if x[2].rsplit(":", 1)[0] != y[2].rsplit(":", 1)[0]:
            moved.append((i, x[2], y[2]))
    aa = dict((k, v) for k, v in a["authored"].items() if not k.startswith("pattern:"))
    ab = dict((k, v) for k, v in b["authored"].items() if not k.startswith("pattern:"))
    a_added, a_removed = sorted(set(ab) - set(aa)), sorted(set(aa) - set(ab))
    regraded = [(i, (aa[i].get("grade") or "none").upper(),
                 (ab[i].get("grade") or "none").upper())
                for i in sorted(set(aa) & set(ab))
                if (aa[i].get("grade") or "").upper() != (ab[i].get("grade") or "").upper()]
    faces = {}
    for i in added:
        faces.setdefault(fb[i][4], [0, 0])[0] += 1
    for i in removed:
        faces.setdefault(fa[i][4], [0, 0])[1] += 1
    if as_json:
        print(json.dumps({
            "from": {"ref": a["label"], "commit": a["sha"], "date": a["date"]},
            "to": {"ref": b["label"], "commit": b["sha"], "date": b["date"]},
            "added": [dict(zip(("id", "surface", "code", "note", "face"),
                               (i,) + fb[i][1:])) for i in added],
            "removed": [dict(zip(("id", "surface", "code", "note", "face"),
                                 (i,) + fa[i][1:])) for i in removed],
            "changed": [{"id": i, "what": w} for i, w in changed],
            "moved": [{"id": i, "from": x, "to": y} for i, x, y in moved],
            "authored_added": a_added, "authored_removed": a_removed,
            "regraded": [{"id": i, "from": x, "to": y} for i, x, y in regraded]},
            indent=2, sort_keys=True))
        return 0
    print("compare %s -> %s" % (_label(a), _label(b)))
    print("derived: %d -> %d capabilities; +%d added, -%d removed, %d changed, "
          "%d moved to another file" % (len(fa), len(fb), len(added), len(removed),
                                        len(changed), len(moved)))
    for i in added:
        print("  + %-40s [%s] %s  %s" % (i, fb[i][4], fb[i][2], fb[i][3][:90]))
    for i in removed:
        print("  - %-40s [%s] %s" % (i, fa[i][4], fa[i][2]))
    for i, w in changed:
        print("  ~ %-40s %s" % (i, w))
    for i, x, y in moved:
        print("  > %-40s %s -> %s" % (i, x, y))
    print("authored: %d -> %d entries; +%d added, -%d removed, %d regraded"
          % (len(aa), len(ab), len(a_added), len(a_removed), len(regraded)))
    for i in a_added:
        print("  + %-40s %s" % (i, (ab[i].get("grade") or "no grade").upper()))
    for i in a_removed:
        print("  - %s" % i)
    for i, x, y in regraded:
        print("  ~ %-40s grade %s -> %s" % (i, x, y))
    if faces:
        print("by face (added/removed): " + ", ".join(
            "%s +%d/-%d" % (k, v[0], v[1]) for k, v in sorted(
                faces.items(), key=lambda kv: (_FACE_ORDER.get(kv[0], 2), kv[0]))))
    return 0


# ------------------------------------------------------------- what is live
# "Reflective of live": the branch that deploys is not proof of what is
# deployed - a build can fail, a deploy can be paused, a host can serve an old
# instance. So production is asked, and it is asked narrowly: GET only, only the
# paths an authored entry declares, redirects reported and never followed.
# What it serves is then placed in git: a file served verbatim (a compiled
# bundle) hashes to exactly one blob, and the commits that carry that blob say
# which code production is running.

LIVE_FIELDS = ("url", "fingerprint", "probes", "branch")
_URL_PATH = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*(?:\?[^\s#]*)?$")


def _fetched(root, ref):
    """When `ref`, a remote-tracking branch, was last fetched here - the answer
    is only as current as that."""
    if not ref.startswith("origin/"):
        return ""
    # A worktree keeps its own FETCH_HEAD. Reading only the shared one called a
    # fetch made minutes earlier in one web app's worktree twelve days old.
    stamps = []
    for flag in ("--git-dir", "--git-common-dir"):
        ok, d = git(root, "rev-parse", flag)
        p = os.path.join(root, d, "FETCH_HEAD") if ok and d else ""
        if p and os.path.exists(p):
            stamps.append(os.path.getmtime(p))
    if not stamps:
        return "never"
    return datetime.datetime.fromtimestamp(max(stamps)).strftime("%Y-%m-%d %H:%M")


def _get(url, limit):
    """(status, body_or_None, ms, location). GET only, no cookies, no
    redirects, at most `limit` bytes kept."""
    import time
    import urllib.error
    import urllib.parse
    import urllib.request

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None                   # report the 3xx, never follow it
    handlers = [NoRedirect()]
    if urllib.parse.urlsplit(url).hostname in ("127.0.0.1", "localhost", "::1"):
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, method="GET",
                                 headers={"User-Agent": "verafox-live"})
    t0 = time.time()
    try:
        with opener.open(req, timeout=30) as resp:
            body = resp.read(limit)
            return resp.status, body, int((time.time() - t0) * 1000), ""
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location", "") if e.headers else ""
        return e.code, None, int((time.time() - t0) * 1000), loc
    except Exception as e:
        # Any failure to fetch is a reading, never a traceback: the first run
        # against one web app's production crashed on a path the shell had rewritten.
        return None, None, int((time.time() - t0) * 1000), str(
            getattr(e, "reason", e))[:120]


def _blob(body):
    import hashlib
    return hashlib.sha1(b"blob %d\0" % len(body) + body).hexdigest()


def _versions(root, branch, path):
    """[(sha, blob)] newest first: each commit on `branch` that changed `path`,
    with the blob it left there - one git call, however long the history."""
    ok, out = git(root, "log", branch, "--format=%H", "--raw", "--no-abbrev",
                  "--no-renames", "--", path)
    if not ok:
        return None
    found, sha = [], None
    for line in out.split("\n"):
        if re.match(r"^[0-9a-f]{40}$", line.strip()):
            sha = line.strip()
        elif line.startswith(":") and sha:
            parts = line.split()
            if len(parts) >= 4:
                found.append((sha, parts[3]))
    return found


def live_targets(root, authored, args):
    """[(name, fields)] - from the command line when --url is given, else every
    authored entry that declares a `url:`."""
    if args.url:
        return [("command line", {"url": args.url,
                                  "fingerprint": args.fingerprint or "",
                                  "probes": ",".join(args.probe or []),
                                  "branch": args.branch or ""})]
    return [(fid, f) for fid, f in sorted(authored.items())
            if f.get("url", "").strip()]


def cmd_live(root, mp, args):
    authored = parse_map(read(mp))[1] if os.path.exists(mp) else {}
    targets = live_targets(root, authored, args)
    if not targets:
        print("REFUSED nothing declares a live environment. Add to one authored "
              "entry (a deploy.* one, or live.<name>):\n"
              "    - url: https://your.site\n"
              "    - fingerprint: static/app.js   (a file served exactly as "
              "committed)\n"
              "    - probes: /health               (safe GET paths only)\n"
              "or pass --url, --fingerprint and --probe.")
        return 2
    bad = 0
    for name, f in targets:
        base = f.get("url", "").strip().rstrip("/")
        if not re.match(r"^https?://[^/\s]+$", base):
            print("REFUSED %s: url must be http(s)://host with no path, got %r"
                  % (name, base))
            bad += 1
            continue
        print("live %s  %s" % (name, base))
        for path in [x.strip() for x in f.get("probes", "").split(",") if x.strip()]:
            if not _URL_PATH.match(path):
                # Git Bash turns `/health` into `C:/Program Files/Git/health`
                # before Python sees it. Declare probes in the map, or set
                # MSYS_NO_PATHCONV=1, and a rewritten path is refused here.
                print("  REFUSED probe %r - not a URL path" % path)
                bad += 1
                continue
            status, _, ms, loc = _get(base + path, 65536)
            if status is None:
                print("  GET %-28s FAILED (%s, %d ms)" % (path, loc, ms))
                bad += 1
            elif status >= 400:
                print("  GET %-28s %d (%d ms)" % (path, status, ms))
                bad += 1
            else:
                print("  GET %-28s %d (%d ms)%s" % (
                    path, status, ms, ("  -> redirect to %s, not followed" % loc)
                    if 300 <= status < 400 else ""))
        fp = f.get("fingerprint", "").strip().strip("`").lstrip("/")
        if not fp:
            print("  no fingerprint declared, so which commit is live was NOT "
                  "measured")
            continue
        status, body, ms, loc = _get(base + "/" + fp, 64 * 1024 * 1024)
        if status != 200 or body is None:
            print("  GET /%-27s %s - the fingerprint could not be read, so which "
                  "commit is live was NOT measured" % (fp, status or loc))
            bad += 1
            continue
        blob = _blob(body)
        print("  GET /%-27s 200 (%d ms, %d bytes) blob %s" % (fp, ms, len(body),
                                                             blob[:12]))
        branch = f.get("branch", "").strip() or _deploy_branch(root) or "main"
        ref = ("origin/" + branch) if git(root, "rev-parse", "--verify", "--quiet",
                                          "origin/" + branch)[0] else branch
        when = _fetched(root, ref)
        if when:
            print("  %s as last fetched here, %s - fetch first for a current "
                  "answer" % (ref, when))
        # A static site serves public/licenses/X.txt at /licenses/X.txt (Astro,
        # Vite, Next; mk1made.us). `root` names that folder; undeclared, the
        # usual ones are tried, and a match is by content, so it cannot mislead.
        served = f.get("root", "").strip().strip("`").strip("/")
        cands = ([served + "/" + fp] if served
                 else [fp] + [d + "/" + fp for d in ("public", "static")])
        versions, hit, path = None, [], cands[0]
        for c in cands:
            v = _versions(root, ref, c)
            if v is None:
                break
            h = [i for i, (_, b) in enumerate(v) if b == blob]
            if versions is None or h:
                versions, hit, path = v, h, c
            if h:
                break
        if versions is None:
            print("  deploy branch %s is not in this repository - NOT measured"
                  % ref)
            bad += 1
            continue
        if not hit:
            print("  production serves a version of %s that no commit on %s "
                  "carries (looked for it as %s) - built differently, deployed "
                  "from elsewhere, or not fetched here. Which code is live is "
                  "UNKNOWN." % (fp, ref, ", ".join(cands)))
            bad += 1
            continue
        if path != fp:
            print("  /%s is served from %s in the repository (%s)"
                  % (fp, path, "declared root" if served else
                     "found by content; declare `root: %s` to say so"
                     % path.split("/")[0]))
        fp = path
        i = hit[0]
        since, date = versions[i][0], git(root, "log", "-1", "--format=%cI",
                                          versions[i][0])[1][:16].replace("T", " ")
        if i == 0:
            upper = ref
            print("  production serves %s as %s last changed it, at %s (%s): live "
                  "is at or after that commit, at most %s" % (fp, ref, since[:10],
                                                              date, ref))
            if len(hit) > 1:
                print("  (the same version of %s also stood at %s, earlier - the "
                      "served file cannot tell those apart)"
                      % (fp, versions[hit[1]][0][:10]))
        else:
            nxt = versions[i - 1][0]
            upper = nxt + "^"
            ok, behind = git(root, "rev-list", "--count", nxt + "^.." + ref)
            print("  production is BEHIND %s: it serves %s as of %s (%s), and %s "
                  "has changed that file %d time(s) since, first at %s - so %s "
                  "commit(s) on %s, from %s on, are certainly not live."
                  % (ref, fp, since[:10], date, ref, i, nxt[:10],
                     behind if ok else "?", ref, nxt[:10]))
        print("  what the working tree has that production cannot - newer than "
              "%s:" % upper)
        cmd_compare(root, [upper], False)
    return 1 if bad else 0


# ------------------------------------------------------------ judged by Jev
# The Intended bar - does the evidence speak to what the operator actually asked
# for - is the one no test suite checks, because the suite was written from the
# same reading. Two short texts and one yes/no is a bounded judgment, which is
# what Jev is for: it decides, this code computes, and every rule it must not be
# asked to break is enforced in jev.py rather than remembered here. The gate is
# code's. Until its two numbers are validated on the operator's own entries a judgment is
# a reading to look at - never a failure.
JUDGE_LOW, JUDGE_HIGH = 0.30, 0.70       # unvalidated: reference/jev-calibration.md


def _jev_client():
    """(module, path) of the levjev skill's client, installed beside this skill -
    its own skill since 2026-09-24 and LevJev since 2026-09-29, the one home for
    all Jev integration, so every caller asks Jev one way. The module is None
    when that skill is not there, and --judge then asks nothing."""
    path = os.path.normpath(os.path.join(
        os.path.dirname(os.path.realpath(__file__)), os.pardir, os.pardir, "levjev",
        "scripts", "jev.py"))
    if not os.path.exists(path):
        return None, path
    import importlib.util
    spec = importlib.util.spec_from_file_location("jev", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, path


# Two identical requests moved 73 of 316 readings by up to this much
# (a static site, 2026-09-29): one reading is one sample, so a reading this close
# to a threshold could land on its other side next time.
JUDGE_SPREAD = 0.08


def _intent_question(intent, observable):
    return {"type": "noul",
            "instructions": {
                "intent": intent, "observable": observable,
                "question": "Would reading back `observable` show whether "
                            "`intent` was achieved?"},
            "criteria": {
                "true": "Reading it back shows whether the intent was met",
                "false": "It could read back as expected while the intent "
                         "is unmet"}}


def _judge_record(root, feature, observable):
    """Jev's reading of one proof as it is recorded: does the observable just
    captured show the entry's intent? One request; printed and kept with the
    proof as a reading, never a gate. On 2026-09-29 Jev was asked at most four
    times a day, because --judge ran only when someone thought to run it."""
    entry = parse_map(read(os.path.join(root, MAP_NAME)))[1].get(feature) or {}
    if not entry.get("intent"):
        print("  not judged: %s carries no intent: in the map, so there is nothing "
              "to hold the observable against" % feature)
        return {"not_judged": "no intent"}
    jev, where = _jev_client()
    if jev is None:
        print("  NOT JUDGED the levjev skill is not installed beside this one")
        return {"not_judged": "no levjev skill"}
    q = _intent_question(entry["intent"], observable)
    problems = jev.lint({feature: q})
    if problems:
        print("  not judged: %s" % problems[0].split(": ", 1)[-1])
        return {"not_judged": problems[0]}
    try:
        r = jev.ask("One recorded proof of a feature of %s, held against the "
                    "intent it was built for." % os.path.basename(root),
                    {feature: q})
    except (jev.Refused, jev.Unavailable) as e:
        print("  NOT JUDGED %s - the proof is recorded; Jev's reading is not" % e)
        return {"not_judged": str(e)}
    p = r["answers"][feature]["noul"]
    near = min(abs(p - JUDGE_LOW), abs(p - JUDGE_HIGH)) < JUDGE_SPREAD
    print("  judge: %.2f - %s%s. A reading, never a gate: its thresholds are not "
          "yet validated on the operator's entries (reference/jev-calibration.md)"
          % (p, "the observable may NOT show the intent" if p < JUDGE_LOW else
             "torn - read the intent and the observable yourself" if p < JUDGE_HIGH
             else "shows the intent",
             "; within %.2f of a threshold, and one reading is one sample"
             % JUDGE_SPREAD if near else ""))
    return {"noul": p, "model": r["model"], "question": q["instructions"]["question"],
            "intent": entry["intent"]}


def cmd_judge(root, mp, feature):
    if not os.path.exists(mp):
        print("no %s - run --init first" % MAP_NAME)
        return 1
    jev, where = _jev_client()
    if jev is None:
        print("NOT JUDGED the levjev skill is not installed beside this one (no %s) "
              "- nothing was asked" % where)
        return 2
    authored = parse_map(read(mp))[1]
    pool = [(fid, f) for fid, f in sorted(authored.items())
            if not fid.startswith("pattern:") and (not feature or fid == feature)]
    todo = [(fid, f) for fid, f in pool if f.get("intent") and f.get("observable")]
    if len(todo) < len(pool):
        # Said, not dropped: an entry left out silently reads as judged.
        print("  %d authored entry/entries carry no intent: or no observable: - "
              "nothing there to judge" % (len(pool) - len(todo)))
    if not todo:
        print("nothing to judge: no authored entry carries both intent: and "
              "observable:")
        return 0
    # The template's own example is not an entry of this project. A map fresh
    # from --init still holds it, and on 2026-09-24 07:50 its placeholder text
    # went to TypeSafe as if it were one. Copied under a real id it is no
    # different, so it is matched by id and by text.
    tpl = parse_map(read(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      os.pardir, "templates", MAP_NAME)) or "")[1]
    placeholder = {(f.get("intent"), f.get("observable")) for f in tpl.values()}
    questions, skipped = {}, []
    for fid, f in todo:
        if fid in tpl or (f["intent"], f["observable"]) in placeholder:
            skipped.append((fid, "the template's own placeholder, not an entry of "
                                 "this project - fill it in or delete it"))
            continue
        q = _intent_question(f["intent"], f["observable"])
        problems = jev.lint({fid: q})
        if problems:
            skipped.append((fid, problems[0]))
        else:
            questions[fid] = q
    for fid, why in skipped:
        print("  not judged %-30s %s" % (fid, why.split(": ", 1)[-1]))
    if not questions:
        return 0
    state = ("The feature map of %s. Each question pairs one feature's recorded "
             "observable with the intent it was built for." % os.path.basename(root))
    try:
        r = jev.ask(state, questions)
    except jev.Refused as e:
        print("REFUSED %s" % e)
        return 2
    except jev.Unavailable as e:
        print("NOT JUDGED %s - %d entry/entries unjudged, and nothing here is "
              "evidence either way" % (e, len(questions)))
        return 2
    low, torn, high = [], [], []
    for fid in sorted(questions):
        p = r["answers"][fid]["noul"]
        (low if p < JUDGE_LOW else torn if p < JUDGE_HIGH else high).append((fid, p))
    print("judge: %d entry/entries asked in one request to %s - %d ms, %s input "
          "tokens" % (len(questions), r["model"], r["ms"],
                      r["usage"].get("input_tokens", "?")))
    if low:
        print("  observable may NOT show the intent (below %.2f):" % JUDGE_LOW)
        for fid, p in low:
            print("    %-36s %.2f  intent: %s" % (fid, p, authored[fid]["intent"][:90]))
    if torn:
        print("  torn (%.2f to %.2f) - read these two fields yourself:"
              % (JUDGE_LOW, JUDGE_HIGH))
        for fid, p in torn:
            print("    %-36s %.2f" % (fid, p))
    if high:
        print("  shows the intent (%.2f or more): %s" % (
            JUDGE_HIGH, ", ".join("%s %.2f" % x for x in high)))
    print("these thresholds are not yet validated on the operator's own entries: a reading to "
          "look at, never a gate (reference/jev-calibration.md)")
    return 0


def _deploy_branch(root):
    for p, kind, text in _deploy_configs(root):
        if kind == "render":
            for s in _render_services(text):
                if _mine(root, s) and s[3].get("branch"):
                    return s[3]["branch"]
    return ""


def main(argv=None):
    # A report is read by hooks, harnesses and CI through a pipe, where Windows
    # defaults to the console's legacy code page. There, one arrow in a source
    # line a rule quotes crashed the whole check with a traceback - a report
    # that exits 1 without saying why. UTF-8 with replacement cannot crash.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=".")
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--reaim", action="store_true")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--ratchet", action="store_true")
    ap.add_argument("--feature")
    ap.add_argument("--grade")
    ap.add_argument("--result", choices=("pass", "fail", "blocked"))
    ap.add_argument("--how")
    ap.add_argument("--observable")
    ap.add_argument("--bound")
    ap.add_argument("--conditions")
    ap.add_argument("--metric", action="append")
    ap.add_argument("--artifact", action="append")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--ref")
    ap.add_argument("--compare", nargs="+", metavar="REF")
    ap.add_argument("--face", choices=("user", "dev", "unclassified"))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--url")
    ap.add_argument("--fingerprint")
    ap.add_argument("--probe", action="append")
    ap.add_argument("--branch")
    ap.add_argument("--judge", action="store_true")
    a = ap.parse_args(argv)

    root = os.path.abspath(a.project)
    if not os.path.isdir(root):
        print("no such project directory: %s" % root)
        return 2
    mp = os.path.join(root, MAP_NAME)
    if a.ref and not a.list:
        print("--ref reads a past commit or another branch for --list; to set "
              "two refs side by side use --compare A B")
        return 2
    if a.compare:
        return cmd_compare(root, a.compare, a.json)
    if a.live:
        return cmd_live(root, mp, a)
    if a.judge:
        return cmd_judge(root, mp, a.feature)
    if a.list:
        return cmd_list(root, a.ref, a.face, a.json)
    if a.init:
        return cmd_init(root, mp)
    if a.write:
        return cmd_write(root, mp)
    if a.reaim:
        return cmd_reaim(root, mp)
    if a.record:
        return cmd_record(root, a)
    if a.ratchet:
        return cmd_ratchet(root, mp)
    if a.check:
        return cmd_check(root, mp)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
