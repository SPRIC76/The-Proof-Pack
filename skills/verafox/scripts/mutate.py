# Deps: python3.10+ stdlib, git optional | Path: skills/verafox/scripts | Filename: mutate.py | Created: 2026-09-29
# -*- coding: utf-8 -*-
"""mutate.py - Mutate, the Verafox stage that inspects, collates and absorbs
outside skills, plugins and tools, and keeps what was absorbed current.

The brief, 2026-09-29: read-only inspect and inventory, then collate, distill,
mutate, calibrate and evolve items, assets and componentry for multi-platform,
multi-agent functionality, capability and use on the user's behalf.

WHAT IT DOES
    inventory <folder>   walk a clone or folder of skills, plugins or tools and
                         report per skill: folder versus frontmatter name, the
                         description's length, style and unquoted ": ", every
                         file it references and any reference OUTSIDE its own
                         folder, licence files per repo and per skill, the git
                         SHA and remote, red flags with file:line and a
                         category, defensive mentions counted apart, the
                         binaries, CLIs, env vars and MCP servers it names and
                         whether each is here, and its size. Markdown by
                         default, --json for machines, --out to a file.
    collate <inv.json>   overlap with skills already homed (--home DIR): names,
                         description tokens and trigger words, so a human or
                         an agent decides keep, absorb or skip per row.
    ledger               read or write the Mutate ledger: what was absorbed
                         from where, at which commit, under which licence, what
                         was left out and why, the verdict and the date. A row
                         without a reason is refused; a hand-edited row without
                         one fails the listing.
    evolve               for each ledger row with a git remote, compare its
                         pinned commit to the upstream head. Read-only
                         `git ls-remote`, and ONLY with --online; without it the
                         command says what it would check and touches nothing.

HOW IT READS A LINE
    Code, prose (markdown, text, a file with no extension) and data (JSON,
    YAML, CSV) are read apart; a file with a #! line is code whatever its
    name. A URL in code flags when the line loads it or names it as one
    (VENDOR_URL = ...); elsewhere it is a link. Files under tests/, fixtures/
    and the like, and a *selftest.py, are set apart as in_tests - listed, not
    flagged - unless the skill's own markdown names the file, because then the
    agent runs it. A code file sets its own matches apart - a self-test's
    fixture strings, a detector table - with a comment line of its own:
    `mutate: fixture` in its first ten lines for the whole file, or
    `mutate: fixture-begin` / `mutate: fixture-end` around a region. Those
    hits are listed under the file's name as the file's own claim, prose is
    never set apart this way, and a file without the pragma reads as before. In
    prose a match counts apart as defensive when a prohibition before it in
    its clause covers it ("never run `git push --force`"), or when it sits
    under an anti-pattern heading ("Red flags", "Common mistakes"); injection
    text also when it is quoted or its sentence carries a defensive cue. Any
    match on the line that nothing covers still flags. The calibration that
    set these is held by mutate_selftest.py, case 4b.

WHAT IT WILL NEVER DO
    Write, move or touch anything under the folder it inspects. Run, install or
    import anything it finds there. Make a network request outside
    `evolve --online`. Print the value of an environment variable: presence
    only. Decide for you: every flag is a line to read, with its file and line,
    and the verdict stays a human's or an agent's, recorded in the ledger with
    its reason.

EXIT CODES
    0  ran, nothing to act on       1  ran, findings       2  could not run
    Every command ends in a RESULT: line.

USAGE
    python mutate.py inventory ~/clones/ten [--json] [--out inv.json] [--skill NAME]
    python mutate.py collate inv.json --home ~/.agents/skills
    python mutate.py ledger --ledger C:\\path\\mutate-ledger.json [--json]
    python mutate.py ledger --ledger ... --add --source URL --commit SHA --licence MIT \\
        --absorbed "what -> where" --left-out "what: why" --verdict absorbed --reason "why"
    python mutate.py evolve --ledger ... [--online]
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

DEFAULT_LEDGER = os.path.join(os.path.expanduser("~"), ".agents", "mutate-ledger.json")
VERDICTS = ("absorbed", "kept-candidate", "skipped")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2",
              ".ttf", ".otf", ".eot", ".wasm", ".exe", ".dll", ".so", ".dylib",
              ".zip", ".tgz", ".gz", ".bz2", ".xz", ".7z", ".pdf", ".mp4", ".webm",
              ".mp3", ".wav", ".pyc", ".pack", ".idx", ".jar", ".class", ".bin",
              ".sqlite", ".db"}
# Code: a URL here may be requested (see _URL_LOADED), not only followed by a
# reader. A file with no extension is code when its first line is #!.
CODE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".sh", ".bash",
            ".zsh", ".ps1", ".psm1", ".cmd", ".bat", ".rs", ".go", ".rb", ".php",
            ".swift", ".kt", ".java", ".cs", ".pl", ".lua"}
PROSE_EXT = {".md", ".mdx", ".txt", ".rst", ""}
MAX_FILE = 2 * 1024 * 1024
MAX_REPO_LEVEL_FILES = 400

# The tables below hold every string the detectors hunt, so a read of this
# folder flagged them (the pack's reviewer, 2026-09-30); see fixture_spans.
# mutate: fixture-begin
_URL = re.compile(r"https?://[^\s\"'`)>\]\\]+")
_SAFE_HOSTS = ("w3.org", "json-schema.org", "schemas.", "schema.org", "opensource.org",
               "spdx.org", "example.com", "example.org", "example.invalid", "example.net",
               "purl.org", "creativecommons.org", "apache.org/licenses", "choosealicense",
               "keepachangelog", "semver.org", "shields.io", "badgen.net", "xmlns",
               "mit-license.org", "unlicense.org")
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "[::1]")
_SETUP_HEADING = re.compile(r"setup|install|prereq|getting started|activat|bootstrap|"
                            r"before you|first run|step 1|quick ?start|requirements",
                            re.I)
_WRITE_VERB = re.compile(
    r"\b(write|writes|written|writing|edit|edits|edited|editing|add|adds|added|"
    r"adding|append|appends|create|creates|created|update|updates|updated|modify|"
    r"modifies|set up|insert|inserts|merge|merges|put|save|saves|overwrite|"
    r"overwrites|register|registers|inject|injects|trim|trims|compress|rewrite|"
    r"rewrites|generate|generates|move|moves|remove|removes|delete|deletes|strip|"
    r"place|places|drop|drops|configure|configures|patch|patches|install|installs|"
    r"copy|copies|junction|symlink)\b|>>?\s*[~./%$]", re.I)
# A defensive cue in an injection match's own sentence makes it a mention (the
# addyosmani lines that say page text is data). Inherited as a search of the
# whole line with one trailing \b, which made e.g., defence, sanitize and
# guards unmatchable and let "report" anywhere on a line excuse an injection
# in another sentence; each cue now ends where its word does.
_DEFENSIVE = re.compile(
    r"\b(?:never\s+(?:interpret|obey|follow|execute|treat|act|run|trust)|treat\s+(?:it|them|"
    r"this|that|these|as)|as\s+data|data,?\s+not|not\s+(?:an?\s+)?(?:action|"
    r"instruction|command)s?|report(?:s|ed|ing)?|threats?|attacks?|injections?|"
    r"defen[cs]\w*|guard\w*|sanitiz\w*|refus\w*|reject\w*|detect\w*|flag(?:s|ged)?|"
    r"suspicious|malicious|untrusted|look(?:s|ed)?\s+like|for\s+example|such\s+as|"
    r"if\s+[^.\n]{0,40}\bcontains?|warn(?:s|ing)?|red\s+flags?|do\s+not\s+(?:follow|"
    r"obey|execute|act\s+on)|ignore\s+them)\b|\be\.g\.|\bi\.e\.", re.I)
# A prohibition before a match, in its clause, covers it: "never run `rm -rf`".
# "Don't forget to run it" is an instruction, so forget/skip/miss are not one.
_PROHIBIT = re.compile(
    r"\b(?:never|don'?t|do\s+not|must\s+not|mustn'?t|should\s+not|shouldn'?t|"
    r"avoid(?:s|ing)?|refuse\s+to|no\s+need\s+to|not\s+allowed\s+to|forbidden)\b"
    r"(?!\s+(?:forget|skip|miss|fail|hesitate|neglect|wait)\b)", re.I)
_NO_BEFORE = re.compile(r"\b(?:no|not|without|zero)\s+(?:\w+\s+)?[`\"']?$", re.I)
# A string wrapped across two code lines carries its determiner on the line
# above: "names no " + "commit this repository has" (Verafox's featuremap.py,
# the pack's review 2026-09-30). The line above, its closing quote and joining
# operator set aside, ends in the word the detector's own lookbehind would read.
_DETERMINER_END = re.compile(
    r"\b(?:the|a|an|this|that|each|every|which|base|merge|first|last|new|one|your|its|"
    r"no|any|not|without)\s*[\"'`]?\s*[+,\\]?\s*$", re.I)
# "upload it in your skill settings" is the user installing a pack, not data
# leaving; the sentence may wrap, so the next prose line is read with it (the
# pack's own README, 2026-09-30).
_UPLOAD_SETTINGS = re.compile(r"[^.\n]{0,60}\bsettings\b", re.I)
# A pack's README says how to install the pack itself; that line is the
# pack's, not a fetch of someone else's (the pack's review, 2026-09-30).
_OWN_INSTALL = re.compile(r"\bnpx\s+skills\s+add\s+[\w.-]+/[\w.-]+", re.I)
_CLAUSE_END = re.compile("[.;:!?](?:\\s|$)|\\s[-–—]+\\s|"
                         "\\b(?:then|but|instead|otherwise)\\b", re.I)
_SENTENCE_END = re.compile(r"[.;!?](?:\s|$)")
# A heading that lists what not to do covers the lines under it - but not a
# line that says always / must, nor the fix after 'instead:' or an arrow.
# 'Known Pitfalls' in 832 Composio skills lists instructions ("Always include
# memory in RUBE_MULTI_EXECUTE_TOOL calls"), so a pitfall heading alone is not
# one.
_ANTI_HEADING = re.compile(
    r"red\s+flags?|anti-?patterns?|common\s+(?:mistakes|pitfalls|rationali[sz]ations)|"
    r"\bdon'?ts\b|warning\s+signs|what\s+not\s+to|bad\s+examples?|\bmistakes\b|"
    r"\bnever\b|\bdo\s+not\b", re.I)
_AFFIRM = re.compile(r"\b(?:always|must|make\s+sure|be\s+sure|remember\s+to|ensure)\b",
                     re.I)
_FIX_BEFORE = re.compile("\\b(?:instead|fix|correct|better|do\\s+this|use)\\b\\s*[:\\-]|"
                         "✅|→|->|=>", re.I)
_QUOTED = re.compile("\"[^\"\n]+\"|“[^”\n]+”|`[^`\n]+`|"
                     "(?<!\\w)'[^'\n]{8,}'(?!\\w)")
# A line that starts a new item does not carry the verb of the line above.
_NEW_ITEM = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|#|\||>|```|~~~)")
_FETCHED = re.compile(r"\b(?:fetch\w*|download\w*|curl|wget|visit\w*)\b", re.I)
_GIT_CONTEXT = re.compile(r"\b(?:git|branch(?:es)?|repo(?:sitory)?|push|merge|PRs?|pull\s+"
                          r"requests?|staged?|diff|changes|history|worktrees?|commits)\b",
                          re.I)
_HTTP_WORDS = re.compile(r"\b(?:header|headers|http|https|status|endpoint|server|api|"
                         r"request|cache|cookie|csp|json|payload|body|bodies|cors)\b", re.I)
# A URL in code is requested when its line loads it or names it as one;
# otherwise (a data key, a comment, a docstring) it is a link.
_URL_NAMED = re.compile(r"(?:url|uri|endpoint|host|api|base|origin|server|webhook|"
                        r"manifest|src|href|image|cdn|domain)\w*[\"'\]]?\s*[:=(]\s*"
                        r"[\"'`(]?\s*$", re.I)
_URL_LOADED = re.compile(
    r"\b(?:src|href|action)\s*=|<(?:script|link|img|iframe|source|video|audio)\b|\burl\(|"
    r"\bimport\b|\brequire\(|\bfetch\w*|\.(?:get|post|put|patch|request|open)\(|"
    r"\brequests?\b|\bnew\s+URL\(|WebSocket|XMLHttpRequest|\bdownload\w*|\bcurl\b|"
    r"\bwget\b|Invoke-WebRequest|Invoke-RestMethod|\biwr\b|\birm\b|urlopen|\baxios\b|"
    r"\bgit\s+(?:clone|ls-remote|fetch|pull)\b|\bnpx\b|\bpip\s+install\b|"
    r"\bnpm\s+install\b", re.I)
# Tests and fixtures do not run at load or use: their hits are set apart,
# unless the skill's own markdown names the file (then the agent runs it).
# A *selftest.py is a test file by name, as a test_*.py is.
_TEST_PATH = re.compile(r"(?:^|/)(?:tests?|__tests__|specs?|fixtures|__fixtures__|testdata|"
                        r"test-fixtures|e2e)/|(?:^|/)[^/]*\.(?:test|spec)\.\w+$|"
                        r"(?:^|/)[^/]*_test\.\w+$|(?:^|/)test_[^/]*\.py$|"
                        r"(?:^|/)[^/]*selftest\.\w+$")
CODE_NAMES = {"Dockerfile", "Makefile", "Rakefile", "Justfile"}
# Injection detectors whose text IS the negation: a prohibition cannot excuse them.
NEG_IS_FINDING = {"do not read", "do not ask or pause for permission",
                  "do not search for config", "do not consult the user"}

# ---------------------------------------------------------------- detectors
# (category, label, regex, scope). scope: any | code (code files only) |
# verb-md (in prose, only with a write verb on the line or the line it
# continues) | verb (the same, in code too: a name that is only an edit when
# something writes it) | git-context (a git word on the line or its heading) |
# not-http (skipped on a line about HTTP) | after-fetch (kept only when a
# fetch word comes before it, on its line or the line it continues). Each
# category has a fixture home in mutate_selftest.py; case 4b holds the
# calibration against an audit of ten public repositories.
# Telemetry is what reports on the user: a tracker, a beacon that is loaded or
# sent, an update or version check, a setting that turns reporting on or off
# (SUPERPOWERS_DISABLE_TELEMETRY), analytics that are called or imported. The
# bare words were 300+ false flags in the calibration: 'analytics dashboard',
# a drone fleet's 'telemetry' panel in a CSV, a CSS class '.evidence-beacon'.
_TELEMETRY = (
    r"\bsendBeacon\b|\b(?:send|sends|load|loads|fires?|ping|pings|image|pixel|url)\b"
    r"[^.\n]{0,30}\bbeacons?\b|\bbeacons?\b[^.\n]{0,30}\b(?:image|pixel|url|request|ping|"
    r"endpoint)\b|\btracking\s+pixels?\b|DO_NOT_TRACK|\bposthog\b|\bmixpanel\b|"
    r"\bsegment\.(?:io|com)\b|\bgtag\(|\bgoogletagmanager\b|\bgoogle-analytics\b|"
    r"\bplausible\.io\b|\bumami\.is\b|\butm_source\b|\bupdate[-_ ]?checks?\b|"
    r"\bchecks?[-_ ]?(?:for[-_ ]?)?updates?\b|UPDATE_AVAILABLE|\bversion[-_ ]?checks?\b|"
    r"\bapi/version\b|\bphones?\s+home\b|\bstaleness[-_ ]?checks?\b[^.\n]{0,40}"
    r"\b(?:upstream|remote|latest|release|vendor|version|update)s?\b|"
    r"\b(?:upstream|remote|latest|release|vendor|version|update)s?\b[^.\n]{0,40}"
    r"\bstaleness[-_ ]?checks?\b|"
    r"\b(?:anonymous|anonymi[sz]ed|usage)\s+(?:telemetry|analytics|data|statistics|stats|"
    r"metrics)\b|\b(?:send|sends|sending|collect|collects|collecting)\b[^.\n]{0,40}"
    r"\b(?:telemetry|analytics)\b|[A-Z0-9]_TELEMETRY\b|\bTELEMETRY_[A-Z]|"
    r"\b(?:disable[sd]?|enable[sd]?|opt[- ]?(?:out|in)|report\w*)\b[^.\n]{0,30}"
    r"\btelemetry\b|\btelemetry\b[^.\n]{0,20}\b(?:enabled|disabled|endpoint|url|"
    r"opt[- ]?out|collected|is\s+sent)\b|\"(?:telemetry|analytics)\"\s*:|"
    r"\banalytics\.(?:track|identify|page|capture|init|send|log)\w*\s*\(|"
    r"\b(?:import|require)\b[^\n]{0,80}\banalytics\b")
DETECTORS = [
    ("network", "fetch verb",
     re.compile(r"\b(?:curl|wget|Invoke-WebRequest|Invoke-RestMethod|iwr|irm)\b"), "any"),
    ("network", "HTTP client call",
     re.compile(r"\b(?:requests\.(?:get|post|put|patch|delete|head|request|Session)|"
                r"urllib\.request|urlopen\(|http\.client|httpx\.|aiohttp|axios\.|"
                r"fetch\(|net/http|reqwest::|ureq::|Net::HTTP|HttpClient|WebClient|"
                r"XMLHttpRequest|http\.get\(|https\.get\(|https\.request\()"), "any"),
    ("install", "package install",
     re.compile(r"\b(?:npm\s+(?:i|install|ci|add)\b|npx\b|pnpm\b|yarn\s+(?:add|install|dlx)\b|"
                r"bun\s+(?:add|install|x)\b|pip3?\s+install\b|pipx\b|uvx?\s+(?:tool\s+)?"
                r"install\b|uvx\b|poetry\s+install\b|brew\s+install\b|cargo\s+(?:install|"
                r"build)\b|go\s+(?:install|get|mod\s+download)\b|winget\s+install\b|"
                r"choco\s+install\b|apt(?:-get)?\s+install\b|gem\s+install\b|corepack\b)|"
                r"(?<![\w/])/plugin\s+(?:install|marketplace\s+add)\b"), "any"),
    ("install", "unpinned @latest", re.compile(r"@latest\b"), "any"),
    ("exec", "pipe into a shell",
     re.compile(r"\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b|\|\s*iex\b|\|\s*Invoke-Expression\b"),
     "any"),
    ("exec", "execution policy bypass", re.compile(r"-ExecutionPolicy\s+Bypass"), "any"),
    ("exec", "binary download or run",
     re.compile(r"releases/download/|https?://\S+\.(?:exe|msi|dmg|pkg|deb|rpm|AppImage)\b|"
                r"\b(?:download\w*|curl|wget|Invoke-WebRequest|iwr|fetch)\b[^\n]*"
                r"\.(?:exe|msi|dmg|pkg|deb|rpm|AppImage)\b|\.(?:exe|msi|dmg|pkg|deb|rpm|"
                r"AppImage)\b[^\n]*\b(?:download\w*|curl|wget|Invoke-WebRequest|iwr)\b|"
                r"\b(?:npx|curl|wget|Invoke-WebRequest|iwr)\b[^\n]*\.(?:tgz|tar\.gz|zip)\b|"
                r"\.(?:tgz|tar\.gz|zip)\b[^\n]*\b(?:npx|curl|wget|Invoke-WebRequest|iwr)\b|"
                r"\bStart-Process\b|\bchmod\s+\+x\b|downloaded\s+(?:once\s+)?on\s+first\s+"
                r"run|self-contained\s+binary"), "any"),
    ("exec", "shell=True runs a string through the shell",
     re.compile(r"\bshell\s*=\s*True\b"), "code"),
    ("config", "agent settings file",
     re.compile(r"settings(?:\.local)?\.json|\.mcp\.json|\bmcp\.json|known_marketplaces|"
                r"installed_plugins\.json|claude_desktop_config"), "verb-md"),
    ("config", "agent instruction file",
     re.compile(r"\b(?:CLAUDE|AGENTS|GEMINI|CURSOR|COPILOT)\.md\b"), "verb-md"),
    ("config", "hook registration",
     re.compile(r"\b(?:SessionStart|SubagentStart|PreToolUse|PostToolUse|UserPromptSubmit|"
                r"PreCompact|SessionEnd)\b|\bhooks?\.json\b|\"hooks\"\s*:"), "any"),
    ("config", "git config write",
     re.compile(r"\bgit\s+config\b(?!\s+--get)|core\.hooksPath|hooksPath|"
                r"\.git/hooks|merge\.[\w-]+\.driver"), "any"),
    # named in prose or a comment it is a fact about git; edited, it is a write
    ("config", "git attributes edit", re.compile(r"\.gitattributes\b"), "verb"),
    ("config", "environment variable set",
     re.compile(r"(?:^|[\s;`(])(?:export|setx)\s+[A-Z_][A-Z0-9_]*=|^\s*set\s+[A-Z_][A-Z0-9_]*="
                r"|\$env:[A-Z_][A-Z0-9_]*\s*=(?!=)|os\.environ\[[^\]]+\]\s*=(?!=)|"
                r"os\.environ\.setdefault\(|os\.putenv\(|process\.env\.[A-Z_][A-Z0-9_]*\s*=(?!=)"
                r"|process\.env\[[^\]]+\]\s*=(?!=)|\[Environment\]::SetEnvironmentVariable|"
                r"\.(?:bashrc|zshrc|bash_profile)\b|\bshell\s+profile\b"), "any"),
    ("config", "path outside the skill folder",
     re.compile(r"~/\.[\w.-]+|\$HOME/\.[\w.-]+|~\\\.[\w.-]+|%(?:APPDATA|LOCALAPPDATA|"
                r"USERPROFILE)%|\$XDG_(?:CONFIG|DATA|CACHE)_HOME|\bjunctions?\s+(?:directly\s+)?"
                r"in(?:to)?\b"), "verb-md"),
    ("config", ".gitignore edit", re.compile(r"\.gitignore\b"), "verb-md"),
    ("telemetry", "telemetry, analytics or an update check",
     re.compile(_TELEMETRY, re.I), "any"),
    ("injection", "ignore prior instructions or data",
     re.compile(r"\bignore\s+(?:all\s+|any\s+|the\s+|your\s+)?(?:previous|prior|earlier|above|"
                r"pretrained|pre-trained|existing|other|system)\s+(?:data|instructions?|"
                r"rules?|guidelines?|prompts?|training|knowledge|context)\b", re.I), "any"),
    ("injection", "do not read",
     re.compile(r"\b(?:do\s+not|don'?t|never)\s+read\b[^.\n]{0,60}\b(?:until|before|unless|"
                r"first)\b", re.I), "any"),
    ("injection", "without confirmation",
     re.compile(r"\bwithout\s+(?:asking|confirmation|confirming|permission|user\s+"
                r"confirmation|the\s+user'?s?\s+(?:confirmation|permission))\b", re.I),
     "any"),
    ("injection", "do not ask or pause for permission",
     re.compile(r"\b(?:do\s+not|don'?t|never)\s+(?:ask|pause|stop|wait)\b[^.\n]{0,40}"
                r"\b(?:confirm|confirmation|permission|approval|user|check\s+in|check\s+with)"
                r"\b", re.I), "any"),
    ("injection", "just do it", re.compile(r"\bjust\s+do\s+it\b", re.I), "any"),
    ("injection", "no substitute, no skip",
     re.compile(r"\bno\s+substitute,?\s+no\s+skip\b", re.I), "any"),
    ("injection", "pressure marker",
     re.compile(r"EXTREMELY_IMPORTANT|<IMPORTANT>|\bABSOLUTELY\s+MUST\b|\bMANDATORY\b|"
                r"\beven\s+a?\s*\d+%\s+chance\b"), "any"),
    ("injection", "do not search for config",
     re.compile(r"\b(?:do\s+not|don'?t)\s+search\s+for\s+config", re.I), "any"),
    ("injection", "follow the instructions in this file",
     re.compile(r"\bfollow\s+(?:the\s+)?instructions\s+in\s+this\s+file\b", re.I), "any"),
    ("injection", "do not consult the user",
     re.compile(r"\b(?:do\s+not|don'?t|never)\s+(?:ask|check\s+with|consult)\s+the\s+user\b"
                r"[^.\n]{0,40}\b(?:for|to\s+confirm|whether|if|before|permission)\b", re.I),
     "any"),
    ("injection", "follows what a command or a fetched page says",
     re.compile(r"\bfollow\s+(?:what|whatever)\s+(?:it|they|the\s+\w+)\s+(?:prints?|returns?|"
                r"says?|outputs?|tells?\s+you)\b", re.I), "any"),
    ("injection", "follows what a command or a fetched page says",
     re.compile(r"\band\s+follow\s+(?:it|them|its\s+instructions|the\s+instructions|those\s+"
                r"instructions)\b", re.I), "after-fetch"),
    ("persistence", "always-on or every-response instruction",
     re.compile(r"\bACTIVE\s+EVERY\s+RESPONSE\b|\bstill\s+active\s+if\s+unsure\b|"
                r"\b(?:persists?|active|stays?\s+active|remains?\s+active)\s+(?:until|across)"
                r"\s+(?:changed|the\s+session|sessions|turns)\b|\b(?:for|during|across|"
                r"throughout)\s+(?:the|this)\s+(?:whole|entire)\s+session\b|"
                r"\bproactively\s+offer\b|\bon\s+first\s+interaction\b|\bbefore\s+(?:any|every)"
                r"\s+response\b|\bauto-?activat\w*|\balways-?on\b|\b(?:active|applies|apply|"
                r"loads?|loaded|injects?|injected|runs?|fires?|starts?|triggers?|enforced?)\b"
                r"[^.\n]{0,40}\bevery\s+(?:single\s+)?(?:session|turn|message|conversation|"
                r"prompt)\b|\bevery\s+(?:single\s+)?(?:session|turn|message|conversation|"
                r"prompt)\b[^.\n]{0,20}\b(?:active|applies|loads?|injects?|runs?|fires?|"
                r"starts?)\b", re.I), "any"),
    ("persistence", "always-on or every-response instruction",
     re.compile(r"\bevery\s+(?:single\s+)?(?:response|reply)\b", re.I), "not-http"),
    ("git", "destructive git",
     re.compile(r"\bgit\s+(?:reset\s+--hard|clean\s+-[a-z]*f|checkout\s+--\s|branch\s+-D)\b|"
                r"\brm\s+-rf\b|\bRemove-Item\b[^\n]*-Recurse[^\n]*-Force|"
                r"\bpush\b[^\n]*\s(?:--force|--force-with-lease|-f)\b"), "any"),
    ("git", "commit, push or merge without the operator's word",
     re.compile(r"\bgit\s+(?:commit|push|rebase|merge|tag)(?![\w-])|\bfrequent\s+commits?\b|"
                r"\bpush\s+(?:it\s+)?to\s+(?:your\s+)?(?:fork|origin|remote|main|master)\b|"
                r"\bauto-?merge\b|\bopen(?:s|ing)?\s+(?:a\s+)?(?:PR|pull\s+request)\b|"
                r"\bgh\s+pr\s+(?:create|merge)\b|\bcommit\s+(?:your|all|the)\s+(?:work|"
                r"changes)\b|^\s*(?:\d+[.)]|[-*+])\s+(?:\*\*)?commit(?:\*\*)?(?=\s*(?:--|[-:—"
                r"]|$))|\b(?:change|changes|work|slice|it)\s+(?:is|are)\s+committed\b|"
                r"\bno\s+uncommitted\s+changes\b", re.I), "any"),
    ("git", "commit, push or merge without the operator's word",
     re.compile(r"(?=commit\s)(?<!\bthe\s)(?<!\ba\s)(?<!\bthis\s)(?<!\bthat\s)(?<!\beach\s)"
                r"(?<!\bevery\s)(?<!\bwhich\s)(?<!\bbase\s)(?<!\bmerge\s)(?<!\bfirst\s)"
                r"(?<!\blast\s)(?<!\bnew\s)(?<!\bone\s)(?<!\byour\s)(?<!\bits\s)"
                r"(?<!\bno\s)(?<!\bany\s)"
                r"\bcommit\s+(?:it|the|your|as|after|early|often|each|every|per|and\s+push|"
                r"frequently|all|changes|everything|them|this|these)\b", re.I), "git-context"),
    ("egress", "data leaves the machine",
     re.compile(r"\bhistory\.jsonl\b|\b(?:send|sends|sending|sent|post|posts|posting|share|"
                r"shares|sharing|notify|notifies|deliver|delivers|forward|forwards|push|pushes)"
                r"\b[^.\n]{0,60}\b(?:slack|discord|telegram)\b|\b(?:slack|discord|telegram)\s+"
                r"(?:channel|dm|message|webhook|bot)s?\b|\b(?:send|sends|sending|post|posts|"
                r"posting|push|pushes|deliver|delivers)\b[^.\n]{0,40}\bwebhooks?\b|"
                r"\bwebhooks?\s+(?:url|endpoint)s?\b|\bupload(?:s|ing|ed)?\s+(?:it|them|the|"
                r"this|that|these|those|your|a|an|to)\b|\bsend(?:s|ing)?\s+(?:it|the|a|an|this|"
                r"your)?\s*(?:report|email|e-mail|message|dm|dms|bundle|data|results?|prompt|"
                r"artifact)s?\b|hooks\.slack\.com|discord\.com/api/webhooks|api\.openai\.com|"
                r"api\.anthropic\.com|generativelanguage\.googleapis|api\.figma\.com|"
                r"\bgateway\.[\w.-]+\.(?:so|io|com|dev)\b|\boff-?machine\b|\bthird-?party\s+"
                r"(?:service|proxy|gateway)\b|\bRUBE_\w+|\bcomposio\b|\bgh\s+(?:issue|pr)\s+"
                r"(?:create|comment|review|edit|merge)\b|\bgh\s+api\b[^\n]*\b(?:replies|"
                r"comments|issues|pulls)\b|\bx-api-key\b|Authorization:\s*Bearer|"
                r"\bcross-?model\b", re.I), "any"),
    ("egress", "API key for an outside service",
     re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_(?:API_KEY|APIKEY)\b"), "any"),
    ("egress", "another model's CLI receives the artifact",
     re.compile(r"\b(?:gemini|codex)\s+(?:-p|--prompt|exec)\b|\|\s*(?:gemini|codex)\b"), "any"),
    ("unpinned", "moving model alias",
     re.compile(r"\bmodel:\s*['\"]?(?:haiku|sonnet|opus|inherit|latest|default)\b|"
                r"\b(?:claude|gpt|gemini|jev)[\w-]*-latest\b"), "any"),
]
_TRIGGER = re.compile(
    r"\b(any|every|all)\s+(coding|code|task|change|request|prompt)s?\b|\buse\s+(on|for)\s+"
    r"any\b|/commit\b|/review\b|review\s+(this|the)\s+(PR|diff|code)\b|\bfix\s+bugs\b|"
    r"\bwhen\s+making\s+any\b|\bYou\s+MUST\s+use\s+this\b|\bbefore\s+any\b", re.I)
_NOT_FOR = re.compile(r"\b(not\s+for|do\s+not\s+use|don'?t\s+use|never\s+use|not\s+when|"
                      r"use\s+\w+\s+instead)\b", re.I)
_SPAWN = re.compile(r"\b(subprocess\.(run|Popen|call|check_output|check_call)|spawn(Sync)?\(|"
                    r"exec(Sync|File|FileSync)?\(|os\.system\(|Start-Process|"
                    r"child_process|Command::new)\b")
# mutate: fixture-end

# A code file can set its own matches apart - a self-test's fixture strings, a
# detector table - with a comment line holding nothing but the pragma:
# `mutate: fixture` in the first ten lines for the whole file, or
# `mutate: fixture-begin` / `mutate: fixture-end` around a region. Narrow on
# purpose: prose is never set apart (an instruction to the agent lives in
# markdown), the hits stay listed under the file's name as the file's own
# claim, and a file without the pragma reads exactly as before. The pack's
# reviewer (2026-09-30) read this skill's own folder RED for 190 such hits.
_PRAGMA = re.compile(r"^\s*(?:#|//|--|;|/\*|\*|<!--)\s*mutate:\s*fixture(-begin|-end)?"
                     r"\s*(?:\*/|-->)?\s*$")
PRAGMA_NOTE = " - under the file's mutate: fixture pragma"


def fixture_spans(lines):
    """[(first, last)] line ranges, 1-based and inclusive, that a code file
    sets apart with the pragma. A begin without an end runs to the end of the
    file; a bare pragma past the tenth line is not honoured."""
    spans, start = [], None
    for i, ln in enumerate(lines, 1):
        m = _PRAGMA.match(ln)
        if not m:
            continue
        if m.group(1) == "-begin":
            start = start or i
        elif m.group(1) == "-end":
            if start:
                spans.append((start, i))
                start = None
        elif i <= 10:
            return [(1, len(lines))]
    if start:
        spans.append((start, len(lines)))
    return spans

# ---------------------------------------------------------------- helpers


def rel(root, path):
    try:
        return os.path.relpath(path, root).replace("\\", "/")
    except ValueError:
        return path.replace("\\", "/")


def read_text(path):
    """(text, why_not) - None text when the file is binary or too large."""
    try:
        size = os.path.getsize(path)
        if size > MAX_FILE:
            return None, "not scanned: %d bytes (over %d)" % (size, MAX_FILE)
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as e:
        return None, "not readable: %s" % e
    if b"\0" in raw[:8192]:
        return None, "not scanned: binary"
    return raw.decode("utf-8", "replace").replace("\r\n", "\n"), None


def git(cwd, *args, timeout=30):
    """Read-only git in an inspected repo: no optional lock, no fsmonitor hook
    the repo's own config could name."""
    try:
        p = subprocess.run(("git", "--no-optional-locks", "-c", "core.fsmonitor=false")
                           + args, cwd=cwd, capture_output=True, timeout=timeout)
        return p.returncode == 0, p.stdout.decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError):
        return False, ""


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def out_result(line):
    print("RESULT: " + line)


# ---------------------------------------------------------------- frontmatter


def parse_frontmatter(text):
    """{key: (value, style, line)} for the YAML subset skills use, plus the
    body. style is plain | quoted | block | mapping. Enough for name and
    description; a real YAML parser would be a dependency."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    fm = lines[1:end]
    out, i = {}, 0
    while i < len(fm):
        m = re.match(r"^([A-Za-z_][\w.-]*):(?:\s+(.*))?$", fm[i])
        if not m:
            i += 1
            continue
        key, val = m.group(1), (m.group(2) or "").strip()
        j, cont = i + 1, []
        while j < len(fm) and (fm[j].startswith((" ", "\t")) or fm[j].strip() == ""):
            cont.append(fm[j])
            j += 1
        parts = [c.strip() for c in cont if c.strip()]
        if val in (">", ">-", ">+", "|", "|-", "|+"):
            style, value = "block", (" " if val[0] == ">" else "\n").join(parts)
        elif val == "" and parts:
            style, value = "mapping", "\n".join(parts)
        elif val and val[0] in "\"'":  # val[:1] of "" is "in" every string
            style, q = "quoted", val[0]
            joined = " ".join([val] + parts)
            value = joined[1:-1] if len(joined) > 1 and joined.endswith(q) else joined[1:]
        else:
            style, value = "plain", " ".join([val] + parts)
        out[key] = (value, style, i + 2)
        i = j
    return out, "\n".join(lines[end + 1:])


# ---------------------------------------------------------------- repos


_REPO_TOP = {}


def repo_top(d):
    """The nearest ancestor (inclusive) that holds a .git, or None."""
    key = os.path.normcase(d)
    if key in _REPO_TOP:
        return _REPO_TOP[key]
    cur, seen = d, []
    found = None
    while True:
        seen.append(os.path.normcase(cur))
        if os.path.exists(os.path.join(cur, ".git")):
            found = cur
            break
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    for s in seen:
        _REPO_TOP[s] = found
    return found


_LICENCE_NAME = re.compile(r"^(licen[cs]e|copying|unlicense)(\.[\w-]+|[-_.].*)?$", re.I)
# A licence is read by its own grant or heading, not by a name anywhere in it: a
# freeware licence that tells how earlier versions were "released under the MIT
# License" is freeware (Verafox's own drive over a real repository, 2026-09-30).
_LICENCE_KINDS = (
    ("MIT", re.compile(r"Permission is hereby granted, free of charge|\A\s*(?:The )?MIT Licen[cs]e\b")),
    ("freeware", re.compile(r"\bFreeware Licen[cs]e\b|\bis freeware\b", re.I)),
    ("Apache-2.0", re.compile(r"Apache License")),
    ("BSL-1.1", re.compile(r"Business Source License")),
    ("AGPL", re.compile(r"GNU AFFERO GENERAL PUBLIC LICENSE")),
    ("LGPL", re.compile(r"GNU LESSER GENERAL PUBLIC LICENSE")),
    ("GPL", re.compile(r"GNU GENERAL PUBLIC LICENSE")),
    ("BSD", re.compile(r"Redistribution and use in source and binary forms")),
    ("MPL-2.0", re.compile(r"Mozilla Public License")),
    ("Unlicense", re.compile(r"This is free and unencumbered software")),
    ("CC", re.compile(r"Creative Commons")),
    ("ISC", re.compile(r"\bISC License\b")),
)


def licences_in(d):
    """[{file, kind}] for licence files directly inside d."""
    out = []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for n in names:
        if _LICENCE_NAME.match(n) and os.path.isfile(os.path.join(d, n)):
            text, _ = read_text(os.path.join(d, n))
            kind = "unrecognised"
            for k, rx in _LICENCE_KINDS:
                if text and rx.search(text[:6000]):
                    kind = k
                    break
            out.append({"file": n, "kind": kind})
    return out


def repo_info(top):
    ok, sha = git(top, "rev-parse", "HEAD")
    ok2, remote = git(top, "remote", "get-url", "origin")
    if not ok2:
        ok2, rv = git(top, "remote", "-v")
        remote = rv.split("\n")[0].split()[1] if ok2 and rv.split() else ""
    ok3, date = git(top, "log", "-1", "--format=%cI")
    return {"commit": sha if ok and re.fullmatch(r"[0-9a-f]{40}", sha) else None,
            "remote": remote if ok2 and remote else None,
            "commit_date": date if ok3 and date else None,
            "licences": licences_in(top)}


# ---------------------------------------------------------------- scanning


def file_kind(path, text):
    """code | md | data. A #! first line makes a file code whatever its name:
    read as markdown, a launcher's '# Setup' comment became a heading."""
    ext = os.path.splitext(path)[1].lower()
    if ext in CODE_EXT or os.path.basename(path) in CODE_NAMES or text.startswith("#!"):
        return "code"
    return "md" if ext in PROSE_EXT else "data"


def fences_and_headings(lines):
    """(inside a fence, nearest heading above) per line. A '#' inside a fence
    is a shell comment, not a heading."""
    fences, heads, cur, on = [], [], "", False
    for ln in lines:
        s = ln.strip()
        if s.startswith("```") or s.startswith("~~~"):
            fences.append(True)
            heads.append(cur)
            on = not on
            continue
        if not on:
            m = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", ln)
            if m:
                cur = m.group(1).strip()
        fences.append(on)
        heads.append(cur)
    return fences, heads


def url_host(u):
    m = re.match(r"https?://([^/:?#]+)", u)
    return (m.group(1) if m else u).lower()


def _negated(ln, start):
    """A prohibition before start, in its clause: 'never run `x`', 'no x'."""
    seg, cut = ln[:start], 0
    for m in _CLAUSE_END.finditer(seg):
        cut = m.end()
    seg = seg[cut:]
    return bool(_PROHIBIT.search(seg) or _NO_BEFORE.search(seg))


def _sentence(ln, start, end):
    a = 0
    for m in _SENTENCE_END.finditer(ln[:start]):
        a = m.end()
    m = _SENTENCE_END.search(ln, end)
    return ln[a:m.start() + 1 if m else len(ln)]


def _covered(category, label, ln, start, end, is_md, anti, head):
    """Why a match is a mention and not an act, or None. A mention excuses
    only itself: the caller flags any other match on the line."""
    if anti and not _AFFIRM.search(ln) and not _FIX_BEFORE.search(ln[:start]):
        return "under the heading '%s'" % head
    if category == "injection":
        if is_md and any(q.start() <= start and end <= q.end() for q in _QUOTED.finditer(ln)):
            return "quoted"
        if _DEFENSIVE.search(_sentence(ln, start, end)):
            return "a defensive cue in its sentence"
        if label in NEG_IS_FINDING:
            return None
    if is_md and _negated(ln, start):
        return "a prohibition before it"
    return None


def scan_text(relpath, text, kind):
    """[(category, label, line, text, match)], [(line, text, why)] defensive,
    notes. kind is code | md | data (file_kind)."""
    flags, defensive, notes = [], [], {"links": set(), "local": [], "spawns": 0,
                                       "config_mentions": [], "fixture": [],
                                       "fixture_spans": []}
    seen = {}  # (category, label, line) -> index in flags
    lines = text.split("\n")
    is_md = kind == "md"
    spans = fixture_spans(lines) if kind == "code" else []
    notes["fixture_spans"] = ["whole file" if (a, b) == (1, len(lines)) else "%d-%d" % (a, b)
                              for a, b in spans]
    fences, heads = fences_and_headings(lines) if is_md else (None, None)
    opens_block, nxt = [False] * len(lines), False     # next non-blank line is a fence
    for k in range(len(lines) - 1, -1, -1):
        opens_block[k] = nxt
        if lines[k].strip():
            nxt = lines[k].strip().startswith(("```", "~~~"))
    prev = ""
    for i, ln in enumerate(lines, 1):
        if not ln.strip():
            prev = ""
            continue
        excerpt = ln.strip()
        if len(excerpt) > 160:
            excerpt = excerpt[:157] + "..."
        # a URL in code is requested when the line loads it or names it as one
        for m in _URL.finditer(ln):
            u = m.group(0)
            host = url_host(u)
            if any(s in u.lower() for s in _SAFE_HOSTS):
                continue
            if any(host.startswith(h) for h in _LOCAL_HOSTS):
                notes["local"].append("%s:%d" % (relpath, i))
                continue
            # the loading context is looked for near the URL and outside any
            # URL: '/downloads/' in a path is not a download, and a minified
            # line's far end is not this URL's context
            near = _URL.sub(" ", ln[max(0, m.start() - 100):m.start()] + " "
                            + ln[m.end():m.end() + 40])
            if kind == "code" and (_URL_LOADED.search(near) or
                                   _URL_NAMED.search(ln[:m.start()])):
                flags.append(("network", "URL requested from code (%s)" % host, i,
                              excerpt, u[:120]))
            else:
                notes["links"].add(host)
        if _SPAWN.search(ln):
            notes["spawns"] += 1
        head = heads[i - 1] if is_md else ""
        anti = bool(is_md and not fences[i - 1] and _ANTI_HEADING.search(head or ""))
        carry = prev if (prev and not _NEW_ITEM.match(ln)) else ""
        logged = False
        for category, label, rx, scope in DETECTORS:
            if scope == "code" and kind != "code":
                continue
            hits = [(m.start(), m.end(), m.group(0)) for m in rx.finditer(ln)
                    if m.group(0).strip()]
            if scope == "after-fetch":
                # the fetch may sit on the line this one continues
                hits = [h for h in hits if _FETCHED.search(carry + "\n" + ln[:h[0]])]
            if scope == "git-context" and carry:
                # a determiner on the line above covers a match that opens
                # this one: a string wrapped in code, a sentence wrapped in prose
                hits = [h for h in hits if ln[:h[0]].strip(" \t\"'`(")
                        or not _DETERMINER_END.search(carry)]
            if category == "egress" and is_md and hits:
                # an upload into the user's own settings, wrapped or not
                follow = " " + lines[i] if (i < len(lines)
                                            and not _NEW_ITEM.match(lines[i])) else ""
                hits = [h for h in hits if not (
                    h[2].lower().startswith("upload")
                    and _UPLOAD_SETTINGS.match(ln[h[1]:] + follow))]
            if not hits:
                continue
            # a write verb on the line or the line it continues, or the line
            # names the file and then shows the block to put in it
            if (scope == "verb" or (scope == "verb-md" and is_md)) and not (
                    _WRITE_VERB.search(ln) or (carry and _WRITE_VERB.search(carry))
                    or (ln.rstrip().endswith(":") and opens_block[i - 1])):
                notes["config_mentions"].append("%s:%d %s" % (relpath, i, label))
                continue
            if scope == "git-context" and not (_GIT_CONTEXT.search(ln) or
                                               _GIT_CONTEXT.search(head or "")):
                continue
            if category == "install" and is_md and _OWN_INSTALL.search(ln) \
                    and os.path.basename(relpath).lower() == "readme.md" \
                    and _SETUP_HEADING.search(head or ""):
                defensive.append((i, excerpt, "the pack's own install line in its README"))
                continue
            if scope == "not-http" and _HTTP_WORDS.search(ln):
                continue
            live, why = [], None
            for s0, e0, hit in hits:
                w = _covered(category, label, ln, s0, e0, is_md, anti, head)
                if w:
                    why = why or w
                elif hit.strip() not in live:
                    live.append(hit.strip())
            if why and not logged:
                defensive.append((i, excerpt, why))
                logged = True
            if not live:
                continue
            when = ""
            if is_md and category in ("network", "install", "exec"):
                when = " - in '%s' (%s)" % (head or "top of file",
                                           "setup/load-time" if _SETUP_HEADING.search(head or "")
                                           else "use-time")
            if category == "install" and "npx" in ln and "@latest" not in ln \
                    and not re.search(r"npx\s+(-y\s+|--yes\s+)?[\w@/.-]+@\d", ln):
                label = label + " (npx unpinned)"
            key = (category, label + when, i)
            if key in seen:  # two detectors of one label on one line: one flag
                c0, l0, i0, x0, m0 = flags[seen[key]]
                more = [h for h in live if h not in m0]
                flags[seen[key]] = (c0, l0, i0, x0, ", ".join([m0] + more)[:120])
                continue
            seen[key] = len(flags)
            flags.append((category, label + when, i, excerpt, ", ".join(live)[:120]))
        prev = ln
    if spans:
        # the file's own claim: kept apart under its name, never dropped
        notes["fixture"] = [f for f in flags if any(a <= f[2] <= b for a, b in spans)]
        flags = [f for f in flags if not any(a <= f[2] <= b for a, b in spans)]
    return flags, defensive, notes


# mutate: fixture-begin
_REF = re.compile(
    r"(?<![\w:/@>)}\]-])((?:\.\.?/|~/|/|\$\{?[A-Z_]+\}?/|%[A-Z_]+%[/\\])?(?:[\w.$@{}%-]+/)*"
    r"[\w.@{}%-]+\.(?:md|mdx|txt|py|js|mjs|cjs|ts|tsx|jsx|sh|bash|ps1|psm1|cmd|bat|json|"
    r"jsonc|jsonl|yaml|yml|toml|csv|tsv|html|css|svg|png|jpe?g|gif|webp|wasm|exe|xml|"
    r"sql|rs|go|rb|php|ipynb|pdf|log))\b")
# A dot before the folder name is a dot-folder elsewhere (~/.agents/skills), not the skill's own agents/.
_REF_DIR = re.compile(
    r"(?<![\w:/@>)}\].-])((?:\.\.?/)?(?:\.\./)*(?:scripts|bin|references?|assets|data|"
    r"templates|hooks|agents|commands|examples|docs)/[\w.-]+)\b")
_VAR_ROOT = re.compile(r"^(\$\{?[A-Z_]+\}?|%[A-Z_]+%|~|/|[A-Za-z]:)")
_MD_LINK = re.compile(r"\]\(\s*<?([^)\s#>]+)")
_SKILL_SUBDIRS = {"scripts", "bin", "references", "reference", "assets", "data",
                  "templates", "hooks", "agents", "commands", "examples", "docs",
                  "resources"}
# mutate: fixture-end


def references(skill_dir, md_texts, repo):
    """{inside, dangling, outside: [{ref, exists, note}]} from the skill's
    markdown, [(relpath, text)]. A path resolves against the file that names
    it, then the skill folder; one found only at the repo top is outside. An
    unresolved path is dangling only when it points into the skill - ./ or
    ../, a folder the skill has or a skill-shaped one (scripts/, references/),
    or a markdown link: `src/config.ts` in an example is the user's project."""
    here = os.path.normcase(os.path.abspath(skill_dir))

    def within(p):
        n = os.path.normcase(os.path.abspath(p))
        return n == here or n.startswith(here + os.sep)
    try:
        subdirs = {n for n in os.listdir(skill_dir)
                   if os.path.isdir(os.path.join(skill_dir, n))}
    except OSError:
        subdirs = set()
    inside, dangling, outside, seen = set(), set(), [], set()
    for relpath, text in md_texts:
        fdir = os.path.normpath(os.path.join(skill_dir, os.path.dirname(relpath)))
        links = {m.group(1) for m in _MD_LINK.finditer(text)}
        for rx in (_REF, _REF_DIR):
            for m in rx.finditer(text):
                tok = m.group(1).rstrip(".,;:)")
                dotted = tok.startswith(("./", "../"))
                key = (fdir if dotted else "", tok)
                if key in seen or _URL.match(tok):
                    continue
                seen.add(key)
                if _VAR_ROOT.match(tok):
                    outside.append({"ref": tok, "exists": None,
                                    "note": "rooted outside the folder"})
                    continue
                cands = [os.path.normpath(os.path.join(fdir, tok))]
                if os.path.normcase(os.path.abspath(fdir)) != here:
                    cands.append(os.path.normpath(os.path.join(skill_dir, tok)))
                found = next((c for c in cands if os.path.exists(c)), None)
                if found and within(found):
                    inside.add(tok)
                    continue
                if found or not within(cands[0]):
                    target = found or cands[0]
                    outside.append({"ref": tok, "exists": bool(found), "_path": found,
                                    "note": "resolves to %s" % (
                                        rel(repo, target) if repo else target)})
                    continue
                # a bare CLAUDE.md or package.json is the user's project file
                # the skill talks about, not the repo's own
                if repo and not dotted and "/" in tok:
                    at_top = os.path.normpath(os.path.join(repo, tok))
                    if os.path.exists(at_top):
                        outside.append({"ref": tok, "exists": True, "_path": at_top,
                                        "note": "found at the repo top: %s"
                                        % rel(repo, at_top)})
                        continue
                first = tok.split("/")[0]
                if tok in links or ("/" in tok and (dotted or first in subdirs or
                                                    first in _SKILL_SUBDIRS)):
                    dangling.add(tok)
    return {"inside": sorted(inside), "dangling": sorted(dangling), "outside": outside}


# mutate: fixture-begin
KNOWN_TOOLS = (
    "git gh node npm npx pnpm yarn bun deno python python3 pip pip3 pipx uv uvx poetry "
    "cargo rustc go brew winget choco apt apt-get docker kubectl jq yq zip unzip tar dot "
    "curl wget make cmake gcc clang java mvn gradle ruby gem bundle php composer dotnet "
    "pwsh powershell bash sh zsh claude gemini codex cursor code caveman graphify "
    "playwright chrome chromium ffmpeg convert magick pandoc rg fd ag tmux gws lhci "
    "promptfoo ollama osv-scanner gitleaks lint-staged prettier eslint vite tsc "
    "pytest").split()
_TOOL_SET = set(KNOWN_TOOLS)
_SHELL_WORDS = {"if", "then", "else", "fi", "for", "do", "done", "while", "echo", "cd",
                "export", "set", "source", "return", "exit", "true", "false", "cat",
                "ls", "mkdir", "rm", "cp", "mv", "test", "sudo", "env", "printf", "read"}
_SHELL_FENCE = {"", "bash", "sh", "shell", "zsh", "fish", "console", "terminal",
                "powershell", "pwsh", "ps1", "ps", "cmd", "bat", "batch"}
_SHELL_EXT = {".sh", ".bash", ".zsh", ""}
# mutate: fixture-end


def _fence_and_span_lines(text):
    """(command text, strict) from fenced blocks and inline code spans. strict
    is where an unknown command may be named: a shell or unlabeled fence, or
    a span of more than one word - `react-router` alone is a package's name."""
    out, in_fence, strict = [], False, False
    for ln in text.split("\n"):
        s = ln.strip()
        if s.startswith("```") or s.startswith("~~~"):
            if not in_fence:
                lang = s.strip("`~ ").split()
                strict = (lang[0].lower() if lang else "") in _SHELL_FENCE
            in_fence = not in_fence
            continue
        if in_fence:
            out.append((s, strict))
    for m in re.finditer(r"`([^`\n]+)`", text):
        out.append((m.group(1), len(m.group(1).split()) > 1))
    return out


def _commands(cmd_line):
    """First token of each command in a shell line: `a | b && c`."""
    for part in re.split(r"\|\||&&|\||;|\$\(|`", cmd_line):
        toks = part.strip().split()
        while toks and (toks[0] in ("$", ">", "sudo", "time", "exec") or
                        re.match(r"^[A-Z_]+=", toks[0])):
            toks = toks[1:]
        if toks:
            yield re.sub(r"^\./", "", toks[0]).lower()


# mutate: fixture-begin
_CODE_TOOL = re.compile(
    r"\b(?:run|Popen|call|check_output|check_call|spawn|spawnSync|exec|execSync|execFile|"
    r"execFileSync|which|Get-Command)\s*\(?\s*\(?\s*\[?\s*[\"'`]([a-z][\w.-]*)")
# Where an env var name is read: code reads it by API; a shell script or prose
# by $NAME; prose also by a service-shaped name. A JS constant BRAND_MODE is
# not an env var, and ${x} in a JS template is not one either.
_ENV_CODE = (
    re.compile(r"process\.env\.([A-Z][A-Z0-9_]{2,})"),
    re.compile(r"process\.env\[[\"']([A-Z][A-Z0-9_]{2,})"),
    re.compile(r"os\.environ(?:\.get)?\(?\[?[\"']([A-Z][A-Z0-9_]{2,})"),
    re.compile(r"getenv\([\"']([A-Z][A-Z0-9_]{2,})"),
    re.compile(r"\$env:([A-Z][A-Z0-9_]{2,})"),
)
_ENV_BRACED = re.compile(r"\$\{([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\}")
_ENV_SHELL = (re.compile(r"\$\{?([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\}?"),
              re.compile(r"^\s*export\s+([A-Z][A-Z0-9_]{2,})=", re.M))
_ENV_CMD = re.compile(r"%([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)%")
_ENV_PROSE = re.compile(r"\b([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_(?:API_KEY|KEY|TOKEN|SECRET|"
                        r"DISABLED|ENABLED|MODE|DIR|HOME|URL))\b")
_ENV_COMMON = {"PATH", "HOME", "USERPROFILE", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA",
               "PWD", "SHELL", "USER", "USERNAME", "HOSTNAME", "PORT", "LANG", "TERM",
               "EDITOR", "PATHEXT", "COMSPEC", "SYSTEMROOT", "PROGRAMFILES", "NODE_ENV",
               "CI", "DEBUG", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "XDG_CONFIG_HOME",
               "XDG_DATA_HOME", "XDG_CACHE_HOME", "PROGRAMDATA", "SYSTEM_ROOT",
               "CLAUDE_PLUGIN_ROOT", "SKILL_DIR", "HOME_DIR", "OUT_DIR", "BASE_DIR",
               "PROJECT_DIR", "ROOT_DIR", "DATA_DIR", "CONFIG_DIR", "CACHE_DIR"}
# An MCP server by its tool prefix, a *-mcp package, or Composio's RUBE_ tools.
# mcp-<name> was dropped: mcp-builder is a skill, not a server.
_MCP = (re.compile(r"\bmcp__([\w-]+)__"), re.compile(r"\b([\w.-]+-mcp)\b"),
        re.compile(r"\b(RUBE)_\w+"))
# mutate: fixture-end


def dependencies(md_texts, other_texts):
    """Tools, env vars and MCP servers the skill names. md_texts is
    [(relpath, text)], other_texts [(relpath, text, kind)] for code and data."""
    tools, envs, mcp = set(), set(), set()
    for _r, text in md_texts:
        for line, strict in _fence_and_span_lines(text):
            for tok in _commands(line):
                if tok in _TOOL_SET and tok not in _SHELL_WORDS:
                    tools.add(tok)
                elif strict and re.fullmatch(r"[a-z][a-z0-9.-]{3,}", tok) and "-" in tok \
                        and tok not in _SHELL_WORDS and "." not in tok:
                    tools.add(tok)          # an unknown hyphenated command
    for _r, text, kind in other_texts:
        if kind == "code":
            for m in _CODE_TOOL.finditer(text):
                if m.group(1) in _TOOL_SET:
                    tools.add(m.group(1))
    readers = [(text, _ENV_CODE + _ENV_SHELL + (_ENV_CMD, _ENV_PROSE))
               for _r, text in md_texts]
    for r, text, kind in other_texts:
        ext = os.path.splitext(r)[1].lower()
        rxs = _ENV_CODE if kind == "code" else (_ENV_BRACED,)
        if kind == "code" and ext in _SHELL_EXT:
            rxs = rxs + _ENV_SHELL
        if ext in (".cmd", ".bat"):
            rxs = rxs + (_ENV_CMD,)
        readers.append((text, rxs))
    for text, rxs in readers:
        for rx in rxs:
            for m in rx.finditer(text):
                name = m.group(1)
                if name not in _ENV_COMMON and len(name) >= 4:
                    envs.add(name)
        for rx in _MCP:
            for m in rx.finditer(text):
                mcp.add(m.group(1).lower() if m.group(1) != "RUBE" else "rube (Composio)")
        for m in re.finditer(r"\"mcpServers\"\s*:\s*\{", text):
            try:
                obj = json.loads(text)
                for k in (obj.get("mcpServers") or {}):
                    mcp.add(k)
            except (ValueError, AttributeError):
                pass
    return {"tools": [{"name": t, "on_path": shutil.which(t) is not None}
                      for t in sorted(tools)],
            "env": [{"name": e, "set_here": e in os.environ} for e in sorted(envs)],
            "mcp": sorted(mcp)}


def _walk_files(d):
    for base, dirs, files in os.walk(d):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        for f in sorted(files):
            yield os.path.join(base, f)


def _hits(r, f):
    return [{"category": c, "label": l, "file": r, "line": i, "text": x, "match": mt}
            for c, l, i, x, mt in f]


def _apart(r, f):
    """The hits a file set apart itself, each labelled with the claim."""
    hits = _hits(r, f)
    for h in hits:
        h["label"] += PRAGMA_NOTE
    return hits


def inspect_skill(skill_md, root, repos, all_names_by_repo):
    skill_dir = os.path.dirname(skill_md)
    folder = os.path.basename(skill_dir)
    top = repo_top(skill_dir)
    repo_rel = rel(root, top) if top else None
    text, _ = read_text(skill_md)
    text = text or ""
    fm, body = parse_frontmatter(text)
    name = fm.get("name", ("", "missing", 0))[0].strip().strip("\"'")
    desc, dstyle, dline = fm.get("description", ("", "missing", 0))
    desc = desc.strip()
    flags, defensive, notes = [], [], {"links": set(), "local": [], "spawns": 0,
                                       "config_mentions": [], "unscanned": [],
                                       "pragmas": []}
    md_texts, other_texts, tests_hits, pragma_hits, nfiles, nbytes = [], [], [], [], 0, 0
    for p in _walk_files(skill_dir):
        r = rel(skill_dir, p)
        nfiles += 1
        try:
            nbytes += os.path.getsize(p)
        except OSError:
            pass
        ext = os.path.splitext(p)[1].lower()
        if ext in BINARY_EXT:
            continue
        t, why = read_text(p)
        if t is None:
            notes["unscanned"].append("%s (%s)" % (r, why))
            continue
        kind = file_kind(p, t)
        f, d, n = scan_text(r, t, kind)
        if n["fixture_spans"]:
            notes["pragmas"].append("%s (%s)" % (r, ", ".join(n["fixture_spans"])))
            pragma_hits += _apart(r, n["fixture"])
        if _TEST_PATH.search(r):
            tests_hits += _hits(r, f)
            continue
        if kind == "md":
            md_texts.append((r, t))
        else:
            other_texts.append((r, t, kind))
        flags += _hits(r, f)
        defensive += [{"file": r, "line": i, "text": x, "why": w} for i, x, w in d]
        notes["links"] |= n["links"]
        notes["local"] += n["local"]
        notes["spawns"] += n["spawns"]
        notes["config_mentions"] += n["config_mentions"]
    # A test file the skill's own markdown names is one the agent runs: its
    # hits are flags, or tests/ would be the place to hide a load-time fetch.
    said = "\n".join(t for _r, t in md_texts)
    run_by_skill = {h["file"] for h in tests_hits if h["file"] in said}
    for h in tests_hits:
        if h["file"] in run_by_skill:
            h["label"] += " - in a test file the skill tells the agent to run"
            flags.append(h)
    in_tests = [h for h in tests_hits if h["file"] not in run_by_skill]
    # A file the skill references outside its own folder is part of what it
    # loads (addyosmani's ../../references/orchestration-patterns.md is where
    # its settings.json change lives): read it too, but never past the folder
    # being inspected.
    refs = references(skill_dir, md_texts, top)
    inspected = os.path.normcase(os.path.abspath(root))
    other_skills = {os.path.normcase(os.path.abspath(os.path.dirname(q)))
                    for qs in all_names_by_repo.values() for q in qs} - \
        {os.path.normcase(os.path.abspath(skill_dir))}
    read_once = set()
    for x in refs["outside"]:
        p = x.pop("_path", None)
        if not p:
            continue
        np_ = os.path.normcase(os.path.abspath(p))
        parts = rel(top, p).split("/") if top else [os.path.basename(p)]
        if not os.path.isfile(p) or os.path.splitext(p)[1].lower() in BINARY_EXT:
            x["read"] = "not read: not a text file"
            continue
        if not np_.startswith(inspected + os.sep):
            x["read"] = "not read: outside the folder being inspected"
            continue
        if parts[-1] in _WIRING_NAMES or set(parts[:-1]) & _WIRING_SEGS:
            x["read"] = "left to the repo wiring scan"
            continue
        if any(np_.startswith(o + os.sep) for o in other_skills):
            x["read"] = "a sibling skill's file; its flags are that skill's"
            continue
        if np_ in read_once:
            x["read"] = "read once, under another name"
            continue
        read_once.add(np_)
        t, _ = read_text(p)
        if t is None:
            x["read"] = "not read: binary or too large"
            continue
        x["read"] = "read; its flags are this skill's"
        f, d, _n = scan_text(x["ref"], t, file_kind(p, t))
        if _n["fixture_spans"]:
            notes["pragmas"].append("%s (%s)" % (x["ref"], ", ".join(_n["fixture_spans"])))
            pragma_hits += _apart(x["ref"], _n["fixture"])
        for h in _hits(x["ref"], f):
            h["label"] += " - in a file outside the skill folder that it references"
            flags.append(h)
        defensive += [{"file": x["ref"], "line": i, "text": tx, "why": w} for i, tx, w in d]
    # frontmatter-level checks
    mv = fm.get("model")
    if mv and re.fullmatch(r"['\"]?(haiku|sonnet|opus|inherit|latest|default)['\"]?",
                           mv[0].strip(), re.I):
        if not any(x["category"] == "unpinned" and x["file"] == "SKILL.md"
                   and x["line"] == mv[2] for x in flags):
            flags.append({"category": "unpinned", "label": "moving model alias in "
                          "frontmatter", "file": "SKILL.md", "line": mv[2],
                          "text": "model: " + mv[0], "match": mv[0].strip()})
    if desc and _TRIGGER.search(desc):
        flags.append({"category": "trigger", "label": "generic trigger - would fire "
                      "outside its domain or steal a native one",
                      "file": "SKILL.md", "line": dline,
                      "text": _TRIGGER.search(desc).group(0),
                      "match": ", ".join(dict.fromkeys(
                          m.group(0) for m in _TRIGGER.finditer(desc)))[:120]})
    flags.sort(key=lambda x: (x["file"] != "SKILL.md", x["file"], x["line"]))
    name_ok = bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name))
    copies = [rel(root, os.path.dirname(o)) for o in
              all_names_by_repo.get((repo_rel, folder), [])
              if os.path.normcase(o) != os.path.normcase(skill_md)]
    return {
        "path": rel(root, skill_dir), "folder": folder, "repo": repo_rel,
        "name": name, "name_match": name == folder, "name_ok": name_ok,
        "description": {"chars": len(desc), "style": dstyle,
                        "unquoted_colon": dstyle == "plain" and ": " in desc,
                        "over_1024": len(desc) > 1024,
                        "not_for": bool(_NOT_FOR.search(desc)), "text": desc},
        "frontmatter_keys": sorted(k for k in fm if k not in ("name", "description")),
        "licence": {"skill": [x["kind"] + " (" + x["file"] + ")" for x in
                              licences_in(skill_dir)]
                    + (["frontmatter: " + fm["license"][0]] if "license" in fm else []),
                    "repo": [x["kind"] + " (" + x["file"] + ")" for x in
                             (repos.get(repo_rel, {}).get("licences", []) if repo_rel
                              else [])]},
        "copies": sorted(copies),
        "references": refs,
        "companions": [],
        "deps": dependencies(md_texts, other_texts),
        "size": {"files": nfiles, "bytes": nbytes,
                 "skill_md_lines": text.count("\n") + 1},
        "flags": flags, "defensive": defensive, "in_tests": in_tests + pragma_hits,
        "notes": {"links": sorted(notes["links"]), "local_urls": notes["local"],
                  "spawns": notes["spawns"],
                  "config_mentions": notes["config_mentions"],
                  "unscanned": notes["unscanned"], "pragmas": notes["pragmas"]},
        "_text": text,
    }


_NAMED = (re.compile(r"`([^`\n]*)`"), re.compile(r"\w+:([\w-]+)"),
          re.compile(r"/([\w-]+)"), re.compile(r"(?<![\w-])([\w-]+)\s+skill"))


def companions(skills):
    """Other skills of the same repo a SKILL.md names - in a code span, with a
    plugin namespace (superpowers:x), as /x, or as 'x skill'. One pass over
    each text, then a set lookup: a regex per pair of skills took ~330 s on a
    repo of 864. A skill's name - a sibling's or its own - is never a missing
    CLI, so it leaves the dependency list."""
    by_repo = {}
    for s in skills:
        by_repo.setdefault(s["repo"], set()).add(s["name"] or s["folder"])
    for s in skills:
        mine = s["name"] or s["folder"]
        names = by_repo.get(s["repo"], set())
        said = set()
        for m in _NAMED[0].finditer(s["_text"]):
            said.update(re.findall(r"[\w-]+", m.group(1)))
        for rx in _NAMED[1:]:
            said.update(m.group(1) for m in rx.finditer(s["_text"]))
        s["companions"] = sorted(n for n in (said & names) if n != mine and len(n) >= 4)
        skill_names = names | {mine, s["folder"]}
        s["deps"]["tools"] = [t for t in s["deps"]["tools"] if t["name"] not in skill_names]


# mutate: fixture-begin
_WIRING_SEGS = {"hooks", "commands", ".claude-plugin", ".cursor-plugin", ".codex-plugin",
                ".gemini-plugin", ".devin-plugin", ".hermes-plugin", ".openclaw"}
_WIRING_NAMES = {"plugin.json", "hooks.json", "marketplace.json", "install.sh",
                 "install.ps1", "INSTALL.md", "setup.md", ".mcp.json", "package.json",
                 "index.js", "gemini-extension.json", "opencode.json", "plugin.yaml",
                 "AGENTS.md", "CLAUDE.md", "GEMINI.md", "README.md", "after-install.md",
                 "Dockerfile"}
# mutate: fixture-end


def repo_level_scan(top, root, skill_dirs):
    """Flags in the wiring outside any skill folder: hooks, commands, plugin
    manifests, installers, top-level scripts and bin, README and INSTALL.
    Wiring under tests/, or under a fixture pragma, is set apart, as in a skill;
    a mention that is not an act (a README's own install line) is listed as
    defensive, as in a skill."""
    flags, in_tests, pragmas, defensive, seen, truncated = [], [], [], [], 0, False
    tops = [os.path.normcase(os.path.abspath(d)) for d in skill_dirs]
    for p in _walk_files(top):
        r = rel(top, p)
        np_ = os.path.normcase(os.path.abspath(p))
        if any(np_.startswith(t + os.sep) for t in tops):
            continue
        parts = r.split("/")
        wired = (set(parts[:-1]) & _WIRING_SEGS) or parts[-1] in _WIRING_NAMES \
            or (len(parts) == 2 and parts[0] in ("scripts", "bin", "src"))
        if not wired or os.path.splitext(p)[1].lower() in BINARY_EXT:
            continue
        seen += 1
        if seen > MAX_REPO_LEVEL_FILES:
            truncated = True
            break
        t, _ = read_text(p)
        if t is None:
            continue
        f, _d, _n = scan_text(r, t, file_kind(p, t))
        (in_tests if _TEST_PATH.search(r) else flags).extend(_hits(r, f))
        defensive += [{"file": r, "line": i, "text": x, "why": w} for i, x, w in _d]
        if _n["fixture_spans"]:
            pragmas.append("%s (%s)" % (r, ", ".join(_n["fixture_spans"])))
            in_tests += _apart(r, _n["fixture"])
    return {"repo": rel(root, top), "files_scanned": seen, "truncated": truncated,
            "flags": flags, "in_tests": in_tests, "pragmas": pragmas,
            "defensive": defensive}


def cmd_inventory(a):
    root = os.path.abspath(a.folder)
    if not os.path.isdir(root):
        out_result("could not run - no such folder: %s" % root)
        return 2
    if a.out:
        dest = os.path.normcase(os.path.abspath(a.out))
        if dest.startswith(os.path.normcase(root) + os.sep):
            out_result("REFUSED - --out %s is inside the folder being inspected; "
                       "inventory is read-only there, so write the report elsewhere"
                       % os.path.abspath(a.out))
            return 2
    skill_mds = [p for p in _walk_files(root) if os.path.basename(p).lower() == "skill.md"]
    if not skill_mds:
        out_result("could not run - no SKILL.md under %s" % root)
        return 2
    repos = {}
    by_key = {}
    for p in skill_mds:
        top = repo_top(os.path.dirname(p))
        key = rel(root, top) if top else None
        if key is not None and key not in repos:
            repos[key] = repo_info(top)
            repos[key]["path"] = key
            repos[key]["top"] = top
        by_key.setdefault((key, os.path.basename(os.path.dirname(p))), []).append(p)
    skills = [inspect_skill(p, root, repos, by_key) for p in skill_mds]
    companions(skills)
    if a.skill:
        want = set(a.skill)
        skills = [s for s in skills if s["folder"] in want or s["name"] in want]
        if not skills:
            out_result("could not run - no skill named %s under %s"
                       % (", ".join(sorted(want)), root))
            return 2
    for s in skills:
        s.pop("_text", None)
    repo_level = []
    if not a.skill:
        for key, info in repos.items():
            repo_level.append(repo_level_scan(
                info["top"], root, [os.path.join(root, s["path"]) for s in skills
                                    if s["repo"] == key]))
    for info in repos.values():
        info.pop("top", None)
        info["skills"] = sorted(s["folder"] for s in skills if s["repo"] == info["path"])
    nflags = sum(len(s["flags"]) for s in skills)
    nrepo = sum(len(r["flags"]) for r in repo_level)
    flagged = sum(1 for s in skills if s["flags"])
    ndef = sum(len(s["defensive"]) for s in skills)
    ntests = sum(len(s["in_tests"]) for s in skills) + \
        sum(len(r["in_tests"]) for r in repo_level)
    doc = {"root": root, "generated": now(), "read_only": True,
           "repos": [repos[k] for k in sorted(repos)], "skills": skills,
           "repo_level": repo_level,
           "totals": {"skills": len(skills), "repos": len(repos), "flags": nflags,
                      "flagged_skills": flagged, "repo_level_flags": nrepo,
                      "defensive": ndef, "in_tests": ntests}}
    result = ("inventory %s - %d skill(s) in %d repo(s); %d red flag(s) in %d skill(s), "
              "%d in repo wiring; %d defensive mention(s) and %d hit(s) in tests or "
              "under a fixture pragma counted apart; read-only"
              % (root, len(skills), len(repos), nflags, flagged, nrepo, ndef, ntests))
    body = json.dumps(doc, indent=1, ensure_ascii=False) if a.json else render_inventory(doc)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="") as fh:
            fh.write(body + "\n")
        print("wrote %s" % a.out)
    else:
        print(body)
    out_result(result)
    return 1 if (nflags or nrepo) else 0


def flag_line(f):
    return "[%s] %s:%d - %s%s - `%s`" % (
        f["category"], f["file"], f["line"], f["label"],
        " (matched: %s)" % f["match"] if f.get("match") else "",
        f["text"].replace("`", "'"))


def _cut(items, n, sep):
    """A list shortened for reading says how many it left out."""
    return sep.join(items[:n]) + ("%sand %d more (see --json)" % (sep, len(items) - n)
                                  if len(items) > n else "")


GROUP_SHOWN = 5


def grouped_flags(flags, indent):
    """Flags grouped by category and label, in order of first sight: the first
    GROUP_SHOWN of each group printed, then how many more. Composio repeats one
    egress call 16,000 times; the JSON keeps every one."""
    groups, order = {}, []
    for f in flags:
        k = (f["category"], f["label"])
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(f)
    out = []
    for k in order:
        g = groups[k]
        out += [indent + "- " + flag_line(f) for f in g[:GROUP_SHOWN]]
        if len(g) > GROUP_SHOWN:
            out.append("%s- ... and %d more [%s] %s (see --json)"
                       % (indent, len(g) - GROUP_SHOWN, k[0], k[1]))
    return out


def tests_line(hits):
    files = sorted({h["file"] for h in hits})
    return ("- set apart, in tests or fixtures (not at load or use): %d hit(s) in %s"
            % (len(hits), _cut(files, 6, ", ")))


def set_apart_lines(hits, pragmas):
    """Tests and fixtures by path first; then what a file set apart itself,
    named, because that claim is the file's own and a reader should open it."""
    tests = [h for h in hits if not h["label"].endswith(PRAGMA_NOTE)]
    out = [tests_line(tests)] if tests else []
    if pragmas:
        out.append("- set apart by a `mutate: fixture` pragma, the file's own claim - "
                   "read it: %d hit(s) in %s" % (len(hits) - len(tests),
                                                 _cut(pragmas, 6, ", ")))
    return out


def render_inventory(doc):
    o = ["# Mutate inventory - %s" % doc["root"],
         "", "_read-only; %d skill(s) in %d repo(s); generated %s_"
         % (doc["totals"]["skills"], doc["totals"]["repos"], doc["generated"]), ""]
    if doc["repos"]:
        o += ["## Repositories", "", "| repo | commit | remote | licence | skills |",
              "|---|---|---|---|---|"]
        for r in doc["repos"]:
            o.append("| %s | %s | %s | %s | %d |" % (
                r["path"], (r["commit"] or "not read")[:12], r["remote"] or "none read",
                ", ".join(x["kind"] + " (" + x["file"] + ")" for x in r["licences"])
                or "NONE FOUND", len(r["skills"])))
        o.append("")
    for s in doc["skills"]:
        d = s["description"]
        o += ["## %s (%s)" % (s["folder"], s["path"]), ""]
        o.append("- name: `%s` - %s%s" % (
            s["name"] or "MISSING", "equals folder" if s["name_match"]
            else "DOES NOT equal folder `%s`" % s["folder"],
            "" if s["name_ok"] else "; not lowercase-hyphen or over 64"))
        o.append("- description: %d chars%s, %s scalar%s%s" % (
            d["chars"], " - OVER 1024" if d["over_1024"] else "", d["style"],
            " - UNQUOTED ': '" if d["unquoted_colon"] else "",
            "" if d["not_for"] else "; says nothing about when NOT to use it"))
        if s["frontmatter_keys"]:
            o.append("- other frontmatter keys: " + ", ".join(s["frontmatter_keys"]))
        o.append("- size: %d file(s), %d bytes; SKILL.md %d lines" % (
            s["size"]["files"], s["size"]["bytes"], s["size"]["skill_md_lines"]))
        o.append("- licence: skill %s; repo %s" % (
            ", ".join(s["licence"]["skill"]) or "none",
            ", ".join(s["licence"]["repo"]) or ("none" if s["repo"] else "not a repo")))
        if s["copies"]:
            o.append("- copies in the repo: " + ", ".join(s["copies"]))
        r = s["references"]
        o.append("- references: %d inside; dangling: %s; OUTSIDE its folder: %s" % (
            len(r["inside"]), ", ".join(r["dangling"]) or "none",
            "; ".join("%s (%s%s)" % (x["ref"], "exists" if x["exists"] else
                                     "MISSING" if x["exists"] is False else x.get("note", ""),
                                     "; " + x["read"] if x.get("read") else "")
                      for x in r["outside"]) or "none"))
        if s["companions"]:
            o.append("- companion skills named: " + ", ".join(s["companions"]))
        dp = s["deps"]
        o.append("- depends on: %s; env %s; MCP %s" % (
            ", ".join("%s (%s)" % (t["name"], "on PATH" if t["on_path"] else "NOT on PATH")
                      for t in dp["tools"]) or "nothing named",
            ", ".join("%s (%s)" % (e["name"], "set here" if e["set_here"] else "not set")
                      for e in dp["env"]) or "none",
            ", ".join(dp["mcp"]) or "none"))
        if s["flags"]:
            o.append("- red flags (%d):" % len(s["flags"]))
            o += grouped_flags(s["flags"], "  ")
        else:
            o.append("- red flags: none")
        if s["defensive"]:
            o.append("- defensive mentions (not flags): " + _cut(
                ["%s:%d (%s)" % (x["file"], x["line"], x.get("why", ""))
                 for x in s["defensive"]], 12, "; "))
        o += set_apart_lines(s["in_tests"], s["notes"].get("pragmas", []))
        n = s["notes"]
        bits = []
        if n["links"]:
            bits.append("links to " + ", ".join(n["links"]))
        if n["local_urls"]:
            bits.append("local URLs at " + _cut(n["local_urls"], 6, ", "))
        if n["spawns"]:
            bits.append("spawns processes (%d site(s))" % n["spawns"])
        if n["config_mentions"]:
            bits.append("mentions config files without a write verb: "
                        + _cut(n["config_mentions"], 8, "; "))
        if n["unscanned"]:
            bits.append("not scanned: " + _cut(n["unscanned"], 8, ", "))
        if bits:
            o.append("- notes: " + " | ".join(bits))
        o.append("")
    for r in doc["repo_level"]:
        o += ["## Repo wiring outside skill folders - %s" % r["repo"], "",
              "_%d file(s) scanned%s_" % (r["files_scanned"],
                                          "; TRUNCATED at %d" % MAX_REPO_LEVEL_FILES
                                          if r["truncated"] else ""), ""]
        o += grouped_flags(r["flags"], "")
        if not r["flags"]:
            o.append("- none")
        if r.get("defensive"):
            o.append("- defensive mentions (not flags): " + _cut(
                ["%s:%d (%s)" % (x["file"], x["line"], x.get("why", ""))
                 for x in r["defensive"]], 12, "; "))
        o += set_apart_lines(r["in_tests"], r.get("pragmas", []))
        o.append("")
    return "\n".join(o)


# ---------------------------------------------------------------- collate

_STOP = set(("the and for use when not with that this from into your you are its one per "
             "each then than them they what who how why where which will can may any all "
             "only also but has have had been being before after over under out off about "
             "just like more most some such very via skill skills says asks user claude "
             "code agent file files using used uses onto does done did make makes need needs "
             "should must never always whenever every other without within through across "
             "between while both either neither see reference references tool tools new own "
             "way set get put run runs running say said ask asked asking invoke invokes "
             "instead there here these those it's dont don't").split())


def tokens(text):
    return set(t for t in re.findall(r"[a-z][a-z0-9-]{2,}", (text or "").lower())
               if t not in _STOP)


def triggers(desc):
    """Phrases a description says it fires on: quoted phrases, /commands, and
    what follows says / invokes / mentions / asks for."""
    out = set()
    d = desc or ""
    for m in re.finditer(r"[\"“']([^\"”'\n]{3,60})[\"”']", d):
        out.add(m.group(1).strip().lower())
    for m in re.finditer(r"(?<![\w/])(/[a-z][a-z0-9-]+)", d):
        out.add(m.group(1).lower())
    for m in re.finditer(r"\b(?:says?|invokes?|mentions?|types?|asks?(?:\s+for)?|calls?\s+it)"
                         r"\s+([a-z][a-z0-9 -]{2,50}?)(?=[,.;:)]|\s+or\s+|\s+and\s+|$)",
                         d, re.I):
        out.add(re.sub(r"\s+", " ", m.group(1).strip().lower()))
    return set(x.strip("\"' ") for x in out if len(x.strip("\"' ")) >= 3)


def load_home(dirs):
    homed = []
    for d in dirs:
        d = os.path.abspath(d)
        if not os.path.isdir(d):
            continue
        for n in sorted(os.listdir(d)):
            p = os.path.join(d, n, "SKILL.md")
            if os.path.isfile(p):
                t, _ = read_text(p)
                fm, _b = parse_frontmatter(t or "")
                desc = fm.get("description", ("", "", 0))[0]
                homed.append({"folder": n, "name": fm.get("name", (n, "", 0))[0].strip(),
                              "home": d, "desc": desc, "tokens": tokens(desc),
                              "triggers": triggers(desc)})
    return homed


def relate(s, h):
    a, b = s["tokens"], h["tokens"]
    shared = a & b
    jacc = len(shared) / len(a | b) if (a | b) else 0.0
    overlap = len(shared) / min(len(a), len(b)) if a and b else 0.0
    st = sorted(s["triggers"] & h["triggers"])
    na, nb = s["name"], h["name"]
    # two shared name parts alone are a naming habit, not a sibling
    # (subagent-driven-development and source-driven-development share no
    # domain, jaccard 0.01): they count only with some shared content too
    parts = len(set(na.split("-")) & set(nb.split("-")) - {"skill", "skills", "and", "the"})
    name_hit = na == nb or (len(na) > 5 and na in nb) or (len(nb) > 5 and nb in na) or \
        (parts >= 2 and (jacc >= 0.05 or bool(st)))
    if na == nb or (st and jacc >= 0.20) or jacc >= 0.35 or (overlap >= 0.6 and
                                                                len(shared) >= 8):
        kind = "duplicate"
    elif name_hit or st or jacc >= 0.15 or (overlap >= 0.4 and len(shared) >= 5):
        kind = "sibling"
    else:
        return None
    return {"skill": s["name"], "skill_path": s["path"], "homed": h["name"],
            "home": h["home"], "kind": kind, "jaccard": round(jacc, 3),
            "overlap": round(overlap, 3), "shared_tokens": sorted(shared)[:12],
            "shared_triggers": st, "same_name": na == nb, "decision": ""}


def cmd_collate(a):
    if not os.path.isfile(a.inventory):
        out_result("could not run - no inventory file at %s" % a.inventory)
        return 2
    try:
        with open(a.inventory, encoding="utf-8") as fh:
            inv = json.load(fh)
    except ValueError as e:
        out_result("could not run - %s is not JSON (%s); write it with inventory --json "
                   "--out" % (a.inventory, e))
        return 2
    homed = load_home(a.home)
    if not homed:
        out_result("could not run - no SKILL.md under --home %s" % ", ".join(a.home))
        return 2
    matches = []
    for s in inv.get("skills", []):
        cand = {"name": s.get("name") or s.get("folder"), "path": s.get("path"),
                "tokens": tokens(s.get("description", {}).get("text", "")),
                "triggers": triggers(s.get("description", {}).get("text", ""))}
        for h in homed:
            m = relate(cand, h)
            if m:
                matches.append(m)
    matches.sort(key=lambda m: (m["kind"] != "duplicate", -m["jaccard"]))
    dups = sum(1 for m in matches if m["kind"] == "duplicate")
    sibs = len(matches) - dups
    doc = {"inventory": os.path.abspath(a.inventory), "homes": [os.path.abspath(h)
                                                                 for h in a.home],
           "homed": len(homed), "skills": len(inv.get("skills", [])),
           "matches": matches, "generated": now()}
    if a.json:
        print(json.dumps(doc, indent=1, ensure_ascii=False))
    else:
        o = ["# Mutate collate - %d inventoried skill(s) against %d homed" % (
            doc["skills"], len(homed)), "",
            "_decide per row: keep (both, distinct domains), absorb (take the "
            "better parts into the homed one), or skip; the home's rule: a "
            "duplicate is rejected unless it verifiably supersedes_", "",
            "| inventoried | homed | kind | jaccard | shared tokens | shared triggers |"
            " decision |", "|---|---|---|---|---|---|---|"]
        for m in matches:
            o.append("| %s | %s | %s | %.2f | %s | %s | |" % (
                m["skill"], m["homed"], m["kind"].upper() if m["kind"] == "duplicate"
                else m["kind"], m["jaccard"], ", ".join(m["shared_tokens"][:8]),
                ", ".join(m["shared_triggers"]) or "-"))
        if not matches:
            o.append("| - | - | none | | | | |")
        print("\n".join(o))
    out_result("collate - %d skill(s) against %d homed: %d likely duplicate(s), %d "
               "sibling(s)%s" % (doc["skills"], len(homed), dups, sibs,
                                 "; decide keep, absorb or skip per row" if matches
                                 else "; no overlap found"))
    return 1 if matches else 0


# ---------------------------------------------------------------- ledger


def load_ledger(path):
    if not os.path.isfile(path):
        return {"version": 1, "rows": []}
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict) or not isinstance(doc.get("rows"), list):
        raise ValueError("not a ledger: no rows list")
    return doc


def save_ledger(path, doc):
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def _split(items, sep, what, problems):
    out = []
    for x in items or []:
        if sep not in x:
            problems.append("--%s %r has no '%s' - say %s" % (
                what, x, sep.strip(), "what -> where" if what == "absorbed" else "what: why"))
            continue
        left, right = x.split(sep, 1)
        if not left.strip() or not right.strip():
            problems.append("--%s %r is missing a side of '%s'" % (what, x, sep.strip()))
            continue
        out.append({"what": left.strip(), "where" if what == "absorbed" else "why":
                    right.strip()})
    return out


def cmd_ledger(a):
    path = os.path.abspath(a.ledger or DEFAULT_LEDGER)
    try:
        doc = load_ledger(path)
    except (OSError, ValueError) as e:
        out_result("could not run - ledger %s unreadable: %s" % (path, e))
        return 2
    if a.add:
        problems = []
        if not (a.source or "").strip():
            problems.append("--source is required (repo URL or a plain name)")
        if not re.fullmatch(r"[0-9a-fA-F]{7,40}", a.commit or ""):
            problems.append("--commit must be a hex SHA of 7 to 40 characters")
        if not (a.licence or "").strip():
            problems.append("--licence is required - say 'none' when there is none")
        if a.verdict not in VERDICTS:
            problems.append("--verdict must be one of %s" % " | ".join(VERDICTS))
        if not (a.reason or "").strip():
            problems.append("--reason is required: a row without a reason is refused "
                            "(the ratchet - every verdict carries its why)")
        absorbed = _split(a.absorbed, "->", "absorbed", problems)
        left_out = _split(a.left_out, ":", "left-out", problems)
        if a.verdict == "absorbed" and not absorbed and not problems:
            problems.append("--verdict absorbed with nothing --absorbed: say what and where")
        if problems:
            for p in problems:
                print("  " + p)
            out_result("REFUSED - ledger row not written (%d problem(s)); %s unchanged"
                       % (len(problems), path))
            return 2
        row = {"source": a.source.strip(), "commit": a.commit.lower(),
               "licence": a.licence.strip(), "absorbed": absorbed, "left_out": left_out,
               "verdict": a.verdict, "reason": a.reason.strip(),
               "date": a.date or datetime.date.today().isoformat()}
        doc["rows"].append(row)
        try:
            save_ledger(path, doc)
        except OSError as e:
            out_result("could not run - cannot write %s: %s" % (path, e))
            return 2
        out_result("ledger row %d written to %s - %s %s @ %s (%s)" % (
            len(doc["rows"]), path, a.verdict, row["source"], row["commit"][:7],
            row["licence"]))
        return 0
    rows = doc["rows"]
    bad = [i for i, r in enumerate(rows) if not str(r.get("reason") or "").strip()]
    if a.json:
        print(json.dumps({"ledger": path, "rows": rows, "without_reason": bad},
                         indent=1, ensure_ascii=False))
    else:
        o = ["# Mutate ledger - %s" % path, "", "| # | date | verdict | source @ commit | "
             "licence | absorbed | left out | reason |", "|---|---|---|---|---|---|---|---|"]
        for i, r in enumerate(rows, 1):
            o.append("| %d | %s | %s | %s @ %s | %s | %s | %s | %s |" % (
                i, r.get("date", ""), r.get("verdict", ""), r.get("source", ""),
                str(r.get("commit", ""))[:7], r.get("licence", ""),
                "; ".join("%s -> %s" % (x.get("what"), x.get("where"))
                          for x in r.get("absorbed", [])) or "-",
                "; ".join("%s: %s" % (x.get("what"), x.get("why"))
                          for x in r.get("left_out", [])) or "-",
                r.get("reason") or "MISSING - refused"))
        if not rows:
            o.append("| - | | | | | | | |")
        print("\n".join(o))
        for i in bad:
            print("  row %d (%s) has no reason - a row without a reason is refused"
                  % (i + 1, rows[i].get("source", "?")))
    out_result("ledger %s - %d row(s); %d without a reason%s" % (
        path, len(rows), len(bad), " (FAIL: add the reason)" if bad else ""))
    return 1 if bad else 0


# ---------------------------------------------------------------- evolve

_GIT_URL = re.compile(r"^(https?://[\w.-]+/[\w./-]+?|git@[\w.-]+:[\w./-]+?|ssh://[\w.@/-]+?)"
                      r"(\.git)?/?$")


def git_url(source):
    s = (source or "").strip()
    return s if _GIT_URL.match(s) else None


def ls_remote(url):
    """(head sha or None, error text). The only network call in this file."""
    try:
        p = subprocess.run(("git", "ls-remote", "--exit-code", url, "HEAD"),
                           capture_output=True, timeout=60,
                           env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    except (OSError, subprocess.SubprocessError) as e:
        return None, "git ls-remote could not run: %s" % e
    if p.returncode != 0:
        return None, (p.stderr.decode("utf-8", "replace").strip().split("\n")[-1]
                      or "exit %d" % p.returncode)
    line = p.stdout.decode("utf-8", "replace").strip().split("\n")[0]
    sha = line.split("\t")[0].strip() if line else ""
    return (sha if re.fullmatch(r"[0-9a-f]{40}", sha) else None), ""


def cmd_evolve(a):
    path = os.path.abspath(a.ledger or DEFAULT_LEDGER)
    try:
        doc = load_ledger(path)
    except (OSError, ValueError) as e:
        out_result("could not run - ledger %s unreadable: %s" % (path, e))
        return 2
    sources, new, failed, checked = [], 0, 0, 0
    for r in doc["rows"]:
        url = git_url(r.get("source", ""))
        pin = str(r.get("commit") or "")
        e = {"source": r.get("source"), "commit": pin, "verdict": r.get("verdict"),
             "checkable": bool(url), "upstream": None, "status": ""}
        if not url:
            e["status"] = "no remote - source is not a git URL, nothing to check"
        elif not a.online:
            e["status"] = "would check %s against upstream HEAD (pass --online)" % pin[:7]
        else:
            head, err = ls_remote(url)
            checked += 1
            if head is None:
                failed += 1
                e["status"] = "UNKNOWN - %s" % err
            elif head.startswith(pin.lower()) or pin.lower().startswith(head):
                e["status"] = "up to date - upstream HEAD is the pinned commit"
            else:
                new += 1
                e["upstream"] = head
                e["status"] = ("NEW upstream commits - pinned %s, HEAD %s: diff and "
                               "absorb what does not break anything" % (pin[:7], head[:7]))
        sources.append(e)
    when = now()
    if a.json:
        print(json.dumps({"ledger": path, "online": bool(a.online), "checked_at": when,
                          "sources": sources}, indent=1, ensure_ascii=False))
    else:
        print("# Mutate evolve - %s (%s, %s)" % (path, "ONLINE: git ls-remote, read-only"
                                                 if a.online else "offline", when))
        print("")
        for e in sources:
            print("- %s @ %s [%s]: %s" % (e["source"], (e["commit"] or "")[:7],
                                         e["verdict"], e["status"]))
        if not sources:
            print("- the ledger has no rows")
    if not a.online:
        out_result("evolve offline - %d source(s) would be checked, %d have no remote; "
                   "nothing was requested; pass --online to ask each upstream HEAD with "
                   "git ls-remote (read-only)" % (
                       sum(1 for e in sources if e["checkable"]),
                       sum(1 for e in sources if not e["checkable"])))
        return 0
    out_result("evolve online - %d source(s) checked at %s: %d with new upstream commits, "
               "%d up to date, %d unknown" % (checked, when, new,
                                              checked - new - failed, failed))
    return 1 if new else (2 if failed and not new else 0)


# ---------------------------------------------------------------- main


class Parser(argparse.ArgumentParser):
    """argparse, except a usage error still ends in a RESULT line - the operator reads
    that line, and argparse's own exit 2 printed only usage."""

    def error(self, message):
        self.print_usage(sys.stderr)
        out_result("could not run - %s: %s" % (self.prog, message))
        sys.exit(2)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = Parser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", parser_class=Parser)
    i = sub.add_parser("inventory", help="read-only inspect a folder of skills")
    i.add_argument("folder")
    i.add_argument("--json", action="store_true")
    i.add_argument("--out", help="write the report here instead of stdout")
    i.add_argument("--skill", action="append", help="only this skill (repeatable)")
    c = sub.add_parser("collate", help="overlap with skills already homed")
    c.add_argument("inventory", help="inventory JSON from `inventory --json --out`")
    c.add_argument("--home", action="append", required=True)
    c.add_argument("--json", action="store_true")
    l = sub.add_parser("ledger", help="read or write the Mutate ledger")
    l.add_argument("--ledger", help="ledger path (default %s)" % DEFAULT_LEDGER)
    l.add_argument("--add", action="store_true")
    l.add_argument("--source")
    l.add_argument("--commit")
    l.add_argument("--licence", "--license", dest="licence")
    l.add_argument("--absorbed", action="append", help='"what -> where" (repeatable)')
    l.add_argument("--left-out", action="append", help='"what: why" (repeatable)')
    l.add_argument("--verdict", help=" | ".join(VERDICTS))
    l.add_argument("--reason")
    l.add_argument("--date")
    l.add_argument("--json", action="store_true")
    e = sub.add_parser("evolve", help="pinned commit versus upstream head, per ledger row")
    e.add_argument("--ledger")
    e.add_argument("--online", action="store_true",
                   help="ask each remote with git ls-remote - the only network call")
    e.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cmds = {"inventory": cmd_inventory, "collate": cmd_collate,
            "ledger": cmd_ledger, "evolve": cmd_evolve}
    if a.cmd in cmds:
        try:
            return cmds[a.cmd](a)
        except Exception as ex:  # a crash still ends in a RESULT line, exit 2
            import traceback
            traceback.print_exc()
            out_result("could not run - %s crashed: %s: %s"
                       % (a.cmd, type(ex).__name__, ex))
            return 2
    ap.print_help()
    out_result("could not run - no command given (inventory | collate | ledger | evolve)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
