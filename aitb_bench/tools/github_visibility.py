#!/usr/bin/env python3
"""Classify a GitHub repo as PUBLIC / PRIVATE / UNKNOWN without any credential.

Why not the REST API: unauthenticated api.github.com answers 404 for a private
repo but 403 when it rate-limits you, and 403 also appears for abuse detection.
Treating 403 as "private" (or as "checked") is a fake green -- see
00_发布前审查标准_v2, pseudo-green #5. The git wire protocol is steadier:
a private or missing repo cannot serve refs without credentials, so
`git ls-remote` fails with an auth/not-found error, while a public repo lists
heads with no credential at all.

Usage:  python github_visibility.py owner/repo [owner/repo ...]
Prints one line per repo:  S9: PUBLIC owner/repo  (or PRIVATE / UNKNOWN)
Exit 0 always (the caller reads the classification), 2 on bad usage.
"""
import json, os, re, subprocess, sys, time

PRIVATE_HINTS = (
    "could not read Username", "Authentication failed", "terminal prompts disabled",
    "Repository not found", "not found", "fatal: could not read",
)

def classify(slug, tries=3):
    verdict, note = "UNKNOWN", "no attempt"
    for i in range(tries):
        verdict, note = _once(slug)
        if verdict in ("PUBLIC", "PRIVATE"):
            return verdict, note
        if i + 1 < tries:
            time.sleep(4 + 3 * i)  # network flake: back off, do not report a verdict we did not get
    return verdict, note


def _once(slug):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="echo", GCM_INTERACTIVE="never")
    url = f"https://github.com/{slug}.git"
    try:
        r = subprocess.run(["git", "ls-remote", "--heads", url],
                           capture_output=True, text=True, timeout=45, env=env)
    except subprocess.TimeoutExpired:
        return "UNKNOWN", "timeout"
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode == 0 and re.search(r"refs/heads/", r.stdout or ""):
        return "PUBLIC", (r.stdout or "").strip().splitlines()[0]
    if r.returncode == 0:
        return "UNKNOWN", "no refs listed"
    low = out.lower()
    if any(h.lower() in low for h in PRIVATE_HINTS):
        return "PRIVATE", out.strip().splitlines()[-1][:120]
    return "UNKNOWN", out.strip().splitlines()[-1][:120] if out.strip() else f"rc={r.returncode}"

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    emit = None
    for a in sys.argv[1:]:
        if a.startswith("--emit="):
            emit = a.split("=", 1)[1]
    if not args:
        print("usage: github_visibility.py owner/repo [...] [--emit=path.json]")
        return 2
    rows = []
    for slug in args:
        verdict, note = classify(slug)
        print(f"S9: {verdict} {slug}  ({note})")
        rows.append({"repo": slug, "verdict": verdict, "note": note})
    if emit:
        os.makedirs(os.path.dirname(emit) or ".", exist_ok=True)
        payload = {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "epoch": int(time.time()),
                   "tool": "github_visibility.py (git ls-remote, no credential)", "results": rows}
        with open(emit, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        print(f"evidence written: {emit}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
