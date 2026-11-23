# AITB · Assurance Instrument Test Bench

**Make it fail first.**

AITB tests the instrument you use to judge — not the thing being judged.
Gates, checkers, judges, policy files, evidence bundles, promises written in documentation:
if it emits a pass/fail verdict, it can be put on this bench.

A green that has never been seen red is not treated as green.

> `instrument` here is metrological: a device that produces a reading.
> It is **not** the legal sense of "instrument" (a document / treaty).
>
> This bench is the engineering form of **Assayance** (试真法, TH-META-014), a five-test doctrine
> for assurance that can fail. Theory: https://github.com/zhaoxinghua09-cell/assayance
>
> AITB — an assurance bench, **run by an agent**, **refuted by humans**.

---

## What it does

One command runs every verifiable item on a line of work, writes an evidence bundle, and exits
non-zero when anything is absent.

```
aitb list                # available presets
aitb demo                # 3 checks, zero local paths, zero network: see a green
aitb selftest            # the bench must be able to go red — this proves it (exit 1)
aitb demo --strict       # SKIP / BLOCKED also count as not-passed (T2: absence reaches the exit code)
```

Every run lands in `runs/<timestamp>_<preset>/` containing:

| file | what it is |
|---|---|
| `run.json` | environment, counts, strictness |
| `verdicts.json` | one verdict per check, each with its reason |
| `report.md` | human-readable table |
| `snapshot.html` | single-page view |
| `manifest.json` | sha256 of the four above — so a run can be re-checked, not just believed |

## Four states, no fifth bucket

`PASS` / `FAIL` / `SKIP` / `BLOCKED`. A timeout is BLOCKED; a missing interpreter is SKIP.
Neither is ever folded into PASS. Add `--strict` when the bench is used as a gate.

## Where the directory goes

By default, runs are written next to the package. If that location is not writable (installed
into site-packages), it falls back to `./runs`. Override with:

```
AITB_RUNS=/path/to/runs
AITB_PRESETS=/path/to/presets
```

## Adding a check

A preset is JSON; checks live in data, not code:

```json
{"id": "vectors.diff-91", "type": "cmd", "cmd": "python diff_harness.py", "expect": "DIFF: PASS"}
```

- `expect` is a substring assertion, not fuzzy matching. No `expect` → exit code decides.
- `expect_status: "FAIL"` asserts that this check **must** fail. It is how a negative control is
  written into the record — and it makes the run red on purpose, which is exactly what `selftest`
  does. It is not an "expected failure counts as pass" mechanism; if you want a green run, do not
  put negative controls in it.
- `files` checks take `min_size`, so "the file exists" is never sufficient.
- `needs_network: true` marks online checks; `--offline` turns them into SKIP.

## What this does not do

- It does not decide whether something *should* be published. It shows whether it *can* be verified.
- It does not vouch for the subject's conclusions. A `DOCTRINE: 5/5` is a statement about the bench,
  not about what was measured.
- It does not fold skips into passes, by design.

Theory: Assayance, T1–T5 — negative control · absence must reach the exit code · the criterion is
itself under test · a description is a claim · a proxy is not an identity judgment.

License: Apache-2.0. The name AITB is not registered as a trademark; it is used as a source marker only.
