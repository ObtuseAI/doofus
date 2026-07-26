"""Shared, mutation-authority-neutral evidence contract for research systems."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MetricEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    baseline: float
    candidate: float
    delta: float
    direction: Literal["higher_is_better", "lower_is_better"] = "higher_is_better"


class ResearchEvidence(BaseModel):
    """Portable result envelope; it never grants another system write access."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    evidence_id: str
    producer: str
    domain: Literal["code_parameter_evolution", "cognitive_method_evolution", "other"]
    generated_at: str
    subject_ref: str
    evaluation_ref: str
    isolation_verified: bool
    mutation_authority: Literal["producer_only"] = "producer_only"
    metrics: tuple[MetricEvidence, ...]
    artifacts: tuple[str, ...] = ()
    notes: dict[str, Any] = Field(default_factory=dict)
