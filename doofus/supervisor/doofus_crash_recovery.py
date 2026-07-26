"""Crash recovery with atomic checkpoint writes."""
from __future__ import annotations

from doofus.core.atomic_json import load_json, save_json
from doofus.core.doofus_paths import STATE
from doofus.core.doofus_events import utc_now

CHECKPOINT = STATE / "last_checkpoint.json"


def save_checkpoint(state: dict) -> None:
    state = dict(state)
    state["saved_at"] = utc_now()
    save_json(CHECKPOINT, state)


def finalize_checkpoint(
    *,
    generation: int,
    baseline_score: float,
    run_id: str,
    phase: str,
    **extra,
) -> dict:
    state = {
        "generation": generation,
        "baseline_score": baseline_score,
        "run_id": run_id,
        "phase": phase,
        **extra,
    }
    save_checkpoint(state)
    return state


def load_checkpoint() -> dict:
    data = load_json(CHECKPOINT, default={"generation": 0, "baseline_score": 0.5})
    if not isinstance(data, dict):
        return {"generation": 0, "baseline_score": 0.5}
    return data
