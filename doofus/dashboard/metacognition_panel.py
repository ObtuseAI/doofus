"""Dashboard snapshot for the metacognitive cortex and research gates."""
from __future__ import annotations

from doofus.arenas.metacognitive.evaluator import run_metacognitive_arenas
from doofus.config.metacognition_config import target_id
from doofus.meta.meta_metacognition import get_meta_metacognitive_snapshot
from doofus.metacognition.controller import get_metacognitive_snapshot


def get_metacognition_panel() -> dict[str, object]:
    current_target = target_id()
    return {
        "classification": "METACOGNITION_DASHBOARD_EXPERIMENTAL",
        "cortex": get_metacognitive_snapshot(current_target),
        "arenas": run_metacognitive_arenas(current_target),
        "meta_metacognition": get_meta_metacognitive_snapshot(),
    }
