"""Classify rejection reasons."""
from __future__ import annotations

def classify_rejection(candidate: dict, scores: dict) -> str | None:
    if scores.get("score_safety", 1) < 0.5:
        return "safety_violation"
    if scores.get("score_total", 0) < 0.35:
        return "low_score"
    if scores.get("bloat_penalty", 0) > 0.5:
        return "bloat"
    if scores.get("score_replay", 0) < 0.4:
        return "replay_failed"
    return None
