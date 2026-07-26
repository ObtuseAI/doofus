"""Replay proof evidence builder."""
from __future__ import annotations


def build_replay_proof(candidate: dict, scores: dict) -> dict:
    replay = float(scores.get("score_replay") or 0)
    passed = replay >= 0.45
    return {"replay_passed": passed, "score_replay": replay, "evidence": "replay" if passed else None}
