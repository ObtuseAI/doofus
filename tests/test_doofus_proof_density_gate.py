"""Tests for proof density and arena gates."""
from doofus.scoring.proof_density_gate import check_proof_density
from doofus.scoring.arena_support_gate import check_arena_support
from doofus.scoring.promotion_gate import evaluate_promotion, PROMOTION_THRESHOLD


def test_proof_density_gate_pass():
    r = check_proof_density({"traits": ["proof_density"]}, {"proof_density_score": 0.6})
    assert r["proof_density_passed"] is True


def test_arena_support_gate_pass():
    r = check_arena_support([{"result": "pass:0.7"}])
    assert r["arena_support_passed"] is True


def test_promotion_gate_full_promote():
    c = {"traits": ["proof_density", "replay_stability"], "candidate_id": "x"}
    s = {
        "score_total": 0.8, "score_safety": 1.0, "score_replay": 0.5,
        "proof_density_score": 0.6, "bloat_penalty": 0.05,
    }
    p = evaluate_promotion(c, s, 0.5, arena_results=[{"result": "pass:0.6"}])
    assert p["promoted"] is True
    assert p["promotion_status"] == "promoted"


def test_promotion_gate_shadow_without_proof(monkeypatch):
    monkeypatch.delenv("DOOFUS_PROOF_BUILDER_MODE", raising=False)
    monkeypatch.setenv("DOOFUS_EVIDENCE_BASED_PROOF_DENSITY", "0")
    c = {"traits": [], "candidate_id": "x"}
    s = {"score_total": 0.8, "score_safety": 1.0, "score_replay": 0.5, "proof_density_score": 0.2, "bloat_penalty": 0.05}
    p = evaluate_promotion(c, s, 0.5, arena_results=[{"result": "pass:0.6"}])
    assert p["shadow_promoted"] is True
    assert p["promoted"] is False


def test_threshold_unchanged():
    assert PROMOTION_THRESHOLD == 0.72
