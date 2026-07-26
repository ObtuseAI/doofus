"""Classify whether an evolutionary task lies inside the evidence boundary."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from doofus.metacognition.confidence import clamp_probability
from doofus.metacognition.state import KnowledgeBoundaryState


class KnowledgeSignals(BaseModel):
    model_config = ConfigDict(frozen=True)

    archive_similarity: float = Field(ge=0.0, le=1.0)
    applicable_capsule_rate: float = Field(ge=0.0, le=1.0)
    target_familiarity: float = Field(ge=0.0, le=1.0)
    historical_success_rate: float = Field(ge=0.0, le=1.0)
    benchmark_stability: float = Field(ge=0.0, le=1.0)
    model_agreement: float = Field(ge=0.0, le=1.0)
    authority_eligible: bool


def boundary_score(signals: KnowledgeSignals) -> float:
    return clamp_probability(
        signals.archive_similarity * 0.20
        + signals.applicable_capsule_rate * 0.15
        + signals.target_familiarity * 0.20
        + signals.historical_success_rate * 0.20
        + signals.benchmark_stability * 0.15
        + signals.model_agreement * 0.10
    )


def classify_boundary(signals: KnowledgeSignals) -> tuple[KnowledgeBoundaryState, float]:
    score = boundary_score(signals)
    if not signals.authority_eligible:
        return KnowledgeBoundaryState.OUTSIDE_AUTHORITY, score
    if score >= 0.72:
        return KnowledgeBoundaryState.KNOWN, score
    if score >= 0.38:
        return KnowledgeBoundaryState.PARTIALLY_KNOWN, score
    return KnowledgeBoundaryState.UNKNOWN, score
