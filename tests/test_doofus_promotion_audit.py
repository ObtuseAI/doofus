"""Tests for promotion audit modules."""
from doofus.scoring.promotion_replay_audit import audit_replay
from doofus.scoring.promotion_regression_audit import audit_regression
from doofus.scoring.promotion_bloat_audit import audit_bloat
from doofus.scoring.promotion_safety_audit import audit_safety
from doofus.scoring.promotion_gate_recommendation import recommend_gate


def test_audit_replay_pass():
    r = audit_replay({"score_replay": 0.5})
    assert r["replay_passed"] is True


def test_audit_regression_weak():
    r = audit_regression({"score_total": 0.73}, {"score_total": 0.72}, 0.5)
    assert r["regression_passed"] is True


def test_audit_bloat():
    r = audit_bloat({"traits": ["a", "b", "c"], "bloat_penalty": 0.1})
    assert r["bloat_passed"] is True


def test_audit_safety():
    r = audit_safety({"traits": [], "score_safety": 1.0})
    assert r["safety_passed"] is True


def test_gate_recommendation_keep():
    audit = {"summary": {"promotions_audited": 5, "validated": 4, "weak": 1, "unsafe": 0, "unreplayable": 0, "rollback_recommended": 0}, "promotions": []}
    rec = recommend_gate(audit)
    assert rec["recommendation"] in ("keep_gate_current", "require_higher_proof_density")
