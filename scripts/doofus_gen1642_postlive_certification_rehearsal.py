"""Non-live post-gen1642 certification rehearsal from gen1642 complete baseline."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from doofus.reports.run_window_telemetry_filter import filter_events_by_run_window, read_jsonl
from doofus.runtime.live_db_preflight import inspect_live_db
from doofus.safety.on_off_switch import status
from doofus.supervisor.controlled_cycle import ControlledCycleMode
from doofus.supervisor.doofus_crash_recovery import load_checkpoint
from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint
from doofus.supervisor.live_cycle_launch_guard import verify_nonlive_dry_run_guard


def write_pair(output_dir: Path, stem: str, payload: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{stem}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [f"# {stem}", "", f"**Classification:** `{payload.get('classification')}`", ""]
    for key, value in payload.items():
        if key == "classification":
            continue
        lines.append(f"- **{key}:** `{value}`")
    (output_dir / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_rehearsal(*, output_dir: Path) -> dict:
    canonical_ck = load_checkpoint()
    canonical_cc = read_checkpoint()
    canonical_stop = status()
    canonical_pf = inspect_live_db(target_generation=1643)

    tmp = Path(tempfile.mkdtemp(prefix="doofus-postlive-1642-"))
    state = tmp / "state"
    state.mkdir()
    db = tmp / "metrics.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE candidates (
            candidate_id TEXT PRIMARY KEY, parent_id TEXT, generation INTEGER, status TEXT,
            score_total REAL, rejection_reason TEXT, promotion_status TEXT, traits TEXT, mutation_type TEXT
        );
        """
    )
    for i in range(5):
        conn.execute(
            "INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?,?)",
            (f"g1642_{i}", "p", 1642, "rejected", 0.8, "proof_density_gate", "none", "{}", "mut"),
        )
    conn.commit()
    conn.close()

    env = os.environ.copy()
    env["DOOFUS_STATE"] = str(state)
    env["DOOFUS_METRICS_DB"] = str(db)
    env["DOOFUS_FORCE_MODEL_DRY_RUN"] = "1"

    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(WORKSPACE / "scripts" / "doofus_gen1640_shadow_upgrade_rehearsal_worker.py")],
        cwd=WORKSPACE,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    elapsed = time.monotonic() - started
    worker = json.loads(proc.stdout.strip() or "{}")
    shutil.rmtree(tmp, ignore_errors=True)

    nonlive = verify_nonlive_dry_run_guard()
    pf_after = inspect_live_db(target_generation=1643)

    rehearsal_start = datetime.now(timezone.utc).timestamp() - elapsed - 1
    rehearsal_end = datetime.now(timezone.utc).timestamp() + 1
    stale_init = read_jsonl(WORKSPACE / "runtime" / "state" / "cycle_init_events.jsonl")
    filtered = filter_events_by_run_window(
        stale_init,
        generation=1642,
        window_start=datetime.fromtimestamp(rehearsal_start, tz=timezone.utc),
        window_end=datetime.fromtimestamp(rehearsal_end, tz=timezone.utc),
        source_name="cycle_init_events.jsonl",
    )

    passed = all(
        [
            worker.get("inline_rescue_classification") == "INLINE_RESCUE_OK",
            worker.get("shadow_upgrade_deferred_or_bounded") is True,
            nonlive.get("classification") == "DOOFUS_MODEL_DRY_RUN",
            load_checkpoint() == canonical_ck,
            read_checkpoint() == canonical_cc,
            status().get("stop_requested") == canonical_stop.get("stop_requested"),
            pf_after.get("target_generation_total") == 0,
            pf_after.get("db_max_generation") == 1642,
        ]
    )

    payload = {
        "classification": "DOOFUS_POSTLIVE_NONLIVE_CERTIFICATION_REHEARSAL_PASS"
        if passed
        else "DOOFUS_POSTLIVE_NONLIVE_CERTIFICATION_REHEARSAL_PARTIAL",
        "passed": passed,
        "mode": ControlledCycleMode.POSTLIVE_CERTIFICATION.value,
        "worker": worker,
        "nonlive_guard": nonlive.get("classification"),
        "elapsed_seconds": round(elapsed, 2),
        "canonical_checkpoint_unchanged": load_checkpoint() == canonical_ck,
        "canonical_cycle_checkpoint_unchanged": read_checkpoint() == canonical_cc,
        "canonical_stop_unchanged": status().get("stop_requested") == canonical_stop.get("stop_requested"),
        "gen1643_rows_after": pf_after.get("target_generation_total"),
        "db_max_generation_after": pf_after.get("db_max_generation"),
        "run_window_stale_excluded_count": filtered.events_excluded_count,
        "live_provider_invoked": False,
    }
    write_pair(output_dir, "POSTLIVE_NONLIVE_CERTIFICATION_REHEARSAL", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    payload = run_rehearsal(output_dir=Path(args.output_dir))
    print(json.dumps({"classification": payload["classification"], "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
