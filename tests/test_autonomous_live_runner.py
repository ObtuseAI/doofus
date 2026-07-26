"""Tests for autonomous live runner and run lease stop semantics."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from doofus.core import doofus_paths
from doofus.supervisor import autonomous_run_lease as lease
from doofus.supervisor.autonomous_live_runner import AutonomousLiveRunner, RunnerConfig


@pytest.fixture
def lease_paths(tmp_path, monkeypatch):
    session = tmp_path / "session.json"
    halt = tmp_path / "halt.request"
    monkeypatch.setattr(lease, "SESSION_PATH", session)
    monkeypatch.setattr(lease, "EXTERNAL_HALT_PATH", halt)
    monkeypatch.setattr(doofus_paths, "STOP_REQUEST", tmp_path / "stop.request")
    monkeypatch.setattr(doofus_paths, "RUN_ENABLED", tmp_path / "run.enabled")
    monkeypatch.setattr(doofus_paths, "EMERGENCY_STOP", tmp_path / "emergency.request")
    doofus_paths.RUN_ENABLED.write_text("enabled", encoding="utf-8")
    doofus_paths.STOP_REQUEST.write_text("stop_at=internal\n", encoding="utf-8")
    return tmp_path


def test_dry_run_never_calls_live_cycle():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = RunnerConfig(dry_run=True, once=True, output_dir=Path(tmp), max_cycles=1)
        runner = AutonomousLiveRunner(cfg)
        with patch.object(runner, "_run_one_live_cycle") as live_mock:
            with patch.object(runner, "_preflight", return_value={"passed": True, "blockers": []}):
                result = runner.run()
        live_mock.assert_not_called()
        assert "DRY_RUN" in result["classification"]


def test_daemon_requires_operator_approval():
    cfg = RunnerConfig(dry_run=False, daemon=True, operator_approved=False, max_cycles=1)
    runner = AutonomousLiveRunner(cfg)
    result = runner.run()
    assert result["classification"] == "DOOFUS_AUTONOMOUS_LIVE_RUNNER_FAIL"
    assert "operator-approved" in result["reason"]


def test_daemon_requires_autonomous_env(monkeypatch):
    monkeypatch.delenv("DOOFUS_AUTONOMOUS_LIVE_MODE", raising=False)
    cfg = RunnerConfig(dry_run=False, daemon=True, operator_approved=True, max_cycles=1)
    runner = AutonomousLiveRunner(cfg)
    result = runner.run()
    assert "DOOFUS_AUTONOMOUS_LIVE_MODE" in result["reason"]


def test_max_cycles_required():
    cfg = RunnerConfig(dry_run=True, max_cycles=0)
    runner = AutonomousLiveRunner(cfg)
    result = runner.run()
    assert "max_cycles" in result["reason"]


def test_internal_stop_restore_does_not_halt_daemon(lease_paths):
    lease.start_session(session_id="sess_test", max_cycles=3)
    lease.record_internal_stop_restore()
    halted, reason = lease.external_stop_detected()
    assert halted is False
    assert reason == "ok"


def test_external_halt_request_halts_daemon(lease_paths):
    lease.start_session(session_id="sess_test", max_cycles=3)
    lease.record_internal_stop_restore()
    lease.request_external_halt(reason="operator_stop")
    halted, reason = lease.external_stop_detected()
    assert halted is True
    assert reason == "autonomous_run_halt_request"


def test_external_stop_mtime_halts_daemon(lease_paths):
    lease.start_session(session_id="sess_test", max_cycles=3)
    lease.record_internal_stop_restore()
    doofus_paths.STOP_REQUEST.write_text("new_stop_at=external\n", encoding="utf-8")
    halted, reason = lease.external_stop_detected()
    assert halted is True
    assert reason == "external_stop_request_mtime"


def test_successful_cycle_does_not_classify_as_halted_by_stop(lease_paths, monkeypatch):
    monkeypatch.setenv("DOOFUS_AUTONOMOUS_LIVE_MODE", "1")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = RunnerConfig(
            dry_run=False,
            daemon=False,
            once=True,
            operator_approved=True,
            max_cycles=1,
            require_postlive_certification=False,
            output_dir=Path(tmp),
        )
        runner = AutonomousLiveRunner(cfg)
        live_result = {
            "exit_code": 0,
            "cycle_output": {
                "classification": "B1053_PROVIDER_AWARE_LIVE_CYCLE_PASS",
                "cycle_classification": "B1003_LIVE_MODEL_CYCLE_PASS",
                "generation": 1645,
                "provider_selected": "openrouter",
            },
        }
        with patch.object(runner, "_preflight", return_value={"passed": True, "blockers": [], "checkpoint_state": {"checkpoint": {"generation": 1644}}}):
            with patch.object(runner, "_run_one_live_cycle", return_value=live_result):
                result = runner.run()
        assert result["classification"] != "DOOFUS_AUTONOMOUS_LIVE_RUNNER_HALTED_BY_STOP"
        assert result["cycles_completed"] == 1
        assert result["runner_session_id"]


def test_max_cycles_completion(lease_paths, monkeypatch):
    monkeypatch.setenv("DOOFUS_AUTONOMOUS_LIVE_MODE", "1")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = RunnerConfig(
            dry_run=False,
            daemon=True,
            operator_approved=True,
            max_cycles=2,
            sleep_seconds=0,
            require_postlive_certification=False,
            output_dir=Path(tmp),
        )
        runner = AutonomousLiveRunner(cfg)
        live_result = {
            "exit_code": 0,
            "cycle_output": {
                "classification": "B1053_PROVIDER_AWARE_LIVE_CYCLE_PASS",
                "cycle_classification": "B1003_LIVE_MODEL_CYCLE_PASS",
                "generation": 1645,
                "provider_selected": "openrouter",
            },
        }
        with patch.object(runner, "_preflight", return_value={"passed": True, "blockers": [], "checkpoint_state": {"checkpoint": {"generation": 1644}}}):
            with patch.object(runner, "_run_one_live_cycle", return_value=live_result):
                result = runner.run()
        assert result["classification"] == "DOOFUS_AUTONOMOUS_LIVE_RUNNER_COMPLETED_MAX_CYCLES"
        assert result["cycles_completed"] == 2


def test_proof_backlog_monitored_not_blocking_by_default():
    cfg = RunnerConfig(no_live_if_proof_queue_pending=False)
    runner = AutonomousLiveRunner(cfg)
    assert runner._proof_blocks_live({"pending": 54}) is False


def test_proof_safety_critical_blocks():
    cfg = RunnerConfig(proof_safety_critical_threshold=50)
    runner = AutonomousLiveRunner(cfg)
    assert runner._proof_blocks_live({"pending": 54}) is True
