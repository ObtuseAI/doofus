"""Deterministic scoring for Doofus improvement items."""
from __future__ import annotations

from doofus.self_improvement.improvement_item import ImprovementItem

TYPE_WEIGHT = {
    "guard_pattern": 88,
    "repair_recipe": 85,
    "proof_builder_improvement": 84,
    "mutation_method": 80,
    "telemetry_improvement": 75,
    "scoring_improvement": 74,
    "cycle_quality_improvement": 72,
    "runtime_isolation_improvement": 70,
    "artifact_feed_improvement": 65,
    "operator_packet_improvement": 60,
}

RISK_PENALTY = {"low": 0, "medium": 12, "high": 28}
VALUE_BONUS = {"low": 5, "medium": 15, "high": 25}


def score_item(item: ImprovementItem) -> int:
    base = TYPE_WEIGHT.get(item.type, 50)
    risk = RISK_PENALTY.get(item.risk_level, 10)
    value = VALUE_BONUS.get(item.expected_value, 10)
    artifact_bonus = min(10, len(item.source_artifacts) * 2)
    test_bonus = min(8, len(item.required_tests) * 2)
    blocked_penalty = min(15, len(item.blocked_by) * 5)
    score = base + value + artifact_bonus + test_bonus - risk - blocked_penalty
    return max(0, min(100, int(score)))


def apply_scores(items: list[ImprovementItem]) -> list[ImprovementItem]:
    for item in items:
        item.score = score_item(item)
    return items
