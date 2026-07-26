"""Non-live inline rescue rehearsal with isolated runtime."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from doofus.proof.high_score_rescue_loop import run_inline_rescue
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


def _seed_db(db: Path) -> None:
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE candidates (
            candidate_id TEXT PRIMARY KEY, parent_id TEXT, generation INTEGER, status TEXT,
            score_total REAL, rejection_reason TEXT, promotion_status TEXT, traits TEXT, mutation_type TEXT
        );
        CREATE TABLE promotions (candidate_id TEXT PRIMARY KEY);
        CREATE TABLE scores (candidate_id TEXT, metric TEXT, value REAL);
        CREATE TABLE arena_results (candidate_id TEXT, metric TEXT, value REAL);
        """
    )
    for i in range(30):
        conn.execute(
            "INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?,?)",
            (f"c{i}", "p", 1638, "rejected", 0.8 + i * 0.001, "proof_density_gate", "none", "{}", "mut"),
        )
    conn.commit()
    conn.close()


def run_rehearsal(*, output_dir: Path, simulate_slow: bool = False) -> dict:
    canonical_ck = load_checkpoint()
    canonical_stop = status().get("stop_requested")
    tmp = Path(tempfile.mkdtemp(prefix="doofus-inline-rescue-"))
    state = tmp / "state"
    state.mkdir()
    db = tmp / "metrics.sqlite"
    _seed_db(db)

    env = os.environ.copy()
    env["DOOFUS_STATE"] = str(state)
    env["DOOFUS_METRICS_DB"] = str(db)
    env["DOOFUS_FORCE_MODEL_DRY_RUN"] = "1"
    if simulate_slow:
        env["DOOFUS_MINER_REHEARSAL_SLOW_MS"] = "5000"

    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(WORKSPACE / "scripts" / "doofus_gen1640_inline_rescue_rehearsal_worker.py")],
        cwd=WORKSPACE,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    elapsed = time.monotonic() - started
    worker = json.loads(proc.stdout.strip() or "{}")
    shutil.rmtree(tmp, ignore_errors=True)

    passed = (
        worker.get("classification") in {"INLINE_RESCUE_OK", "INLINE_RESCUE_TIMEOUT"}
        and worker.get("elapsed_seconds", 999) < 30
        and load_checkpoint() == canonical_ck
        and status().get("stop_requested") == canonical_stop
    )
    payload = {
        "classification": "INLINE_RESCUE_REHEARSAL_PASS" if passed else "INLINE_RESCUE_REHEARSAL_PARTIAL",
        "passed": passed,
        "simulate_slow": simulate_slow,
        "worker": worker,
        "elapsed_seconds": round(elapsed, 2),
        "canonical_checkpoint_unchanged": load_checkpoint() == canonical_ck,
        "canonical_stop_unchanged": status().get("stop_requested") == canonical_stop,
        "live_provider_invoked": False,
        "worker_exit_code": proc.returncode,
    }
    write_pair(output_dir, "INLINE_RESCUE_REHEARSAL_RESULT", payload)
    return payload


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--simulate-slow", action="store_true")
    args = parser.parse_args()
    payload = run_rehearsal(output_dir=Path(args.output_dir), simulate_slow=args.simulate_slow)
    print(json.dumps({"classification": payload["classification"], "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
