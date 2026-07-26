"""Independent evidence roles and deterministic metacognitive decision merger."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from doofus.metacognition.state import ControlAction, MetacognitiveState


class CouncilContribution(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: str
    supported_action: ControlAction
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: tuple[str, ...]


class CouncilVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: ControlAction
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: tuple[str, ...]
    contributions: tuple[CouncilContribution, ...]


def introspector_contribution(state: MetacognitiveState) -> CouncilContribution:
    return CouncilContribution(
        role="introspector",
        supported_action=state.recommended_control,
        confidence=state.confidence.model,
        evidence=(
            f"selected_strategy={state.selected_strategy.strategy_id}",
            f"model_confidence={state.confidence.model:.4f}",
        ),
    )


def empiricist_contribution(state: MetacognitiveState) -> CouncilContribution:
    action = state.recommended_control
    if state.progress.fitness_variance >= 0.02:
        action = ControlAction.REPLAY
    return CouncilContribution(
        role="empiricist",
        supported_action=action,
        confidence=state.confidence.evidential,
        evidence=(
            f"velocity={state.progress.velocity:.6f}",
            f"fitness_variance={state.progress.fitness_variance:.6f}",
            f"evidential_confidence={state.confidence.evidential:.4f}",
        ),
    )


def skeptic_contribution(state: MetacognitiveState) -> CouncilContribution:
    action = state.recommended_control
    if state.knowledge_boundary.value == "outside_authority":
        action = ControlAction.ABSTAIN
    elif state.uncertainty.measurement >= 0.45:
        action = ControlAction.REPLAY
    elif state.search_saturation >= 0.75:
        action = ControlAction.DIVERSIFY
    confidence = max(
        state.uncertainty.epistemic,
        state.uncertainty.measurement,
        state.progress.regression_rate,
    )
    return CouncilContribution(
        role="skeptic",
        supported_action=action,
        confidence=confidence,
        evidence=(
            f"epistemic_uncertainty={state.uncertainty.epistemic:.4f}",
            f"measurement_uncertainty={state.uncertainty.measurement:.4f}",
            f"regression_rate={state.progress.regression_rate:.4f}",
        ),
    )


def controller_contribution(state: MetacognitiveState) -> CouncilContribution:
    return CouncilContribution(
        role="controller",
        supported_action=state.recommended_control,
        confidence=state.confidence.final_control,
        evidence=(
            f"expected_improvability={state.expected_improvability:.4f}",
            f"strategy_utility={state.selected_strategy.utility:.6f}",
            f"allocated_candidates={state.resource_allocation.candidates}",
        ),
    )


def merge_council(state: MetacognitiveState) -> CouncilVerdict:
    contributions = (
        introspector_contribution(state),
        empiricist_contribution(state),
        skeptic_contribution(state),
        controller_contribution(state),
    )
    weights: dict[ControlAction, float] = {}
    for contribution in contributions:
        weights[contribution.supported_action] = (
            weights.get(contribution.supported_action, 0.0) + contribution.confidence
        )
    action = max(weights, key=weights.get)
    confidence = weights[action] / max(
        sum(contribution.confidence for contribution in contributions),
        0.001,
    )
    reasons = tuple(
        evidence
        for contribution in contributions
        if contribution.supported_action == action
        for evidence in contribution.evidence
    )
    return CouncilVerdict(
        action=action,
        confidence=max(0.0, min(1.0, confidence)),
        reasons=reasons,
        contributions=contributions,
    )
