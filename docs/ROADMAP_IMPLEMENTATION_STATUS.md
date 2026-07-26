# Roadmap implementation status

Updated: 2026-07-16

| Roadmap item | Repository implementation |
| --- | --- |
| Held-out baseline | Suite 1.0.0 and committed baseline report |
| Opt-in held-out CI | `heldout-benchmarks.yml`, label or manual dispatch |
| Evolution-vs-baseline | Registered toy target, snapshot/rollback evolution, frozen candidate, JSON evidence |
| Registered targets | Manifest import plus reviewed example; live third-party mutation remains operator-authorized |
| Calibration KPI | Brier score, Brier skill, ECE, sample count in KPI snapshots/hourly reports |
| Cross-system interop | `ResearchEvidence` 1.0.0 with producer-only mutation authority |
| Second-machine metrics | Online SQLite replication, checksum manifest, explicit failover gate |
| Ruff | Blocking CI for all non-legacy rules; dynamic-binding exceptions are documented in `pyproject.toml` pending explicit-registry migration |

The repository deliberately does not claim that elapsed time occurred when it
did not. Long-duration campaign JSON must come from a real long-duration run.
Likewise, a real ObtuseAI target must be registered with its actual local path
and reviewed non-protected parameter surface before write authorization is
enabled; the checked-in manifest is disabled and contains no machine-specific
path.
