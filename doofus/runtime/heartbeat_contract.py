"""Heartbeat freshness contract for runtime health."""
from __future__ import annotations

STALE_SECONDS = 180
WARN_SECONDS = 120


def classify_heartbeat_age(age: float | None) -> dict:
    if age is None:
        return {"fresh": False, "status": "missing", "stale": True}
    if age < WARN_SECONDS:
        return {"fresh": True, "status": "fresh", "stale": False}
    if age < STALE_SECONDS:
        return {"fresh": True, "status": "warn", "stale": False}
    return {"fresh": False, "status": "stale", "stale": True}
