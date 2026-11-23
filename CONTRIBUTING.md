# Contributing to AITB

AITB is a bench, not a standards body. It issues no conformance verdicts and claims no trademark.
What it publishes is: a runner, a set of presets, and evidence bundles that a stranger can re-run.

Contributions are welcome in three shapes. All three are judged by the same rule: **can someone else
reproduce it without you?**

## 1. A new check (a preset entry)

A check lives in data, not code:

```json
{"id": "vectors.diff-91", "type": "cmd", "cmd": "python diff_harness.py", "expect": "DIFF: PASS"}
```

Requirements for a check PR:

- It must be runnable by a stranger: no absolute paths, no credentials, no files outside the repo.
- `expect` is a substring assertion, not a regex and not fuzzy matching.
- If the check can be satisfied by an empty file or a zero-byte artifact, set `min_size` explicitly.
- Online checks must set `needs_network: true`, so `--offline` can turn them into `SKIP`.
- Add a **negative control** (`expect_status: "FAIL"`) that proves the check can go red, or explain in
  the PR why a negative control is impossible here. A green that was never seen red is not treated
  as green.

## 2. An adapter (a new check type)

Adapters live in `aitb_bench/core.py` and must honour the four states:

- `PASS` — measured, and it matched.
- `FAIL` — measured, and it did not match.
- `SKIP` — not present (missing interpreter, missing tool, offline mode).
- `BLOCKED` — present but not measurable (timeout, present-but-broken, unknown adapter).

Two lines are load-bearing and will be reviewed hard:

- **`BLOCKED` must never be folded into `PASS`.** "Not measured" is not "measured and fine".
- **`BLOCKED` must never be rewritten into `FAIL` by the runner.** That is the same error in reverse.

## 3. A refutation of a claim

If you can kill a sentence in `README.md` with one counterexample, that is a valid contribution —
open an issue with the quoted sentence, the counterexample, and where you ran it. Claims that survive
a counterexample get edited; doctrine does not get defended.

## Ground rules

- **No path that only works on your machine.** `D:\`, `/Users/you/`, `${HOME}` — none of these belong
  in a preset or a doc.
- **No unverifiable superlatives.** "First", "stronger", "best" need a source or they get removed.
- **Evidence over assertion.** If your PR says "verified", include the run directory's `manifest.json`
  hash in the description.
- **Small, single-purpose PRs.** One check or one adapter per PR, where practical.

## Review

`main` is protected: PRs require the CI matrix (Ubuntu + Windows × Python 3.11 / 3.12) to be green,
plus one review. Direct pushes are reserved for release bookkeeping.

If a PR is rejected, the reason is written into the PR. Rejections are about reproducibility, not
about who you are.

## Licence

Contributions are accepted under Apache-2.0. By opening a PR you agree to license your contribution
under the same terms.
