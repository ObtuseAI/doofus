"""Regression tests for live runtime write isolation under pytest."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from doofus.core.doofus_paths import CANONICAL_METRICS_DB, CANONICAL_ROOT, CANONICAL_STATE
from doofus.supervisor.doofus_loop_runner import run_one_cycle


def _safe_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _db_counts() -> dict[str, int]:
    conn = sqlite3.connect(CANONICAL_METRICS_DB, timeout=5.0)
    try:
        return {
            "model_call_events": int(conn.execute("SELECT COUNT(*) FROM model_call_events").fetchone()[0]),
            "codeevolve_events": int(conn.execute("SELECT COUNT(*) FROM codeevolve_events").fetchone()[0]),
            "gepa_traces": int(conn.execute("SELECT COUNT(*) FROM gepa_traces").fetchone()[0]),
        }
    finally:
        conn.close()


def test_dry_run_cycle_does_not_mutate_live_runtime(monkeypatch):
    live_checkpoint = CANONICAL_STATE / "last_checkpoint.json"
    live_map = CANONICAL_STATE / "map_elites_archive.json"
    live_best = CANONICAL_STATE / "best_ever_ledger.json"
    live_kpi = CANONICAL_STATE / "kpi_tracker.json"
    live_heartbeat = CANONICAL_ROOT / "runtime" / "heartbeats" / "latest.json"

    before = {
        "checkpoint": _safe_text(live_checkpoint),
        "map": _safe_text(live_map),
        "best": _safe_text(live_best),
        "kpi": _safe_text(live_kpi),
        "heartbeat": _safe_text(live_heartbeat),
        "db": _db_counts(),
    }

    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.check_may_proceed", lambda: (True, "ok"))
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.prepare_cycle", lambda: {"candidate_count_next": 1})
    monkeypatch.setattr(
        "doofus.supervisor.doofus_loop_runner.provider_propose_mutations",
        lambda _ctx: {"classification": "DOOFUS_MODEL_DRY_RUN", "proposals": []},
    )
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.run_arenas", lambda *a, **k: [])
    monkeypatch.setattr(
        "doofus.supervisor.doofus_loop_runner._score_one_candidate",
        lambda conn, c, generation, baseline, dry_run, traits_before: (
            dict(c, status="rejected", rejection_reason="synthetic"),
            {"promotion_status": "rejected"},
            0,
            0,
            1,
            baseline,
        ),
    )
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.after_cycle", lambda **kw: {})
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.after_compounding_cycle", lambda **kw: {})

    result = run_one_cycle(dry_run=True)
    assert result["classification"] == "DOOFUS_CYCLE_COMPLETE"

    after = {
        "checkpoint": _safe_text(live_checkpoint),
        "map": _safe_text(live_map),
        "best": _safe_text(live_best),
        "kpi": _safe_text(live_kpi),
        "heartbeat": _safe_text(live_heartbeat),
        "db": _db_counts(),
    }
    assert after == before
