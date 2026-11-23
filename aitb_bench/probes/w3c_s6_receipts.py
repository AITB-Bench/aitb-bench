#!/usr/bin/env python3
"""S6 receipt gate: does each external-review receipt match ITS OWN current document?

A receipt produced from an older draft proves nothing, and a receipt for the
markdown file does not cover the plain-text email that will actually be posted.
So every directory that holds receipts is checked, and each aggregate is
compared against the file named in its own "target" field.

No absolute paths are written here. The package root comes from, in order:
environment W3C_PKG, config.local.json / config.example.json "W3C_PKG",
then the repo-local bundle evidence/w3c-aiam. A receipt whose "target" is a
bare relative path is resolved against the same root, so a bundled copy runs
off a clean clone.

Exit 0 = PASS, 1 = FAIL. Prints one line starting with "S6:".
"""
import glob, hashlib, json, os, sys
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))
try:
    from vars import load_vars
    _V = load_vars()
except Exception:
    _V = {}

def _default_pkg():
    """evidence/w3c-aiam: env, then config, then beside the package, then repo root.

    A relative value in config.example.json is read against the repo root, not
    against the process cwd, because the runner sets cwd to the package dir.
    """
    raw = os.environ.get("W3C_PKG") or _V.get("W3C_PKG")
    cands = []
    if raw:
        cands += [Path(raw), BENCH / raw, BENCH.parent / raw]
    cands += [BENCH / "evidence" / "w3c-aiam", BENCH.parent / "evidence" / "w3c-aiam"]
    for c in cands:
        if c.is_dir():
            return c
    return BENCH / "evidence" / "w3c-aiam"


PKG = _default_pkg()
DOC = str(PKG / "04b_提案_list版.md")
RECS = [str(PKG / "22_S6外部AI实跑"), str(PKG / "22_S6外部AI实跑" / "email")]
WANT_LENSES = {"expert", "process", "adversary", "outsider"}
REQUIRED_TARGETS = {os.path.normcase(DOC)}


def resolve(tgt):
    if not tgt:
        return tgt
    p = Path(tgt)
    if p.is_absolute():
        return str(p)
    return str((PKG / p).resolve())


def check(path):
    a = json.load(open(path, encoding="utf-8"))
    tgt = resolve(a.get("target") or "")
    if not os.path.exists(tgt):
        return ["target file missing: " + tgt]
    h = hashlib.sha256(open(tgt, encoding="utf-8").read().encode("utf-8")).hexdigest()[:16]
    problems = []
    if a.get("doc_sha256_16") != h:
        problems.append(f"hash drift {os.path.basename(tgt)}: receipt {a.get('doc_sha256_16')} vs file {h}")
    if set(a.get("lenses", [])) != WANT_LENSES:
        problems.append(f"lenses {a.get('lenses')} {os.path.basename(tgt)}")
    if not a.get("all_parsed"):
        problems.append("unparseable output " + os.path.basename(tgt))
    if a.get("counts", {}).get("blocker", 1) != 0:
        problems.append(f"blockers={a.get('counts', {}).get('blocker')} {os.path.basename(tgt)}")
    if not a.get("model"):
        problems.append("no model recorded")
    return problems


def main():
    seen, problems, lines = set(), [], []
    for rec in RECS:
        aggs = sorted(glob.glob(os.path.join(rec, "*_aggregate.json")))
        if not aggs:
            problems.append("no receipts in " + rec)
            continue
        latest = aggs[-1]
        p = check(latest)
        a = json.load(open(latest, encoding="utf-8"))
        if p:
            problems.extend(p)
        else:
            tgt = resolve(a["target"])
            seen.add(os.path.normcase(tgt))
            c = a["counts"]
            lines.append(f"{os.path.basename(tgt)}={c['blocker']}/{c['major']}/{c['minor']}")
    missing = REQUIRED_TARGETS - seen
    if missing:
        problems.append("no valid receipt for: " + ", ".join(os.path.basename(m) for m in missing))
    if problems:
        print("S6: FAIL " + "; ".join(problems))
        return 1
    print("S6: PASS " + " | ".join(lines) + " (b/m/mi)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
