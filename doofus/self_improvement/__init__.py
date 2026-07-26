"""Doofus-native self-improvement kernel - local catalog, no live actions."""
from __future__ import annotations

from doofus.self_improvement.improvement_item import ImprovementItem, ALLOWED_STATUSES, ALLOWED_TYPES
from doofus.self_improvement.improvement_catalog import ImprovementCatalog
from doofus.self_improvement.improvement_scorer import score_item
from doofus.self_improvement.cycle_lesson_extractor import extract_lessons_from_artifacts
from doofus.self_improvement.next_cycle_seed_builder import build_seed_recommendations

__all__ = [
    "ImprovementItem",
    "ALLOWED_STATUSES",
    "ALLOWED_TYPES",
    "ImprovementCatalog",
    "score_item",
    "extract_lessons_from_artifacts",
    "build_seed_recommendations",
]
