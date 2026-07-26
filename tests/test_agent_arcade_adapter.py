"""Tests for Agent Arcade adapter."""
from __future__ import annotations

from doofus.arenas.agent_arcade_adapter import run_agent_arcade
from doofus.arenas.arena_result_schema import normalize_arena_result, parse_result_string


def test_enhanced_stub_returns_structured_result():
    c = {"candidate_id": "DOOFUS_1_abc", "traits": ["arena_agent_arcade", "replay_stability"]}
    r = run_agent_arcade(c, live=False)
    assert r["arena"] == "agent_arcade"
    assert "score" in r
    assert "steps" in r
    assert r["result"].startswith("pass") or r["result"].startswith("fail")


def test_trait_bonus_improves_score():
    plain = {"candidate_id": "DOOFUS_1_plain", "traits": []}
    boosted = {"candidate_id": "DOOFUS_1_boost", "traits": ["arena_agent_arcade", "replay_stability", "proof_density"]}
    s_plain = run_agent_arcade(plain)["score"]
    s_boost = run_agent_arcade(boosted)["score"]
    assert s_boost >= s_plain


def test_parse_result_string():
    passed, score = parse_result_string("pass:0.72")
    assert passed is True
    assert score == 0.72


def test_normalize_arena_result():
    r = normalize_arena_result({"candidate_id": "x", "arena": "a", "score": 0.6, "passed": True})
    assert r["result"] == "pass:0.6"
