"""Calibrated confidence aggregation without trusting model self-report alone."""
from __future__ import annotations

from doofus.metacognition.state import ConfidenceEstimate


def clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def behavioral_confidence(successes: int, trials: int) -> float:
    if successes < 0 or trials < 0 or successes > trials:
        raise ValueError(f"Invalid behavioral evidence: successes={successes}, trials={trials}")
    return clamp_probability((successes + 1.0) / (trials + 2.0))


def evidential_confidence(passed_checks: int, total_checks: int, disagreement: float) -> float:
    if passed_checks < 0 or total_checks < 0 or passed_checks > total_checks:
        raise ValueError(
            f"Invalid evidential counts: passed_checks={passed_checks}, total_checks={total_checks}"
        )
    evidence_rate = (passed_checks + 1.0) / (total_checks + 2.0)
    return clamp_probability(evidence_rate * (1.0 - 0.5 * clamp_probability(disagreement)))


def aggregate_confidence(
    model_confidence: float,
    behavioral_value: float,
    evidential_value: float,
) -> ConfidenceEstimate:
    model = clamp_probability(model_confidence)
    behavioral = clamp_probability(behavioral_value)
    evidential = clamp_probability(evidential_value)
    disagreement_penalty = (max(model, behavioral, evidential) - min(model, behavioral, evidential)) * 0.25
    final_control = clamp_probability(
        model * 0.15 + behavioral * 0.35 + evidential * 0.50 - disagreement_penalty
    )
    return ConfidenceEstimate(
        model=model,
        behavioral=behavioral,
        evidential=evidential,
        final_control=final_control,
    )
