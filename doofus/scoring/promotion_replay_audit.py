"""Replay audit for promoted candidates."""
from __future__ import annotations

MIN_REPLAY = 0.45


def audit_replay(candidate: dict) -> dict:
    replay = float(candidate.get("score_replay") or 0)
    stability = float(candidate.get("replay_stability_score") or candidate.get("score_replay") or 0)
    passed = replay >= MIN_REPLAY and stability >= MIN_REPLAY
    verdict = "replay_ok" if passed else "promotion_unreplayable"
    return {
        "replay_score": replay,
        "replay_stability_score": stability,
        "replay_passed": passed,
        "replay_verdict": verdict,
        "min_replay_threshold": MIN_REPLAY,
    }
