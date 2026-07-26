"""Post-gen1638 provider-gate and preflight certification tests."""
from __future__ import annotations

import json

import pytest

from doofus.core import doofus_paths
from doofus.core.metrics_db import connect_metrics_db
from doofus.runtime.live_db_preflight import inspect_live_db
from doofus.safety import on_off_switch
from doofus.supervisor import doofus_crash_recovery as crash_recovery
from doofus.supervisor import doofus_cycle_checkpoint as cycle_checkpoint
from doofus.supervisor import live_cycle_launch_guard as guard
from doofus.supervisor import provider_aware_live_cycle as provider_cycle


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


def _enable_stop_state() -> None:
    doofus_paths.RUN_ENABLED.parent.mkdir(parents=True, exist_ok=True)
    doofus_paths.RUN_ENABLED.write_text("enabled", encoding="utf-8")
    doofus_paths.STOP_REQUEST.write_text("stop", encoding="utf-8")


@pytest.fixture(autouse=True)
def _reset_wrapper(monkeypatch):
    monkeypatch.setattr(provider_cycle, "_ONE_CYCLE_WRAPPER_CONSUMED", False)
    guard.ONE_CYCLE_ACTIVE_MARKER.unlink(missing_ok=True)


def test_operator_approved_one_cycle_provider_gate_does_not_preblock_on_stop_requested(monkeypatch):
    _write_checkpoint(1637)
    _enable_stop_state()
    monkeypatch.setattr(provider_cycle, "check_budget", lambda _cfg: {"ok": True})
    monkeypatch.setattr(
        provider_cycle,
        "resolve_provider",
        lambda: {"provider_selected": "cursor", "live_provider_ready": True, "model_name": "composer-2.5"},
    )
    monkeypatch.setattr(provider_cycle.DoofusConfig, "from_env", lambda: type("Cfg", (), {"model_mode": "live"})())
    monkeypatch.setattr(
        provider_cycle,
        "guarded_live_cycle_launch",
        lambda **kwargs: {"classification": "DOOFUS_LIVE_CYCLE_LAUNCH_GUARD_RESULT", "decision": "allowed", "result": {}},
    )
    monkeypatch.setattr(provider_cycle, "classify_cycle", lambda *_a, **_k: "B1053_PROVIDER_AWARE_LIVE_CYCLE_PASS")
    result = provider_cycle.run_provider_aware_cycle(operator_approved_one_cycle=True)
    assert "PASS" in result["classification"]
    assert result.get("gate_reason") != "stop_requested"


def test_live_provider_gate_still_blocks_open_ended_loop_when_stop_requested(monkeypatch):
    _write_checkpoint(1638)
    _enable_stop_state()
    monkeypatch.setattr(provider_cycle, "check_budget", lambda _cfg: {"ok": True})
    result = provider_cycle.run_provider_aware_cycle(operator_approved_one_cycle=False)
    assert result["classification"] == "B1053_PROVIDER_AWARE_LIVE_CYCLE_BLOCKED"
    assert result["reason"] == "stop_requested"


def test_live_provider_gate_requires_operator_approved_one_cycle_flag(monkeypatch):
    _write_checkpoint(1638)
    _enable_stop_state()
    monkeypatch.setattr(provider_cycle, "check_budget", lambda _cfg: {"ok": True})
    monkeypatch.setattr(
        provider_cycle,
        "may_call_live_provider",
        lambda **kwargs: {"allowed": False, "reason": "stop_requested"},
    )
    result = provider_cycle.run_provider_aware_cycle(operator_approved_one_cycle=False)
    assert result["classification"] == "B1053_PROVIDER_AWARE_LIVE_CYCLE_BLOCKED"


def test_provider_gate_no_silent_dry_run_fallback(monkeypatch):
    _write_checkpoint(1637)
    _enable_stop_state()
    monkeypatch.setattr(provider_cycle, "check_budget", lambda _cfg: {"ok": True})
    monkeypatch.setattr(
        provider_cycle,
        "resolve_provider",
        lambda: {"provider_selected": "cursor", "live_provider_ready": True, "model_name": "composer-2.5"},
    )
    monkeypatch.setattr(provider_cycle.DoofusConfig, "from_env", lambda: type("Cfg", (), {"model_mode": "dry_run"})())
    result = provider_cycle.run_provider_aware_cycle(operator_approved_one_cycle=True)
    assert result["classification"] == "B1053_PROVIDER_AWARE_LIVE_CYCLE_AUTH_BLOCKED"
    assert result["gate_reason"] == "model_mode_not_live"


def test_provider_gate_no_unintended_provider_fallback(monkeypatch):
    _write_checkpoint(1637)
    _enable_stop_state()
    monkeypatch.setattr(provider_cycle, "check_budget", lambda _cfg: {"ok": True})
    monkeypatch.setattr(
        provider_cycle,
        "resolve_provider",
        lambda: {"provider_selected": "cursor", "live_provider_ready": True, "model_name": "composer-2.5"},
    )
    monkeypatch.setattr(provider_cycle.DoofusConfig, "from_env", lambda: type("Cfg", (), {"model_mode": "live"})())
    monkeypatch.setattr(
        provider_cycle,
        "guarded_live_cycle_launch",
        lambda **kwargs: {
            "classification": "DOOFUS_LIVE_CYCLE_LAUNCH_GUARD_RESULT",
            "decision": "allowed",
            "result": {"classification": "DOOFUS_CYCLE_COMPLETE", "model_result": {"classification": "DOOFUS_MODEL_LIVE_OK"}},
        },
    )
    monkeypatch.setattr(provider_cycle, "classify_cycle", lambda *_a, **_k: "B1053_PROVIDER_AWARE_LIVE_CYCLE_PASS")
    result = provider_cycle.run_provider_aware_cycle(operator_approved_one_cycle=True)
    assert result["provider_selected"] == "cursor"
    assert result["model_name"] == "composer-2.5"


def test_stop_restored_when_provider_gate_or_cycle_raises(monkeypatch, tmp_path):
    _write_checkpoint(1637)
    _enable_stop_state()
    monkeypatch.setattr(guard, "EVENTS", tmp_path / "events.jsonl")
    monkeypatch.setattr(guard, "GUARDED_STOP_CLEAR_EVENTS", tmp_path / "stop_clear.jsonl")
    monkeypatch.setattr(guard, "ONE_CYCLE_ACTIVE_MARKER", tmp_path / "active.marker")
    monkeypatch.setattr(guard, "resolve_provider", lambda: {"provider_selected": "cursor"})
    with pytest.raises(RuntimeError, match="boom"):
        guard.guarded_live_cycle_launch(
            requested_live_mode=True,
            one_cycle_only=True,
            operator_approved_one_cycle=True,
            run_cycle=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )
    assert on_off_switch.status()["stop_requested"] is True


def test_nonlive_dry_run_guard_unchanged_after_provider_gate_fix(monkeypatch):
    monkeypatch.setattr(guard, "resolve_provider", lambda: {"provider_selected": "cursor"})
    assert guard.verify_nonlive_dry_run_guard()["classification"] == "DOOFUS_MODEL_DRY_RUN"


def test_gen1639_target_refused_without_separate_authorization(monkeypatch, tmp_path):
    _write_checkpoint(1638)
    _enable_stop_state()
    monkeypatch.setattr(guard, "EVENTS", tmp_path / "events.jsonl")
    monkeypatch.setattr(guard, "GUARDED_STOP_CLEAR_EVENTS", tmp_path / "stop_clear.jsonl")
    monkeypatch.setattr(guard, "ONE_CYCLE_ACTIVE_MARKER", tmp_path / "active.marker")
    monkeypatch.setattr(guard, "resolve_provider", lambda: {"provider_selected": "cursor"})

    conn = connect_metrics_db()
    try:
        conn.execute(
            "INSERT INTO candidates (candidate_id, parent_id, generation, traits, mutation_type, arena_targets, status, created_at, score_total) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("C1639", None, 1639, "", "trait_mutation", "", "generated", "2026-07-04T00:00:00+00:00", 0.55),
        )
        conn.commit()
    finally:
        conn.close()

    result = guard.guarded_live_cycle_launch(
        requested_live_mode=True,
        one_cycle_only=True,
        operator_approved_one_cycle=True,
        requested_target_generation=1639,
        run_cycle=lambda **_kwargs: {"classification": "should_not_run"},
    )
    assert result["classification"] == "DOOFUS_LIVE_CYCLE_LAUNCH_GUARD_REFUSED"
    assert result["reason"] == "target_generation_already_present"


def test_authorized_gen1638_rows_not_scrubbed_as_contamination():
    _write_checkpoint(1638)
    conn = connect_metrics_db()
    try:
        conn.execute(
            "INSERT INTO candidates (candidate_id, parent_id, generation, traits, mutation_type, arena_targets, status, created_at, score_total) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("C1638_AUTH", None, 1638, "", "trait_mutation", "", "rejected", "2026-07-04T00:00:00+00:00", 0.75),
        )
        conn.commit()
    finally:
        conn.close()
    report = inspect_live_db(target_generation=1639)
    assert report["checkpoint_generation"] == 1638
    assert report["target_generation"] == 1639
    assert report["target_generation_total"] == 0
    assert "target_generation_already_present" not in report["blockers"]


def test_postlive_certification_accepts_gen1638_db_max_generation():
    _write_checkpoint(1638)
    conn = connect_metrics_db()
    try:
        conn.execute(
            "INSERT INTO candidates (candidate_id, parent_id, generation, traits, mutation_type, arena_targets, status, created_at, score_total) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("C1638_MAX", None, 1638, "", "trait_mutation", "", "rejected", "2026-07-04T00:00:00+00:00", 0.75),
        )
        conn.commit()
    finally:
        conn.close()
    report = inspect_live_db(target_generation=1639)
    assert report["db_max_generation"] == 1638
    assert report["checkpoint_generation"] == 1638
    assert report["contamination_detected"] is False
