"""Falsifiable critique contracts instead of unscored reflective prose."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CritiquePrediction(BaseModel):
    model_config = ConfigDict(frozen=True)

    prediction: str
    gain_interval_low: float
    gain_interval_high: float
    probability_of_non_regression: float = Field(ge=0.0, le=1.0)
    likely_failure_mode: str
    required_disconfirmation_test: str
    recommended_budget: int = Field(ge=0)


class CritiqueScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    interval_hit: bool
    outcome_probability_error: float = Field(ge=0.0, le=1.0)
    disconfirmation_test_run: bool
    score: float = Field(ge=0.0, le=1.0)


def build_critique(
    expected_gain: float,
    uncertainty_width: float,
    probability_of_non_regression: float,
    fitness_noise: float,
    recommended_budget: int,
) -> CritiquePrediction:
    width = max(0.005, uncertainty_width)
    failure_mode = "benchmark_noise" if fitness_noise >= 0.35 else "benchmark_overfitting"
    disconfirmation_test = "counterfactual_replay" if fitness_noise >= 0.35 else "held_out_arena"
    return CritiquePrediction(
        prediction=f"noise-adjusted fitness gain in [{expected_gain - width:.4f}, {expected_gain + width:.4f}]",
        gain_interval_low=expected_gain - width,
        gain_interval_high=expected_gain + width,
        probability_of_non_regression=max(0.0, min(1.0, probability_of_non_regression)),
        likely_failure_mode=failure_mode,
        required_disconfirmation_test=disconfirmation_test,
        recommended_budget=recommended_budget,
    )


def score_critique(
    critique: CritiquePrediction,
    actual_gain: float,
    disconfirmation_test_run: bool,
) -> CritiqueScore:
    interval_hit = critique.gain_interval_low <= actual_gain <= critique.gain_interval_high
    actual_non_regression = actual_gain >= 0.0
    probability_error = abs(critique.probability_of_non_regression - float(actual_non_regression))
    score = (
        float(interval_hit) * 0.45
        + (1.0 - probability_error) * 0.40
        + float(disconfirmation_test_run) * 0.15
    )
    return CritiqueScore(
        interval_hit=interval_hit,
        outcome_probability_error=probability_error,
        disconfirmation_test_run=disconfirmation_test_run,
        score=max(0.0, min(1.0, score)),
    )
