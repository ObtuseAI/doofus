"""Adaptive mutation pressure — increase generation when stagnant."""
from __future__ import annotations

import json
import os
from pathlib import Path

from doofus.core.doofus_paths import STATE
from doofus.evolution.evolution_policy import (
    base_candidates_per_cycle,
    max_candidates_per_cycle,
    stagnation_cycles_before_pressure,
)

STATE_FILE = STATE / "evolution_pressure_state.json"


def _max_pressure_level() -> float:
    return float(os.environ.get("DOOFUS_MAX_PRESSURE_LEVEL", "6.0"))


def _pressure_ramp_step() -> float:
    return float(os.environ.get("DOOFUS_PRESSURE_RAMP_STEP", "0.35"))


def _load() -> dict:
    if not STATE_FILE.exists():
        return {"stagnation_cycles": 0, "pressure_level": 1.0, "last_promotion_generation": 0}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def _save(data: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def record_cycle(*, generation: int, promoted: int) -> dict:
    data = _load()
    if promoted > 0:
        data["stagnation_cycles"] = 0
        data["last_promotion_generation"] = generation
        data["pressure_level"] = max(1.0, float(data.get("pressure_level", 1.0)) - 0.1)
    else:
        data["stagnation_cycles"] = int(data.get("stagnation_cycles", 0)) + 1
        if data["stagnation_cycles"] >= stagnation_cycles_before_pressure():
            data["pressure_level"] = min(_max_pressure_level(), float(data.get("pressure_level", 1.0)) + _pressure_ramp_step())
    _save(data)
    return data


def candidate_count_for_cycle() -> int:
    data = _load()
    level = float(data.get("pressure_level", 1.0))
    base = base_candidates_per_cycle()
    mx = max_candidates_per_cycle()
    count = int(min(mx, max(base, round(base * level))))
    return count


def boost_pressure_level(*, level: float = 2.5) -> dict:
    """Kickstart aggressive evolution (used by enable script)."""
    data = _load()
    data["pressure_level"] = min(_max_pressure_level(), max(float(data.get("pressure_level", 1.0)), level))
    _save(data)
    return get_pressure_state()


def get_pressure_state() -> dict:
    data = _load()
    return {
        "stagnation_cycles": data.get("stagnation_cycles", 0),
        "pressure_level": data.get("pressure_level", 1.0),
        "candidate_count_next": candidate_count_for_cycle(),
        "last_promotion_generation": data.get("last_promotion_generation", 0),
    }
