"""Tests for reusable controlled-cycle tooling."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from doofus.reports.cycle_certification import build_prep_only_launch_packet, validate_live_verification_evidence
from doofus.reports.cycle_finalizer import write_artifact_pair
from doofus.supervisor.controlled_cycle import (
    AUTHORIZED_LIVE_COMMAND_TEMPLATE,
    ControlledCycleMode,
    allows_live_db_mutation,
    allows_live_route,
    live_verification_artifact_dir,
    postlive_artifact_dir,
    requires_operator_approval,
    validate_baseline_for_live_launch,
    validate_baseline_for_postlive,
)


def test_default_mode_is_prep_only_safe():
    assert ControlledCycleMode.PREFLIGHT_ONLY.value == "preflight_only"
    assert not requires_operator_approval(ControlledCycleMode.PREFLIGHT_ONLY)
    assert not allows_live_route(ControlledCycleMode.PREFLIGHT_ONLY)
    assert not allows_live_db_mutation(ControlledCycleMode.PREFLIGHT_ONLY)


def test_live_mode_requires_operator_approval():
    assert requires_operator_approval(ControlledCycleMode.LIVE_VERIFICATION)
    assert allows_live_route(ControlledCycleMode.LIVE_VERIFICATION)
    assert allows_live_db_mutation(ControlledCycleMode.LIVE_VERIFICATION)


def test_postlive_mode_never_allows_live_route():
    assert not allows_live_route(ControlledCycleMode.POSTLIVE_CERTIFICATION)
    assert not allows_live_db_mutation(ControlledCycleMode.POSTLIVE_CERTIFICATION)


def test_continuous_loop_refused_by_stop_flag_requirement():
    ok, reasons = validate_baseline_for_live_launch(
        checkpoint={"generation": 1641, "phase": "complete"},
        cycle_checkpoint={"data": {"classification": "B1003_LIVE_MODEL_CYCLE_PASS", "generation": 1641}},
        stop_flag={"stop_requested": False},
        db_max_generation=1641,
        candidates_max_generation=1641,
        target_generation=1642,
        target_generation_row_count=0,
        next_generation_row_count=0,
        checkpoint_schema_valid=True,
        cycle_checkpoint_schema_valid=True,
    )
    assert not ok
    assert "stop_flag" in reasons


def test_target_generation_contamination_refused():
    ok, reasons = validate_baseline_for_live_launch(
        checkpoint={"generation": 1641, "phase": "complete"},
        cycle_checkpoint={"data": {"classification": "B1003_LIVE_MODEL_CYCLE_PASS", "generation": 1641}},
        stop_flag={"stop_requested": True},
        db_max_generation=1641,
        candidates_max_generation=1641,
        target_generation=1642,
        target_generation_row_count=3,
        next_generation_row_count=0,
        checkpoint_schema_valid=True,
        cycle_checkpoint_schema_valid=True,
    )
    assert not ok
    assert "gen1642_rows_exist" in reasons


def test_postlive_certification_does_not_launch_next_generation():
    packet = build_prep_only_launch_packet(next_generation=1642, certified_generation=1641)
    assert "does not authorize gen1642 launch" in packet["warning"]
    assert packet["required_baseline"]["checkpoint_generation"] == 1641
    assert packet["required_baseline"]["gen1642_row_count"] == 0
    assert "--operator-approved-one-cycle" in packet["future_command_template"]


def test_gen1641_evidence_validation_accepts_pass():
    final = {"classification": "DOOFUS_GEN1641_LIVE_VERIFICATION_PASS"}
    telemetry = {
        "provider_route": "cursor",
        "model": "composer-2.5",
        "live_model_call_count": 1,
        "model_call_limit": 2,
        "cost_observed_usd": None,
        "cost_limit_usd": 0.05,
        "generation_before": 1640,
        "generation_after": 1641,
        "checkpoint_after": {"generation": 1641, "phase": "complete"},
        "cycle_checkpoint_after": {"data": {"classification": "B1003_LIVE_MODEL_CYCLE_PASS", "generation": 1641}},
        "db_max_generation_after": 1641,
        "gen1642_row_count_after": 0,
        "candidate_count": 24,
        "promoted_count": 0,
        "shadow_promoted_count": 0,
        "rejected_count": 24,
        "inline_rescue_timeout_status": False,
        "run_window_filter_applied": True,
        "stale_events_changed_classification": False,
    }
    post = {"stop_flag": {"stop_requested": True}}
    result = validate_live_verification_evidence(
        final_report=final,
        telemetry=telemetry,
        post_run=post,
        expected_classification="DOOFUS_GEN1641_LIVE_VERIFICATION_PASS",
        source_generation=1640,
        target_generation=1641,
    )
    assert result["validated"] is True


def test_gen1642_prep_packet_names_correct_baseline():
    packet = build_prep_only_launch_packet(next_generation=1642, certified_generation=1641)
    assert packet["required_baseline"]["db_max_generation"] == 1641
    assert packet["future_artifact_directory"] == live_verification_artifact_dir(1642) + "/"
    assert packet["provider_expected"] == "openrouter"
    assert packet["model_expected"] == "deepseekv4flash"


def test_artifact_dir_helpers():
    assert live_verification_artifact_dir(1642) == "artifacts/doofus/gen1642-live-verification-v1"
    assert postlive_artifact_dir(1641) == "artifacts/doofus/gen1641-postlive-certification-loop-hardening-v1"


def test_postlive_baseline_validation():
    ok, reasons = validate_baseline_for_postlive(
        checkpoint={"generation": 1641, "phase": "complete"},
        cycle_checkpoint={"data": {"classification": "B1003_LIVE_MODEL_CYCLE_PASS", "generation": 1641}},
        stop_flag={"stop_requested": True},
        db_max_generation=1641,
        certified_generation=1641,
        next_generation_row_count=0,
        checkpoint_schema_valid=True,
        cycle_checkpoint_schema_valid=True,
    )
    assert ok
    assert reasons == []


def test_deterministic_final_report_output():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        payload = {"classification": "TEST", "value": 1}
        write_artifact_pair(out, "FINAL_REPORT", payload)
        assert (out / "FINAL_REPORT.json").exists()
        assert (out / "FINAL_REPORT.md").exists()
        loaded = json.loads((out / "FINAL_REPORT.json").read_text(encoding="utf-8"))
        assert loaded["classification"] == "TEST"


def test_authorized_command_template_has_one_cycle_flag():
    assert "--operator-approved-one-cycle" in AUTHORIZED_LIVE_COMMAND_TEMPLATE


def test_controlled_cycle_bundle_preflight_only_mode():
    import os
    import subprocess
    import sys
    from pathlib import Path

    workspace = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as tmp:
        env = os.environ.copy()
        env.pop("PYTEST_CURRENT_TEST", None)
        proc = subprocess.run(
            [
                sys.executable,
                str(workspace / "scripts" / "doofus_controlled_cycle_bundle.py"),
                "--mode",
                "preflight_only",
                "--output-dir",
                tmp,
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        assert proc.returncode in (0, 1)
        assert (Path(tmp) / "CONTROLLED_CYCLE_MODE_RESULT.json").exists() or "CONTROLLED_CYCLE" in proc.stdout


def test_controlled_cycle_bundle_postlive_certification_no_live():
    import os
    import subprocess
    import sys
    from pathlib import Path

    workspace = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as tmp:
        env = os.environ.copy()
        env.pop("PYTEST_CURRENT_TEST", None)
        proc = subprocess.run(
            [
                sys.executable,
                str(workspace / "scripts" / "doofus_controlled_cycle_bundle.py"),
                "--mode",
                "postlive_certification",
                "--output-dir",
                tmp,
                "--certified-generation",
                "1642",
                "--next-generation",
                "1643",
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        assert proc.returncode == 0
        result = json.loads((Path(tmp) / "CONTROLLED_CYCLE_MODE_RESULT.json").read_text(encoding="utf-8"))
        assert result.get("live_route_invoked") is False


def test_controlled_cycle_bundle_refuses_live_without_flag():
    import subprocess
    import sys
    from pathlib import Path

    workspace = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run(
            [
                sys.executable,
                str(workspace / "scripts" / "doofus_controlled_cycle_bundle.py"),
                "--mode",
                "live_verification",
                "--output-dir",
                tmp,
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 1
        assert "operator-approved-one-cycle" in proc.stdout or "operator-approved-one-cycle" in proc.stderr
