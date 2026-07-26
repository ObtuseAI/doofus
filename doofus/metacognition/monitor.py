"""Build an empirical cognitive state from Doofus runtime evidence."""
from __future__ import annotations

import json
import math
from statistics import fmean

from pydantic import BaseModel, ConfigDict, Field

from doofus.config.metacognition_config import int_setting, metacognition_mode
from doofus.core.doofus_events import utc_now
from doofus.core.metrics_db import metrics_conn
from doofus.evolution.adaptive_mutation_pressure import get_pressure_state
from doofus.metacognition.abstention import evaluate_abstention
from doofus.metacognition.confidence import (
    aggregate_confidence,
    behavioral_confidence,
    clamp_probability,
    evidential_confidence,
)
from doofus.metacognition.difficulty_model import DifficultySignals, estimate_difficulty
from doofus.metacognition.knowledge_boundary import KnowledgeSignals, classify_boundary
from doofus.metacognition.meta_evolution import MetaPolicy, get_active_meta_policy
from doofus.metacognition.progress_model import estimate_progress, estimate_search_saturation
from doofus.metacognition.resource_allocator import allocate_resources
from doofus.metacognition.state import (
    ControlAction,
    FitnessPrediction,
    MetacognitiveState,
    UncertaintyEstimate,
)
from doofus.metacognition.strategy_selector import StrategyContext, rank_strategies
from doofus.supervisor.doofus_crash_recovery import load_checkpoint


class MonitorEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    baseline_fitness: float = Field(ge=0.0, le=1.0)
    score_history: tuple[float, ...]
    novelty_keys: tuple[str, ...]
    evaluated_count: int = Field(ge=0)
    invalid_count: int = Field(ge=0)
    historical_successes: int = Field(ge=0)
    historical_trials: int = Field(ge=0)
    passed_checks: int = Field(ge=0)
    total_checks: int = Field(ge=0)
    archive_cell_count: int = Field(ge=0)
    capsule_count: int = Field(ge=0)
    arena_disagreement: float = Field(ge=0.0, le=1.0)
    model_disagreement: float = Field(ge=0.0, le=1.0)
    model_confidence: float = Field(ge=0.0, le=1.0)
    resource_cost: float = Field(ge=0.0)
    generation: int = Field(ge=0)
    stagnation_cycles: int = Field(ge=0)


def _json_signature(raw: object) -> str:
    if raw is None:
        return "none"
    try:
        value = json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return str(raw)
    if isinstance(value, list):
        return "|".join(sorted(str(item) for item in value))
    return json.dumps(value, sort_keys=True, default=str)


def _arena_disagreement(rows: list[tuple[str, float]]) -> float:
    by_candidate: dict[str, list[float]] = {}
    for candidate_id, score in rows:
        by_candidate.setdefault(candidate_id, []).append(float(score))
    spreads = [max(scores) - min(scores) for scores in by_candidate.values() if len(scores) > 1]
    return clamp_probability(fmean(spreads) if spreads else 0.0)


def collect_evidence() -> MonitorEvidence:
    checkpoint = load_checkpoint()
    pressure = get_pressure_state()
    with metrics_conn() as conn:
        generation_rows = conn.execute(
            """SELECT generation, AVG(score_total), MAX(score_total), COUNT(*),
                      SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END)
               FROM candidates GROUP BY generation ORDER BY generation DESC LIMIT 20"""
        ).fetchall()
        generation_rows.reverse()
        candidate_rows = conn.execute(
            "SELECT traits FROM candidates ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
        prediction_counts = conn.execute(
            """SELECT COUNT(*), COALESCE(SUM(actual_non_regression), 0)
               FROM metacognitive_predictions WHERE resolved_at IS NOT NULL"""
        ).fetchone()
        promotion_count = int(conn.execute("SELECT COUNT(*) FROM promotions").fetchone()[0])
        arena_counts = conn.execute(
            """SELECT COUNT(*), COALESCE(SUM(CASE WHEN result LIKE 'pass%' THEN 1 ELSE 0 END), 0)
               FROM arena_results"""
        ).fetchone()
        arena_rows = conn.execute(
            """SELECT candidate_id, COALESCE(score, 0.0) FROM arena_results
               ORDER BY id DESC LIMIT 200"""
        ).fetchall()
        model_counts = conn.execute(
            """SELECT COUNT(*), COALESCE(SUM(success), 0)
               FROM model_call_events WHERE attempted = 1"""
        ).fetchone()
        archive_cell_count = int(conn.execute("SELECT COUNT(*) FROM map_elites_cells").fetchone()[0])
        capsule_count = int(conn.execute("SELECT COUNT(*) FROM gep_capsules").fetchone()[0])
        resource_cost = float(
            conn.execute("SELECT COALESCE(SUM(cost_est), 0.0) FROM model_calls").fetchone()[0]
        )
    score_history = tuple(float(row[2] or row[1] or 0.0) for row in generation_rows)
    evaluated_count = sum(int(row[3] or 0) for row in generation_rows)
    invalid_count = sum(int(row[4] or 0) for row in generation_rows)
    historical_trials = int(prediction_counts[0] or 0)
    historical_successes = int(prediction_counts[1] or 0)
    if historical_trials == 0:
        historical_trials = max(0, len(generation_rows))
        historical_successes = min(historical_trials, promotion_count)
    total_checks = int(arena_counts[0] or 0)
    passed_checks = int(arena_counts[1] or 0)
    model_trials = int(model_counts[0] or 0)
    model_successes = int(model_counts[1] or 0)
    model_value = behavioral_confidence(model_successes, model_trials) if model_trials else 0.50
    baseline = float(checkpoint.get("baseline_score", 0.5))
    next_generation = int(checkpoint.get("generation", 0)) + 1
    return MonitorEvidence(
        baseline_fitness=clamp_probability(baseline),
        score_history=score_history,
        novelty_keys=tuple(_json_signature(row[0]) for row in candidate_rows),
        evaluated_count=evaluated_count,
        invalid_count=min(invalid_count, evaluated_count),
        historical_successes=min(historical_successes, historical_trials),
        historical_trials=historical_trials,
        passed_checks=min(passed_checks, total_checks),
        total_checks=total_checks,
        archive_cell_count=archive_cell_count,
        capsule_count=capsule_count,
        arena_disagreement=_arena_disagreement(arena_rows),
        model_disagreement=clamp_probability(1.0 - model_value),
        model_confidence=model_value,
        resource_cost=max(0.0, resource_cost),
        generation=next_generation,
        stagnation_cycles=int(pressure.get("stagnation_cycles", 0)),
    )


def _recommended_action(
    policy: MetaPolicy,
    selected_strategy: str,
    fitness_noise: float,
    search_saturation: float,
    velocity: float,
    regression_rate: float,
) -> ControlAction:
    if selected_strategy in {"research_first", "adversarial_testing"}:
        return ControlAction.RESEARCH
    if selected_strategy in {"architecture_mutation", "program_synthesis"}:
        return ControlAction.ESCALATE
    if fitness_noise >= policy.replay_noise_threshold:
        return ControlAction.REPLAY
    if search_saturation >= policy.diversify_saturation_threshold:
        return ControlAction.DIVERSIFY
    if regression_rate >= policy.narrow_regression_threshold:
        return ControlAction.NARROW
    if velocity >= policy.intensify_velocity_threshold:
        return ControlAction.INTENSIFY
    return ControlAction.CONTINUE


def monitor_evolution(target_id: str, authority_eligible: bool) -> tuple[MetacognitiveState, MonitorEvidence]:
    evidence = collect_evidence()
    progress = estimate_progress(
        list(evidence.score_history),
        list(evidence.novelty_keys),
        evidence.invalid_count,
        evidence.evaluated_count,
        evidence.arena_disagreement,
        evidence.model_disagreement,
        evidence.resource_cost,
    )
    saturation = estimate_search_saturation(progress, evidence.stagnation_cycles)
    behavioral = behavioral_confidence(evidence.historical_successes, evidence.historical_trials)
    evidential = evidential_confidence(
        evidence.passed_checks,
        evidence.total_checks,
        evidence.arena_disagreement,
    )
    confidence = aggregate_confidence(evidence.model_confidence, behavioral, evidential)
    evidence_density = clamp_probability((evidence.historical_trials + evidence.total_checks) / 100.0)
    fitness_noise = clamp_probability(math.sqrt(progress.fitness_variance) * 5.0)
    uncertainty = UncertaintyEstimate(
        epistemic=clamp_probability(1.0 - evidence_density),
        aleatoric=fitness_noise,
        measurement=clamp_probability((evidence.arena_disagreement + progress.invalid_candidate_rate) / 2.0),
    )
    archive_evidence = clamp_probability((evidence.archive_cell_count + evidence.capsule_count) / 80.0)
    difficulty = estimate_difficulty(
        DifficultySignals(
            archive_dissimilarity=1.0 - archive_evidence,
            code_novelty=uncertainty.epistemic,
            dependency_uncertainty=progress.invalid_candidate_rate,
            fitness_noise=fitness_noise,
            previous_failure_rate=progress.regression_rate,
            arena_disagreement=evidence.arena_disagreement,
            evidence_sparsity=1.0 - evidence_density,
        )
    )
    boundary, boundary_value = classify_boundary(
        KnowledgeSignals(
            archive_similarity=archive_evidence,
            applicable_capsule_rate=clamp_probability(evidence.capsule_count / 30.0),
            target_familiarity=clamp_probability(evidence.historical_trials / 30.0),
            historical_success_rate=behavioral,
            benchmark_stability=1.0 - fitness_noise,
            model_agreement=1.0 - evidence.model_disagreement,
            authority_eligible=authority_eligible,
        )
    )
    improvability = clamp_probability(
        behavioral * 0.35
        + (1.0 - saturation) * 0.35
        + boundary_value * 0.20
        + uncertainty.epistemic * 0.10
    )
    strategies = rank_strategies(
        StrategyContext(
            difficulty=difficulty,
            expected_improvability=improvability,
            search_saturation=saturation,
            confidence=confidence.final_control,
            transfer_probability=boundary_value,
            uncertainty=uncertainty,
            boundary=boundary,
            regression_rate=progress.regression_rate,
            fitness_noise=fitness_noise,
        )
    )
    selected = strategies[0]
    meta_policy = get_active_meta_policy()
    action = _recommended_action(
        meta_policy,
        selected.strategy_id,
        fitness_noise,
        saturation,
        progress.velocity,
        progress.regression_rate,
    )
    abstention = evaluate_abstention(
        boundary,
        confidence.final_control,
        improvability,
        saturation,
        selected.utility,
    )
    if abstention.should_abstain:
        action = abstention.action
    allocation = allocate_resources(
        uncertainty,
        improvability,
        saturation,
        fitness_noise,
        action,
        int_setting("DOOFUS_METACOGNITION_MIN_CANDIDATES"),
        int_setting("DOOFUS_METACOGNITION_MAX_CANDIDATES"),
        int_setting("DOOFUS_METACOGNITION_MAX_ARENA_REPETITIONS"),
        int_setting("DOOFUS_METACOGNITION_MAX_REPLAY_DEPTH"),
    )
    predicted_gain = selected.predicted_gain * confidence.final_control
    interval_width = 0.015 + uncertainty.epistemic * 0.05 + uncertainty.aleatoric * 0.05
    predicted_fitness = clamp_probability(evidence.baseline_fitness + predicted_gain)
    return MetacognitiveState(
        target_id=target_id,
        generation=evidence.generation,
        mode=metacognition_mode(),
        task_difficulty=difficulty,
        knowledge_boundary_score=boundary_value,
        knowledge_boundary=boundary,
        expected_improvability=improvability,
        search_saturation=saturation,
        strategy_confidence=confidence.final_control,
        fitness_prediction=FitnessPrediction(
            mean=predicted_fitness,
            interval_low=clamp_probability(predicted_fitness - interval_width),
            interval_high=clamp_probability(predicted_fitness + interval_width),
            probability_of_non_regression=clamp_probability(
                confidence.final_control * (1.0 - selected.regression_risk) + behavioral * 0.35
            ),
        ),
        uncertainty=uncertainty,
        confidence=confidence,
        progress=progress,
        selected_strategy=selected,
        alternative_strategies=strategies[1:5],
        resource_allocation=allocation,
        recommended_control=action,
        authority_eligible=authority_eligible,
        policy_version=meta_policy.policy_id,
        created_at=utc_now(),
    ), evidence
