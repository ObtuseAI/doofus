"""Post-session cleanup — remove orphan/duplicate Doofus processes."""
from __future__ import annotations

import json
import os
import subprocess
import sys

from doofus.core.doofus_paths import STATE
from doofus.runtime.process_classifier import _fetch_processes
from doofus.runtime.process_registry import PROTECTED_ROLES, protected_pids
from doofus.runtime.safe_cleanup import run_safe_cleanup
from doofus.supervisor.process_singleton import read_singleton_pid, _pid_alive

LAST = STATE / "session_cleanup_last.json"
SCHEDULER_PID_FILE = STATE / "autopilot_scheduler.pid"


def _kill_pid(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        if sys.platform == "win32":
            proc = subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True,
                timeout=5,
            )
            return proc.returncode == 0
        os.kill(pid, 9)
        return True
    except Exception:
        return False


def cleanup_after_autopilot_session(*, session_pid: int | None = None, dry_run: bool = False) -> dict:
    """Kill stale autopilot sessions, duplicates, and orphan Doofus python processes."""
    session_pid = session_pid or os.getpid()
    keep = protected_pids()
    keep.add(session_pid)

    if SCHEDULER_PID_FILE.exists():
        try:
            sched_pid = int(SCHEDULER_PID_FILE.read_text(encoding="utf-8").strip())
            if _pid_alive(sched_pid):
                keep.add(sched_pid)
        except ValueError:
            pass

    canonical: dict[str, int] = {}
    for role in PROTECTED_ROLES:
        pid = read_singleton_pid(role)
        if pid and _pid_alive(pid):
            canonical[role] = pid
            keep.add(pid)

    killed: list[dict] = []
    skipped: list[dict] = []

    processes = _fetch_processes()
    scan_skipped = len(processes) == 0
    if os.environ.get("DOOFUS_SKIP_PROCESS_SCAN", "").lower() in ("1", "true", "yes"):
        processes = []
        scan_skipped = True

    for info in processes:
        pid = info.pid
        if pid in keep:
            skipped.append({"pid": pid, "role": info.role, "reason": "protected"})
            continue

        should_kill = False
        reason = ""

        if info.role == "autopilot_session":
            should_kill = pid != session_pid
            reason = "stale_autopilot_session"
        elif info.role == "orphan":
            should_kill = True
            reason = "orphan"
        elif info.role == "watchdog":
            should_kill = True
            reason = "watchdog_leftover"
        elif info.role == "tool":
            should_kill = True
            reason = "tool_leftover"
        elif info.role == "supervisor":
            canonical_pid = canonical.get("doofus_supervisor")
            should_kill = canonical_pid is not None and pid != canonical_pid
            reason = "duplicate_supervisor"
        elif info.role == "dashboard":
            canonical_pid = canonical.get("doofus_dashboard")
            should_kill = canonical_pid is not None and pid != canonical_pid
            reason = "duplicate_dashboard"
        elif info.role == "runtime_manager":
            canonical_pid = canonical.get("doofus_runtime_manager")
            should_kill = canonical_pid is not None and pid != canonical_pid
            reason = "duplicate_runtime_manager"

        if should_kill:
            ok = False if dry_run else _kill_pid(pid)
            killed.append({"pid": pid, "role": info.role, "reason": reason, "killed": ok})
        else:
            skipped.append({"pid": pid, "role": info.role, "reason": "allowed"})

    lock_cleanup = run_safe_cleanup(dry_run=dry_run)
    result = {
        "classification": "SESSION_CLEANUP_OK",
        "killed": killed,
        "skipped": skipped,
        "process_scan_skipped": scan_skipped,
        "stale_locks_cleared": lock_cleanup.get("stale_locks_cleared", []),
        "protected_pids": sorted(keep),
        "dry_run": dry_run,
    }
    if not dry_run:
        STATE.mkdir(parents=True, exist_ok=True)
        LAST.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    print(json.dumps(cleanup_after_autopilot_session(dry_run=args.dry_run), indent=2))
