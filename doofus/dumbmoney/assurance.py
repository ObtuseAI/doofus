"""Consequence-proportional assurance policy for research candidates."""
from __future__ import annotations

from .contracts import AssuranceLevel, ConsequenceProfileV1

ASSURANCE_ORDER = (
    AssuranceLevel.IDEA,
    AssuranceLevel.REPLAY,
    AssuranceLevel.SHADOW,
    AssuranceLevel.EXPLORATORY_LIVE,
    AssuranceLevel.SCALED_LIVE,
)


def assurance_rank(level: AssuranceLevel) -> int:
    return ASSURANCE_ORDER.index(level)


def minimum_assurance(
    left: AssuranceLevel,
    right: AssuranceLevel,
) -> AssuranceLevel:
    return left if assurance_rank(left) <= assurance_rank(right) else right


def required_assurance(profile: ConsequenceProfileV1) -> AssuranceLevel:
    """Map possible consequence to evidence strength without granting authority."""

    loss = profile.maximum_external_loss_cents
    if profile.irreversible_change or loss > 100_000:
        return AssuranceLevel.SCALED_LIVE
    if profile.live_execution_relevance:
        return (
            AssuranceLevel.EXPLORATORY_LIVE
            if loss <= 25_000
            else AssuranceLevel.SCALED_LIVE
        )
    if profile.external_side_effects:
        return AssuranceLevel.SHADOW if loss <= 25_000 else AssuranceLevel.EXPLORATORY_LIVE
    if loss == 0:
        return AssuranceLevel.IDEA
    if loss <= 2_500:
        return AssuranceLevel.REPLAY
    return AssuranceLevel.SHADOW
