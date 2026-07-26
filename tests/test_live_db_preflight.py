from __future__ import annotations

import json
from pathlib import Path

from doofus.core import doofus_paths
from doofus.runtime.live_db_preflight import inspect_live_db, scrub_live_db
from doofus.supervisor import doofus_crash_recovery as crash_recovery
from doofus.supervisor import doofus_cycle_checkpoint as cycle_checkpoint
from doofus.core.metrics_db import connect_metrics_db


def _write_checkpoint(gen: int, phase: str = "complete") -> None:
    crash_recovery.CHECKPOINT.write_text(
        json.dumps(
            {
                "generation": gen,
                "baseline_score": 0.9378,
                "run_id": "test-run",
                "phase": phase,
                "saved_at": "2026-07-04T00:00:00+00:00",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    cycle_checkpoint.CHECKPOINT.write_text(
        json.dumps(
            {
                "stage": "cycle_complete",
                "data": {"classification": "B1003_LIVE_MODEL_CYCLE_PASS", "generation": gen},
                "saved_at": "2026-07-04T00:00:01+00:00",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _seed_generation_rows() -> None:
    conn = connect_metrics_db()
    try:
        conn.execute(
            "INSERT INTO candidates (candidate_id, parent_id, generation, traits, mutation_type, arena_targets, status, created_at, score_total) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("C1637", None, 1637, "", "trait_mutation", "", "rejected", "2026-07-04T00:00:00+00:00", 0.75),
        )
        conn.execute(
            "INSERT INTO rejections (candidate_id, reason, created_at) VALUES (?,?,?)",
            ("C1637", "proof_density_gate", "2026-07-04T00:00:02+00:00"),
        )
        conn.execute(
            "INSERT INTO model_call_events (generation, classification, provider, transport, mode, proposals_applied, proposal_valid, cost_est, success, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (1637, "DOOFUS_MODEL_LIVE", "cursor", "agent_cli", "live", 8, 1, 0.0, 1, "2026-07-04T00:00:03+00:00"),
        )
        conn.execute(
            "INSERT INTO map_elites_cells (cell_key, measure_safety, measure_mutation, measure_arena, fitness, candidate_id, generation, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            ("cell-1638", 0.99, "trait_mutation", 0.5, 0.81, "C1637", 1638, "2026-07-04T00:00:04+00:00"),
        )
        conn.commit()
    finally:
        conn.close()


def test_live_db_preflight_detects_target_and_above_contamination():
    _write_checkpoint(1636)
    _seed_generation_rows()

    report = inspect_live_db(target_generation=1637)

    assert report["contamination_detected"] is True
    assert "target_generation_already_present" in report["blockers"]
    assert "rows_present_above_target_generation" in report["blockers"]
    assert report["table_counts"]["candidates"]["target_generation_count"] == 1
    assert report["table_counts"]["map_elites_cells"]["above_target_generation_count"] == 1
    assert report["db_max_generation"] == 1638


def test_live_db_preflight_refuses_scrub_when_checkpoint_is_ambiguous(tmp_path):
    _write_checkpoint(1636, phase="started")
    _seed_generation_rows()

    report = scrub_live_db(
        mode="scrub_target_generation",
        confirm=True,
        output_dir=tmp_path / "reports",
        target_generation=1637,
    )

    assert report["classification"] == "DOOFUS_LIVE_DB_PREFLIGHT_REFUSED"
    assert report["reason"] == "checkpoint_state_ambiguous"


def test_live_db_preflight_scrubs_target_generation_and_linked_rows(tmp_path):
    _write_checkpoint(1636)
    _seed_generation_rows()

    report = scrub_live_db(
        mode="scrub_target_generation",
        confirm=True,
        output_dir=tmp_path / "reports",
        target_generation=1637,
    )

    assert report["classification"] == "DOOFUS_LIVE_DB_PREFLIGHT_SCRUBBED"
    assert Path(report["backup_path"]).exists()
    assert report["deletions"]["candidates"] == 1
    assert report["deletions"]["model_call_events"] == 1
    assert report["deletions"]["map_elites_cells"] == 1
    assert report["deletions"]["rejections"] == 1
    assert report["after"]["table_counts"]["candidates"]["target_generation_count"] == 0
    assert report["after"]["table_counts"]["map_elites_cells"]["above_target_generation_count"] == 0
