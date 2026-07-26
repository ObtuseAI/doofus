from __future__ import annotations

import json

import pytest

from doofus.core import doofus_paths
from doofus.core.metrics_db import connect_metrics_db
from doofus.safety import on_off_switch
from doofus.supervisor import doofus_crash_recovery as crash_recovery
from doofus.supervisor import doofus_cycle_checkpoint as cycle_checkpoint
from doofus.supervisor import live_cycle_launch_guard as guard


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


def test_live_cycle_launch_guard_refuses_when_one_cycle_intent_missing(monkeypatch, tmp_path):
    _write_checkpoint(1637)
    _enable_stop_state()
    monkeypatch.setattr(guard, "EVENTS", tmp_path / "live_cycle_launch_guard_events.jsonl")
    monkeypatch.setattr(guard, "resolve_provider", lambda: {"provider_selected": "cursor"})

    result = guard.guarded_live_cycle_launch(
        requested_live_mode=True,
        one_cycle_only=False,
        run_cycle=lambda **_kwargs: {"classification": "should_not_run"},
    )

    assert result["classification"] == "DOOFUS_LIVE_CYCLE_LAUNCH_GUARD_REFUSED"
    assert result["reason"] == "one_cycle_only_required"


def test_live_cycle_launch_guard_refuses_when_target_generation_present(monkeypatch, tmp_path):
    _write_checkpoint(1637)
    _enable_stop_state()
    monkeypatch.setattr(guard, "EVENTS", tmp_path / "live_cycle_launch_guard_events.jsonl")
    monkeypatch.setattr(guard, "resolve_provider", lambda: {"provider_selected": "cursor"})

    conn = connect_metrics_db()
    try:
        conn.execute(
            "INSERT INTO candidates (candidate_id, parent_id, generation, traits, mutation_type, arena_targets, status, created_at, score_total) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("C1638", None, 1638, "", "trait_mutation", "", "generated", "2026-07-04T00:00:00+00:00", 0.55),
        )
        conn.commit()
    finally:
        conn.close()

    result = guard.guarded_live_cycle_launch(
        requested_live_mode=True,
        one_cycle_only=True,
        run_cycle=lambda **_kwargs: {"classification": "should_not_run"},
    )

    assert result["classification"] == "DOOFUS_LIVE_CYCLE_LAUNCH_GUARD_REFUSED"
    assert result["reason"] == "target_generation_already_present"


def test_live_cycle_launch_guard_restores_stop_flag_when_cycle_raises(monkeypatch, tmp_path):
    _write_checkpoint(1637)
    _enable_stop_state()
    monkeypatch.setattr(guard, "EVENTS", tmp_path / "live_cycle_launch_guard_events.jsonl")
    monkeypatch.setattr(guard, "resolve_provider", lambda: {"provider_selected": "cursor"})

    with pytest.raises(RuntimeError, match="boom"):
        guard.guarded_live_cycle_launch(
            requested_live_mode=True,
            one_cycle_only=True,
            run_cycle=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

    assert on_off_switch.status()["stop_requested"] is True
    rows = [
        json.loads(line)
        for line in guard.EVENTS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows[-1]["stop_state_restored"] is True


def test_live_cycle_launch_guard_flags_live_to_dry_run_fallback(monkeypatch, tmp_path):
    _write_checkpoint(1637)
    _enable_stop_state()
    monkeypatch.setattr(guard, "EVENTS", tmp_path / "live_cycle_launch_guard_events.jsonl")
    monkeypatch.setattr(guard, "resolve_provider", lambda: {"provider_selected": "cursor"})

    result = guard.guarded_live_cycle_launch(
        requested_live_mode=True,
        one_cycle_only=True,
        run_cycle=lambda **_kwargs: {
            "classification": "DOOFUS_CYCLE_COMPLETE",
            "model_result": {"classification": "DOOFUS_MODEL_DRY_RUN"},
            "inline_rescue": {"classification": "INLINE_RESCUE_TIMEOUT"},
        },
    )

    assert result["classification"] == "DOOFUS_LIVE_CYCLE_LAUNCH_GUARD_RESULT"
    assert result["decision"] == "refused"
    assert result["refusal_reason"] == "live_cycle_did_not_remain_live"
    assert on_off_switch.status()["stop_requested"] is True
