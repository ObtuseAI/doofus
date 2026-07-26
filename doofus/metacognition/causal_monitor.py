"""Noise-aware causal confidence for observed evolutionary gains."""
from __future__ import annotations

import math
from statistics import fmean, pvariance

from pydantic import BaseModel, ConfigDict, Field

from doofus.metacognition.confidence import clamp_probability


class CausalAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    observed_gain: float
    causal_confidence: float = Field(ge=0.0, le=1.0)
    noise_adjusted_gain: float
    replication_count: int = Field(ge=0)
    variance: float = Field(ge=0.0)
    environment_match: bool
    baseline_match: bool


def assess_causal_gain(
    observed_gain: float,
    replication_gains: list[float],
    environment_match: bool,
    baseline_match: bool,
) -> CausalAssessment:
    gains = [float(value) for value in replication_gains] or [float(observed_gain)]
    variance = pvariance(gains) if len(gains) > 1 else 0.0
    replication_support = min(1.0, max(0, len(gains) - 1) / 4.0)
    sign_agreement = (
        sum(1 for value in gains if (value >= 0.0) == (observed_gain >= 0.0)) / len(gains)
        if len(gains) > 1
        else 0.0
    )
    variance_penalty = min(1.0, math.sqrt(variance) / 0.05) if variance > 0.0 else 0.0
    causal_confidence = clamp_probability(
        0.05
        + replication_support * 0.35
        + sign_agreement * 0.25
        + float(environment_match) * 0.15
        + float(baseline_match) * 0.10
        - variance_penalty * 0.25
    )
    central_gain = fmean(gains)
    noise_adjusted = central_gain * causal_confidence
    return CausalAssessment(
        observed_gain=float(observed_gain),
        causal_confidence=causal_confidence,
        noise_adjusted_gain=noise_adjusted,
        replication_count=len(gains),
        variance=variance,
        environment_match=environment_match,
        baseline_match=baseline_match,
    )
