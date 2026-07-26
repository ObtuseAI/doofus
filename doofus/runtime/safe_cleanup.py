"""Safe cleanup — stale locks only; never kill live singleton PIDs."""
from __future__ import annotations

import json
import os

from doofus.core.doofus_paths import STATE
from doofus.runtime.process_registry import protected_pids, PROTECTED_ROLES
from doofus.supervisor.process_singleton import cleanup_stale_lock, read_singleton_pid, _pid_alive

LAST = STATE / "safe_cleanup_last.json"


def run_safe_cleanup(*, dry_run: bool = False) -> dict:
    protected = protected_pids()
    protected.add(os.getpid())
    stale_locks: list[str] = []
    for role in PROTECTED_ROLES:
        had_lock = read_singleton_pid(role) is not None
        alive_before = _pid_alive(read_singleton_pid(role) or 0) if had_lock else False
        if not cleanup_stale_lock(role):
            stale_locks.append(role)
        elif had_lock and not alive_before and not dry_run:
            stale_locks.append(f"{role}:cleared")

    result = {
        "classification": "SAFE_CLEANUP_OK",
        "killed": [],
        "kept": sorted(protected),
        "stale_locks_cleared": stale_locks,
        "protected_pids": sorted(protected),
        "dry_run": dry_run,
        "mode": "lock_only_no_process_kill",
    }
    STATE.mkdir(parents=True, exist_ok=True)
    LAST.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run_safe_cleanup(), indent=2))
