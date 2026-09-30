# -*- coding: utf-8 -*-
"""jev.py - the one way to ask Jev (TypeSafe's System One model) a question.

Version 1.0 | Deps: Python 3 standard library only | Parent: levjev skill 1.0.3 |
Path: scripts | Filename: jev.py | Created: 2026-09-23

WHAT IT ENFORCES, so that nobody has to remember it (a constraint that has to be
remembered will be violated under time pressure, so make it a property of the system):
    - The model is pinned to jev-1.13.0. Anything else is refused, aliases
      first: jev-latest and jev-preview move on the next release and every
      threshold calibrated today moves with them, with no diff (pin what can drift).
      Moving the pin is an edit to PIN below, with its selftest.
    - The answer is checked against the pin. An answer from any other model is
      refused, not used.
    - No question addresses state by index (`turns[5].text`). The first measured
      run, 2026-09-21, failed exactly there and returned a plausible
      WRONG table - and the vendor's own docs still teach that form. Inline the
      text in structured instructions instead.
    - Questions over one state go in ONE request (one variable at a time,
      made structural: each judgment is an independent number the caller's
      code combines).
    - The literal forms of some prohibited asks are refused: counting ("how
      many"), and hex, RGB and binary literals. The rest of the prohibition
      table - dates, math, double negatives, large unrelated state, generation -
      cannot be checked by code, and this says so rather than pretending.
    - The key is TYPESAFE_API_KEY: from the environment, else from this
      machine's ~/.agents/.env, where the first install put it. It is never
      written, printed or logged. Without it the client is Unavailable and says
      why; a caller then degrades and states what it did not judge.

WHAT IT NEVER DOES
    Combine answers or pick thresholds (the caller's code owns weights and
    gates), generate text, retry forever, or send the key anywhere but TypeSafe
    or this machine.

USAGE
    python jev.py --ping                    one tiny real request: key + pin
    python jev.py --check-question q.json   lint a {id: question} map, no request
"""
import argparse
import json
import os
import re
import sys
import time

PIN = "jev-1.13.0"
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
KEY_ENV = "TYPESAFE_API_KEY"
ENDPOINT_ENV = "JEV_ENDPOINT"       # tests only: loopback addresses only
TYPES = ("noul", "choice", "score")
# Estimates, not the tokenizer: the service's 422 is the authority. They exist
# to refuse the request that is obviously too big before the key is spent.
CHARS_PER_TOKEN = 4
REQUEST_TOKENS, STATE_TOKENS = 64000, 32000

_INDEX = re.compile(r"\[\s*\d+\s*\]|`[^`\n]*\.\d+(?:[.`\[]|$)")
_COUNTING = re.compile(r"\bhow\s+many\b", re.I)
# Three hex digits count only with a letter among them: `#123` is an issue number.
_LITERAL = re.compile(r"(?<![\w&])#(?:[0-9a-fA-F]{6}|(?=[0-9]*[a-fA-F])[0-9a-fA-F]{3})\b"
                      r"|\brgba?\s*\(|\b0x[0-9a-fA-F]+\b|\b0b[01]+\b")


def _asking(q):
    """The text that ASKS - the question and its criteria - apart from data
    inlined beside it in named fields. Evidence quoting `items[0]` or the words
    "how many" is data, not an index or a count Jev is asked to do."""
    ins = q.get("instructions")
    if isinstance(ins, dict) and "question" in ins:
        ins = ins["question"]
    return json.dumps([ins, q.get("criteria")], ensure_ascii=False)


class Refused(Exception):
    """A request this client will not send, or an answer it will not use."""


class Unavailable(Exception):
    """No key, no network, or the service failed. The caller degrades."""


def lint(questions):
    """Every rule this client can check in a question map, as sentences."""
    problems = []
    if not isinstance(questions, dict) or not questions:
        return ["questions must be a non-empty map of id -> question"]
    for qid, q in sorted(questions.items()):
        if not isinstance(q, dict):
            problems.append("%s: a question is an object with type and "
                            "instructions" % qid)
            continue
        kind = q.get("type")
        if kind not in TYPES:
            problems.append("%s: type must be one of %s" % (qid, "/".join(TYPES)))
        if not q.get("instructions"):
            problems.append("%s: no instructions" % qid)
        crit = q.get("criteria")
        if kind == "choice" and not (isinstance(crit, dict) and 2 <= len(crit) <= 255):
            problems.append("%s: a choice needs criteria with 2 to 255 options" % qid)
        if kind == "score" and not (isinstance(crit, list) and 2 <= len(crit) <= 10):
            problems.append("%s: a score needs criteria with 2 to 10 levels" % qid)
        text = _asking(q)
        if _INDEX.search(text):
            problems.append(
                "%s: addresses state by index (%s). The first measured run failed "
                "exactly there with a plausible wrong answer - inline the text in "
                "structured instructions instead" % (qid, _INDEX.search(text).group(0)))
        if _COUNTING.search(text):
            problems.append("%s: asks Jev to count. Count in code; ask one question "
                            "per candidate" % qid)
        # A literal Jev cannot read is a problem wherever it sits, data included:
        # the judgment would rest on it.
        everything = json.dumps([q.get("instructions"), crit], ensure_ascii=False)
        if _LITERAL.search(everything):
            problems.append("%s: carries a hex, RGB or binary literal (%s). Jev cannot "
                            "read those - convert to named buckets first"
                            % (qid, _LITERAL.search(everything).group(0)))
    return problems


def _size_problem(state, questions):
    s = len(json.dumps(state, ensure_ascii=False))
    qs = [len(json.dumps(q, ensure_ascii=False)) for q in questions.values()]
    if (s + sum(qs)) / CHARS_PER_TOKEN > REQUEST_TOKENS:
        return "about %d tokens against the %d-token request limit" % (
            (s + sum(qs)) // CHARS_PER_TOKEN, REQUEST_TOKENS)
    if (s + max(qs)) / CHARS_PER_TOKEN > STATE_TOKENS:
        return "state plus the longest question is about %d tokens against the " \
               "%d-token limit" % ((s + max(qs)) // CHARS_PER_TOKEN, STATE_TOKENS)
    return None


def _endpoint():
    """The override exists for tests and may only point at this machine: the key
    travels wherever the endpoint is."""
    url = os.environ.get(ENDPOINT_ENV, "").strip()
    if not url:
        return ENDPOINT
    if not re.match(r"^http://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?(/|$)", url):
        raise Refused("%s may only point at this machine - the key goes wherever "
                      "the endpoint is" % ENDPOINT_ENV)
    return url


def _key():
    """(key, where it came from). The environment first, then this machine's
    ~/.agents/.env - the file the first install made for it. Reading only
    the environment told every agent on the machine the key was missing while it sat
    there. The value never leaves this function except in the request header."""
    key = os.environ.get(KEY_ENV, "").strip()
    if key:
        return key, "the environment"
    path = os.path.join(os.path.expanduser("~"), ".agents", ".env")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"\s*(?:export\s+)?%s\s*=\s*(.*)$" % KEY_ENV, line)
                if m:
                    v = m.group(1).strip().strip("\"'").strip()
                    if v and v != "PASTE_KEY_HERE":
                        return v, "~/.agents/.env"
    except (OSError, UnicodeDecodeError):
        pass
    return "", ""


def _check_answers(questions, body):
    answers = body.get("answers")
    if not isinstance(answers, dict):
        raise Refused("the response carries no answers map")
    for qid, q in questions.items():
        a = answers.get(qid)
        if not isinstance(a, dict) or a.get("type") != q["type"]:
            raise Refused("answer %s is missing or of the wrong type" % qid)
        if q["type"] == "noul":
            if not isinstance(a.get("noul"), (int, float)) or not 0 <= a["noul"] <= 1:
                raise Refused("answer %s: noul must be a probability" % qid)
        elif q["type"] == "choice":
            if a.get("choice") not in (q.get("criteria") or {}):
                raise Refused("answer %s chose an option that was not offered" % qid)
        elif not isinstance(a.get("score"), (int, float)) or \
                not 0 <= a["score"] <= len(q.get("criteria") or []) - 1:
            raise Refused("answer %s: score is outside its levels" % qid)
    return answers


def ask(state, questions, model=PIN, timeout=30, retries=3):
    """{"answers", "usage", "model", "ms"} for one request, or Refused, or
    Unavailable. Questions over the same state belong in one call."""
    if model != PIN:
        raise Refused("model %r refused: this client is pinned to %s%s. Moving the "
                      "pin is an edit to PIN in jev.py, with its selftest"
                      % (model, PIN, " - an alias moves on the next release"
                         if not re.match(r"^jev-\d+\.\d+\.\d+$", str(model)) else ""))
    problems = lint(questions)
    if problems:
        raise Refused("; ".join(problems))
    too_big = _size_problem(state, questions)
    if too_big:
        raise Refused("request too large: " + too_big)
    url = _endpoint()
    key = _key()[0]
    if not key:
        raise Unavailable("%s is not set on this machine - not in the environment, "
                          "not in ~/.agents/.env - so nothing was asked" % KEY_ENV)
    import urllib.error
    import urllib.request
    data = json.dumps({"state": state, "model": model, "questions": questions},
                      ensure_ascii=False).encode("utf-8")
    delay = 0.5
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Authorization": "Bearer " + key, "Content-Type": "application/json",
            "User-Agent": "jev"})
        t0 = time.time()
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) \
                if url.startswith("http://") else urllib.request.build_opener()
            with opener.open(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            ms = int((time.time() - t0) * 1000)
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 529) and attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:200]
            except Exception:
                pass
            if e.code == 422:
                raise Refused("the service rejected the request: " + detail)
            if e.code in (401, 403):
                raise Unavailable("the key in %s was rejected (%d)" % (KEY_ENV, e.code))
            raise Unavailable("the service answered %d %s" % (e.code, detail[:80]))
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise Unavailable("could not reach the service: %s"
                              % str(getattr(e, "reason", e))[:120])
    if body.get("model") != model:
        raise Refused("answered by %r, pinned %s - not used" % (body.get("model"), model))
    return {"answers": _check_answers(questions, body), "usage": body.get("usage", {}),
            "model": body["model"], "ms": ms}


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ping", action="store_true")
    ap.add_argument("--model", default=PIN)
    ap.add_argument("--check-question")
    a = ap.parse_args(argv)
    if a.check_question:
        try:
            with open(a.check_question, encoding="utf-8") as fh:
                questions = json.load(fh)
        except (OSError, ValueError) as e:
            print("REFUSED cannot read %s: %s" % (a.check_question, e))
            return 2
        problems = lint(questions)
        for p in problems:
            print("REFUSED " + p)
        if not problems:
            print("ok %d question(s) pass every rule this client can check - the "
                  "rest of the prohibition table is yours to read" % len(questions))
        return 1 if problems else 0
    if a.ping:
        q = {"is_greeting": {"type": "noul",
                             "instructions": "Is this message a greeting?"}}
        try:
            r = ask("Hello there!", q, model=a.model)
        except Refused as e:
            print("REFUSED %s" % e)
            return 2
        except Unavailable as e:
            print("UNAVAILABLE %s" % e)
            return 2
        print("ok %s answered in %d ms (%s input tokens): noul %.2f - key from %s"
              % (r["model"], r["ms"], r["usage"].get("input_tokens", "?"),
                 r["answers"]["is_greeting"]["noul"], _key()[1]))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
