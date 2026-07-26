"""A-Evolve algorithm registry."""
from __future__ import annotations

from typing import Callable

ALGORITHMS: dict[str, dict] = {
    "trait_shuffle": {
        "name": "trait_shuffle",
        "description": "Standard trait mutation via mutation_engine",
        "weight": 1.0,
    },
    "model_guided": {
        "name": "model_guided",
        "description": "LLM-guided mutation (applied in loop runner)",
        "weight": 0.8,
    },
    "gene_crossover": {
        "name": "gene_crossover",
        "description": "GEP capsule gene crossover",
        "weight": 0.6,
    },
    "map_elites_niche": {
        "name": "map_elites_niche",
        "description": "Parent from MAP-Elites niche cell",
        "weight": 0.7,
    },
    "gepa_reflective": {
        "name": "gepa_reflective",
        "description": "GEPA-evolved prompt context",
        "weight": 0.5,
    },
}


def list_algorithms() -> list[str]:
    return list(ALGORITHMS.keys())


def get_algorithm(algorithm_id: str) -> dict | None:
    return ALGORITHMS.get(algorithm_id)


def update_weight(algorithm_id: str, weight: float) -> None:
    if algorithm_id in ALGORITHMS:
        ALGORITHMS[algorithm_id]["weight"] = max(0.1, weight)


def apply_env_weight_overrides() -> dict[str, float]:
    """Apply optional env-driven algorithm weights (e.g. cursor composer profile)."""
    import os

    applied: dict[str, float] = {}
    raw = os.environ.get("DOOFUS_MODEL_GUIDED_WEIGHT", "").strip()
    if raw:
        weight = max(0.1, float(raw))
        update_weight("model_guided", weight)
        applied["model_guided"] = weight
    return applied
