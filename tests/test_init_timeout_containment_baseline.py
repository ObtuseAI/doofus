"""Tests for containment baseline-json extraction and checkpoint schema validation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from doofus.supervisor.checkpoint_baseline import (
    CheckpointSchemaError,
    backup_checkpoint_files,
    extract_checkpoint,
    extract_cycle_checkpoint,
    validate_checkpoint,
)
from doofus.supervisor.doofus_crash_recovery import CHECKPOINT, load_checkpoint, save_checkpoint


def test_containment_accepts_raw_checkpoint():
    raw = {
        "generation": 1639,
        "baseline_score": 0.9378,
        "run_id": "f45ce1a3-c56",
        "phase": "complete",
    }
    cp = extract_checkpoint(raw)
    assert cp["generation"] == 1639


def test_containment_accepts_starting_state_artifact():
    artifact = {
        "classification": "DOOFUS_GEN1640_RETRY_STARTING_STATE",
        "branch": "test",
        "commit": "abc",
        "checkpoint": {
            "generation": 1639,
            "baseline_score": 0.9378,
            "run_id": "f45ce1a3-c56",
            "phase": "complete",
        },
        "cycle_checkpoint": {
            "stage": "cycle_complete",
            "data": {"classification": "B1003_LIVE_MODEL_CYCLE_PASS", "generation": 1639},
        },
    }
    cp = extract_checkpoint(artifact)
    cc = extract_cycle_checkpoint(artifact)
    assert cp["phase"] == "complete"
    assert cc["data"]["generation"] == 1639


def test_containment_refuses_invalid_shape():
    with pytest.raises(CheckpointSchemaError):
        extract_checkpoint({"classification": "DOOFUS_GEN1640_RETRY_STARTING_STATE", "branch": "x"})


def test_containment_never_writes_starting_state_shape(tmp_path, monkeypatch):
    from doofus.core import doofus_paths
    from doofus.supervisor import doofus_crash_recovery

    state = tmp_path / "state"
    state.mkdir()
    ck = state / "last_checkpoint.json"
    monkeypatch.setattr(doofus_paths, "STATE", state)
    monkeypatch.setattr(doofus_crash_recovery, "CHECKPOINT", ck)
    artifact = {
        "classification": "DOOFUS_GEN1640_RETRY_STARTING_STATE",
        "checkpoint": {
            "generation": 1639,
            "baseline_score": 0.9378,
            "run_id": "run",
            "phase": "complete",
        },
    }
    baseline = extract_checkpoint(artifact)
    validate_checkpoint(baseline)
    save_checkpoint(baseline)
    loaded = load_checkpoint()
    assert loaded["generation"] == 1639
    assert "classification" not in loaded or loaded.get("classification") != "DOOFUS_GEN1640_RETRY_STARTING_STATE"


def test_checkpoint_backup_created(tmp_path, monkeypatch):
    from doofus.core import doofus_paths
    from doofus.supervisor import doofus_crash_recovery
    from doofus.supervisor import doofus_cycle_checkpoint

    state = tmp_path / "state"
    state.mkdir()
    ck = state / "last_checkpoint.json"
    cc = state / "cycle_checkpoint.json"
    ck.write_text(json.dumps({"generation": 1639, "baseline_score": 0.9, "run_id": "r", "phase": "complete"}))
    cc.write_text(json.dumps({"stage": "cycle_complete", "data": {"generation": 1639}}))
    monkeypatch.setattr(doofus_paths, "STATE", state)
    monkeypatch.setattr(doofus_crash_recovery, "CHECKPOINT", ck)
    monkeypatch.setattr(doofus_cycle_checkpoint, "CHECKPOINT", cc)
    backups = backup_checkpoint_files(output_dir=tmp_path / "backups", label="test")
    assert "last_checkpoint.json" in backups
