"""Outermost loop for held-out evolution of the metacognitive controller."""
from __future__ import annotations

from doofus.metacognition.meta_evolution import evolve_meta_policy, get_active_meta_policy


def run_meta_metacognitive_cycle(target_id: str) -> dict[str, object]:
    return evolve_meta_policy(target_id)


def get_meta_metacognitive_snapshot() -> dict[str, object]:
    return {
        "classification": "META_METACOGNITION_EXPERIMENTAL",
        "active_policy": get_active_meta_policy().model_dump(),
        "safety_surface_mutable": False,
        "promotion_requires_held_out_improvement": True,
    }
