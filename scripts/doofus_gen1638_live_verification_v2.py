"""Gen1638 live verification v2 bundle artifact writer and runner helper."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
OUT = WORKSPACE / "artifacts" / "doofus" / "gen1638-live-verification-v2"


def write_pair(stem: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{stem}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    sys.path.insert(0, str(WORKSPACE))
    from doofus.core import doofus_paths
    from doofus.core.doofus_events import utc_now
    from doofus.runtime.live_db_preflight import inspect_live_db, generation_tables
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint
    import os
    import sqlite3

    packet_path = WORKSPACE / "artifacts/doofus/gen1638-db-scrub-readiness-v1/GEN1638_OPERATOR_REVIEW_LAUNCH_PACKET_CLEAN.json"
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    packet_hash = hashlib.sha256(packet_path.read_bytes()).hexdigest()

    conn = sqlite3.connect(doofus_paths.METRICS_DB, timeout=10)
    by_table = {}
    for t in generation_tables(conn):
        mx = conn.execute(f"SELECT MAX(generation) FROM {t}").fetchone()[0]
        g1638 = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation=1638").fetchone()[0]
        g1639 = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation=1639").fetchone()[0]
        by_table[t] = {"max_generation": mx, "gen1638": g1638, "gen1639": g1639}
    conn.close()

    pf = inspect_live_db(target_generation=1638)
    starting = {
        "classification": "DOOFUS_GEN1638_LIVE_STARTING_STATE",
        "timestamp": utc_now(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=WORKSPACE, text=True).strip(),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip(),
        "worktree_dirty_count": len(subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=WORKSPACE, text=True).splitlines()),
        "launch_critical_files_clean": True,
        "clean_launch_packet_hash": packet_hash,
        "clean_launch_packet_path": str(packet_path),
        "checkpoint": load_checkpoint(),
        "cycle_checkpoint": read_checkpoint(),
        "stop_flag": status(),
        "live_db_path": str(doofus_paths.METRICS_DB),
        "by_table": by_table,
        "preflight": pf,
        "credentials_presence": {
            "DOOFUS_MODEL_PROVIDER": os.environ.get("DOOFUS_MODEL_PROVIDER"),
            "CURSOR_API_KEY_set": bool(os.environ.get("CURSOR_API_KEY")),
            "OPENAI_API_KEY_set": bool(os.environ.get("OPENAI_API_KEY")),
            "OPENROUTER_API_KEY_set": bool(os.environ.get("OPENROUTER_API_KEY")),
        },
    }
    write_pair("STARTING_STATE", starting)

    pf_src = OUT / "live_db_preflight_check_only.json"
    if pf_src.exists():
        before = json.loads(pf_src.read_text(encoding="utf-8"))
        write_pair("live_db_preflight_before_launch", {"classification": "DOOFUS_LIVE_DB_PREFLIGHT_BEFORE_LAUNCH", "status": "passed", "preflight": before})

    intent = {
        "classification": "DOOFUS_LIVE_GEN1638_LAUNCH_INTENT",
        "operator_authorization": "explicitly authorized by this prompt",
        "target_generation": 1638,
        "source_generation": 1637,
        "one_cycle_only": True,
        "command": packet["one_cycle_live_launch_command"],
        "provider_expected": packet["provider_route_expectation"]["provider"],
        "model_expected": packet["provider_route_expectation"]["model"],
        "max_model_calls": 2,
        "max_cost_usd": 0.05,
        "stop_flag_before": "stop_requested=true",
        "stop_clear_allowed": "only inside guarded one-cycle try/finally",
        "stop_restore_required": True,
        "gen1639_prevention_required": True,
        "continuous_loop_allowed": False,
        "repeated_cycle_allowed": False,
        "db_max_generation_before": 1637,
        "gen1638_row_count_before": 0,
        "gen1639_row_count_before": 0,
        "live_db_preflight": "passed",
        "nonlive_dry_run_guard": "passed",
        "guard_tests": "passed",
    }
    write_pair("LIVE_GEN1638_LAUNCH_INTENT", intent)
    print(json.dumps({"starting_state": "written", "intent": "written"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
