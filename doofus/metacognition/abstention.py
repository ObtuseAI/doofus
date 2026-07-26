"""Calibrated abstention and stop policy."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from doofus.metacognition.state import ControlAction, KnowledgeBoundaryState


class AbstentionDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    should_abstain: bool
    action: ControlAction
    reason: str


def evaluate_abstention(
    boundary: KnowledgeBoundaryState,
    control_confidence: float,
    expected_improvability: float,
    search_saturation: float,
    marginal_utility: float,
) -> AbstentionDecision:
    if boundary == KnowledgeBoundaryState.OUTSIDE_AUTHORITY:
        return AbstentionDecision(
            should_abstain=True,
            action=ControlAction.ABSTAIN,
            reason="target_outside_autonomous_authority",
        )
    if search_saturation >= 0.92 and marginal_utility <= 0.0:
        return AbstentionDecision(
            should_abstain=True,
            action=ControlAction.TERMINATE,
            reason="expected_marginal_value_exhausted",
        )
    if boundary == KnowledgeBoundaryState.UNKNOWN and control_confidence < 0.35:
        return AbstentionDecision(
            should_abstain=True,
            action=ControlAction.RESEARCH,
            reason="insufficient_evidence_inside_unknown_boundary",
        )
    if expected_improvability < 0.12 and control_confidence < 0.50:
        return AbstentionDecision(
            should_abstain=True,
            action=ControlAction.ABSTAIN,
            reason="low_expected_gain_and_low_control_confidence",
        )
    return AbstentionDecision(
        should_abstain=False,
        action=ControlAction.CONTINUE,
        reason="mutation_has_positive_evidence",
    )
