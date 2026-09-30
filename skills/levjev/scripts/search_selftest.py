# -*- coding: utf-8 -*-
# The strings below are fixtures Mutate reads as data, not things this file does:
# mutate: fixture
"""search_selftest.py - the cases search.py must not regress on.

Version 1.0 | Deps: Python 3 standard library only | Parent: levjev skill 1.0.3 (search.py) |
Path: scripts | Filename: search_selftest.py | Created: 2026-09-29 10:48 ET

Run:  python -B scripts/search_selftest.py       (exit 0 = all green)

Same pattern as selftest.py: a fake TypeSafe on this machine, and every run in a
fresh process with a home of its own, so this machine's real key in
~/.agents/.env is never read and no request ever leaves the machine. The fake
answers by a marker in the excerpt it was sent (RELEVANT 0.95, MAYBE 0.6, else
0.05): these prove what search.py SENDS, skips, caches and computes - never
what Jev would say about real code.
"""
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
SEARCH = os.path.join(HERE, "search.py")
sys.path.insert(0, HERE)
import jev  # noqa: E402  the copy beside this file, for lint() only

PASS, FAIL = [], []
Q = "Where are session tokens issued?"


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + (
        ("\n         " + str(detail).replace("\n", "\n         ")[:3000]) if
        (detail and not cond) else ""))


def put(path, text, binary=False):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    if binary:
        with open(path, "wb") as fh:
            fh.write(text)
    else:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)


AUTH = ("import secrets\n\n"
        "def issue_token(user):  # RELEVANT session\n"
        "    token = secrets.token_hex(16)\n"
        "    user.sessions.append(token)\n"
        "    return token\n")
LONG = "".join(("value = compute()  # RELEVANT\n" if i == 100 else
                "x%d = %d\n" % (i, i)) for i in range(1, 151))


def fixture(repo):
    put(os.path.join(repo, "src", "auth.py"), AUTH)
    put(os.path.join(repo, "src", "util.py"), "def helper():  # MAYBE\n    return 1\n")
    put(os.path.join(repo, "src", "other.py"), "def unrelated():\n    return 2\n")
    put(os.path.join(repo, "src", "colors.py"), "MASK = 0xFF\nRED = 'red'\n")
    put(os.path.join(repo, "long.py"), LONG)
    # sensitive by name, and by content
    put(os.path.join(repo, ".env"), "TYPESAFE_API_KEY=SECRET-ENV-VALUE\n")
    put(os.path.join(repo, "config", "credentials.json"), '{"k": "SECRET-CRED-VALUE"}\n')
    put(os.path.join(repo, "keys", "server.pem"), "SECRET-PEM-VALUE\n")
    put(os.path.join(repo, "id_rsa"), "SECRET-RSA-VALUE\n")
    put(os.path.join(repo, "src", "key_in_body.py"),
        "K = '''-----BEGIN RSA PRIVATE KEY-----\nSECRET-BODY-VALUE\n'''\n")
    # dependencies, build output, git metadata, ignored, binary, oversize
    put(os.path.join(repo, "node_modules", "pkg", "index.js"), "DEPCODE\n")
    put(os.path.join(repo, "dist", "bundle.js"), "BUILDOUT\n")
    put(os.path.join(repo, ".git", "config"), "GITMETA\n")
    put(os.path.join(repo, ".gitignore"), "ignored/\n*.log\n")
    put(os.path.join(repo, "ignored", "by_gitignore.py"), "IGNOREDCODE\n")
    put(os.path.join(repo, "app.log"), "LOGTEXT\n")
    put(os.path.join(repo, "image.bin"), b"\x89PNG\x00\x00BINARYDATA", binary=True)
    put(os.path.join(repo, "big.txt"), "BIGFILE\n" * 40000)


NEVER_SENT = ("SECRET-", "DEPCODE", "BUILDOUT", "GITMETA", "IGNOREDCODE", "LOGTEXT",
              "BINARYDATA", "BIGFILE")


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    tmp = tempfile.mkdtemp(prefix="jevsearchtest-")
    posts, reply = [], {}

    class J(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            body = json.loads(raw.decode("utf-8"))
            posts.append((self.headers.get("Authorization"), body, raw.decode("utf-8")))
            if reply.get("fail"):
                self.send_response(reply["fail"].pop(0))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            answers = {}
            for q, spec in body["questions"].items():
                ex = json.dumps(spec.get("instructions"))
                p = 0.95 if "RELEVANT" in ex else 0.6 if "MAYBE" in ex else 0.05
                answers[q] = {"type": "noul", "noul": p}
            out = json.dumps({"model": body["model"], "answers": answers,
                              "usage": {"input_tokens": 42}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *args):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), J)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    home = os.path.join(tmp, "home")
    os.makedirs(os.path.join(home, ".agents"))
    fake = dict(os.environ, TYPESAFE_API_KEY="test-key-not-real",
                JEV_ENDPOINT="http://127.0.0.1:%d/v1/systemone" % srv.server_address[1],
                USERPROFILE=home, HOME=home)
    fake.pop("LOCALAPPDATA", None)
    nokey = dict(fake)
    del nokey["TYPESAFE_API_KEY"]
    repo = os.path.join(tmp, "repo")
    fixture(repo)

    def run(*args, env=fake):
        p = subprocess.run([sys.executable, "-B", SEARCH] + list(args),
                           capture_output=True, timeout=120, env=env)
        return p.returncode, p.stdout.decode("utf-8", "replace") + \
            p.stderr.decode("utf-8", "replace")

    def sent_since(n):
        return "\n".join(p[2] for p in posts[n:])

    try:
        # ------------------------------------------------ 1 files: count, send nothing
        print("\n1. files mode and --dry-run count what a search would send, and send nothing")
        rc, out = run("files", repo, env=nokey)
        check("files counts the eligible files and chunks, with no key and no request",
              rc == 0 and re.search(r"\b5 files\b", out) and re.search(r"\b7 chunks\b", out)
              and not posts, out)
        check("...and names every skip category with its count - nothing skipped silently",
              re.search(r"sensitive 5\b", out) and re.search(r"binary 1\b", out)
              and re.search(r"over size cap 1\b", out) and re.search(r"gitignored 2\b", out)
              and "dependency/build" in out and "hidden" in out, out)
        # Found on the first sample run (verafox, 2026-09-29): registry.md is
        # hand-written prose with 2,400-char paragraph lines and was skipped as
        # minified. A long paragraph is source; one 30,000-char line is not.
        prose = os.path.join(tmp, "prose")
        put(os.path.join(prose, "notes.md"), "# Notes\n\n" + "word " * 500 + "\n")
        put(os.path.join(prose, "bundle.min.js"), "var a=1;" * 4000 + "\n")
        rc, out = run("files", prose, env=nokey)
        check("a long prose paragraph is searched; only a truly minified line is skipped",
              rc == 0 and re.search(r"\b1 files\b", out) and re.search(r"minified[^\n]* 1\b", out),
              out)
        rc, out = run(Q, repo, "--dry-run", "--no-cache")
        check("--dry-run with a question states the requests it would send, sends none",
              rc == 0 and re.search(r"\b7 requests to send\b", out) and not posts
              and "RESULT dry-run" in out, out)

        # ------------------------------------------------ 1b secret shapes in content
        # Found 2026-09-30 driving --include-sensitive by hand: a JSON or YAML key, a key
        # name with a prefix (TYPESAFE_API_KEY =), a password under 16 characters and the
        # common token shapes were all eligible, so a default search sent them to Jev.
        print("\n1b. secret shapes in content are skipped as sensitive; talk about them is not")
        sec = os.path.join(tmp, "secrets2")
        shapes = {
            "json_key.json": '{"api_key": "abcd1234efgh5678"}\n',
            "prefixed.py": 'TYPESAFE_API_KEY = "abcd1234efgh5678"\n',
            "short_pw.py": 'password = "hunter2!x"\n',
            "yaml_secret.yml": 'client_secret: "abcd1234efgh"\n',
            "github.py": 'T = "ghp_' + "A1b2C3d4" * 4 + 'wxyz"\n',
            "slack.py": 'T = "xo' + 'xb-1234567890-abcdefghij"\n',  # split: no scanner reads a token here
            "stripe.py": 'T = "sk_live_' + "a1B2" * 6 + '"\n',
            "google.py": 'T = "AIza' + "b" * 35 + '"\n',
            "llm.py": 'T = "sk-ant-' + "c3D4" * 6 + '"\n',
            "bearer.py": 'H = {"Authorization": "Bearer ' + "e5F6" * 6 + '"}\n',
            "jwt.py": 'T = "eyJhbGciOiJIUzI1NiJ9.' + 'eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig"\n',
        }
        for name, text in shapes.items():
            put(os.path.join(sec, name), "# SECRET-SHAPE\n" + text)
        rc, out = run("files", sec, env=nokey)
        check("every secret shape is skipped as sensitive by content (%d)" % len(shapes),
              rc == 0 and re.search(r"sensitive %d\b" % len(shapes), out)
              and re.search(r"\b0 files\b", out), out)
        n = len(posts)
        rc, out = run(Q, sec)
        check("...and a search over them sends nothing",
              len(posts) == n and "SECRET-" not in sent_since(n), out)
        plain = os.path.join(tmp, "plain")
        put(os.path.join(plain, "auth_doc.py"),
            "def check_password(pw):  # compares against the stored hash\n"
            "    password = pw.strip()\n"
            '    schema = {"password": "string", "api_key": "<your key>"}\n'
            '    token = os.environ["ACCESS_TOKEN"]\n'
            '    header = "Authorization: Bearer <token>"\n'
            # Placeholders read from real repos on 2026-09-30 (one web app, the clerk-cli skill):
            # an environment variable's name, a your-... value, a template reference.
            '    secret = "ALPACA_API_SECRET"\n'
            '    API_KEY = "your-api-key-here"\n'
            '    db = {"password": "${DB_PASSWORD}", "pwd": "example-only"}\n')
        rc, out = run("files", plain, env=nokey)
        check("code that only talks about passwords, keys and tokens is still searched",
              rc == 0 and re.search(r"\b1 files\b", out)
              and not re.search(r"sensitive [1-9]", out), out)

        # ------------------------------------------------ 2 a real search
        print("\n2. a search: plan first, one pinned request per chunk, code ranks")
        rc, out = run(Q, repo)
        body = sent_since(0)
        check("the plan line is printed before the results",
              "PLAN" in out and out.index("PLAN") < out.find("1. "), out)
        check("one request per chunk, each to the pinned model",
              len(posts) == 7 and all(p[1]["model"] == "jev-1.13.0" for p in posts)
              and all(len(p[1]["questions"]) == 1 for p in posts), out)
        check("nothing sensitive, ignored, dependency, build, git, binary or oversize "
              "is ever sent", len(posts) == 7 and not any(m in body for m in NEVER_SENT),
              [m for m in NEVER_SENT if m in body])
        qs = [p[1]["questions"] for p in posts]
        check("every question passes jev's lint and carries its excerpt inlined, "
              "never an index into state",
              qs and all(jev.lint(q) == [] for q in qs)
              and all(isinstance(list(q.values())[0]["instructions"].get("excerpt"), str)
                      for q in qs), json.dumps(qs)[:800])
        auth_sent = [q for q in qs if list(q.values())[0]["instructions"].get("path")
                     == "src/auth.py"]
        check("the excerpt sent is the file's text verbatim",
              auth_sent and list(auth_sent[0].values())[0]["instructions"]["excerpt"] == AUTH,
              json.dumps(auth_sent)[:600])
        pos = {k: out.find(k) for k in ("src/auth.py:1-6", "long.py:61-120",
                                        "src/util.py:1-2", "src/other.py:1-2")}
        check("ranked by reading, highest first, as file:line ranges",
              rc == 0 and all(v >= 0 for v in pos.values())
              and max(pos["src/auth.py:1-6"], pos["long.py:61-120"]) < pos["src/util.py:1-2"]
              < pos["src/other.py:1-2"], out)
        check("with verbatim excerpts", "def issue_token(user):  # RELEVANT session" in out
              and "value = compute()  # RELEVANT" in out, out)
        check("the close states requests, cache hits and the result",
              re.search(r"7 answered, 0 failed", out) and re.search(r"cache hits: 0\b", out)
              and "RESULT complete" in out, out)
        check("the key never appears in the output",
              "RESULT complete" in out and "test-key-not-real" not in out, out)
        colors = [p for p in posts if p[1]["questions"] and list(p[1]["questions"].values())[0]
                  ["instructions"].get("path") == "src/colors.py"]
        check("a hex literal Jev cannot read is masked in what is sent, shown verbatim "
              "in the excerpt", colors and "0xFF" not in colors[0][2]
              and "MASK = 0xFF" in out and re.search(r"refused: 0\b", out), out)

        # ------------------------------------------------ 3 the cache
        print("\n3. the cache: an unchanged rerun costs nothing")
        n = len(posts)
        rc, out = run(Q, repo)
        check("a rerun on unchanged code sends nothing and answers from the cache",
              rc == 0 and len(posts) == n and re.search(r"cache hits: 7\b", out)
              and re.search(r"0 answered", out) and "RESULT complete" in out
              and out.find("src/auth.py:1-6") < out.find("src/other.py:1-2"), out)
        rc, out = run(Q, repo, "--dry-run")
        check("--dry-run sees the cache: 7 cached, 0 requests to send",
              rc == 0 and len(posts) == n and re.search(r"7 cached, 0 requests to send", out),
              out)
        put(os.path.join(repo, "src", "util.py"), "def helper():  # MAYBE\n    return 3\n")
        rc, out = run(Q, repo)
        check("a changed chunk is asked again, the rest come from the cache",
              len(posts) == n + 1 and re.search(r"cache hits: 6\b", out), out)
        n = len(posts)
        rc, out = run(Q, repo, "--no-cache")
        check("--no-cache bypasses it", len(posts) == n + 7, out)
        cached = ""
        for dp, _, fns in os.walk(home):
            for fn in fns:
                if fn != ".env":
                    with open(os.path.join(dp, fn), encoding="utf-8", errors="replace") as fh:
                        cached += fh.read()
        check("the cache holds answers, never the key", cached and "0.95" in cached
              and "test-key-not-real" not in cached, cached[:300])

        # ------------------------------------------------ 4 bounds and failures
        print("\n4. cost is capped, and anything not judged is said")
        n = len(posts)
        rc, out = run(Q, repo, "--no-cache", "--max-requests", "1")
        sent = [list(p[1]["questions"].values())[0]["instructions"]["path"] for p in posts[n:]]
        check("the cap bounds requests; the one spent goes to the likeliest chunk; "
              "the result says incomplete",
              rc == 2 and sent == ["src/auth.py"] and re.search(r"not asked: 6\b", out)
              and "RESULT incomplete" in out and "cap 1" in out, out)
        n = len(posts)
        rc, out = run("How many files issue tokens?", repo, "--no-cache")
        check("a question jev's lint refuses is refused before anything is sent",
              rc == 1 and "REFUSED" in out and "count" in out and len(posts) == n, out)
        rc, out = run(Q, repo, "--no-cache", env=nokey)
        check("with no key nothing is sent and it says why",
              rc == 1 and "TYPESAFE_API_KEY is not set" in out and len(posts) == n
              and "RESULT failed" in out, out)
        fresh = os.path.join(tmp, "fresh-cache")
        reply["fail"] = [500]
        rc, out = run(Q, repo, "--cache-dir", fresh)
        check("a failed request is counted and the result marked incomplete",
              rc == 2 and re.search(r"6 answered, 1 failed", out)
              and "RESULT incomplete" in out, out)
        n = len(posts)
        rc, out = run(Q, repo, "--cache-dir", fresh)
        check("...and a failure is never cached: the rerun asks that chunk again",
              len(posts) == n + 1 and "RESULT complete" in out, out)

        # ------------------------------------------------ 5 what a search could not see
        # A web app's first use (2026-09-29): the 200 KB cap skipped app.py and
        # its main JSX file, the heart of the codebase, and the plan said only
        # "over size cap 2"; and docs filled the top of the results.
        print("\n5. the plan names each file skipped by size, and the top says when docs fill it")
        rc, out = run("files", repo, env=nokey)
        check("files names big.txt with its size and the flag that reads it, without --show-skipped",
              rc == 0 and re.search(r"over size cap: big\.txt \(\d+ KB\)", out)
              and "--max-file-bytes" in out, out)
        docs = os.path.join(tmp, "docs")
        for k in range(3):
            put(os.path.join(docs, "guide%d.md" % k), "# Guide %d\n\nsession RELEVANT notes\n" % k)
        put(os.path.join(docs, "src", "session.py"), "def open_session():  # MAYBE\n    return 1\n")
        rc, out = run(Q, docs, "--no-cache", "--top", "3")
        check("a top that is all Markdown says --exclude '*.md' searches the code alone",
              rc == 0 and "--exclude '*.md'" in out, out)
        rc, out = run(Q, repo, "--no-cache")
        check("...and a top led by code says nothing of the kind", rc == 0 and "--exclude '*.md'" not in out, out)
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    for f in FAIL:
        print("  FAILED: " + f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
