"""Non-live shadow upgrade rehearsal with simulated slow items."""
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


def _seed_shadow_archive(state: Path) -> None:
    archive = state / "shadow_elite_archive.json"
    entries = [
        {"candidate_id": f"SHADOW_{i}", "score": 0.9 - i * 0.01, "generation": 1638, "upgraded": False}
        for i in range(5)
    ]
    archive.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def run_rehearsal(*, output_dir: Path, simulate_slow: bool = False, low_budget: bool = False) -> dict:
    canonical_ck = load_checkpoint()
    canonical_stop = status().get("stop_requested")
    tmp = Path(tempfile.mkdtemp(prefix="doofus-shadow-upgrade-"))
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
        CREATE TABLE scores (candidate_id TEXT, metric TEXT, value REAL);
        CREATE TABLE arena_results (candidate_id TEXT, arena TEXT, result TEXT);
        CREATE TABLE rejections (candidate_id TEXT, reason TEXT, created_at TEXT);
        """
    )
    conn.commit()
    conn.close()
    _seed_shadow_archive(state)

    env = os.environ.copy()
    env["DOOFUS_STATE"] = str(state)
    env["DOOFUS_METRICS_DB"] = str(db)
    env["DOOFUS_FORCE_MODEL_DRY_RUN"] = "1"
    if simulate_slow:
        env["DOOFUS_SHADOW_UPGRADE_REHEARSAL_SLOW"] = "1"
    if low_budget:
        env["DOOFUS_INLINE_RESCUE_SHADOW_UPGRADE_MAX_SECONDS"] = "0.5"
        env["DOOFUS_SHADOW_UPGRADE_MIN_BUDGET_SECONDS"] = "0.1"

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

    passed = (
        worker.get("inline_rescue_classification") == "INLINE_RESCUE_OK"
        and worker.get("shadow_upgrade_deferred_or_bounded") is True
        and worker.get("elapsed_seconds", 999) < 30
        and load_checkpoint() == canonical_ck
        and status().get("stop_requested") == canonical_stop
    )
    payload = {
        "classification": "SHADOW_UPGRADE_REHEARSAL_PASS" if passed else "SHADOW_UPGRADE_REHEARSAL_PARTIAL",
        "passed": passed,
        "simulate_slow": simulate_slow,
        "low_budget": low_budget,
        "worker": worker,
        "elapsed_seconds": round(elapsed, 2),
        "canonical_checkpoint_unchanged": load_checkpoint() == canonical_ck,
        "canonical_stop_unchanged": status().get("stop_requested") == canonical_stop,
        "live_provider_invoked": False,
        "worker_exit_code": proc.returncode,
    }
    write_pair(output_dir, "SHADOW_UPGRADE_REHEARSAL_RESULT", payload)
    return payload


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--simulate-slow", action="store_true")
    parser.add_argument("--low-budget", action="store_true")
    args = parser.parse_args()
    payload = run_rehearsal(
        output_dir=Path(args.output_dir),
        simulate_slow=args.simulate_slow,
        low_budget=args.low_budget,
    )
    print(json.dumps({"classification": payload["classification"], "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
