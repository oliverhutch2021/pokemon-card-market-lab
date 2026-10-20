#!/usr/bin/env python3
"""Publish guard: blocks commits/pushes that would leak secrets, personal
details, licensed raw data, card images or oversized files.

Usage
  guard.py staged            check files staged for commit (pre-commit hook)
  guard.py tree [REV]        check every file in a revision (pre-push hook, CI)
  guard.py msg FILE          check a commit message (commit-msg hook)
  guard.py add "TEXT"        add a private term to the hashed denylist

The private denylist stores SHA-256 hashes of lower-cased private terms
(emails, phone numbers, addresses). It is NOT committed to the public repo:
short terms like phone numbers can be brute-forced from their hashes. Matching hashes every 1-4 word window of a file.
"""
import fnmatch, hashlib, os, re, subprocess, sys

ROOT = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip() or "."
# The denylist is private: phone numbers and guessable emails can be brute-forced
# from hashes, so it lives outside the public repo (path set by `git config guard.denylist`).
DENYLIST = subprocess.run(["git", "config", "guard.denylist"], capture_output=True, text=True, cwd=ROOT).stdout.strip() \
    or os.path.join(ROOT, "tools", "denylist.sha256")
CONFIG = os.path.join(ROOT, "tools", "guard_config.py")

# ---- defaults (the data repo overrides these in tools/guard_config.py) ----
MAX_BYTES = 1_000_000          # nothing big: raw dumps are the usual culprit
BLOCKED_PATHS = [
    "data/raw/*", "data/cache/*", "data/private/*", "*.env", ".env*", "*secret*", "*credential*",
    "*apikey*", "*api_key*", "*.pem", "*.key", "*.p12", "*.sqlite", "*.db", "*.duckdb", "*.parquet",
    "*.csv.gz", "*.json.gz", "*.zip", "*.7z", "*.pkl", "*.ipynb_checkpoints*",
]
# images only allowed as our own charts in docs/figures
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".bmp", ".tif", ".tiff")
IMAGE_ALLOWED = ["docs/figures/*"]
# tabular data only allowed as small derived summaries
DATA_EXT = (".csv", ".tsv", ".json", ".jsonl", ".xlsx", ".xls")
DATA_ALLOWED = ["data/derived/*", "tests/fixtures/*", "*.schema.json", ".github/*", "package.json"]
# field names that only appear in raw responses from licensed sources
RAW_MARKERS = [
    r'"salesByGrade"', r'"soldListings"', r'"priceHistory"', r'"cardmarketPrices"', r'"smartMarketPrice"',
    r'"priceGuides"', r'"idProduct"\s*:\s*\d+\s*,\s*"idCategory"', r'"avg-holo"', r'"apiCallsConsumed"',
]
PUBLIC_REPO = True
try:
    exec(open(CONFIG).read())
except FileNotFoundError:
    pass

SECRET_PATTERNS = [
    (r"(?i)authorization\s*[:=]\s*['\"]?bearer\s+[A-Za-z0-9._\-]{12,}", "Bearer token"),
    (r"gh[pousr]_[A-Za-z0-9]{30,}", "GitHub token"),
    (r"github_pat_[A-Za-z0-9_]{40,}", "GitHub token"),
    (r"AKIA[0-9A-Z]{16}", "AWS key"),
    (r"sk-[A-Za-z0-9_\-]{20,}", "API secret key"),
    (r"AIza[0-9A-Za-z_\-]{35}", "Google API key"),
    (r"xox[abprs]-[A-Za-z0-9-]{10,}", "Slack token"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key"),
    (r"(?i)\b\w*(key|secret|token|password|passwd)\b\s*[:=]\s*['\"][^'\"\s]{12,}['\"]", "hard-coded credential"),
]
PERSONAL_PATTERNS = [
    (r"[A-Za-z0-9._%+\-]+@(?!users\.noreply\.github\.com\b|example\.(com|org)\b|noreply\.)[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", "email address"),
    (r"(?<!\d)(?:\+44\s?7\d{3}|\(?07\d{3}\)?)\s?\d{3}\s?\d{3}(?!\d)", "UK mobile number"),
    (r"(?<![\d.])(?:\+44\s?|0)(?:1|2|3)\d{2,3}\s?\d{3}\s?\d{3,4}(?!\d)", "UK phone number"),
    (r"\b[A-Z]{1,2}\d[A-Z\d]?\s+\d[A-Z]{2}\b", "UK postcode"),
    (r"https?://claude\.ai/(?:artifact|code|chat|share|project)/\S+", "private claude.ai link"),
    (r"\b\d{2}-?\d{2}-?\d{2}\s+\d{8}\b", "sort code + account number"),
    (r"\b(?:\d[ -]?){13,19}\b(?=.*(?i:card|visa|mastercard))", "card number"),
]
MSG_PATTERNS = [
    (r"(?im)^co-authored-by:.*", "co-author trailer"),
    (r"(?im)^claude-session:.*", "session link trailer"),
    (r"https?://claude\.ai/\S+", "private claude.ai link"),
]
ALLOW_INLINE = "guard:allow"   # put on a line to whitelist it (e.g. a regex test)


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, cwd=ROOT).stdout


def load_hashes():
    try:
        return {l.strip() for l in open(DENYLIST) if l.strip() and not l.startswith("#")}
    except FileNotFoundError:
        return set()


def norm(t):
    return re.sub(r"\s+", " ", t.strip().lower())


def h(t):
    return hashlib.sha256(norm(t).encode()).hexdigest()


def windows(text, n=4):
    words = re.findall(r"[\w@.+\-']+", text.lower())
    for i in range(len(words)):
        for k in range(1, n + 1):
            if i + k <= len(words):
                yield " ".join(words[i:i + k])


def match_any(path, pats):
    return any(fnmatch.fnmatch(path, p) or fnmatch.fnmatch(os.path.basename(path), p) for p in pats)


def check_file(path, blob, hashes):
    errs = []
    low = path.lower()
    if path.startswith("tools/denylist") or path == "tools/guard.py":
        return errs  # the guard itself contains the patterns
    if match_any(low, BLOCKED_PATHS):
        errs.append("blocked path/type")
    if len(blob) > MAX_BYTES:
        errs.append(f"too large ({len(blob):,} bytes > {MAX_BYTES:,})")
    if PUBLIC_REPO and low.endswith(IMAGE_EXT) and not match_any(low, IMAGE_ALLOWED):
        errs.append("image outside docs/figures (card images are copyrighted)")
    if PUBLIC_REPO and low.endswith(DATA_EXT) and not match_any(low, DATA_ALLOWED):
        errs.append("data file outside data/derived (raw data is licensed)")
    if b"\x00" in blob[:8000]:
        return errs  # binary: path/size rules only
    text = blob.decode("utf-8", "replace")
    lines = [l for l in text.splitlines() if ALLOW_INLINE not in l]
    body = "\n".join(lines)
    for pat, name in SECRET_PATTERNS + PERSONAL_PATTERNS:
        m = re.search(pat, body)
        if m:
            errs.append(f"{name}: {m.group(0)[:6]}… (line {body[:m.start()].count(chr(10)) + 1})")
    if PUBLIC_REPO:
        for pat in RAW_MARKERS:
            if re.search(pat, body):
                errs.append(f"looks like a raw licensed API response ({pat.strip(chr(92))[:20]})")
                break
    if hashes:
        for w in windows(body):
            if h(w) in hashes:
                errs.append("matches a private denylist term")
                break
    return errs


def report(bad):
    if not bad:
        return 0
    print("\n❌ guard: blocked. Nothing was committed/pushed.\n", file=sys.stderr)
    for p, errs in bad:
        for e in errs:
            print(f"  {p}: {e}", file=sys.stderr)
    print("\nFix the file, or move it to a git-ignored folder (data/raw, data/private).", file=sys.stderr)
    return 1


def main():
    if len(sys.argv) < 2:
        print(__doc__); return 2
    cmd = sys.argv[1]
    hashes = load_hashes()
    if cmd == "add":
        t = " ".join(sys.argv[2:])
        if not t:
            print("usage: guard.py add TEXT"); return 2
        with open(DENYLIST, "a") as f:
            f.write(h(t) + "\n")
        print("added 1 hashed term"); return 0
    if cmd == "msg":
        text = open(sys.argv[2], encoding="utf-8").read()
        text = "\n".join(l for l in text.splitlines() if not l.startswith("#"))
        errs = [f"{n}" for p, n in MSG_PATTERNS + PERSONAL_PATTERNS + SECRET_PATTERNS if re.search(p, text)]
        if hashes and any(h(w) in hashes for w in windows(text)):
            errs.append("matches a private denylist term")
        return report([("commit message", errs)] if errs else [])
    if cmd == "staged":
        names = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").decode().split("\0")
        bad = []
        for p in filter(None, names):
            blob = git("show", f":{p}")
            e = check_file(p, blob, hashes)
            if e: bad.append((p, e))
        return report(bad)
    if cmd == "tree":
        rev = sys.argv[2] if len(sys.argv) > 2 else "HEAD"
        names = git("ls-tree", "-r", "--name-only", "-z", rev).decode().split("\0")
        bad = []
        for p in filter(None, names):
            e = check_file(p, git("show", f"{rev}:{p}"), hashes)
            if e: bad.append((p, e))
        # also commit messages and author emails on this revision's history
        log = git("log", "--format=%ae%n%B%x00", rev).decode("utf-8", "replace")
        for ae in set(re.findall(r"^(\S+@\S+)$", log, re.M)):
            if not ae.endswith("@users.noreply.github.com"):
                bad.append(("commit author", [f"non-noreply author email {ae[:3]}…"]))
        for p, n in MSG_PATTERNS:
            if re.search(p, log):
                bad.append(("commit history", [n]))
        return report(bad)
    print(__doc__); return 2


if __name__ == "__main__":
    sys.exit(main())
