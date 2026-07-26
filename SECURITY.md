# Security policy

## Reporting a vulnerability

Use this repository's **Security** tab and **Report a vulnerability** to open a
private GitHub security advisory. Do not open a public issue or pull request for
a suspected credential leak, path-containment bypass, budget bypass, unsafe
source mutation, rollback failure, or promotion-gate weakness.

Include the affected revision, component, preconditions, impact, and a minimal
non-destructive reproducer. Good-faith, authorized research that respects the
license, avoids privacy violations and service disruption, and gives the
maintainers reasonable remediation time is welcome.

## Supported versions

Only the current default branch and latest tagged release are supported.
Machine-local runtime state, metrics databases, private handoff bundles, and
historical experiment artifacts are not supported releases.

## High-value report areas

- bypass of kill switches, protected roots, or path containment;
- provider credentials or `DOOFUS_*` control values reaching fitness
  subprocesses, reports, or logs;
- defeat of cost, call, pressure, mutation, or write-authorization limits;
- rollback or snapshot failures that preserve a regressed candidate; and
- held-out benchmark contamination or promotion without frozen evidence.

## Release hygiene

Public releases require clean secret and private-path scans, dependency review,
provider-free tests, held-out protocol checks, read-only workflow permissions,
and exact-SHA GitHub quality proof.
