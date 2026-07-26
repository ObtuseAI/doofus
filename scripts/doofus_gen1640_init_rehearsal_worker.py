"""Isolated subprocess worker for gen1640 init rehearsal."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from doofus.supervisor.doofus_crash_recovery import save_checkpoint
from doofus.supervisor.doofus_cycle_checkpoint import write_checkpoint as write_cycle_ck
from doofus.safety.on_off_switch import stop


def _bootstrap_db(db: Path) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS candidates (candidate_id TEXT PRIMARY KEY, generation INTEGER, status TEXT, score_total REAL, parent_id TEXT, traits TEXT, mutation_type TEXT, promotion_status TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cycles (run_id TEXT, generation INTEGER, created_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS promotions (candidate_id TEXT PRIMARY KEY)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS scores (candidate_id TEXT, metric TEXT, value REAL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS arena_results (candidate_id TEXT, passed INTEGER, result TEXT)"
    )
    conn.commit()
    conn.close()


def main() -> int:
    stall = os.environ.get("DOOFUS_INIT_REHEARSAL_STALL", "none")
    db = Path(os.environ["DOOFUS_METRICS_DB"])
    _bootstrap_db(db)
    save_checkpoint({"generation": 1639, "baseline_score": 0.9, "run_id": "rehearsal", "phase": "complete"})
    write_cycle_ck("cycle_complete", {"classification": "B1003_LIVE_MODEL_CYCLE_PASS", "generation": 1639})

    control = Path(os.environ.get("DOOFUS_CONTROL", ""))
    if control:
        control.mkdir(parents=True, exist_ok=True)
        (control / "DOOFUS_RUN.enabled").write_text("1", encoding="utf-8")
        stop_file = control / "DOOFUS_STOP.request"
        if stop_file.exists():
            stop_file.unlink()

    from doofus.supervisor import doofus_loop_runner as runner

    if stall == "provider":
        runner.resolve_provider = lambda: time.sleep(3) or {"provider_selected": "dry_run"}  # type: ignore[method-assign]
    elif stall == "inline_rescue":
        runner.run_inline_rescue = lambda **_k: time.sleep(3) or {"classification": "INLINE_RESCUE_OK"}  # type: ignore[method-assign]
    elif stall == "db_prepare":
        runner.prepare_cycle = lambda: time.sleep(3) or {"candidate_count": 1}  # type: ignore[method-assign]
    elif stall == "mine":
        from doofus.proof import proof_candidate_selector as pcs

        pcs.mine_high_score_rejections = lambda **_k: time.sleep(3) or {"top_100": [], "count_score_gte_threshold": 0}  # type: ignore[method-assign]
    elif stall == "none":
        runner.bootstrap_autonomous_runtime = lambda: None  # type: ignore[method-assign]
        runner._ensure_db = lambda: None  # type: ignore[method-assign]
        runner.proof_builder_mode = lambda: False  # type: ignore[method-assign]
        runner.resolve_provider = lambda: {"provider_selected": "dry_run", "model_name": "dry_run"}  # type: ignore[method-assign]
        runner.prepare_cycle = lambda: {"candidate_count": 0}  # type: ignore[method-assign]
        runner.generate_cycle_candidates = lambda *_a, **_k: []  # type: ignore[method-assign]
        runner.filter_retired_parents = lambda xs: xs  # type: ignore[method-assign]

        def fake_connect():
            conn = sqlite3.connect(db, timeout=5.0)
            conn.execute("CREATE TABLE IF NOT EXISTS cycles (run_id TEXT, generation INTEGER, created_at TEXT)")
            return conn

        runner.connect_metrics_db = fake_connect  # type: ignore[method-assign]
        runner.after_cycle = lambda **_k: {}  # type: ignore[method-assign]
        runner.after_compounding_cycle = lambda **_k: {}  # type: ignore[method-assign]
        runner.build_live_cycle_report = lambda doc: {"cycle": doc}  # type: ignore[method-assign]
        runner.may_call_model = lambda **_k: {"allowed": False}  # type: ignore[method-assign]
        runner._provider_propose_mutations_for_cycle = lambda *_a, **_k: ({"classification": "DOOFUS_MODEL_DRY_RUN", "proposals": []}, [])  # type: ignore[method-assign]

    result = runner.run_one_cycle(dry_run=(stall == "none"), live_model_if_available=False)
    conn = sqlite3.connect(db)
    gen1640_rows = conn.execute("SELECT COUNT(*) FROM candidates WHERE generation=1640").fetchone()[0]
    conn.close()
    print(
        json.dumps(
            {
                "cycle_classification": result.get("classification"),
                "gen1640_rows_in_temp_db": gen1640_rows,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
