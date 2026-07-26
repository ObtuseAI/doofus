"""Tier 3 final gate tests."""
from __future__ import annotations

import pytest

from doofus.core.doofus_state import init_db
from doofus.promotion.tier3_final_gate import (
    get_tier3_snapshot,
    requires_tier3,
    run_tier3_final_gate,
    tier3_min_score,
)


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    db = tmp_path / "test.sqlite"
    state = tmp_path / "state"
    tier3_state = state / "tier3_finals.json"
    monkeypatch.setattr("doofus.core.doofus_paths.METRICS_DB", db)
    monkeypatch.setattr("doofus.core.doofus_state.METRICS_DB", db)
    monkeypatch.setattr("doofus.core.doofus_paths.STATE", state)
    monkeypatch.setattr("doofus.promotion.tier3_final_gate.STATE", state)
    monkeypatch.setattr("doofus.promotion.tier3_final_gate.TIER3_STATE", tier3_state)
    monkeypatch.setattr("doofus.promotion.tier3_final_gate.TIER3_RESULTS", state / "tier3" / "results.jsonl")
    init_db(db)


def test_requires_tier3_threshold(monkeypatch):
    monkeypatch.setenv("DOOFUS_TIER3_MIN_SCORE", "0.85")
    assert requires_tier3(0.90)
    assert not requires_tier3(0.80)


def test_tier3_audit_only_when_disabled(monkeypatch):
    monkeypatch.setenv("DOOFUS_TIER3_ENABLED", "0")
    candidate = {"candidate_id": "T3_1", "traits": ["proof_density"], "parent_id": "P0", "generation": 1}
    scores = {"score_total": 0.90, "score_safety": 0.99, "score_replay": 0.5}
    result = run_tier3_final_gate(candidate, scores, baseline=0.5)
    assert result["classification"] == "TIER3_AUDIT_ONLY"
    assert result["passed"] is True


def test_tier3_not_required_below_min():
    candidate = {"candidate_id": "T3_2", "traits": [], "generation": 1}
    scores = {"score_total": 0.75, "score_safety": 0.99}
    result = run_tier3_final_gate(candidate, scores)
    assert result["classification"] == "TIER3_NOT_REQUIRED"


def test_tier3_enabled_local_pass(monkeypatch):
    monkeypatch.setenv("DOOFUS_TIER3_ENABLED", "1")
    candidate = {"candidate_id": "T3_3", "traits": ["proof_density"], "parent_id": "P0", "generation": 1}
    scores = {"score_total": 0.90, "score_safety": 0.99, "score_replay": 0.5}
    arena = [{"arena": "agent_arcade", "result": "pass"}]
    result = run_tier3_final_gate(
        candidate,
        scores,
        arena_results=arena,
        baseline=0.5,
        gate_checks={
            "proof_density_passed": True,
            "arena_support_passed": True,
            "replay_passed": True,
        },
    )
    assert result["classification"] == "TIER3_LOCAL_PASS"
    assert result["passed"] is True
    assert result["audit_mode"] == "inline_gate_audit"


def test_tier3_snapshot():
    snap = get_tier3_snapshot()
    assert "enabled" in snap
    assert snap["min_score"] == tier3_min_score()
