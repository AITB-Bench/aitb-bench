#!/usr/bin/env python3
"""S9 gate: read the dated visibility snapshot instead of hitting GitHub live.

Why: `git ls-remote` to github.com failed intermittently on this host
("Failed to connect ... port 443"). A live-network check inside the gate then
goes red for the weather, not for the repo -- and a gate that cries wolf gets
switched off. So the gate reads evidence written by
`tools/github_visibility.py ... --emit=evidence/s9_visibility.json`, and fails
for exactly three honest reasons: no snapshot, a stale snapshot, or a verdict
that is not what we claim in the report.

The snapshot lives inside this checkout; no absolute path is written down.

Exit 0 = PASS, 1 = FAIL. Prints one line starting with "S9:".
"""
import json, os, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
def _default_evidence():
    for cand in (HERE / "evidence" / "s9_visibility.json", HERE.parent / "evidence" / "s9_visibility.json"):
        if cand.exists():
            return str(cand)
    return str(HERE / "evidence" / "s9_visibility.json")


EVIDENCE = os.environ.get("S9_EVIDENCE") or _default_evidence()
MAX_AGE_DAYS = 7
EXPECT = {
    # the instrument itself, cloneable by strangers, under its own organisation
    "AITB-Bench/aitb-bench": "PUBLIC",
    # the contract half of the story: the bench has to be reachable without a login
    "LGD-Eval/aitb-bench": "PUBLIC",
}


def main():
    if not os.path.exists(EVIDENCE):
        print("S9: FAIL no visibility evidence; run tools/github_visibility.py ... --emit=evidence/s9_visibility.json")
        return 1
    ev = json.load(open(EVIDENCE, encoding="utf-8"))
    age_days = (time.time() - float(ev.get("epoch", 0)) ) / 86400.0
    if age_days > MAX_AGE_DAYS:
        print(f"S9: STALE evidence {age_days:.1f}d old (max {MAX_AGE_DAYS}d) -- re-run the collector")
        return 1
    got = {r["repo"]: r["verdict"] for r in ev.get("results", [])}
    bad = [f"{k}={got.get(k, 'MISSING')} want {v}" for k, v in EXPECT.items() if got.get(k) != v]
    if bad:
        print("S9: FAIL " + "; ".join(bad))
        return 1
    print("S9: PASS " + " ".join(f"{k}={v}" for k, v in EXPECT.items()) + f" evidence_age={age_days:.1f}d")
    return 0


if __name__ == "__main__":
    sys.exit(main())
