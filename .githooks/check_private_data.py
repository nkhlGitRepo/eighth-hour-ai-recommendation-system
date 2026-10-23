#!/usr/bin/env python3
"""
Keeps private data out of this repository, which is public.

    python3 .githooks/check_private_data.py --staged        # what is about to be committed (pre-commit)
    python3 .githooks/check_private_data.py --message FILE  # a commit message (commit-msg)
    python3 .githooks/check_private_data.py --push          # commits about to be pushed (pre-push)
    python3 .githooks/check_private_data.py --tree          # every tracked file
    python3 .githooks/check_private_data.py --history       # every commit on every branch

It refuses:
  - files that are never committed: anything in shopify/private/ or
    planning_documents/, .env and secrets files, databases, key files;
  - the values in shopify/private/secrets.env, and the unreleased launch list's
    SKUs, style names and colour names (shopify/private/mystyle-launch-data.liquid),
    whenever those files are on this machine -- plus anything shaped like one of
    the brand's SKUs (tests use made-up ones with the TS99- prefix);
  - text shaped like a credential (Shopify, GitHub, AWS, Google, Slack, Stripe,
    Anthropic/OpenAI keys, private key blocks, a long random string assigned to a
    secret, token, password or key) and links to Google documents, which are the
    brand's own.

Findings name the file, line and kind of data, never the value. The hooks are
switched on per clone with:  git config core.hooksPath .githooks
"""

import json
import math
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = ROOT / "shopify" / "private"
ZERO_SHA = "0" * 40


def _never_committed(path):
    name = path.rsplit("/", 1)[-1]
    if path.startswith(("shopify/private/", "planning_documents/")):
        return "a private file (shopify/private/ and planning_documents/ stay local)"
    if name in ("secrets.env", "secret.env") or (name.startswith(".env") and name != ".env.example"):
        return "an environment or secrets file"
    if re.search(r"\.(db|sqlite3?)$", name):
        return "a database"
    if re.search(r"\.(pem|key|p12|pfx)$", name):
        return "a key file"
    return None


CREDENTIAL_SHAPES = [
    (re.compile(r"\bshp(at|ss|ca|pa|ua)_[0-9a-fA-F]{32}"), "a Shopify access token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a private key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "an AWS access key"),
    (re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})"), "a GitHub token"),
    (re.compile(r"\bsk-(ant-)?[A-Za-z0-9_-]{32,}"), "an Anthropic or OpenAI key"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "a Slack token"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}"), "a Google API key"),
    (re.compile(r"\b[rs]k_live_[0-9A-Za-z]{20,}"), "a Stripe live key"),
    (re.compile(r"(docs\.google\.com/(spreadsheets|document|presentation)/d/|drive\.google\.com/)"),
     "a link to a Google document"),
]
# Anything shaped like the brand's SKUs (season, garment and style codes);
# made-up ones in tests use the TS99- prefix. The
# cached copy of the live store's own products.json holds its public SKUs.
BRAND_SKU = re.compile(r"(?<![A-Z0-9])(?!TS99)[A-Z]{2}\d{2}-[A-Z]{2,4}-[A-Z]\d{3}")
PUBLIC_STORE_SNAPSHOTS = {"backend/catalog_source.json"}
ASSIGNED_SECRET = re.compile(
    r"(?i)(secret|token|passw(or)?d|api[_-]?key|private[_-]?key|server[_-]?key|signing[_-]?key)"
    r"\w*[\"']?\s*[:=]\s*[\"']([A-Za-z0-9_\-+/=.]{20,})[\"']"
)


def _looks_random(value):
    if not (re.search(r"\d", value) and re.search(r"[A-Za-z]", value)):
        return False
    counts = Counter(value)
    entropy = -sum(n / len(value) * math.log2(n / len(value)) for n in counts.values())
    return entropy >= 3.5


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def private_needles():
    """(text, kind, case_sensitive) for every private value on this machine."""
    needles = []
    env = PRIVATE / "secrets.env"
    if env.exists():
        for line in env.read_text().splitlines():
            key, _, value = line.partition("=")
            if not line.startswith("#") and len(value.strip()) >= 8:
                needles.append((value.strip(), f"the value of {key.strip()} from shopify/private/secrets.env", True))
    launch = PRIVATE / "mystyle-launch-data.liquid"
    if launch.exists():
        raw = launch.read_text()
        try:
            data = json.loads(raw[raw.index("endcomment -%}") + len("endcomment -%}"):])
        except ValueError:
            print(f"warning: could not read {launch}; its names are not being checked", file=sys.stderr)
            data = {}
        for style in data.get("styles", []):
            needles.append((style["name"], "an unreleased style name", False))
            needles.append((_slug(style["name"]), "an unreleased style name", False))
            for sku in style.get("skus", []):
                # The code after the season prefix too, so swapping the prefix hides nothing.
                needles += [(sku, "an unreleased SKU", False), (sku.split("-", 1)[-1], "an unreleased SKU", False)]
        needles += [(c["name"], "an unreleased launch colour name", False) for c in data.get("colors", [])]
    return needles


def findings_in_text(where, text, needles=(), brand_skus=True):
    """[(where:line, kind)] for every line of text holding private data."""
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        lowered = line.lower()
        kinds = [kind for needle, kind, exact in needles
                 if (needle in line if exact else needle.lower() in lowered)]
        kinds += [kind for pattern, kind in CREDENTIAL_SHAPES if pattern.search(line)]
        kinds += ["a brand SKU"] if brand_skus and BRAND_SKU.search(line) else []
        kinds += ["a hard-coded secret" for m in ASSIGNED_SECRET.finditer(line) if _looks_random(m.group(3))]
        found += [(f"{where}:{number}", kind) for kind in dict.fromkeys(kinds)]
    return found


def findings_in_file(path, content, needles):
    kind = _never_committed(path)
    if kind:
        return [(path, kind)]
    if b"\0" in content[:8192]:
        return []
    return findings_in_text(path, content.decode("utf-8", errors="ignore"), needles,
                            brand_skus=path not in PUBLIC_STORE_SNAPSHOTS)


def git(*args, check=True):
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=check)
    return result.stdout


def changed_paths(*args):
    return [p for p in git(*args, "-z").decode().split("\0") if p]


def scan_commits(commits, needles):
    found = []
    for commit in commits:
        message = git("log", "-1", "--format=%B", commit).decode("utf-8", errors="ignore")
        found += findings_in_text(f"message of {commit[:7]}", message, needles)
        for path in changed_paths("diff-tree", "--root", "--no-commit-id", "-r", "--name-only",
                                  "--diff-filter=ACMR", commit):
            found += [(f"{commit[:7]} {where}", kind)
                      for where, kind in findings_in_file(path, git("show", f"{commit}:{path}"), needles)]
    return found


def main(argv):
    mode = argv[1] if len(argv) > 1 else "--staged"
    needles = private_needles()
    found = []
    if mode == "--staged":
        for path in changed_paths("diff", "--cached", "--name-only", "--diff-filter=ACMR"):
            found += findings_in_file(path, git("show", f":{path}"), needles)
    elif mode == "--message":
        text = Path(argv[2]).read_text(errors="ignore")
        text = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
        found = findings_in_text("commit message", text, needles)
    elif mode == "--push":
        for line in sys.stdin:
            parts = line.split()
            if len(parts) == 4 and parts[1] != ZERO_SHA:
                commits = git("rev-list", parts[1], "--not", "--remotes").decode().split()
                found += scan_commits(commits, needles)
    elif mode == "--tree":
        for path in changed_paths("ls-files"):
            file = ROOT / path
            if file.is_file():
                found += findings_in_file(path, file.read_bytes(), needles)
    elif mode == "--history":
        found = scan_commits(git("rev-list", "--all").decode().split(), needles)
    else:
        raise SystemExit(__doc__)

    found = list(dict.fromkeys(found))
    for where, kind in found:
        print(f"{where}: {kind}")
    if found:
        print("\nThis repository is public, so that was refused. Keep secrets and the launch list in "
              "shopify/private/ (ignored), and use made-up names and TS99- SKUs in tests.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
