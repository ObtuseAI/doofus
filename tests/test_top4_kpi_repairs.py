"""Focused tests for top-4 KPI repair work."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from doofus.core import doofus_paths
from doofus.core import doofus_state
from doofus.evolution import best_ever_ledger as bel
from doofus.evolution import map_elites_archive as mea
from doofus.meta import recursive_supervisor as rs
from doofus.reports import sota_kpi_tracker as kpi
from doofus.supervisor import doofus_crash_recovery as dcr
from doofus.model_router.model_call_ledger import record_model_event


@pytest.fixture
def isolated_runtime(tmp_path, monkeypatch):
    state = tmp_path / "state"
    shared = tmp_path / "shared"
    state.mkdir(exist_ok=True)
    shared.mkdir(exist_ok=True)
    db = state / "metrics.sqlite"

    monkeypatch.setattr(doofus_paths, "STATE", state)
    monkeypatch.setattr(doofus_paths, "SHARED", shared)
    monkeypatch.setattr(doofus_paths, "METRICS_DB", db)
    monkeypatch.setattr(doofus_state, "STATE", state)
    monkeypatch.setattr(doofus_state, "METRICS_DB", db)
    monkeypatch.setattr(dcr, "CHECKPOINT", state / "last_checkpoint.json")
    monkeypatch.setattr(bel, "LEDGER", state / "best_ever_ledger.json")
    monkeypatch.setattr(mea, "ARCHIVE_JSON", state / "map_elites_archive.json")
    monkeypatch.setattr(rs, "META_STATE_FILE", state / "meta_evolution_state.json")
    monkeypatch.setattr(kpi, "STATE", state)
    monkeypatch.setattr(kpi, "SHARED", shared)
    monkeypatch.setattr(kpi, "METRICS_DB", db)
    monkeypatch.setattr(kpi, "KPI_STATE", state / "kpi_tracker.json")
    monkeypatch.setattr(kpi, "KPI_HISTORY", state / "kpi_history.jsonl")
    monkeypatch.setattr(kpi, "HOURLY_LAST", state / "hourly_kpi_last.json")
    monkeypatch.setattr(kpi, "HOURLY_REPORT_DIR", shared / "hourly-kpi-reports")
    monkeypatch.setattr(kpi, "HOURLY_LATEST_MD", shared / "DOOFUS-HOURLY-KPI-LATEST.md")
    monkeypatch.setattr(kpi, "HOURLY_LATEST_JSON", shared / "DOOFUS-HOURLY-KPI-LATEST.json")

    (state / "last_checkpoint.json").write_text(
        json.dumps(
            {
                "generation": 1634,
                "baseline_score": 0.9378,
                "run_id": "test-run",
                "phase": "complete",
                "saved_at": "2026-07-03T10:33:51+00:00",
            }
        ),
        encoding="utf-8",
    )
    (state / "challenger_tournaments.json").write_text(
        json.dumps({"tournament_count": 1394, "last_winner": "DOOFUS_1634_bc6e22b925", "history": []}),
        encoding="utf-8",
    )
    (state / "best_ever_ledger.json").write_text(
        json.dumps(
            {
                "best_score": 0.9392,
                "best_candidate_id": "DOOFUS_1631_b40ceb1915",
                "best_generation": 1631,
                "history": [{"candidate_id": "DOOFUS_1631_b40ceb1915", "score": 0.9392, "generation": 1631}],
            }
        ),
        encoding="utf-8",
    )
    (state / "map_elites_archive.json").write_text(json.dumps([]), encoding="utf-8")
    (state / "meta_evolution_state.json").write_text(
        json.dumps({"cycle_count": 0, "last_gepa_cycle": 0, "last_map_cycle": 0, "last_codeevolve_cycle": 0}),
        encoding="utf-8",
    )
    doofus_state.init_db(db)
    return {"state": state, "shared": shared, "db": db}


def _db_count(db: Path, table: str) -> int:
    conn = sqlite3.connect(db)
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()


def test_model_cycle_events_cover_live_skip_fallback_and_dry_run(isolated_runtime, monkeypatch):
    db = isolated_runtime["db"]
    monkeypatch.setenv("DOOFUS_MODEL_PROVIDER", "cursor")
    monkeypatch.setenv("DOOFUS_PREFER_CURSOR", "1")
    monkeypatch.setenv("DOOFUS_CURSOR_HYBRID_FALLBACK", "1")
    monkeypatch.setenv("DOOFUS_CURSOR_MUTATION_BATCH", "4")
    monkeypatch.setenv("DOOFUS_MODEL_GUIDED_WEIGHT", "2.5")
    monkeypatch.setattr(
        "doofus.model_router.cursor_agent_cli.probe_agent_auth",
        lambda: {"logged_in": True},
    )

    base_args = {
        "run_id": "test-run",
        "route": {"provider_selected": "cursor", "model_name": "composer-2.5"},
        "gate": {"allowed": True, "reason": "", "mode": "live"},
        "model_context": {"candidate_count": 4},
        "cfg": object(),
        "candidates": [{"candidate_id": "C1", "algorithm_id": "model_guided"}],
        "scored": [],
    }

    kpi.record_cycle_model_event(
        1635,
        {
            "classification": "DOOFUS_MODEL_LIVE",
            "mode": "live",
            "provider": "cursor",
            "transport": "agent_cli",
            "cursor_model": "composer-2.5",
            "attempted": True,
            "proposal_validation": {"valid": True},
            "proposals_returned": 2,
            "proposals_applied_count": 1,
            "duration_ms": 25.0,
            "cost_est": 0.01,
        },
        **base_args,
    )
    kpi.record_cycle_model_event(
        1636,
        {
            "classification": "DOOFUS_MODEL_GATE_BLOCKED",
            "mode": "dry_run",
            "provider": "cursor",
            "transport": "agent_cli",
            "attempted": False,
            "reason": "no_credentials",
            "skip_reason": "no_credentials",
            "proposal_validation": {"valid": False},
        },
        **{**base_args, "gate": {"allowed": False, "reason": "no_credentials", "mode": "dry_run"}},
    )
    kpi.record_cycle_model_event(
        1637,
        {
            "classification": "DOOFUS_MODEL_LIVE",
            "mode": "live",
            "provider": "openrouter",
            "transport": "openrouter",
            "attempted": True,
            "cursor_fallback_from": "DOOFUS_CURSOR_ERROR",
            "proposal_validation": {"valid": True},
            "proposals_returned": 1,
            "proposals_applied_count": 1,
        },
        **base_args,
    )
    kpi.record_cycle_model_event(
        1638,
        {
            "classification": "DOOFUS_MODEL_DRY_RUN",
            "mode": "dry_run",
            "provider": "cursor",
            "transport": "dry_run",
            "attempted": True,
            "skip_reason": "no_model_guided_candidates",
            "proposal_validation": {"valid": False},
        },
        **base_args,
    )

    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            """
            SELECT generation, attempted, skipped, live, dry_run, success, fallback_used, fallback_reason
            FROM model_call_events
            ORDER BY generation
            """
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 4
    assert rows[0][1:7] == (1, 0, 1, 0, 1, 0)
    assert rows[1][1:7] == (0, 1, 0, 1, 0, 0)
    assert rows[2][6] == 1
    assert rows[2][7] == "DOOFUS_CURSOR_ERROR"
    assert rows[3][3] == 0 and rows[3][4] == 1


def test_record_model_event_marks_live_success_with_usable_proposals(isolated_runtime):
    db = isolated_runtime["db"]
    record_model_event(
        generation=2000,
        model_result={
            "classification": "DOOFUS_MODEL_LIVE",
            "provider": "cursor",
            "transport": "agent_cli",
            "mode": "live",
        },
        provider_requested="cursor",
        provider_resolved="cursor",
        model_requested="composer-2.5",
        model_resolved="composer-2.5",
        attempted=True,
        live=True,
        proposals_requested=1,
        proposals_returned=1,
        proposals_applied=0,
        proposal_valid=True,
    )
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT success, proposals_returned, proposals_applied FROM model_call_events WHERE generation=2000"
        ).fetchone()
    finally:
        conn.close()
    assert row == (1, 1, 0)


def test_model_event_insert_failure_logs_db_health(monkeypatch):
    logged: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "doofus.model_router.model_call_ledger.record_model_event",
        lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        "doofus.model_router.model_call_ledger.log_sqlite_health",
        lambda **kw: logged.append((kw["event_type"], kw.get("detail", ""))),
    )
    monkeypatch.setattr(
        "doofus.model_router.cursor_agent_cli.probe_agent_auth",
        lambda: {"logged_in": False},
    )
    kpi.record_cycle_model_event(
        1700,
        {"classification": "DOOFUS_MODEL_GATE_BLOCKED", "mode": "dry_run", "provider": "cursor"},
        run_id="test-run",
        route={"provider_selected": "cursor", "model_name": "composer-2.5"},
        gate={"allowed": False, "reason": "no_credentials", "mode": "dry_run"},
        model_context={"candidate_count": 1},
        cfg=object(),
        candidates=[],
        scored=[],
    )
    assert logged and logged[0][0] == "model_event_insert_failed"


def test_codeevolve_events_cover_run_block_and_not_due(isolated_runtime, monkeypatch):
    db = isolated_runtime["db"]
    monkeypatch.setattr(rs, "bootstrap_autonomous_runtime", lambda: None)
    monkeypatch.setattr(rs, "apply_evo_defaults", lambda: {})
    monkeypatch.setattr(rs, "apply_meta_defaults", lambda: {})
    monkeypatch.setattr(
        rs,
        "run_one_cycle",
        lambda **kw: {"classification": "DOOFUS_CYCLE_COMPLETE", "generation": 10, "promoted": 0},
    )
    monkeypatch.setattr(rs, "run_gepa_batch", lambda: {"classification": "GEPA_BATCH_COMPLETE"})
    monkeypatch.setattr(rs, "maintain_map_elites", lambda: {"classification": "MAP_ELITES_MAINTAIN_OK"})
    monkeypatch.setattr(rs, "aevolve_escalate", lambda *_: {"classification": "AEVOLVE_OK"})
    monkeypatch.setattr(rs, "check_may_proceed", lambda: (True, ""))
    monkeypatch.setenv("DOOFUS_META_EVOLUTION_MODE", "1")
    monkeypatch.setenv("DOOFUS_GEPA_BATCH_EVERY", "999")
    monkeypatch.setenv("DOOFUS_MAP_ELITES_MAINTAIN_EVERY", "999")

    monkeypatch.setenv("DOOFUS_CODEEVOLVE_EVERY", "1")
    monkeypatch.setattr(rs, "check_budget", lambda: {"ok": True})
    monkeypatch.setattr(rs, "run_codeevolve", lambda gen: {"classification": "CODEEVOLVE_GENERATION_COMPLETE", "accepted": False})
    rs.run_meta_cycle(dry_run=False, live_model_if_available=False)

    monkeypatch.setattr(rs, "check_budget", lambda: {"ok": False})
    rs.run_meta_cycle(dry_run=False, live_model_if_available=False)

    monkeypatch.setenv("DOOFUS_CODEEVOLVE_EVERY", "999")
    rs.run_meta_cycle(dry_run=False, live_model_if_available=False)

    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT due, attempted, ran, skipped, skip_reason FROM codeevolve_events ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 3
    assert rows[0][:4] == (1, 1, 1, 0)
    assert rows[1][:4] == (1, 0, 0, 1)
    assert rows[1][4] == "budget_blocked"
    assert rows[2][:4] == (0, 0, 0, 1)
    assert rows[2][4] == "not_due"


def test_map_reconcile_repairs_missing_sql_and_reports_extra_sql(isolated_runtime):
    db = isolated_runtime["db"]
    state = isolated_runtime["state"]
    entry = {
        "cell_key": "s1:mtrait_mutation:a1",
        "measure_safety": 1,
        "measure_mutation": "trait_mutation",
        "measure_arena": 1,
        "fitness": 0.88,
        "candidate_id": "C1",
        "generation": 10,
        "updated_at": "2026-07-03T00:00:00+00:00",
    }
    (state / "map_elites_archive.json").write_text(json.dumps([entry]), encoding="utf-8")
    repaired = kpi.reconcile_map_elites_archive(auto_backfill=True)
    assert repaired["sync_status"] == "repaired"
    assert _db_count(db, "map_elites_cells") == 1

    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO map_elites_cells
            (cell_key, measure_safety, measure_mutation, measure_arena, fitness, candidate_id, generation, updated_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            ("s2:mtrait_mutation:a1", 1, "trait_mutation", 1, 0.5, "C2", 11, "2026-07-03T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        conn.close()
    drift = kpi.reconcile_map_elites_archive(auto_backfill=False)
    assert drift["sync_status"] == "drift_explained_nondestructive"
    assert drift["missing_in_json"] == ["s2:mtrait_mutation:a1"]


def test_capture_snapshot_records_champion_event_without_overwriting_ledger(isolated_runtime):
    db = isolated_runtime["db"]
    state = isolated_runtime["state"]
    before = (state / "best_ever_ledger.json").read_text(encoding="utf-8")
    snap = kpi.capture_kpi_snapshot(since_gen=1633)
    after = (state / "best_ever_ledger.json").read_text(encoding="utf-8")
    assert snap["champion_defense"]["best_ever_score"] == 0.9392
    assert before == after
    assert _db_count(db, "champion_defense_events") == 1


def test_capture_snapshot_reports_certified_rebase_accounting(isolated_runtime):
    state = isolated_runtime["state"]
    runtime = state.parent
    marker_path = state / "test_contamination_marker.json"
    marker_path.write_text(
        json.dumps(
            {
                "expected_generation_before_test": 1634,
                "contaminated_generation_observed": 1636,
                "excluded_from_progress_claims": [1635, 1636],
                "active_contamination_block": False,
            }
        ),
        encoding="utf-8",
    )
    cert_path = runtime / "reports" / "doofus_clean_runtime_baseline_certificate.json"
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    cert_path.write_text(
        json.dumps(
            {
                "timestamp_utc": "2026-07-03T20:00:00Z",
                "baseline_type": "CERTIFIED_POST_CONTAMINATION_REBASE_BASELINE",
                "baseline_generation": 1636,
            }
        ),
        encoding="utf-8",
    )
    snap = kpi.capture_kpi_snapshot(since_gen=1633)
    base = snap["baseline_certification"]
    assert base["baseline_type"] == "CERTIFIED_POST_CONTAMINATION_REBASE_BASELINE"
    assert base["certified_baseline_generation"] == 1636
    assert base["excluded_contaminated_generations"] == [1635, 1636]
    assert base["contamination_adjusted_progress_status"] == "CERTIFIED_REBASE_EXCLUSIONS_ACTIVE"
