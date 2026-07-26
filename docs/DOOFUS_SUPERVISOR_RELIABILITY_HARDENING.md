# Supervisor Reliability Hardening

Watchdog: `python -m doofus.supervisor.supervisor_watchdog --once`

Default thresholds: stale warn 300s, restart 900s, check interval 60s.

Cleanup preserves live singleton PIDs.
