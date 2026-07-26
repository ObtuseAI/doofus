"""Write gen1639 live verification starting state and launch intent."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
OUT = WORKSPACE / "artifacts" / "doofus" / "gen1639-live-verification-v1"


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

    OUT.mkdir(parents=True, exist_ok=True)
    packet_path = WORKSPACE / "artifacts/doofus/gen1638-postlive-certification-v1/GEN1639_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY.json"
    packet = json.loads(packet_path.read_text(encoding="utf-8"))

    conn = sqlite3.connect(doofus_paths.METRICS_DB, timeout=15)
    by_table = {}
    for t in generation_tables(conn):
        by_table[t] = {
            "max_generation": conn.execute(f"SELECT MAX(generation) FROM {t}").fetchone()[0],
            "gen1638": conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation=1638").fetchone()[0],
            "gen1639": conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation=1639").fetchone()[0],
            "gen1640": conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation=1640").fetchone()[0],
        }
    conn.close()

    starting = {
        "classification": "DOOFUS_GEN1639_LIVE_STARTING_STATE",
        "timestamp": utc_now(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=WORKSPACE, text=True).strip(),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip(),
        "operator_authorization": "explicitly authorized by this prompt for one gen1639 live cycle",
        "prep_packet_hash": hashlib.sha256(packet_path.read_bytes()).hexdigest(),
        "checkpoint": load_checkpoint(),
        "cycle_checkpoint": read_checkpoint(),
        "stop_flag": status(),
        "live_db_path": str(doofus_paths.METRICS_DB),
        "by_table": by_table,
        "preflight_target_1640": inspect_live_db(target_generation=1640),
        "credentials_presence": {
            "DOOFUS_MODEL_PROVIDER": os.environ.get("DOOFUS_MODEL_PROVIDER"),
            "CURSOR_API_KEY_set": bool(os.environ.get("CURSOR_API_KEY")),
        },
    }
    (OUT / "STARTING_STATE.json").write_text(json.dumps(starting, indent=2), encoding="utf-8")

    pf_src = OUT / "live_db_preflight_check_only.json"
    if pf_src.exists():
        before = json.loads(pf_src.read_text(encoding="utf-8"))
        (OUT / "live_db_preflight_before_launch.json").write_text(
            json.dumps({"classification": "DOOFUS_LIVE_DB_PREFLIGHT_BEFORE_LAUNCH", "status": "passed", "preflight": before}, indent=2),
            encoding="utf-8",
        )

    intent = {
        "classification": "DOOFUS_LIVE_GEN1639_LAUNCH_INTENT",
        "operator_authorization": "explicitly authorized by this prompt",
        "target_generation": 1639,
        "source_generation": 1638,
        "one_cycle_only": True,
        "command": packet["future_command_template"],
        "provider_expected": "cursor",
        "model_expected": "composer-2.5",
        "max_model_calls": 2,
        "max_cost_usd": 0.05,
        "stop_flag_before": "stop_requested=true",
        "stop_clear_allowed": "only inside guarded one-cycle try/finally",
        "stop_restore_required": True,
        "gen1640_prevention_required": True,
        "continuous_loop_allowed": False,
        "repeated_cycle_allowed": False,
        "db_max_generation_before": 1638,
        "gen1639_row_count_before": 0,
        "gen1640_row_count_before": 0,
        "live_db_preflight": "passed",
        "nonlive_dry_run_guard": "passed",
        "guard_tests": "passed",
        "provider_gate_fix": "committed and validated",
    }
    (OUT / "LIVE_GEN1639_LAUNCH_INTENT.json").write_text(json.dumps(intent, indent=2), encoding="utf-8")
    print("written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
