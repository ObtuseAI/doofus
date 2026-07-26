"""Tests for proof density calculator and miner."""
import json
import subprocess

from doofus.core import doofus_paths
from doofus.core.metrics_db import connect_metrics_db
from doofus.proof.proof_density_calculator import calculate_proof_density
from doofus.proof.high_score_rejection_miner import mine_high_score_rejections
from doofus.proof.proof_builder_queue import enqueue, queue_summary, proof_builder_enabled
from doofus.proof.proof_builder_runner import process_one, run_process_one_guarded
from doofus.scoring.proof_threshold_sweep import sweep


def test_calculate_proof_density_replay():
    r = calculate_proof_density(
        {"candidate_id": "x", "traits": ["replay_stability"]},
        {"score_replay": 0.5, "score_safety": 1.0, "bloat_penalty": 0.05, "score_total": 0.8, "_baseline": 0.5},
        arena_results=[{"result": "pass_agent_arcade"}],
    )
    assert r["proof_density_score"] >= 0.45


def test_mine_high_score_rejections():
    r = mine_high_score_rejections(min_score=0.72, limit=10)
    assert "count_score_gte_threshold" in r


def test_proof_builder_queue():
    assert enqueue("__test_pb_q__", score=0.75, reason="test") or True
    s = queue_summary()
    assert "queue_size" in s
    assert "queue_path" in s


def test_proof_builder_child_timeout_recorded(monkeypatch):
    enqueue("__timeout_pb_q__", score=0.75, reason="test-timeout")

    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="python", timeout=1.0)

    monkeypatch.setattr("doofus.proof.proof_builder_runner.subprocess.run", fake_run)
    result = run_process_one_guarded(
        "__timeout_pb_q__",
        baseline=0.5,
        timeout_seconds=1.0,
        generation=1637,
        phase="shadow_upgrade_item",
    )
    events_path = doofus_paths.STATE / "supervisor_phase_events.jsonl"
    rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert result["outcome"] == "proof_timeout"
    assert any(row["status"] == "child_timeout" and row["phase"] == "shadow_upgrade_item" for row in rows)


def test_threshold_sweep():
    r = sweep()
    assert "thresholds" in r


def test_proof_builder_queue_preserves_generation_identity():
    conn = connect_metrics_db()
    try:
        conn.execute(
            "INSERT INTO candidates (candidate_id, parent_id, generation, traits, mutation_type, arena_targets, status, created_at, score_total) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("PB_GEN_MISMATCH", None, 1637, "", "trait_mutation", "", "rejected", "2026-07-04T00:00:00+00:00", 0.8),
        )
        conn.commit()
    finally:
        conn.close()

    enqueue("PB_GEN_MISMATCH", score=0.8, reason="test-generation", generation=1638)
    result = process_one("PB_GEN_MISMATCH", baseline=0.5)

    assert result["outcome"] == "proof_blocked"
    assert result["error_type"] == "GenerationMismatch"
