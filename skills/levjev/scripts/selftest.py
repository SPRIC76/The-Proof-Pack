# -*- coding: utf-8 -*-
"""selftest.py - the cases jev.py must not regress on.

Version 1.0 | Deps: Python 3 standard library only | Parent: levjev skill 1.0.0 (formerly jev) |
Path: scripts | Filename: selftest.py | Created: 2026-09-24 07:58 ET

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
            "colour": {"type": "noul", "instructions": {
                "colour": "#ff0000", "question": "Is `colour` a warning colour?"}}}))
        rc, out = cli("--check-question", qf, env=nokey)
        check("indexing state, counting, and a hex literal are each refused by name",
              rc == 1 and "by_index: addresses state by index" in out
              and "dotted: addresses state by index" in out
              and "counting: asks Jev to count" in out
              and "colour: carries a hex, RGB or binary literal" in out, out)
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
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    for f in FAIL:
        print("  FAILED: " + f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
