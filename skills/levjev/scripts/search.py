# -*- coding: utf-8 -*-
"""search.py - ask a repository a question; Jev judges each excerpt, code does the rest.

Version 1.0 | Deps: Python 3 standard library only; jev.py beside it |
Parent: levjev skill 1.0.1 | Path: scripts | Filename: search.py | Created: 2026-09-29
Replaces the third-party jevgrep
(@dzhng/jevgrep 0.7.0, MIT), whose design it learned from and none of whose code
it carries.
WHY IT EXISTS (2026-09-29): one client, one set of rules. jevgrep supports macOS
and Linux and keeps its own credentials file; this runs natively on Windows
too, asks Jev ONLY through
jev.py (pin jev-1.13.0, aliases refused, lint, key from the environment or
~/.agents/.env, never printed), and keeps every rule of "Jev decides, code
computes".

PIPELINE
    walk     the root, skipping .git, dependency and build dirs, hidden paths,
             .gitignore matches, binaries, non-UTF-8 text, minified files, files
             over a size cap, and sensitive files by name or by content. Every
             skip is counted by category; nothing is skipped silently.
    chunk    each file into line ranges (up to 60 lines / 6000 chars, cut at a
             blank line after 30 when one comes).
    order    chunks by how many question words they contain, so a capped search
             spends its requests on the likeliest source first (code, not Jev).
    ask      one narrow Noul per chunk, the excerpt and its path INLINED as data,
             never an index into state. Hex, RGB and binary literals - which Jev
             cannot read - are masked in what is sent; the excerpt shown is the
             file's text verbatim.
    cache    each validated answer by sha256 of (pin, state, question with its
             inlined excerpt), so an unchanged rerun costs nothing. Failures and
             refusals are never cached.
    rank     by the reading, highest first; ties by path and line. The reading is
             uncalibrated on the operator's data, so it orders results and never gates them.

USAGE
    python search.py files [root]                 count what a search may read; sends nothing
    python search.py "question" [root] --dry-run  the plan: cached vs requests to send; sends nothing
    python search.py "question" [root]            search (prints the plan first)
Exit: 0 complete, 1 failed or refused, 2 incomplete. The last line is RESULT.
"""
import argparse
import fnmatch
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import jev  # noqa: E402  the one way to ask Jev

CHUNK_LINES, CHUNK_MIN, CHUNK_CHARS = 60, 30, 6000
# A line longer than this marks a minified or generated file. 2000 skipped
# hand-written prose (verafox registry.md, 2,400-char paragraphs); one line this
# long is still about 5k tokens, well inside Jev's 32k for state plus question.
MAX_LINE_CHARS = 20000
DEFAULT_MAX_BYTES = 200000
DEFAULT_MAX_REQUESTS = 100
STOP_AFTER_FAILURES = 3

STATE = ("One source excerpt from a repository search. The excerpt and the path of "
         "its file are inlined in the question.")
ASK = ("Does `excerpt` (source from the file at `path`) implement or directly "
       "explain this: %s")

DEP_DIRS = {"node_modules", "bower_components", "vendor", "dist", "build", "out",
            "target", "bin", "obj", "__pycache__", "venv", ".venv", "env",
            "site-packages", ".tox", ".nox", ".mypy_cache", ".pytest_cache",
            ".ruff_cache", ".next", ".nuxt", ".svelte-kit", ".gradle", "coverage",
            ".cache", ".parcel-cache", ".turbo", "Pods", "DerivedData"}
SENSITIVE_NAMES = (".env", ".env.*", "*.env", "*.pem", "*.key", "*.p12", "*.pfx",
                   "*.jks", "*.keystore", "*.kdbx", "id_rsa*", "id_dsa*",
                   "id_ecdsa*", "id_ed25519*", "credentials*", "*credentials.json",
                   "secrets.*", "*.secret", "*.secrets", ".npmrc", ".pypirc",
                   ".netrc", "_netrc", ".git-credentials", ".htpasswd",
                   "service-account*.json", "*.tfvars", "*.tfstate")
SENSITIVE_CONTENT = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bAKIA[0-9A-Z]{16}\b|"
    # A key, secret, token or password given a quoted value of 8 or more characters with
    # no space: bare, behind a prefix (TYPESAFE_API_KEY =), or as a JSON or YAML key
    # ("api_key": "..."). No word boundary before the name, because _ is a word character.
    # A placeholder is not a secret: an environment variable's NAME, a ${...} or {{...}} or
    # <...> template, or a value that opens with your, example, sample, test, fake, dummy,
    # placeholder, changeme, xxx or replace (read from one web app and clerk-cli, 2026-09-30).
    r"(?i:(?:api[_-]?key|secret(?:[_-]?key)?|client[_-]?secret|(?:access|auth|refresh)[_-]?token"
    r"|passw(?:or)?d|pwd)[\"']?\s*[:=]\s*[\"'](?!(?-i:[A-Z][A-Z0-9_]*)[\"'])(?!\$\{|\{\{|<)"
    r"(?!your|example|sample|test|fake|dummy|placeholder|change[_-]?me|xxx|replace)"
    r"[^\"'\s]{8,}[\"'])|"
    # Token shapes that are a secret wherever they appear: GitHub, Slack, Stripe live,
    # Google API, OpenAI and Anthropic, an HTTP Bearer value, and a JWT.
    r"\bgh[pousr]_[A-Za-z0-9]{36,}|\bgithub_pat_[A-Za-z0-9_]{22,}|\bxox[abposr]-[A-Za-z0-9-]{10,}|"
    r"\b[rs]k_live_[A-Za-z0-9]{16,}|\bAIza[0-9A-Za-z_-]{35}|\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}|"
    r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}|\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.")
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tif",
              ".tiff", ".psd", ".pdf", ".zip", ".gz", ".tgz", ".bz2", ".xz", ".7z",
              ".rar", ".jar", ".war", ".exe", ".dll", ".so", ".dylib", ".lib", ".a",
              ".o", ".obj", ".class", ".pyc", ".pyo", ".pyd", ".whl", ".bin", ".dat",
              ".db", ".sqlite", ".sqlite3", ".woff", ".woff2", ".ttf", ".otf",
              ".eot", ".mp3", ".mp4", ".wav", ".ogg", ".mov", ".avi", ".mkv",
              ".webm", ".flac", ".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt",
              ".iso", ".dmg", ".msi", ".lock"}
CATEGORIES = ("sensitive", "git metadata", "dependency/build", "hidden", "gitignored",
              "excluded", "binary", "over size cap", "not UTF-8 text",
              "minified (line over %d chars)" % MAX_LINE_CHARS, "empty")
STOP = {"the", "and", "for", "are", "was", "were", "does", "did", "how", "what",
        "where", "when", "why", "which", "who", "this", "that", "with", "from",
        "into", "its", "our", "your", "their", "there", "here", "have", "has",
        "code", "file", "files", "work", "works", "use", "used", "uses", "not",
        "any", "all", "can", "will", "should", "would", "about", "get", "set"}
_LITERAL = getattr(jev, "_LITERAL", None)


# ------------------------------------------------------------------ the walk
def _gitignore_regex(pat):
    """(regex, negate, dir_only) for one .gitignore line, or None."""
    pat = pat.rstrip("\r\n")
    if not pat.strip() or pat.startswith("#"):
        return None
    pat = pat.rstrip(" ")
    neg = pat.startswith("!")
    if neg:
        pat = pat[1:]
    if pat.startswith("\\"):
        pat = pat[1:]
    dir_only = pat.endswith("/")
    pat = pat.rstrip("/")
    anchored = "/" in pat
    pat = pat.lstrip("/")
    out, i = [], 0
    while i < len(pat):
        c = pat[i]
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pat.startswith("/**", i) and i + 3 == len(pat):
            out.append("/.*")
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[" and "]" in pat[i + 1:]:
            j = pat.index("]", i + 1)
            out.append("[" + pat[i + 1:j].replace("\\", "\\\\") + "]")
            i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    body = "".join(out)
    try:
        rx = re.compile(("^" if anchored else "^(?:.*/)?") + body + "$")
    except re.error:
        return None
    return rx, neg, dir_only


def _read_rules(path):
    rules = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                r = _gitignore_regex(line)
                if r:
                    rules.append(r)
    except OSError:
        pass
    return rules


def _ignored(rules, rel, is_dir):
    """Last matching rule wins. rules: list of (base, (rx, neg, dir_only))."""
    hit = False
    for base, (rx, neg, dir_only) in rules:
        if base and not rel.startswith(base + "/"):
            continue
        sub = rel[len(base) + 1:] if base else rel
        if dir_only and not is_dir:
            continue
        if rx.match(sub):
            hit = not neg
    return hit


def _sensitive_name(name):
    low = name.lower()
    return any(fnmatch.fnmatchcase(low, p) for p in SENSITIVE_NAMES)


def walk(root, a):
    """([(rel, text)], {category: [rel]}, total_bytes)."""
    skipped = {c: [] for c in CATEGORIES}
    files, total = [], 0
    rules = [("", r) for r in (_gitignore_regex(p) for p in (a.exclude or [])) if r]
    excl = list(rules)
    rules = []
    for dp, dns, fns in os.walk(root):
        rel_dir = os.path.relpath(dp, root).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        if not a.no_ignore and ".gitignore" in fns:
            rules += [(rel_dir, r) for r in _read_rules(os.path.join(dp, ".gitignore"))]
        keep = []
        for d in sorted(dns):
            rel = (rel_dir + "/" + d) if rel_dir else d
            if d == ".git":
                skipped["git metadata"].append(rel + "/")
            elif d in DEP_DIRS and not a.include_dependencies:
                skipped["dependency/build"].append(rel + "/")
            elif d.startswith(".") and not a.hidden:
                skipped["hidden"].append(rel + "/")
            elif not a.no_ignore and _ignored(rules, rel, True):
                skipped["gitignored"].append(rel + "/")
            elif _ignored(excl, rel, True):
                skipped["excluded"].append(rel + "/")
            else:
                keep.append(d)
        dns[:] = keep
        for f in sorted(fns):
            rel = (rel_dir + "/" + f) if rel_dir else f
            path = os.path.join(dp, f)
            cat = None
            if _sensitive_name(f) and not a.include_sensitive:
                cat = "sensitive"
            elif f.startswith(".") and not a.hidden:
                cat = "hidden"
            elif not a.no_ignore and _ignored(rules, rel, False):
                cat = "gitignored"
            elif _ignored(excl, rel, False):
                cat = "excluded"
            elif os.path.splitext(f)[1].lower() in BINARY_EXT:
                cat = "binary"
            else:
                try:
                    size = os.path.getsize(path)
                except OSError:
                    size = -1
                if size > a.max_file_bytes:
                    cat = "over size cap"
                elif size == 0:
                    cat = "empty"
            if cat is None:
                try:
                    with open(path, "rb") as fh:
                        raw = fh.read()
                except OSError:
                    raw = b"\0"
                if b"\0" in raw[:8192]:
                    cat = "binary"
                else:
                    try:
                        text = raw.decode("utf-8-sig")
                    except UnicodeDecodeError:
                        cat = "not UTF-8 text"
                    else:
                        if not a.include_sensitive and SENSITIVE_CONTENT.search(text):
                            cat = "sensitive"
                        elif any(len(ln) > MAX_LINE_CHARS for ln in text.splitlines()):
                            cat = CATEGORIES[9]
                        elif not text.strip():
                            cat = "empty"
            if cat:
                skipped[cat].append(rel)
            else:
                files.append((rel, text))
                total += len(raw)
    return files, skipped, total


# ------------------------------------------------------------------ chunks
def chunk(text):
    """[(first_line, last_line, verbatim_text)] - 1-based, inclusive."""
    lines = text.splitlines(keepends=True)
    out, cur, start, chars = [], [], 1, 0
    for i, ln in enumerate(lines, 1):
        if cur and (len(cur) >= CHUNK_LINES or chars + len(ln) > CHUNK_CHARS):
            out.append((start, i - 1, "".join(cur)))
            cur, start, chars = [], i, 0
        cur.append(ln)
        chars += len(ln)
        if len(cur) >= CHUNK_MIN and not ln.strip():
            out.append((start, i, "".join(cur)))
            cur, start, chars = [], i + 1, 0
    if cur and "".join(cur).strip():
        out.append((start, start + len(cur) - 1, "".join(cur)))
    return out


def _stems(question):
    words = {w for w in re.findall(r"[a-z0-9_]+", question.lower())
             if len(w) >= 3 and w not in STOP}
    return {w[:max(4, len(w) - 2)] if len(w) > 4 else w for w in words}


def _mask(text):
    return _LITERAL.sub("<literal>", text) if _LITERAL else text


def _questions(question, rel, text):
    return {"relevant": {"type": "noul", "instructions": {
        "path": rel, "excerpt": _mask(text), "question": ASK % question}}}


def _cache_key(qs):
    blob = json.dumps([jev.PIN, STATE, qs], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _cache_get(cdir, key):
    try:
        with open(os.path.join(cdir, key[:2], key + ".json"), encoding="utf-8") as fh:
            d = json.load(fh)
        n = d.get("noul")
        if d.get("model") == jev.PIN and isinstance(n, (int, float)) and 0 <= n <= 1:
            return float(n)
    except (OSError, ValueError, AttributeError):
        pass
    return None


def _cache_put(cdir, key, noul):
    d = os.path.join(cdir, key[:2])
    try:
        os.makedirs(d, exist_ok=True)
        tmp = os.path.join(d, key + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"model": jev.PIN, "noul": noul}, fh)
        os.replace(tmp, os.path.join(d, key + ".json"))
    except OSError:
        pass


def _skip_line(skipped, show):
    parts = ["%s %d" % (c, len(v)) for c, v in skipped.items() if v]
    lines = ["SKIPPED " + (", ".join(parts) if parts else "nothing")]
    if show:
        for c, v in skipped.items():
            for rel in v:
                lines.append("  skipped (%s) %s" % (c, rel))
    return "\n".join(lines)


# ------------------------------------------------------------------ main
def _common(ap):
    ap.add_argument("--hidden", action="store_true", help="include hidden paths")
    ap.add_argument("--no-ignore", action="store_true", help="disable .gitignore")
    ap.add_argument("--include-dependencies", action="store_true",
                    help="include dependency and build directories")
    ap.add_argument("--include-sensitive", action="store_true",
                    help="include known sensitive names and content")
    ap.add_argument("--exclude", action="append", metavar="PATTERN",
                    help="skip paths matching a gitignore pattern; repeatable")
    ap.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_BYTES,
                    help="skip files larger than this (default %d)" % DEFAULT_MAX_BYTES)
    ap.add_argument("--show-skipped", action="store_true", help="list every skipped path")


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "files":
        ap = argparse.ArgumentParser(prog="search.py files",
                                     description="count what a search may read; sends nothing")
        ap.add_argument("root", nargs="?", default=".")
        _common(ap)
        a = ap.parse_args(argv[1:])
        if not os.path.isdir(a.root):
            print("RESULT failed - no such folder: %s" % a.root)
            return 1
        files, skipped, total = walk(a.root, a)
        n = sum(len(chunk(t)) for _, t in files)
        print("PLAN %d files (%d bytes), %d chunks: up to %d requests (no question "
              "given, so the cache was not consulted); sends nothing"
              % (len(files), total, n, n))
        print(_skip_line(skipped, a.show_skipped))
        print("RESULT files - nothing sent")
        return 0

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("question")
    ap.add_argument("root", nargs="?", default=".")
    _common(ap)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan (cached vs to send) and send nothing")
    ap.add_argument("--no-cache", action="store_true", help="no cache reads or writes")
    ap.add_argument("--cache-dir", default=os.path.join(
        os.path.expanduser("~"), ".cache", "levjev", "search"))
    ap.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS,
                    help="cap on requests sent per search (default %d)"
                    % DEFAULT_MAX_REQUESTS)
    ap.add_argument("--top", type=int, default=10, help="results shown (default 10)")
    ap.add_argument("--excerpt-lines", type=int, default=0,
                    help="trim each excerpt to N lines around the question's words "
                         "(default 0: the whole chunk)")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.root):
        print("RESULT failed - no such folder: %s" % a.root)
        return 1
    problems = jev.lint(_questions(a.question, "probe.txt", "probe"))
    if problems:
        print("REFUSED " + "; ".join(problems).replace("relevant: ", "the question "))
        print("RESULT failed - the question was refused before anything was sent")
        return 1

    files, skipped, _ = walk(a.root, a)
    stems = _stems(a.question)
    jobs = []
    for rel, text in files:
        for first, last, body in chunk(text):
            qs = _questions(a.question, rel, body)
            low = body.lower() + " " + rel.lower()
            jobs.append({"rel": rel, "first": first, "last": last, "text": body,
                         "qs": qs, "key": _cache_key(qs),
                         "prior": sum(1 for s in stems if s in low)})
    for j in jobs:
        j["noul"] = None if a.no_cache else _cache_get(a.cache_dir, j["key"])
    cached = sum(1 for j in jobs if j["noul"] is not None)
    need = len(jobs) - cached
    to_send = min(need, max(0, a.max_requests))
    print("PLAN %d files, %d chunks: %d cached, %d requests to send (cap %d%s)"
          % (len(files), len(jobs), cached, to_send, a.max_requests,
             "; %d not asked" % (need - to_send) if need > to_send else ""))
    print(_skip_line(skipped, a.show_skipped))
    if a.dry_run:
        print("RESULT dry-run - nothing sent")
        return 0

    answered = failed = streak = 0
    refused, not_asked, reasons = 0, 0, {}
    stopped = None
    order = sorted(range(len(jobs)), key=lambda i: (-jobs[i]["prior"], i))
    for i in order:
        j = jobs[i]
        if j["noul"] is not None:
            continue
        if stopped or answered + failed >= a.max_requests:
            not_asked += 1
            continue
        try:
            r = jev.ask(STATE, j["qs"])
        except jev.Refused as e:
            refused += 1
            reasons.setdefault("refused", "%s:%d-%d %s" % (j["rel"], j["first"], j["last"], e))
            continue
        except jev.Unavailable as e:
            failed += 1
            streak += 1
            reasons.setdefault("failed", str(e))
            if streak >= STOP_AFTER_FAILURES:
                stopped = "stopped after %d failures in a row" % streak
            continue
        streak = 0
        answered += 1
        j["noul"] = float(r["answers"]["relevant"]["noul"])
        if not a.no_cache:
            _cache_put(a.cache_dir, j["key"], j["noul"])

    judged = [j for j in jobs if j["noul"] is not None]
    judged.sort(key=lambda j: (-j["noul"], j["rel"], j["first"]))
    if judged:
        print("\nReadings are Jev's noul (probability the excerpt answers the "
              "question), uncalibrated on the operator's data: they order the list, never gate it.")
    for rank, j in enumerate(judged[:max(0, a.top)], 1):
        print("\n%d. %s:%d-%d  noul %.2f" % (rank, j["rel"], j["first"], j["last"], j["noul"]))
        lines = j["text"].splitlines()
        lo = 0
        if a.excerpt_lines and len(lines) > a.excerpt_lines:
            best = max(range(len(lines) - a.excerpt_lines + 1), key=lambda s: sum(
                1 for ln in lines[s:s + a.excerpt_lines] for st in stems
                if st in ln.lower()))
            lo = best
            lines = lines[lo:lo + a.excerpt_lines]
        width = len(str(j["last"]))
        for k, ln in enumerate(lines):
            print("   %*d | %s" % (width, j["first"] + lo + k, ln))
        if a.excerpt_lines and j["last"] - j["first"] + 1 > len(lines):
            print("   (excerpt trimmed to %d of %d lines)"
                  % (len(lines), j["last"] - j["first"] + 1))
    if len(judged) > a.top:
        print("\n%d more judged chunks below the top %d" % (len(judged) - a.top, a.top))

    print("\nrequests: %d answered, %d failed; cache hits: %d; refused: %d; not asked: %d"
          % (answered, failed, cached, refused, not_asked))
    for k in ("failed", "refused"):
        if k in reasons:
            print("  first %s: %s" % (k, reasons[k]))
    if not_asked:
        print("  not asked: %s" % (stopped or "the cap of %d requests was reached "
                                    "(raise --max-requests)" % a.max_requests))
    if jobs and not judged:
        print("RESULT failed - no chunk was judged")
        return 1
    if failed or refused or not_asked:
        print("RESULT incomplete - %d of %d chunks judged" % (len(judged), len(jobs)))
        return 2
    print("RESULT complete - %d of %d chunks judged" % (len(judged), len(jobs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
