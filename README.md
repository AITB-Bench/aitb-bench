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
| `progress.log` | every console line, flushed to disk as it happens — `tail -f` a long run instead of guessing whether it hung. Hashed into the manifest like the rest. |

## Install

Not on PyPI yet — install from the repository:

```
git clone https://github.com/AITB-Bench/aitb-bench
cd aitb-bench
pip install -e .
aitb demo
```

Or without cloning:

```
pip install "git+https://github.com/AITB-Bench/aitb-bench.git"
```

Python 3.9+. No dependencies. `aitb demo` needs no network and no local paths.

## Four states, no fifth bucket

`PASS` / `FAIL` / `SKIP` / `BLOCKED`. A timeout is BLOCKED; a missing interpreter is SKIP; an
interpreter that is present but cannot execute is BLOCKED (not measured ≠ measured failing).
Neither is ever folded into PASS. Add `--strict` when the bench is used as a gate.

## Where the directory goes

By default, runs are written next to the package. If that location is not writable (installed
into site-packages), it falls back to `./runs`. Override with:

```
AITB_RUNS=/path/to/runs
AITB_PRESETS=/path/to/presets
```

`AITB_PRESETS` **adds** a search directory; it does not replace the built-in presets, so `aitb demo`
still resolves after you set it. Preset names are resolved in this order: `$AITB_PRESETS`, the
package's own `presets/`, then `./presets`. First match wins.

## Adding a check

A preset is JSON; checks live in data, not code:

```json
{"id": "vectors.diff-91", "type": "cmd", "cmd": "python diff_harness.py", "expect": "DIFF: PASS"}
```

- `expect` is a substring assertion, not fuzzy matching. No `expect` → exit code decides.
- `expect_status: "FAIL"` asserts that this check **must** fail. It is how a negative control is
  written into the record — and it makes the run red on purpose, which is exactly what `selftest`
  does. It is not an "expected failure counts as pass" mechanism; if you want a green run, do not
  put negative controls in it. Such checks are labelled `[NEG-CTRL]` in the console and `负控` in
  `report.md` / `snapshot.html`, so a reviewer can tell "designed to be red" from "broke".
- `files` checks default to `min_size: 1`, so a zero-byte file never passes; write `min_size: 0`
  when an empty file is the point (`.gitkeep`), and a larger number when the file must carry content.
- `needs_network: true` marks online checks; `--offline` turns them into SKIP.
- Values may use `${VAR}` from the environment (`${AITB_RUNS}` etc.); expansion happens at preset
  load. Variables resolve from `config.local.json` first, then the environment; a name that resolves
  nowhere keeps its `${NAME}` placeholder and prints a warning once — it is never silently blanked.
- A preset may set `"max_seconds"` (default 900). Past that wall clock, the remaining checks are
  recorded `BLOCKED` ("not executed"), never `PASS` — a bench that hangs must not look green.
- `demo` and `selftest` are two presets running through the same code path — `selftest` is not a
  privileged self-test hook. That is deliberate: the negative controls have to survive the same
  runner that a stranger's preset goes through.

## What this does not do

- It does not decide whether something *should* be published. It shows whether it *can* be verified.
- It does not vouch for the subject's conclusions. A `DOCTRINE: 5/5` is a statement about the bench,
  not about what was measured.
- It does not fold skips into passes, by design.

Theory: Assayance, T1–T5 — negative control · absence must reach the exit code · the criterion is
itself under test · a description is a claim · a proxy is not an identity judgment.

License: Apache-2.0. The name AITB is not registered as a trademark; it is used as a source marker only.
