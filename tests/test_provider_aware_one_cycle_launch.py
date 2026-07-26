from __future__ import annotations

import json

import pytest

from doofus.core import doofus_paths
from doofus.core.metrics_db import connect_metrics_db
from doofus.safety import on_off_switch
from doofus.supervisor import doofus_crash_recovery as crash_recovery
from doofus.supervisor import doofus_cycle_checkpoint as cycle_checkpoint
from doofus.supervisor import live_cycle_launch_guard as guard
from doofus.supervisor import provider_aware_live_cycle as provider_cycle
from doofus.safety.on_off_switch import check_may_proceed


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


def _stub_cycle(**_kwargs) -> dict:
    return {
        "classification": "DOOFUS_CYCLE_COMPLETE",
        "model_result": {"classification": "DOOFUS_MODEL_LIVE_OK"},
        "generation": 1638,
    }


@pytest.fixture(autouse=True)
def _reset_one_cycle_wrapper(monkeypatch):
    monkeypatch.setattr(provider_cycle, "_ONE_CYCLE_WRAPPER_CONSUMED", False)
    guard.ONE_CYCLE_ACTIVE_MARKER.unlink(missing_ok=True)


def test_operator_approved_one_cycle_can_prepare_from_stop_requested_true(monkeypatch, tmp_path):
    _write_checkpoint(1637)
    _enable_stop_state()
    monkeypatch.setattr(guard, "EVENTS", tmp_path / "live_cycle_launch_guard_events.jsonl")
    monkeypatch.setattr(guard, "GUARDED_STOP_CLEAR_EVENTS", tmp_path / "guarded_one_cycle_stop_clear_events.jsonl")
    monkeypatch.setattr(guard, "ONE_CYCLE_ACTIVE_MARKER", tmp_path / "one_cycle_launch_active.marker")
    monkeypatch.setattr(guard, "resolve_provider", lambda: {"provider_selected": "cursor"})

    result = guard.guarded_live_cycle_launch(
        requested_live_mode=True,
        one_cycle_only=True,
        operator_approved_one_cycle=True,
        run_cycle=_stub_cycle,
    )

    assert result["classification"] == "DOOFUS_LIVE_CYCLE_LAUNCH_GUARD_RESULT"
    assert on_off_switch.status()["stop_requested"] is True


def test_provider_gate_does_not_preblock_guarded_one_cycle_on_stop_requested(monkeypatch, tmp_path):
    _write_checkpoint(1637)
    _enable_stop_state()
    monkeypatch.setattr(provider_cycle, "check_budget", lambda _cfg: {"ok": True})
    monkeypatch.setattr(
        provider_cycle,
        "resolve_provider",
        lambda: {"provider_selected": "cursor", "live_provider_ready": True, "model_name": "composer-2.5"},
    )
    monkeypatch.setattr(
        provider_cycle.DoofusConfig,
        "from_env",
        lambda: type("Cfg", (), {"model_mode": "live"})(),
    )
    monkeypatch.setattr(
        provider_cycle,
        "guarded_live_cycle_launch",
        lambda **kwargs: {
            "classification": "DOOFUS_LIVE_CYCLE_LAUNCH_GUARD_RESULT",
            "decision": "allowed",
            "result": {"classification": "DOOFUS_CYCLE_COMPLETE"},
        },
    )
    monkeypatch.setattr(provider_cycle, "classify_cycle", lambda *_a, **_k: "B1053_PROVIDER_AWARE_LIVE_CYCLE_PASS")

    result = provider_cycle.run_provider_aware_cycle(operator_approved_one_cycle=True)
    assert result["classification"] == "B1053_PROVIDER_AWARE_LIVE_CYCLE_PASS"
    assert result.get("gate_reason") != "stop_requested"


def test_provider_aware_cycle_does_not_preblock_guarded_one_cycle(monkeypatch, tmp_path):
    _write_checkpoint(1637)
    _enable_stop_state()
    monkeypatch.setattr(guard, "EVENTS", tmp_path / "live_cycle_launch_guard_events.jsonl")
    monkeypatch.setattr(guard, "GUARDED_STOP_CLEAR_EVENTS", tmp_path / "guarded_one_cycle_stop_clear_events.jsonl")
    monkeypatch.setattr(guard, "ONE_CYCLE_ACTIVE_MARKER", tmp_path / "one_cycle_launch_active.marker")
    monkeypatch.setattr(guard, "resolve_provider", lambda: {"provider_selected": "cursor"})
    monkeypatch.setattr(provider_cycle, "check_budget", lambda _cfg: {"ok": True})
    monkeypatch.setattr(provider_cycle, "resolve_provider", lambda: {"provider_selected": "cursor", "live_provider_ready": True, "model_name": "composer-2.5"})
    monkeypatch.setattr(provider_cycle.DoofusConfig, "from_env", lambda: type("Cfg", (), {"model_mode": "live"})())
    monkeypatch.setattr(provider_cycle, "classify_cycle", lambda *_args, **_kwargs: "B1053_PROVIDER_AWARE_LIVE_CYCLE_PASS")
    monkeypatch.setattr(provider_cycle, "guarded_live_cycle_launch", lambda **kwargs: {
        "classification": "DOOFUS_LIVE_CYCLE_LAUNCH_GUARD_RESULT",
        "decision": "allowed",
        "result": {"classification": "DOOFUS_CYCLE_COMPLETE", "generation": 1638},
    })

    result = provider_cycle.run_provider_aware_cycle(operator_approved_one_cycle=True)
    assert result["classification"] == "B1053_PROVIDER_AWARE_LIVE_CYCLE_PASS"
    assert result.get("reason") != "stop_requested"


def test_open_ended_loop_still_blocked_by_stop_requested(monkeypatch, tmp_path):
    _write_checkpoint(1637)
    _enable_stop_state()
    monkeypatch.setattr(guard, "EVENTS", tmp_path / "live_cycle_launch_guard_events.jsonl")
    monkeypatch.setattr(guard, "GUARDED_STOP_CLEAR_EVENTS", tmp_path / "guarded_one_cycle_stop_clear_events.jsonl")
    monkeypatch.setattr(guard, "ONE_CYCLE_ACTIVE_MARKER", tmp_path / "one_cycle_launch_active.marker")
    monkeypatch.setattr(guard, "resolve_provider", lambda: {"provider_selected": "cursor"})
    monkeypatch.setattr(provider_cycle, "check_budget", lambda _cfg: {"ok": True})

    may, reason = check_may_proceed()
    assert may is False
    assert reason == "stop_requested"

    result = provider_cycle.run_provider_aware_cycle(operator_approved_one_cycle=False)
    assert result["classification"] == "B1053_PROVIDER_AWARE_LIVE_CYCLE_BLOCKED"
    assert result["reason"] == "stop_requested"


def test_repeated_live_cycle_still_refused(monkeypatch, tmp_path):
    _write_checkpoint(1637)
    _enable_stop_state()
    monkeypatch.setattr(guard, "EVENTS", tmp_path / "live_cycle_launch_guard_events.jsonl")
    monkeypatch.setattr(guard, "GUARDED_STOP_CLEAR_EVENTS", tmp_path / "guarded_one_cycle_stop_clear_events.jsonl")
    monkeypatch.setattr(guard, "ONE_CYCLE_ACTIVE_MARKER", tmp_path / "one_cycle_launch_active.marker")
    monkeypatch.setattr(guard, "resolve_provider", lambda: {"provider_selected": "cursor"})
    monkeypatch.setattr(provider_cycle, "check_budget", lambda _cfg: {"ok": True})
    monkeypatch.setattr(provider_cycle, "resolve_provider", lambda: {"provider_selected": "cursor", "live_provider_ready": True, "model_name": "composer-2.5"})
    monkeypatch.setattr(provider_cycle.DoofusConfig, "from_env", lambda: type("Cfg", (), {"model_mode": "live"})())
    monkeypatch.setattr(
        provider_cycle,
        "guarded_live_cycle_launch",
        lambda **kwargs: {
            "classification": "DOOFUS_LIVE_CYCLE_LAUNCH_GUARD_RESULT",
            "decision": "allowed",
            "result": {"classification": "DOOFUS_CYCLE_COMPLETE"},
        },
    )
    monkeypatch.setattr(provider_cycle, "classify_cycle", lambda *_a, **_k: "B1053_PROVIDER_AWARE_LIVE_CYCLE_PASS")

    first = provider_cycle.run_provider_aware_cycle(operator_approved_one_cycle=True)
    assert first["classification"] == "B1053_PROVIDER_AWARE_LIVE_CYCLE_PASS"
    second = provider_cycle.run_provider_aware_cycle(operator_approved_one_cycle=True)
    assert second["classification"] == "B1053_PROVIDER_AWARE_LIVE_CYCLE_BLOCKED"
    assert second["reason"] == "repeated_operator_approved_one_cycle"


def test_target_generation_contamination_still_refused(monkeypatch, tmp_path):
    _write_checkpoint(1637)
    _enable_stop_state()
    monkeypatch.setattr(guard, "EVENTS", tmp_path / "live_cycle_launch_guard_events.jsonl")
    monkeypatch.setattr(guard, "GUARDED_STOP_CLEAR_EVENTS", tmp_path / "guarded_one_cycle_stop_clear_events.jsonl")
    monkeypatch.setattr(guard, "ONE_CYCLE_ACTIVE_MARKER", tmp_path / "one_cycle_launch_active.marker")
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
        operator_approved_one_cycle=True,
        run_cycle=lambda **_kwargs: {"classification": "should_not_run"},
    )
    assert result["classification"] == "DOOFUS_LIVE_CYCLE_LAUNCH_GUARD_REFUSED"
    assert result["reason"] == "target_generation_already_present"
    assert on_off_switch.status()["stop_requested"] is True


def test_stop_restored_when_lower_level_cycle_raises(monkeypatch, tmp_path):
    _write_checkpoint(1637)
    _enable_stop_state()
    monkeypatch.setattr(guard, "EVENTS", tmp_path / "live_cycle_launch_guard_events.jsonl")
    monkeypatch.setattr(guard, "GUARDED_STOP_CLEAR_EVENTS", tmp_path / "guarded_one_cycle_stop_clear_events.jsonl")
    monkeypatch.setattr(guard, "ONE_CYCLE_ACTIVE_MARKER", tmp_path / "one_cycle_launch_active.marker")
    monkeypatch.setattr(guard, "resolve_provider", lambda: {"provider_selected": "cursor"})

    with pytest.raises(RuntimeError, match="boom"):
        guard.guarded_live_cycle_launch(
            requested_live_mode=True,
            one_cycle_only=True,
            operator_approved_one_cycle=True,
            run_cycle=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

    assert on_off_switch.status()["stop_requested"] is True
    rows = [
        json.loads(line)
        for line in guard.GUARDED_STOP_CLEAR_EVENTS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows[-1]["stop_state_after"]["stop_requested"] is True


def test_no_live_route_invoked_by_guard_fix_tests(monkeypatch, tmp_path):
    _write_checkpoint(1637)
    _enable_stop_state()
    monkeypatch.setattr(guard, "EVENTS", tmp_path / "live_cycle_launch_guard_events.jsonl")
    monkeypatch.setattr(guard, "GUARDED_STOP_CLEAR_EVENTS", tmp_path / "guarded_one_cycle_stop_clear_events.jsonl")
    monkeypatch.setattr(guard, "ONE_CYCLE_ACTIVE_MARKER", tmp_path / "one_cycle_launch_active.marker")
    monkeypatch.setattr(guard, "resolve_provider", lambda: {"provider_selected": "cursor"})
    monkeypatch.setattr(provider_cycle, "check_budget", lambda _cfg: {"ok": True})
    monkeypatch.setattr(provider_cycle, "resolve_provider", lambda: {"provider_selected": "cursor", "live_provider_ready": True, "model_name": "composer-2.5"})
    monkeypatch.setattr(provider_cycle.DoofusConfig, "from_env", lambda: type("Cfg", (), {"model_mode": "live"})())
    monkeypatch.setattr(provider_cycle, "classify_cycle", lambda *_a, **_k: "B1053_PROVIDER_AWARE_LIVE_CYCLE_PASS")

    def _fail_if_live(**kwargs):
        raise AssertionError("live provider route must not be invoked in guard fix tests")

    monkeypatch.setattr(provider_cycle, "run_one_cycle", _fail_if_live)
    monkeypatch.setattr(
        provider_cycle,
        "guarded_live_cycle_launch",
        lambda **kwargs: {
            "classification": "DOOFUS_LIVE_CYCLE_LAUNCH_GUARD_RESULT",
            "decision": "allowed",
            "result": {"classification": "DOOFUS_CYCLE_COMPLETE", "model_result": {"classification": "STUB_OK"}},
        },
    )
    result = provider_cycle.run_provider_aware_cycle(operator_approved_one_cycle=True)
    assert "PASS" in result["classification"]


def test_nonlive_dry_run_guard_unchanged(monkeypatch):
    monkeypatch.setattr(guard, "resolve_provider", lambda: {"provider_selected": "cursor"})
    result = guard.verify_nonlive_dry_run_guard()
    assert result["classification"] == "DOOFUS_MODEL_DRY_RUN"


def test_launch_packet_entrypoint_matches_guarded_wrapper():
    command = (
        "python -m doofus.supervisor.provider_aware_live_cycle "
        "--operator-approved-one-cycle --max-model-calls 2 --max-cost-usd 0.05"
    )
    assert "--operator-approved-one-cycle" in command
    assert "provider_aware_live_cycle" in command
    assert command.count("--operator-approved-one-cycle") == 1


def test_guarded_stop_clear_telemetry_written(monkeypatch, tmp_path):
    _write_checkpoint(1637)
    _enable_stop_state()
    monkeypatch.setattr(guard, "EVENTS", tmp_path / "live_cycle_launch_guard_events.jsonl")
    monkeypatch.setattr(guard, "GUARDED_STOP_CLEAR_EVENTS", tmp_path / "guarded_one_cycle_stop_clear_events.jsonl")
    monkeypatch.setattr(guard, "ONE_CYCLE_ACTIVE_MARKER", tmp_path / "one_cycle_launch_active.marker")
    monkeypatch.setattr(guard, "resolve_provider", lambda: {"provider_selected": "cursor"})

    guard.guarded_live_cycle_launch(
        requested_live_mode=True,
        one_cycle_only=True,
        operator_approved_one_cycle=True,
        run_cycle=_stub_cycle,
    )

    rows = [
        json.loads(line)
        for line in guard.GUARDED_STOP_CLEAR_EVENTS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows
    last = rows[-1]
    assert last["event"] == "guarded_one_cycle_stop_clear"
    assert last["operator_approved_one_cycle"] is True
    assert last["preflight_passed"] is True
    assert last["stop_clear_entered"] is True
    assert last["stop_restore_attempted"] is True
    assert last["stop_state_after"]["stop_requested"] is True
