"""Sense convergence, calibration, evaluation, and resource health."""
from __future__ import annotations

import math
from statistics import fmean

from pydantic import BaseModel, ConfigDict, Field

from doofus.core.doofus_config import DoofusConfig
from doofus.core.metrics_db import metrics_conn
from doofus.metacognition.confidence import clamp_probability
from doofus.safety.budget_guard import check_budget


class InteroceptiveState(BaseModel):
    model_config = ConfigDict(frozen=True)

    selection_pressure: float = Field(ge=0.0, le=1.0)
    archive_diversity: float = Field(ge=0.0, le=1.0)
    lineage_concentration: float = Field(ge=0.0, le=1.0)
    optimizer_oscillation: float = Field(ge=0.0, le=1.0)
    confidence_drift: float = Field(ge=0.0, le=1.0)
    evaluation_instability: float = Field(ge=0.0, le=1.0)
    resource_stress: float = Field(ge=0.0, le=1.0)
    model_dependency: float = Field(ge=0.0, le=1.0)
    capability_atrophy: float = Field(ge=0.0, le=1.0)
    diagnosis: str
    responses: tuple[str, ...]


def _lineage_concentration(parent_rows: list[tuple[str, int]]) -> float:
    total = sum(int(row[1]) for row in parent_rows)
    if total == 0:
        return 0.0
    return clamp_probability(max(int(row[1]) for row in parent_rows) / total)


def _optimizer_oscillation(scores: list[float]) -> float:
    deltas = [current - previous for previous, current in zip(scores, scores[1:])]
    if len(deltas) < 2:
        return 0.0
    sign_switches = sum(
        1
        for previous, current in zip(deltas, deltas[1:])
        if (previous >= 0.0) != (current >= 0.0)
    )
    return clamp_probability(sign_switches / (len(deltas) - 1))


def _diagnose(
    archive_diversity: float,
    lineage_concentration: float,
    confidence_drift: float,
    evaluation_instability: float,
    resource_stress: float,
    model_dependency: float,
    capability_atrophy: float,
) -> tuple[str, tuple[str, ...]]:
    if lineage_concentration >= 0.70 and archive_diversity <= 0.30:
        return "premature_convergence", (
            "reduce_elite_reproduction",
            "increase_novelty_weight",
            "inject_external_capsules_only_if_authorized",
        )
    if confidence_drift >= 0.35:
        return "confidence_drift", (
            "increase_calibration_weight",
            "require_replay_before_intensification",
        )
    if evaluation_instability >= 0.45:
        return "evaluation_instability", (
            "increase_re_evaluations",
            "hold_candidate_expansion",
        )
    if resource_stress >= 0.80:
        return "resource_stress", (
            "narrow_search",
            "preserve_hard_budget_caps",
        )
    if model_dependency >= 0.75:
        return "model_dependency", (
            "increase_non_model_strategy_share",
            "run_transfer_replay",
        )
    if capability_atrophy >= 0.70:
        return "capability_atrophy", (
            "diversify_strategy_portfolio",
            "replay_dormant_strategy_cases",
        )
    return "homeostasis_stable", ("continue_monitoring",)


def monitor_interoception() -> InteroceptiveState:
    with metrics_conn() as conn:
        candidate_count = int(conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0])
        promotion_count = int(conn.execute("SELECT COUNT(*) FROM promotions").fetchone()[0])
        cell_count = int(conn.execute("SELECT COUNT(*) FROM map_elites_cells").fetchone()[0])
        parent_rows = conn.execute(
            """SELECT parent_id, COUNT(*) FROM candidates
               WHERE parent_id IS NOT NULL GROUP BY parent_id ORDER BY COUNT(*) DESC LIMIT 100"""
        ).fetchall()
        score_rows = conn.execute(
            """SELECT MAX(score_total) FROM candidates
               GROUP BY generation ORDER BY generation DESC LIMIT 20"""
        ).fetchall()
        prediction_rows = conn.execute(
            """SELECT probability_non_regression, actual_non_regression
               FROM metacognitive_predictions WHERE resolved_at IS NOT NULL
               ORDER BY created_at DESC LIMIT 100"""
        ).fetchall()
        guided_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM candidates WHERE algorithm_id = 'model_guided'"
            ).fetchone()[0]
        ) if "algorithm_id" in {
            str(row[1]) for row in conn.execute("PRAGMA table_info(candidates)").fetchall()
        } else int(
            conn.execute(
                "SELECT COUNT(*) FROM candidates WHERE mutation_type LIKE 'model_guided%'"
            ).fetchone()[0]
        )
        algorithm_rows = conn.execute(
            "SELECT mutation_type, COUNT(*) FROM candidates GROUP BY mutation_type"
        ).fetchall()
    selection_pressure = 1.0 - promotion_count / max(candidate_count, 1)
    archive_diversity = clamp_probability(cell_count / max(min(candidate_count, 50), 1))
    confidence_drift = (
        fmean(abs(float(row[0]) - float(row[1])) for row in prediction_rows)
        if prediction_rows
        else 0.0
    )
    scores = [float(row[0] or 0.0) for row in reversed(score_rows)]
    evaluation_instability = clamp_probability(
        math.sqrt(fmean((score - fmean(scores)) ** 2 for score in scores)) * 5.0
        if len(scores) > 1
        else 0.0
    )
    budget = check_budget(DoofusConfig.from_env())
    call_ratio = float(budget.get("calls_last_hour", 0)) / max(float(budget.get("max_calls_per_hour", 1)), 1.0)
    cost_ratio = float(budget.get("daily_cost_est", 0.0)) / max(float(budget.get("max_daily_cost_usd", 1.0)), 0.001)
    resource_stress = clamp_probability(max(call_ratio, cost_ratio))
    model_dependency = clamp_probability(guided_count / max(candidate_count, 1))
    active_algorithms = sum(1 for row in algorithm_rows if int(row[1]) > 0)
    capability_atrophy = clamp_probability(1.0 - active_algorithms / 5.0)
    lineage_concentration = _lineage_concentration(parent_rows)
    diagnosis, responses = _diagnose(
        archive_diversity,
        lineage_concentration,
        confidence_drift,
        evaluation_instability,
        resource_stress,
        model_dependency,
        capability_atrophy,
    )
    return InteroceptiveState(
        selection_pressure=clamp_probability(selection_pressure),
        archive_diversity=archive_diversity,
        lineage_concentration=lineage_concentration,
        optimizer_oscillation=_optimizer_oscillation(scores),
        confidence_drift=clamp_probability(confidence_drift),
        evaluation_instability=evaluation_instability,
        resource_stress=resource_stress,
        model_dependency=model_dependency,
        capability_atrophy=capability_atrophy,
        diagnosis=diagnosis,
        responses=responses,
    )
