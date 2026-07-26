"""Evidence-based task difficulty estimation."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from doofus.metacognition.confidence import clamp_probability


class DifficultySignals(BaseModel):
    model_config = ConfigDict(frozen=True)

    archive_dissimilarity: float = Field(ge=0.0, le=1.0)
    code_novelty: float = Field(ge=0.0, le=1.0)
    dependency_uncertainty: float = Field(ge=0.0, le=1.0)
    fitness_noise: float = Field(ge=0.0, le=1.0)
    previous_failure_rate: float = Field(ge=0.0, le=1.0)
    arena_disagreement: float = Field(ge=0.0, le=1.0)
    evidence_sparsity: float = Field(ge=0.0, le=1.0)


def estimate_difficulty(signals: DifficultySignals) -> float:
    return clamp_probability(
        signals.archive_dissimilarity * 0.20
        + signals.code_novelty * 0.15
        + signals.dependency_uncertainty * 0.15
        + signals.fitness_noise * 0.15
        + signals.previous_failure_rate * 0.15
        + signals.arena_disagreement * 0.10
        + signals.evidence_sparsity * 0.10
    )
