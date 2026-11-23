#!/usr/bin/env python3
"""After the post is sent: find our message in the public archive and record it as E12.

Why this exists: the moment the mail leaves the sender's mailbox, the evidence
chain changes. The new post must be archived with URL + hash + Date header,
otherwise the next document cites "I posted a proposal" with nothing behind it.

Usage (from bench/):
    python tools/w3c_archive_probe.py --marker "retention-and-erasure crosswalk"

It scans the newest archive month indexes (2026Nov, then 2026Oct) for a message
whose subject matches the marker, prints the permalink, Date header and SHA-16
of the page, and exits 1 if nothing is found yet (an absent post is not an error
to hide, it is simply "not sent yet").
"""
import argparse, hashlib, re, sys, urllib.request

BASE = "https://lists.w3.org/Archives/Public/public-ai-agent-memory-interop/"
MONTHS = ["2026Nov", "2026Dec", "2026Oct"]
UA = {"User-Agent": "w3c-archive-probe/1.0"}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--marker", default="retention-and-erasure crosswalk")
    args = ap.parse_args()
    marker = args.marker.lower()

    for month in MONTHS:
        try:
            idx = get(f"{BASE}{month}/")
        except Exception as e:
            print(f"[skip] {month}: {e}")
            continue
        links = re.findall(r'href="(\d{4}\.html)"[^>]*>([^<]*)<', idx)
        hits = [(u, t) for u, t in links if marker in t.lower()]
        hits = hits or [(u, t) for u, t in links if "crosswalk" in t.lower()]
        if not hits:
            print(f"[none] {month}: {len(links)} messages, no subject match")
            continue
        for url_part, title in hits[-2:]:
            url = f"{BASE}{month}/{url_part}"
            try:
                page = get(url)
            except Exception as e:
                print(f"[warn] {url}: {e}")
                continue
            date = re.search(r"Date\s*:?\s*</th>\s*<td[^>]*>([^<]+)", page) or \
                   re.search(r"Date\s*:\s*([A-Z][a-z]{2},[^<]{5,40})", page)
            sha = hashlib.sha256(page.encode("utf-8")).hexdigest()[:16].upper()
            print(f"FOUND {url}")
            print(f"  subject: {title.strip()}")
            print(f"  date   : {date.group(1).strip() if date else '(not parsed)'}")
            print(f"  sha16  : {sha}")
            print(f"  bytes  : {len(page)}")
        return 0
    print("NOT FOUND yet -- likely not sent, or archive lag. Re-run later; do not record an E12 without it.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
