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

## Agora trust boundaries

Agora treats every provider response, citation, code block, and imported file as
inert untrusted content. Importing content cannot execute it, change this
repository, alter runtime control files, or modify promotion policy.

Mission context must be explicitly classified:

- `SECRET` is never exportable.
- `SANITIZED_INTERNAL` requires a sanitation receipt and explicit operator
  approval.
- `PUBLIC` is rejected if secret, credential, PII, private-address,
  private-path, or governance-control patterns are detected.

Consumer-browser automation is disabled. `ATTENDED` permits manual provider use
and local prompt/response files. `ASSISTED` permits local clipboard/file staging
only. Neither mode may click, submit, scrape, or extract provider content.
Future `AUTONOMOUS_ALLOWED` or `API_OPTIONAL` adapters remain blocked unless a
separately registered adapter, a current fetched-body terms decision, explicit
operator approval, and all existing Doofus budget gates independently pass.

Public evidence retrieval revalidates every redirect destination and rejects
credentials in URLs, private or reserved IP space, unsupported content types,
oversized responses, and unavailable sources. Source existence does not prove a
claim. Retrieval and assessment failures remain explicit in the mission ledger.

Candidate code is never applied to the source checkout. Execution requires two
independently authored implementations and independently authored tests, then
runs in a disposable WSL2 `bubblewrap` namespace with no network, no repository
mount, a cleared environment, a read-only root and input mount, one bounded
output mount, and CPU, memory, process, file, and wall-time limits. External
packages are blocked until an approved offline wheelhouse records exact version,
hash, and license evidence.

Agora's maximum authority is a candidate handoff. `ACT` means eligible for
submission to existing Doofus gates only. Agora cannot change promotion
thresholds, kill switches, protected paths, credential handling, rollback
policy, budget gates, or live execution permissions.
