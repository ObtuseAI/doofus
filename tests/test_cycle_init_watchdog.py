"""Regression tests for pre-candidate cycle init watchdog and bounded inline rescue."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

import pytest

from doofus.core import doofus_paths
from doofus.supervisor.cycle_init_watchdog import (
    CycleInitContext,
    CycleInitTimeout,
    rollback_init_without_progress,
    run_bounded_init_call,
)
from doofus.supervisor.doofus_crash_recovery import load_checkpoint, save_checkpoint
from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint, write_checkpoint as write_cycle_ck
from doofus.safety.on_off_switch import status, stop


@pytest.fixture
def isolated_runtime(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    db = tmp_path / "metrics.sqlite"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE candidates (candidate_id TEXT, generation INTEGER, status TEXT, score_total REAL)"
    )
    conn.execute(
        "CREATE TABLE champion_defense_events (id INTEGER PRIMARY KEY, generation INTEGER, event_type TEXT)"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(doofus_paths, "STATE", state)
    monkeypatch.setattr(doofus_paths, "METRICS_DB", db)
    events_path = state / "cycle_init_events.jsonl"
    monkeypatch.setattr("doofus.supervisor.cycle_init_telemetry.EVENTS", events_path)

    baseline = {
        "generation": 1639,
        "baseline_score": 0.9,
        "run_id": "test-run",
        "phase": "complete",
    }
    save_checkpoint(baseline)
    write_cycle_ck("cycle_complete", {"classification": "B1003_LIVE_MODEL_CYCLE_PASS", "generation": 1639})
    stop()
    return tmp_path, baseline


def _patch_cycle_runner_basics(monkeypatch, tmp_path: Path):
    db = tmp_path / "metrics.sqlite"
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.check_may_proceed", lambda: (True, "ok"))
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner._ensure_db", lambda: None)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.bootstrap_autonomous_runtime", lambda: None)

    def fake_connect():
        conn = sqlite3.connect(db, timeout=5.0)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS cycles (run_id TEXT, generation INTEGER, created_at TEXT)"
        )
        return conn

    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.connect_metrics_db", fake_connect)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.after_cycle", lambda **_k: {})
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.after_compounding_cycle", lambda **_k: {})
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.emit_heartbeat", lambda *_a, **_k: None)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.write_checkpoint", lambda *_a, **_k: None)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.build_live_cycle_report", lambda doc: {"cycle": doc})
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.may_call_model", lambda **_k: {"allowed": False})


def _read_init_events() -> list[dict]:
    from doofus.supervisor.cycle_init_telemetry import EVENTS

    if not EVENTS.exists():
        return []
    return [json.loads(line) for line in EVENTS.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_cycle_init_watchdog_aborts_before_60_minute_hang(isolated_runtime, monkeypatch):
    _tmp, baseline = isolated_runtime
    monkeypatch.setenv("DOOFUS_CYCLE_INIT_TIMEOUT_SECONDS", "1")
    ctx = CycleInitContext(
        generation=1640,
        baseline_checkpoint=baseline,
        run_id="r1",
        dry_run=True,
        live_model_if_available=False,
        model_mode="dry_run",
    )
    ctx.__enter__()
    time.sleep(1.2)
    with pytest.raises(CycleInitTimeout):
        ctx.check("inline_rescue")


def test_cycle_init_timeout_restores_stop_flag(isolated_runtime, monkeypatch):
    _tmp, baseline = isolated_runtime
    monkeypatch.setenv("DOOFUS_CYCLE_INIT_TIMEOUT_SECONDS", "180")
    exc = CycleInitTimeout(step="inline_rescue", duration_ms=200000, limit_ms=180000)
    ctx = CycleInitContext(
        generation=1640,
        baseline_checkpoint=baseline,
        run_id="r1",
        dry_run=True,
        live_model_if_available=False,
        model_mode="dry_run",
    )
    ctx.__enter__()
    ctx._abort(exc)
    assert status().get("stop_requested") is True


def test_cycle_init_timeout_rolls_back_checkpoint_when_no_candidates(isolated_runtime):
    _tmp, baseline = isolated_runtime
    save_checkpoint({**baseline, "generation": 1640, "phase": "started"})
    cleanup = rollback_init_without_progress(
        generation=1640,
        baseline_checkpoint=baseline,
        had_candidates=False,
        model_calls=0,
        stalled_step="inline_rescue",
    )
    cp = load_checkpoint()
    assert cleanup["rollback_applied"] is True
    assert cp["generation"] == 1639
    assert cp["phase"] == "complete"


def test_cycle_init_timeout_records_exact_step(isolated_runtime, monkeypatch):
    _tmp, baseline = isolated_runtime
    monkeypatch.setenv("DOOFUS_CYCLE_INIT_TIMEOUT_SECONDS", "180")
    ctx = CycleInitContext(
        generation=1640,
        baseline_checkpoint=baseline,
        run_id="r1",
        dry_run=True,
        live_model_if_available=False,
        model_mode="dry_run",
    )
    ctx.__enter__()
    ctx._abort(CycleInitTimeout(step="high_score_enqueue", duration_ms=181000, limit_ms=180000))
    steps = [row["step"] for row in _read_init_events()]
    assert "cycle_init_timeout" in steps
    timeout_rows = [row for row in _read_init_events() if row["step"] == "cycle_init_timeout"]
    assert timeout_rows[-1]["error_message_sanitized"]


def test_provider_readiness_hang_is_bounded(isolated_runtime, monkeypatch):
    _tmp, baseline = isolated_runtime
    _patch_cycle_runner_basics(monkeypatch, _tmp)
    monkeypatch.setenv("DOOFUS_CYCLE_INIT_TIMEOUT_SECONDS", "1")

    def slow_provider():
        time.sleep(2)
        return {"provider_selected": "dry_run", "model_name": "dry_run"}

    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.resolve_provider", slow_provider)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.proof_builder_mode", lambda: False)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.prepare_cycle", lambda: {"candidate_count": 1})
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.generate_cycle_candidates", lambda *_a, **_k: [])
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.filter_retired_parents", lambda xs: xs)

    from doofus.supervisor.doofus_loop_runner import run_one_cycle

    result = run_one_cycle(dry_run=True)
    assert result["classification"] == "DOOFUS_CYCLE_INIT_TIMEOUT_ABORTED"


def test_champion_defense_stall_is_bounded(isolated_runtime, monkeypatch):
    _tmp, baseline = isolated_runtime
    _patch_cycle_runner_basics(monkeypatch, _tmp)
    monkeypatch.setenv("DOOFUS_CYCLE_INIT_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("DOOFUS_INLINE_RESCUE_MAX_SECONDS", "1")

    def hang_rescue(**_kwargs):
        time.sleep(3)
        return {"classification": "INLINE_RESCUE_OK", "active": True}

    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.proof_builder_mode", lambda: True)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.run_inline_rescue", hang_rescue)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.resolve_provider", lambda: {"provider_selected": "dry_run"})
    from doofus.supervisor.doofus_loop_runner import run_one_cycle

    result = run_one_cycle(dry_run=False)
    assert result["classification"] == "DOOFUS_CYCLE_INIT_TIMEOUT_ABORTED"


def test_db_prepare_stall_is_bounded(isolated_runtime, monkeypatch):
    _tmp, baseline = isolated_runtime
    _patch_cycle_runner_basics(monkeypatch, _tmp)
    monkeypatch.setenv("DOOFUS_CYCLE_INIT_TIMEOUT_SECONDS", "1")
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.proof_builder_mode", lambda: False)

    def slow_prepare():
        time.sleep(2)
        return {"candidate_count": 1}

    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.prepare_cycle", slow_prepare)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.resolve_provider", lambda: {"provider_selected": "dry_run"})
    from doofus.supervisor.doofus_loop_runner import run_one_cycle

    result = run_one_cycle(dry_run=True)
    assert result["classification"] == "DOOFUS_CYCLE_INIT_TIMEOUT_ABORTED"


def test_seed_context_delay_is_bounded(isolated_runtime, monkeypatch):
    _tmp, baseline = isolated_runtime
    _patch_cycle_runner_basics(monkeypatch, _tmp)
    monkeypatch.setenv("DOOFUS_CYCLE_INIT_TIMEOUT_SECONDS", "1")

    def slow_mine(**_kwargs):
        time.sleep(2)
        return {"top_100": [], "count_score_gte_threshold": 0}

    monkeypatch.setattr("doofus.proof.proof_candidate_selector.mine_high_score_rejections", slow_mine)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.proof_builder_mode", lambda: True)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.resolve_provider", lambda: {"provider_selected": "dry_run"})
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.prepare_cycle", lambda: {"candidate_count": 1})
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.generate_cycle_candidates", lambda *_a, **_k: [])
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.filter_retired_parents", lambda xs: xs)
    from doofus.supervisor.doofus_loop_runner import run_one_cycle

    result = run_one_cycle(dry_run=False)
    assert result["classification"] == "DOOFUS_CYCLE_INIT_TIMEOUT_ABORTED"


def test_no_live_provider_call_after_init_timeout(isolated_runtime, monkeypatch):
    _tmp, baseline = isolated_runtime
    _patch_cycle_runner_basics(monkeypatch, _tmp)
    monkeypatch.setenv("DOOFUS_CYCLE_INIT_TIMEOUT_SECONDS", "1")
    calls = {"provider": 0, "model": 0}

    def slow_prepare():
        time.sleep(2)
        return {"candidate_count": 1}

    def track_provider(*_a, **_k):
        calls["provider"] += 1
        return {"provider_selected": "openai", "model_name": "gpt-test", "live_provider_ready": True}

    def track_model(*_a, **_k):
        calls["model"] += 1
        return {"classification": "DOOFUS_MODEL_LIVE", "proposals": []}

    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.proof_builder_mode", lambda: False)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.prepare_cycle", slow_prepare)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.resolve_provider", track_provider)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.provider_propose_mutations", track_model)
    from doofus.supervisor.doofus_loop_runner import run_one_cycle

    result = run_one_cycle(dry_run=False, live_model_if_available=True)
    assert result["classification"] == "DOOFUS_CYCLE_INIT_TIMEOUT_ABORTED"
    assert calls["model"] == 0


def test_no_gen1640_rows_left_in_live_db_from_rehearsal(isolated_runtime, monkeypatch):
    _tmp, baseline = isolated_runtime
    _patch_cycle_runner_basics(monkeypatch, _tmp)
    monkeypatch.setenv("DOOFUS_CYCLE_INIT_TIMEOUT_SECONDS", "1")
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.proof_builder_mode", lambda: False)

    def slow_prepare():
        time.sleep(2)
        return {"candidate_count": 1}

    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.prepare_cycle", slow_prepare)
    monkeypatch.setattr("doofus.supervisor.doofus_loop_runner.resolve_provider", lambda: {"provider_selected": "dry_run"})
    from doofus.supervisor.doofus_loop_runner import run_one_cycle

    run_one_cycle(dry_run=True)
    conn = sqlite3.connect(_tmp / "metrics.sqlite")
    count = conn.execute("SELECT COUNT(*) FROM candidates WHERE generation=1640").fetchone()[0]
    conn.close()
    assert count == 0


def test_open_ended_loop_still_blocked_by_stop_true(isolated_runtime):
    _tmp, _baseline = isolated_runtime
    assert status().get("stop_requested") is True
    assert status().get("may_run") is False


def test_authorized_one_cycle_still_allowed_after_watchdog_fix(isolated_runtime, monkeypatch):
    _tmp, baseline = isolated_runtime
    monkeypatch.setenv("DOOFUS_ALLOW_LIVE_RUNTIME_TESTS", "1")
    monkeypatch.setattr(
        "doofus.supervisor.live_cycle_launch_guard.verify_nonlive_dry_run_guard",
        lambda: {"classification": "DOOFUS_MODEL_DRY_RUN"},
    )
    monkeypatch.setattr(
        "doofus.supervisor.live_cycle_launch_guard.inspect_live_db",
        lambda **_k: {
            "target_generation_total": 0,
            "above_target_generation_total": 0,
            "db_max_generation": 1639,
            "checkpoint_state_ambiguous": False,
        },
    )
    from doofus.supervisor.live_cycle_launch_guard import guarded_live_cycle_launch

    launch = guarded_live_cycle_launch(
        requested_live_mode=True,
        one_cycle_only=True,
        run_cycle=lambda **_k: {"classification": "DOOFUS_CYCLE_COMPLETE", "model_result": {"classification": "DOOFUS_MODEL_LIVE"}},
        operator_approved_one_cycle=True,
    )
    assert launch["classification"] == "DOOFUS_LIVE_CYCLE_LAUNCH_GUARD_RESULT"


def test_nonlive_dry_run_guard_unchanged(isolated_runtime, monkeypatch):
    from doofus.supervisor.live_cycle_launch_guard import verify_nonlive_dry_run_guard

    result = verify_nonlive_dry_run_guard()
    assert result["classification"] == "DOOFUS_MODEL_DRY_RUN"


def test_init_timeout_containment_report_written(isolated_runtime, tmp_path):
    _tmp, baseline = isolated_runtime
    out = tmp_path / "contain"
    from scripts.doofus_init_timeout_containment import write_containment_report

    report = write_containment_report(
        output_dir=out,
        stalled_step="inline_rescue",
        generation=1640,
        baseline_checkpoint=baseline,
    )
    assert (out / "INIT_TIMEOUT_CONTAINMENT.json").exists()
    assert report["classification"] == "DOOFUS_INIT_TIMEOUT_CONTAINMENT"


def test_run_bounded_init_call_raises_on_hang(isolated_runtime, monkeypatch):
    _tmp, baseline = isolated_runtime
    monkeypatch.setenv("DOOFUS_CYCLE_INIT_TIMEOUT_SECONDS", "1")
    ctx = CycleInitContext(
        generation=1640,
        baseline_checkpoint=baseline,
        run_id="r1",
        dry_run=True,
        live_model_if_available=False,
        model_mode="dry_run",
    )
    ctx.__enter__()
    with pytest.raises(CycleInitTimeout):
        run_bounded_init_call(ctx, step="inline_rescue", func=lambda: time.sleep(2) or {"ok": True})
