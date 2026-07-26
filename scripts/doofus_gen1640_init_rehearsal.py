"""Non-live gen1640 init rehearsal harness with simulated stall injection."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from doofus.supervisor.doofus_crash_recovery import load_checkpoint
from doofus.safety.on_off_switch import status


def write_pair(output_dir: Path, stem: str, payload: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{stem}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [f"# {stem}", "", f"**Classification:** `{payload.get('classification')}`", ""]
    for key, value in payload.items():
        if key == "classification":
            continue
        lines.append(f"- **{key}:** `{value}`")
    (output_dir / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_rehearsal(*, output_dir: Path, stall: str = "none") -> dict:
    canonical_generation = load_checkpoint().get("generation")
    canonical_stop = status().get("stop_requested")
    tmp = Path(tempfile.mkdtemp(prefix="doofus-init-rehearsal-"))
    state = tmp / "state"
    control = tmp / "control"
    state.mkdir(parents=True, exist_ok=True)
    control.mkdir(parents=True, exist_ok=True)
    db = tmp / "metrics.sqlite"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE candidates (candidate_id TEXT PRIMARY KEY, generation INTEGER, status TEXT, score_total REAL, parent_id TEXT, traits TEXT, mutation_type TEXT, promotion_status TEXT)"
    )
    conn.commit()
    conn.close()

    env = os.environ.copy()
    env["DOOFUS_STATE"] = str(state)
    env["DOOFUS_CONTROL"] = str(control)
    env["DOOFUS_METRICS_DB"] = str(db)
    env["DOOFUS_CYCLE_INIT_TIMEOUT_SECONDS"] = "2"
    env["DOOFUS_FORCE_MODEL_DRY_RUN"] = "1"
    env["DOOFUS_ALLOW_LIVE_RUNTIME_TESTS"] = "1"
    env["DOOFUS_INIT_REHEARSAL_STALL"] = stall

    proc = subprocess.run(
        [sys.executable, str(WORKSPACE / "scripts" / "doofus_gen1640_init_rehearsal_worker.py")],
        cwd=WORKSPACE,
        env=env,
        capture_output=True,
        text=True,
    )
    worker = json.loads(proc.stdout.strip() or "{}")
    shutil.rmtree(tmp, ignore_errors=True)

    payload = {
        "classification": "DOOFUS_INIT_REHEARSAL_STALL_ABORT_PASS"
        if stall != "none"
        else "DOOFUS_INIT_REHEARSAL_PASS",
        "stall_simulated": stall,
        "cycle_classification": worker.get("cycle_classification"),
        "gen1640_rows_in_temp_db": worker.get("gen1640_rows_in_temp_db"),
        "canonical_checkpoint_unchanged": load_checkpoint().get("generation") == canonical_generation,
        "canonical_stop_unchanged": status().get("stop_requested") == canonical_stop,
        "live_provider_invoked": False,
        "worker_exit_code": proc.returncode,
        "worker_stderr_tail": (proc.stderr or "")[-500:],
    }
    write_pair(output_dir, "INIT_REHEARSAL_RESULT", payload)
    if stall == "none":
        write_pair(output_dir, "NONLIVE_GEN1640_INIT_REHEARSAL_AFTER_REPAIR", payload)
    return payload


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Non-live init rehearsal harness.")
    parser.add_argument(
        "--output-dir",
        default=str(WORKSPACE / "artifacts" / "doofus" / "gen1640-init-hang-repair-v1"),
    )
    parser.add_argument("--stall", default="inline_rescue", choices=["none", "provider", "inline_rescue", "db_prepare", "mine"])
    args = parser.parse_args()
    payload = run_rehearsal(output_dir=Path(args.output_dir), stall=args.stall)
    print(json.dumps(payload, indent=2))
    ok = payload.get("canonical_checkpoint_unchanged") and payload.get("canonical_stop_unchanged")
    if args.stall == "none":
        ok = ok and payload.get("cycle_classification") != "DOOFUS_CYCLE_INIT_TIMEOUT_ABORTED"
    else:
        ok = ok and payload.get("cycle_classification") == "DOOFUS_CYCLE_INIT_TIMEOUT_ABORTED"
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
