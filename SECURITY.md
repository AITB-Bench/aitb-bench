# Security Policy

## What this project is, for security purposes

AITB runs commands that a **preset** tells it to run. A preset is executable configuration: a
`cmd` check runs a shell command with your user's privileges, in the run's working directory.

That means:

- **A preset is trusted input.** Treat a preset you did not write like a shell script you did not
  read. `aitb <preset>` on an unknown preset is equivalent to running a stranger's script.
- **`a_http` makes network requests** and records them; it does not exfiltrate run data by itself.
- **The evidence bundle is local.** `runs/<timestamp>_<preset>/` is written to disk and nothing is
  uploaded anywhere. `progress.log` is hashed into `manifest.json` like the rest of the pack.

## Supported versions

Only the latest `main` is supported. This is a 0.x project; there are no long-term branches.

## Reporting a vulnerability

Do not open a public issue for a vulnerability that would let a preset gain privileges it should not
have, or that would let a run silently mislabel a result (for example: a way to make `BLOCKED` appear
as `PASS`).

Report privately through the maintainer contact listed on the organisation page
(`https://github.com/AITB-Bench`), or by using GitHub's private vulnerability reporting on this
repository if it is enabled.

Please include:

1. The preset or command sequence that reproduces it.
2. The run directory (`manifest.json` hash) if you have one.
3. What the bench reported versus what actually happened.

We will confirm receipt, state whether we reproduce it, and publish a fix with the reproduction in
the commit message. A result that is silently wrong is treated as a security issue here, not a bug —
this project's whole claim is that its readings can be re-checked.
