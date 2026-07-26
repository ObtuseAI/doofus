"""Typed contracts for metacognitive monitoring, prediction, and control."""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ControlAction(StrEnum):
    CONTINUE = "continue"
    INTENSIFY = "intensify"
    DIVERSIFY = "diversify"
    NARROW = "narrow"
    RESEARCH = "research"
    REPLAY = "replay"
    ESCALATE = "escalate"
    ABSTAIN = "abstain"
    TERMINATE = "terminate"


class KnowledgeBoundaryState(StrEnum):
    KNOWN = "known"
    PARTIALLY_KNOWN = "partially_known"
    UNKNOWN = "unknown"
    OUTSIDE_AUTHORITY = "outside_authority"


class FitnessPrediction(BaseModel):
    model_config = ConfigDict(frozen=True)

    mean: float = Field(ge=0.0, le=1.0)
    interval_low: float = Field(ge=0.0, le=1.0)
    interval_high: float = Field(ge=0.0, le=1.0)
    probability_of_non_regression: float = Field(ge=0.0, le=1.0)


class UncertaintyEstimate(BaseModel):
    model_config = ConfigDict(frozen=True)

    epistemic: float = Field(ge=0.0, le=1.0)
    aleatoric: float = Field(ge=0.0, le=1.0)
    measurement: float = Field(ge=0.0, le=1.0)


class ConfidenceEstimate(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: float = Field(ge=0.0, le=1.0)
    behavioral: float = Field(ge=0.0, le=1.0)
    evidential: float = Field(ge=0.0, le=1.0)
    final_control: float = Field(ge=0.0, le=1.0)


class ProgressSignals(BaseModel):
    model_config = ConfigDict(frozen=True)

    velocity: float
    acceleration: float
    novelty_rate: float = Field(ge=0.0, le=1.0)
    duplicate_rate: float = Field(ge=0.0, le=1.0)
    invalid_candidate_rate: float = Field(ge=0.0, le=1.0)
    regression_rate: float = Field(ge=0.0, le=1.0)
    fitness_variance: float = Field(ge=0.0)
    arena_disagreement: float = Field(ge=0.0, le=1.0)
    model_disagreement: float = Field(ge=0.0, le=1.0)
    resource_burn_per_fitness_unit: float = Field(ge=0.0)


class StrategyAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_id: str
    algorithm_ids: tuple[str, ...]
    predicted_gain: float
    calibrated_confidence: float = Field(ge=0.0, le=1.0)
    transfer_probability: float = Field(ge=0.0, le=1.0)
    information_gain: float = Field(ge=0.0)
    compute_cost: float = Field(ge=0.0)
    regression_risk: float = Field(ge=0.0, le=1.0)
    uncertainty_penalty: float = Field(ge=0.0)
    utility: float
    executable: bool


class ResourceAllocation(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_calls: int = Field(ge=0)
    candidates: int = Field(ge=0)
    arena_repetitions: int = Field(ge=0)
    stronger_model_escalations: int = Field(ge=0)
    simulation_depth: int = Field(ge=0)
    replay_depth: int = Field(ge=0)
    reviewer_count: int = Field(ge=0)
    wall_clock_seconds: int = Field(ge=0)
    early_termination_allowed: bool


class MetacognitiveState(BaseModel):
    model_config = ConfigDict(frozen=True)

    target_id: str
    generation: int = Field(ge=0)
    mode: str
    task_difficulty: float = Field(ge=0.0, le=1.0)
    knowledge_boundary_score: float = Field(ge=0.0, le=1.0)
    knowledge_boundary: KnowledgeBoundaryState
    expected_improvability: float = Field(ge=0.0, le=1.0)
    search_saturation: float = Field(ge=0.0, le=1.0)
    strategy_confidence: float = Field(ge=0.0, le=1.0)
    fitness_prediction: FitnessPrediction
    uncertainty: UncertaintyEstimate
    confidence: ConfidenceEstimate
    progress: ProgressSignals
    selected_strategy: StrategyAssessment
    alternative_strategies: tuple[StrategyAssessment, ...]
    resource_allocation: ResourceAllocation
    recommended_control: ControlAction
    authority_eligible: bool
    policy_version: str
    created_at: str


class ControlDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    target_id: str
    generation: int = Field(ge=0)
    recommendation: ControlAction
    reasons: tuple[str, ...]
    selected_strategy: str
    algorithm_portfolio: dict[str, float]
    requested_allocation: ResourceAllocation
    authorized_allocation: ResourceAllocation
    authorized: bool
    authority_reason: str
    mode: str
    policy_version: str
    created_at: str
