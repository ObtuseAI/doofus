"""Calibration metrics for metacognitive predictions."""
from __future__ import annotations

import math
from statistics import fmean

from pydantic import BaseModel, ConfigDict, Field

from doofus.config.metacognition_config import int_setting
from doofus.core.metrics_db import metrics_conn


class CalibrationObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    predicted_probability: float = Field(ge=0.0, le=1.0)
    actual_outcome: bool
    predicted_fitness: float = Field(ge=0.0, le=1.0)
    actual_fitness: float = Field(ge=0.0, le=1.0)
    interval_low: float = Field(ge=0.0, le=1.0)
    interval_high: float = Field(ge=0.0, le=1.0)
    recommended_action: str


class CalibrationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    sample_count: int = Field(ge=0)
    brier_score: float = Field(ge=0.0, le=1.0)
    expected_calibration_error: float = Field(ge=0.0, le=1.0)
    confidence_fitness_correlation: float = Field(ge=-1.0, le=1.0)
    confidence_promotion_precision: float = Field(ge=0.0, le=1.0)
    false_confidence_rate: float = Field(ge=0.0, le=1.0)
    abstention_quality: float = Field(ge=0.0, le=1.0)
    prediction_interval_coverage: float = Field(ge=0.0, le=1.0)
    experimental: bool


def brier_score(observations: list[CalibrationObservation]) -> float:
    if not observations:
        return 0.0
    return fmean(
        (observation.predicted_probability - float(observation.actual_outcome)) ** 2
        for observation in observations
    )


def expected_calibration_error(observations: list[CalibrationObservation], bin_count: int) -> float:
    if bin_count <= 0:
        raise ValueError(f"bin_count must be positive, received {bin_count}")
    if not observations:
        return 0.0
    total = len(observations)
    error = 0.0
    for index in range(bin_count):
        low = index / bin_count
        high = (index + 1) / bin_count
        bucket = [
            observation
            for observation in observations
            if low <= observation.predicted_probability < high
            or (index == bin_count - 1 and observation.predicted_probability == 1.0)
        ]
        if not bucket:
            continue
        confidence = fmean(observation.predicted_probability for observation in bucket)
        accuracy = fmean(float(observation.actual_outcome) for observation in bucket)
        error += len(bucket) / total * abs(confidence - accuracy)
    return error


def _correlation(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2 or len(xs) != len(ys):
        return 0.0
    mean_x = fmean(xs)
    mean_y = fmean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    denominator_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if denominator_x == 0.0 or denominator_y == 0.0:
        return 0.0
    return max(-1.0, min(1.0, numerator / (denominator_x * denominator_y)))


def summarize_calibration(observations: list[CalibrationObservation]) -> CalibrationSummary:
    confident = [observation for observation in observations if observation.predicted_probability >= 0.70]
    false_confident = [observation for observation in confident if not observation.actual_outcome]
    abstentions = [
        observation
        for observation in observations
        if observation.recommended_action in {"abstain", "terminate", "research"}
    ]
    useful_abstentions = [observation for observation in abstentions if not observation.actual_outcome]
    covered = [
        observation
        for observation in observations
        if observation.interval_low <= observation.actual_fitness <= observation.interval_high
    ]
    return CalibrationSummary(
        sample_count=len(observations),
        brier_score=brier_score(observations),
        expected_calibration_error=expected_calibration_error(observations, 10),
        confidence_fitness_correlation=_correlation(
            [observation.predicted_probability for observation in observations],
            [observation.actual_fitness for observation in observations],
        ),
        confidence_promotion_precision=(
            sum(1 for observation in confident if observation.actual_outcome) / len(confident)
            if confident
            else 0.0
        ),
        false_confidence_rate=len(false_confident) / len(confident) if confident else 0.0,
        abstention_quality=len(useful_abstentions) / len(abstentions) if abstentions else 0.0,
        prediction_interval_coverage=len(covered) / len(observations) if observations else 0.0,
        experimental=len(observations) < 100,
    )


def load_calibration_observations(target_id: str) -> list[CalibrationObservation]:
    window = int_setting("DOOFUS_METACOGNITION_CALIBRATION_WINDOW")
    with metrics_conn() as conn:
        rows = conn.execute(
            """SELECT probability_non_regression, actual_non_regression, predicted_fitness,
                      actual_fitness, interval_low, interval_high, recommended_action
               FROM metacognitive_predictions
               WHERE target_id = ? AND resolved_at IS NOT NULL
               ORDER BY created_at DESC LIMIT ?""",
            (target_id, window),
        ).fetchall()
    return [
        CalibrationObservation(
            predicted_probability=float(row[0]),
            actual_outcome=bool(row[1]),
            predicted_fitness=float(row[2]),
            actual_fitness=float(row[3]),
            interval_low=float(row[4]),
            interval_high=float(row[5]),
            recommended_action=str(row[6]),
        )
        for row in rows
    ]


def get_calibration_summary(target_id: str) -> CalibrationSummary:
    return summarize_calibration(load_calibration_observations(target_id))
