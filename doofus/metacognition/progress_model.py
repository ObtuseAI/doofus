"""Pure progress and saturation estimators for evolutionary histories."""
from __future__ import annotations

from statistics import fmean, pvariance

from doofus.metacognition.confidence import clamp_probability
from doofus.metacognition.state import ProgressSignals


def _deltas(values: list[float]) -> list[float]:
    return [float(current) - float(previous) for previous, current in zip(values, values[1:])]


def estimate_progress(
    score_history: list[float],
    novelty_keys: list[str],
    invalid_count: int,
    evaluated_count: int,
    arena_disagreement: float,
    model_disagreement: float,
    resource_cost: float,
) -> ProgressSignals:
    if invalid_count < 0 or evaluated_count < 0 or invalid_count > evaluated_count:
        raise ValueError(
            f"Invalid progress counts: invalid_count={invalid_count}, evaluated_count={evaluated_count}"
        )
    recent_scores = [float(value) for value in score_history[-12:]]
    deltas = _deltas(recent_scores)
    recent_deltas = deltas[-5:]
    velocity = fmean(recent_deltas) if recent_deltas else 0.0
    delta_changes = _deltas(recent_deltas)
    acceleration = fmean(delta_changes) if delta_changes else 0.0
    regressions = sum(1 for value in deltas if value < 0.0)
    regression_rate = regressions / len(deltas) if deltas else 0.0
    duplicate_rate = 0.0
    novelty_rate = 0.0
    if novelty_keys:
        unique_rate = len(set(novelty_keys)) / len(novelty_keys)
        novelty_rate = clamp_probability(unique_rate)
        duplicate_rate = clamp_probability(1.0 - unique_rate)
    invalid_rate = invalid_count / evaluated_count if evaluated_count else 0.0
    positive_gain = sum(max(0.0, value) for value in deltas)
    burn = max(0.0, float(resource_cost)) / max(positive_gain, 0.001)
    return ProgressSignals(
        velocity=velocity,
        acceleration=acceleration,
        novelty_rate=novelty_rate,
        duplicate_rate=duplicate_rate,
        invalid_candidate_rate=clamp_probability(invalid_rate),
        regression_rate=clamp_probability(regression_rate),
        fitness_variance=pvariance(recent_scores) if len(recent_scores) > 1 else 0.0,
        arena_disagreement=clamp_probability(arena_disagreement),
        model_disagreement=clamp_probability(model_disagreement),
        resource_burn_per_fitness_unit=burn,
    )


def estimate_search_saturation(progress: ProgressSignals, stagnation_cycles: int) -> float:
    stagnation = clamp_probability(stagnation_cycles / 20.0)
    flat_velocity = clamp_probability(1.0 - min(abs(progress.velocity) / 0.02, 1.0))
    collapse = clamp_probability(
        progress.duplicate_rate * 0.45
        + (1.0 - progress.novelty_rate) * 0.25
        + flat_velocity * 0.20
        + stagnation * 0.10
    )
    return collapse
