# -*- coding: utf-8 -*-
# The strings below are fixtures Mutate reads as data, not things this file does:
# mutate: fixture
"""selftest.py - the cases jev.py must not regress on.

Version 1.0 | Deps: Python 3 standard library only | Parent: levjev skill 1.0.6 (formerly jev) |
Path: scripts | Filename: selftest.py | Created: 2026-09-24

Run:  python scripts/selftest.py       (exit 0 = all green)

A fake TypeSafe on this machine stands in for the service: these prove what is
SENT and what is done with the answer, never what Jev would say. The client is
driven the two ways its users reach it - the command line (--ping,
--check-question) and ask(), which a caller's code imports - each in a fresh
process with a home of its own, because this machine's real key sits in
~/.agents/.env and no test may ever read it.

Moved here 2026-09-24 from verafox's selftest case 28, where these rules were
first proved by breaking each on purpose; Verafox keeps the cases about its own
--judge.
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
JEV = os.path.join(HERE, "jev.py")
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + (
        ("\n         " + detail.replace("\n", "\n         ")) if
        (detail and not cond) else ""))


# A skill is modular: any agent that reads SKILL.md can run it, in any workflow,
# beside any other skill or none (the owner, 2026-09-30). So a SKILL.md names a
# neighbor by its job, never by its name, except on the one line that declares
# an optional dependency; and it names an agent host only in an install section
# that names at least two, as examples. The same check is in each of the pack's
# self-tests, so each skill holds it alone. Names are the pack's and other public
# skills', anywhere; and any skill installed beside this one, where a line points
# at it as a skill: `name`, (name) or "name skill".
KNOWN_SKILLS = ("verafox", "levjev", "testcatch", "measure-in-the-browser",
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


def put(path, text):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def cli(*args, env=None):
    p = subprocess.run([sys.executable, JEV] + list(args), capture_output=True,
                       timeout=60, env=env)
    return p.returncode, p.stdout.decode("utf-8", "replace") + \
        p.stderr.decode("utf-8", "replace")


# ask() as a caller's code uses it: import the client, ask, print what came back.
DRIVER = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import jev
state, questions = json.loads(open(sys.argv[2], encoding="utf-8").read())
try:
    r = jev.ask(state, questions)
    print("ANSWERS " + json.dumps(r["answers"], sort_keys=True))
except jev.Refused as e:
    print("REFUSED %s" % e)
except jev.Unavailable as e:
    print("UNAVAILABLE %s" % e)
"""


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    tmp = tempfile.mkdtemp(prefix="jevselftest-")
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
            answers = {}
            for q, spec in body["questions"].items():
                if spec["type"] == "choice":
                    answers[q] = {"type": "choice",
                                  "choice": reply.get("choice", sorted(spec["criteria"])[0])}
                else:
                    answers[q] = {"type": "noul", "noul": reply["p"].get(q, 0.99)}
            out = json.dumps({"model": reply.get("model", body["model"]),
                              "answers": answers,
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
                JEV_ENDPOINT="http://127.0.0.1:%d/v1/systemone"
                % srv.server_address[1], USERPROFILE=home, HOME=home)
    nokey = dict(fake)
    del nokey["TYPESAFE_API_KEY"]
    driver = os.path.join(tmp, "driver.py")
    put(driver, DRIVER)

    def api(state, questions, env):
        qf = os.path.join(tmp, "ask.json")
        put(qf, json.dumps([state, questions]))
        p = subprocess.run([sys.executable, driver, HERE, qf], capture_output=True,
                           timeout=60, env=env)
        return p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")
    try:
        # ------------------------------------------------ 1 the key and the pin
        print("\n1. --ping: one pinned question, and the key never shown")
        rc, out = cli("--ping", env=nokey)
        check("with no key, nothing is asked and it says why",
              rc == 2 and "UNAVAILABLE" in out and "TYPESAFE_API_KEY is not set" in out
              and not posts, out)
        rc, out = cli("--ping", env=fake)
        check("--ping asks one question of the pinned model and reads it back",
              rc == 0 and "ok jev-1.13.0" in out and len(posts) == 1
              and posts[-1][1].get("model") == "jev-1.13.0", out)
        check("the key travels only in the header and is never printed",
              posts and posts[-1][0] == "Bearer test-key-not-real"
              and "test-key-not-real" not in out, out)
        n = len(posts)
        rc, out = cli("--ping", "--model", "jev-latest", env=fake)
        check("the moving alias is refused before anything is sent",
              rc == 2 and "REFUSED" in out and "alias" in out and len(posts) == n, out)
        reply["model"] = "jev-1.14.0"
        rc, out = cli("--ping", env=fake)
        check("an answer from any model but the pin is refused, not used",
              rc == 2 and "REFUSED" in out and "answered by" in out, out)
        del reply["model"]

        # ------------------------------------------------ 2 the service, safely
        print("\n2. a busy service, a foreign endpoint, and where the key lives")
        n = len(posts)
        reply["fail"] = [429, 529]
        rc, out = cli("--ping", env=fake)
        check("a busy service is retried with backoff, then read",
              rc == 0 and len(posts) - n == 3 and "ok jev-1.13.0" in out, out)
        n = len(posts)
        rc, out = cli("--ping", env=dict(
            fake, JEV_ENDPOINT="http://example.invalid/v1/systemone"))
        check("the endpoint override may only point at this machine - the key "
              "goes wherever it points",
              rc == 2 and "may only point at this machine" in out
              and "could not reach" not in out and len(posts) == n, out)
        # Where the first install put the key. Reading only the
        # environment said "not set" while it sat there.
        put(os.path.join(home, ".agents", ".env"),
            "# TypeSafe\nTYPESAFE_API_KEY=\"file-key-not-real\"\n")
        rc, out = cli("--ping", env=nokey)
        check("with no key in the environment, the one in ~/.agents/.env is used "
              "- and never printed", rc == 0 and posts[-1][0] ==
              "Bearer file-key-not-real" and "file-key-not-real" not in out
              and "key from ~/.agents/.env" in out, out)
        # The pack's review (2026-09-30): a 401 said "the key in TYPESAFE_API_KEY
        # was rejected" whichever place the key had come from. It names the
        # place now - the environment, or the file by its path - never the key.
        reply["fail"] = [403]
        rc, out = cli("--ping", env=nokey)
        check("a rejected key from the file says so by the file's path, never the key",
              rc == 2 and "UNAVAILABLE" in out and "rejected" in out
              and "~/.agents/.env" in out and "file-key-not-real" not in out, out)
        reply["fail"] = [401]
        rc, out = cli("--ping", env=fake)
        check("...and one from the environment says the environment",
              rc == 2 and "UNAVAILABLE" in out and "rejected" in out
              and "the environment" in out and "test-key-not-real" not in out, out)
        n = len(posts)
        put(os.path.join(home, ".agents", ".env"), "TYPESAFE_API_KEY=\"PASTE_KEY_HERE\"\n")
        rc, out = cli("--ping", env=nokey)
        check("...while the template's placeholder counts as no key",
              rc == 2 and "UNAVAILABLE" in out and len(posts) == n, out)

        # ------------------------------------------------ 3 the question rules
        print("\n3. --check-question refuses what Jev must never be asked")
        qf = os.path.join(tmp, "q.json")
        put(qf, json.dumps({
            "by_index": {"type": "noul", "instructions":
                         "Does `turns[5].text` ask for a refund?"},
            "dotted": {"type": "noul", "instructions":
                       "Does `ticket.messages.0.text` ask for a refund?"},
            "counting": {"type": "noul", "instructions":
                         "How many messages mention a refund?"},
            "color": {"type": "noul", "instructions": {
                "color": "#ff0000", "question": "Is `color` a warning color?"}}}))
        rc, out = cli("--check-question", qf, env=nokey)
        check("indexing state, counting, and a hex literal are each refused by name",
              rc == 1 and "by_index: addresses state by index" in out
              and "dotted: addresses state by index" in out
              and "counting: asks Jev to count" in out
              and "color: carries a hex, RGB or binary literal" in out, out)
        put(qf, json.dumps({"clean": {"type": "noul", "instructions": {
            "message": "I want my money back - item [0] on the receipt",
            "question": "Does `message` ask for a refund?"}}}))
        rc, out = cli("--check-question", qf, env=nokey)
        check("...while data inlined beside the question may quote anything",
              rc == 0 and "ok 1 question(s)" in out, out)

        # ------------------------------------------------ 4 ask(), as code calls it
        print("\n4. ask(): one request per state, checked answers, bounded size")
        qs = {"refund": {"type": "noul", "instructions": {
                  "message": "I want my money back",
                  "question": "Does `message` ask for a refund?"}},
              "tone": {"type": "choice", "instructions": {
                  "message": "I want my money back",
                  "question": "What is the tone of `message`?"},
                  "criteria": {"calm": "no heat", "angry": "heated"}}}
        n = len(posts)
        out = api("A support message.", qs, fake)
        check("every question about one state goes in ONE request",
              out.startswith("ANSWERS") and len(posts) == n + 1
              and sorted(posts[-1][1]["questions"]) == ["refund", "tone"], out)
        n = len(posts)
        reply["choice"] = "sarcastic"
        out = api("A support message.", qs, fake)
        check("a choice the question never offered is refused, not used",
              out.startswith("REFUSED") and "not offered" in out, out)
        del reply["choice"]
        n = len(posts)
        out = api("word " * 40000, {"q": qs["refund"]}, fake)
        check("an obviously oversize request is refused before anything is sent",
              "REFUSED request too large" in out and len(posts) == n, out[:300])

        # ------------------------------------------------ 5 what SKILL.md shows
        # The pack's review (2026-09-30): SKILL.md showed a question as
        # {"message": ..., "question": ...} - a shape lint() refuses (no type, no
        # instructions). Every JSON object the skill's own text shows as a
        # question map must pass --check-question, offline, or the text teaches
        # a request the client will not send.
        print("\n5. every question shape SKILL.md shows is one --check-question accepts")
        with open(os.path.join(HERE, "..", "SKILL.md"), encoding="utf-8") as fh:
            skill_text = fh.read()
        shapes = []
        pos = 0
        while True:
            i = skill_text.find('{"', pos)
            if i < 0:
                break
            depth, j, in_str = 0, i, False
            while j < len(skill_text):
                ch = skill_text[j]
                if in_str:
                    if ch == "\\":
                        j += 1
                    elif ch == '"':
                        in_str = False
                elif ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            try:
                doc = json.loads(skill_text[i:j + 1])
            except ValueError:
                doc = None
            if isinstance(doc, dict):
                shapes.append((skill_text.count("\n", 0, i) + 1, doc))
            pos = j + 1 if j > i else i + 2
        refused = []
        for line, doc in shapes:
            sf = os.path.join(tmp, "shape.json")
            put(sf, json.dumps(doc))
            rc, out = cli("--check-question", sf, env=nokey)
            if rc != 0:
                refused.append("SKILL.md:%d %s" % (line, out.strip()[:160]))
        check("SKILL.md shows at least one question map, and --check-question accepts "
              "every one it shows", shapes and not refused,
              "; ".join(refused) or "no JSON object found in SKILL.md")
        check("...with a noul, a choice and a score among them",
              {q.get("type") for _, d in shapes for q in d.values()
               if isinstance(q, dict)} >= {"noul", "choice", "score"},
              " | ".join(" ".join(sorted(d)) for _, d in shapes))
        # ------------------------------------------------ 6 --help says what each flag does
        # The pack's second review (2026-09-30): jev.py --help printed --ping,
        # --model and --check-question bare.
        print("\n6. jev.py --help says what every flag does")

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

        rc, out = cli("--help", env=nokey)
        bare6 = bare_flags(out)
        check("RED: --help gives --ping, --model and --check-question a line of help",
              rc == 0 and "--check-question" in out and not bare6,
              " ".join(bare6) or out[-800:])

        # ------------------------------------------------ 7 no sibling by name, no one host
        print("\n7. SKILL.md names no other skill and frames itself for no one host")
        agnostic_cases(os.path.join(HERE, os.pardir, "SKILL.md"),
                       ("levjev", "jev"))

    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    for f in FAIL:
        print("  FAILED: " + f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
