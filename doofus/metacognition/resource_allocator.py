"""Allocate evolutionary resources from uncertainty, opportunity, and noise."""
from __future__ import annotations

from doofus.metacognition.state import ControlAction, ResourceAllocation, UncertaintyEstimate


def allocate_resources(
    uncertainty: UncertaintyEstimate,
    expected_improvability: float,
    search_saturation: float,
    fitness_noise: float,
    action: ControlAction,
    minimum_candidates: int,
    maximum_candidates: int,
    maximum_arena_repetitions: int,
    maximum_replay_depth: int,
) -> ResourceAllocation:
    if minimum_candidates < 0 or maximum_candidates < minimum_candidates:
        raise ValueError(
            f"Invalid candidate bounds: minimum={minimum_candidates}, maximum={maximum_candidates}"
        )
    if action in {ControlAction.ABSTAIN, ControlAction.TERMINATE, ControlAction.RESEARCH}:
        candidates = 0
    elif fitness_noise >= 0.45:
        candidates = minimum_candidates
    else:
        opportunity = max(0.0, min(1.0, expected_improvability))
        epistemic = uncertainty.epistemic
        fraction = 0.20 + 0.45 * opportunity + 0.35 * epistemic
        if action == ControlAction.INTENSIFY:
            fraction = max(fraction, 0.85)
        if action == ControlAction.NARROW:
            fraction = min(fraction, 0.35)
        candidates = round(minimum_candidates + (maximum_candidates - minimum_candidates) * fraction)
    arena_repetitions = min(
        maximum_arena_repetitions,
        max(1, round(1 + fitness_noise * max(0, maximum_arena_repetitions - 1))),
    )
    replay_depth = min(
        maximum_replay_depth,
        max(1, round(1 + (fitness_noise + uncertainty.measurement) * 0.5 * max(0, maximum_replay_depth - 1))),
    )
    return ResourceAllocation(
        provider_calls=0 if candidates == 0 else 1,
        candidates=candidates,
        arena_repetitions=arena_repetitions,
        stronger_model_escalations=1 if action == ControlAction.ESCALATE else 0,
        simulation_depth=2 if uncertainty.epistemic >= 0.55 else 1,
        replay_depth=replay_depth,
        reviewer_count=3 if action in {ControlAction.ESCALATE, ControlAction.REPLAY} else 1,
        wall_clock_seconds=0 if candidates == 0 else 60 + candidates * 5,
        early_termination_allowed=search_saturation >= 0.60 and candidates > 0,
    )
