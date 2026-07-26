"""Metacognitive controller with an immutable external authority boundary."""
from __future__ import annotations

import os
from statistics import fmean

from doofus.config.metacognition_config import (
    bounded_control_enabled,
    int_setting,
    metacognition_mode,
)
from doofus.core.atomic_json import load_json, save_json
from doofus.core.doofus_config import DoofusConfig
from doofus.core.doofus_events import utc_now
from doofus.metacognition.calibration import get_calibration_summary
from doofus.metacognition.council import CouncilVerdict, merge_council
from doofus.metacognition.event_schema import MetacognitiveEvent, MetacognitiveEventType
from doofus.metacognition.evaluator import evaluate_cycle_outcome
from doofus.metacognition.memory import get_memory_snapshot
from doofus.metacognition.meta_evolution import get_active_meta_policy
from doofus.metacognition.monitor import monitor_evolution
from doofus.metacognition.predictions import record_event, record_prediction
from doofus.metacognition.resource_allocator import allocate_resources
from doofus.metacognition.runtime_control import (
    active_control_file,
    get_active_control,
    latest_bundle_file,
    latest_state_file,
    should_skip_cycle,
)
from doofus.metacognition.state import ControlAction, ControlDecision, MetacognitiveState, ResourceAllocation
from doofus.safety.budget_guard import check_budget
from doofus.safety.on_off_switch import check_may_proceed
from doofus.interoception.monitor import monitor_interoception


def deactivate_control(reason: str) -> None:
    save_json(
        active_control_file(),
        {"active": False, "reason": reason, "deactivated_at": utc_now()},
    )


def _algorithm_portfolio(state: MetacognitiveState) -> dict[str, float]:
    algorithms = state.selected_strategy.algorithm_ids
    if not algorithms:
        return {}
    weight = 1.0 / len(algorithms)
    return {algorithm: weight for algorithm in algorithms}


def _zero_allocation(requested: ResourceAllocation) -> ResourceAllocation:
    return ResourceAllocation(
        provider_calls=0,
        candidates=0,
        arena_repetitions=0,
        stronger_model_escalations=0,
        simulation_depth=requested.simulation_depth,
        replay_depth=requested.replay_depth,
        reviewer_count=requested.reviewer_count,
        wall_clock_seconds=0,
        early_termination_allowed=False,
    )


def _authorize_allocation(
    state: MetacognitiveState,
    council: CouncilVerdict,
    dry_run: bool,
) -> tuple[bool, str, ResourceAllocation]:
    requested = state.resource_allocation
    if not bounded_control_enabled():
        return False, f"{metacognition_mode()}_mode_records_advice_only", _zero_allocation(requested)
    if not state.authority_eligible:
        return False, "target_outside_authority", _zero_allocation(requested)
    may_run, switch_reason = check_may_proceed()
    if not may_run and not dry_run:
        return False, f"run_switch_blocked:{switch_reason}", _zero_allocation(requested)
    if council.action in {ControlAction.RESEARCH, ControlAction.ABSTAIN, ControlAction.TERMINATE}:
        return True, "bounded_no_mutation_control", _zero_allocation(requested)
    if council.action == ControlAction.ESCALATE:
        return False, "stronger_model_escalation_requires_existing_provider_authority", _zero_allocation(requested)
    if not state.selected_strategy.executable:
        return False, "selected_strategy_has_no_bounded_executor", _zero_allocation(requested)
    cfg = DoofusConfig.from_env()
    budget = check_budget(cfg)
    evolution_max = int(os.environ.get("DOOFUS_MAX_CANDIDATES_PER_CYCLE", "48"))
    hard_candidate_max = min(
        evolution_max,
        int_setting("DOOFUS_METACOGNITION_MAX_CANDIDATES"),
    )
    current_arena_cap = int(os.environ.get("DOOFUS_ARENA_LIVE_MAX_PER_CYCLE", "4"))
    provider_calls = min(requested.provider_calls, 1) if budget.get("ok") else 0
    authorized = ResourceAllocation(
        provider_calls=provider_calls,
        candidates=min(requested.candidates, hard_candidate_max),
        arena_repetitions=min(requested.arena_repetitions, current_arena_cap),
        stronger_model_escalations=0,
        simulation_depth=requested.simulation_depth,
        replay_depth=min(
            requested.replay_depth,
            int_setting("DOOFUS_METACOGNITION_MAX_REPLAY_DEPTH"),
        ),
        reviewer_count=requested.reviewer_count,
        wall_clock_seconds=requested.wall_clock_seconds,
        early_termination_allowed=requested.early_termination_allowed,
    )
    reason = "bounded_with_budget_clamp" if provider_calls != requested.provider_calls else "bounded_within_constitution"
    return True, reason, authorized


def _decision(
    state: MetacognitiveState,
    council: CouncilVerdict,
    dry_run: bool,
) -> ControlDecision:
    authorized, authority_reason, allocation = _authorize_allocation(state, council, dry_run)
    reasons = council.reasons or (
        f"recommended_control={state.recommended_control.value}",
        f"strategy={state.selected_strategy.strategy_id}",
    )
    return ControlDecision(
        target_id=state.target_id,
        generation=state.generation,
        recommendation=council.action,
        reasons=reasons,
        selected_strategy=state.selected_strategy.strategy_id,
        algorithm_portfolio=_algorithm_portfolio(state),
        requested_allocation=state.resource_allocation,
        authorized_allocation=allocation,
        authorized=authorized,
        authority_reason=authority_reason,
        mode=metacognition_mode(),
        policy_version=state.policy_version,
        created_at=utc_now(),
    )


def _apply_council_action(
    state: MetacognitiveState,
    council: CouncilVerdict,
) -> MetacognitiveState:
    if council.action == state.recommended_control:
        return state
    allocation = allocate_resources(
        state.uncertainty,
        state.expected_improvability,
        state.search_saturation,
        state.uncertainty.aleatoric,
        council.action,
        int_setting("DOOFUS_METACOGNITION_MIN_CANDIDATES"),
        int_setting("DOOFUS_METACOGNITION_MAX_CANDIDATES"),
        int_setting("DOOFUS_METACOGNITION_MAX_ARENA_REPETITIONS"),
        int_setting("DOOFUS_METACOGNITION_MAX_REPLAY_DEPTH"),
    )
    return state.model_copy(
        update={
            "recommended_control": council.action,
            "resource_allocation": allocation,
        }
    )
def prepare_metacognitive_cycle(
    target_id: str,
    authority_eligible: bool,
    dry_run: bool,
) -> dict[str, object]:
    deactivate_control("pre_cycle_reset")
    state, evidence = monitor_evolution(target_id, authority_eligible)
    council = merge_council(state)
    state = _apply_council_action(state, council)
    interoception = monitor_interoception()
    decision = _decision(state, council, dry_run)
    prediction_id = record_prediction(
        state,
        evidence.baseline_fitness,
        decision.recommendation,
        decision.requested_allocation.candidates,
    )
    payload = {
        "active": bool(decision.authorized and bounded_control_enabled()),
        "prediction_id": prediction_id,
        "state": state.model_dump(mode="json"),
        "council": council.model_dump(mode="json"),
        "interoception": interoception.model_dump(mode="json"),
        "decision": decision.model_dump(mode="json"),
    }
    save_json(latest_state_file(), state.model_dump(mode="json"))
    save_json(latest_bundle_file(), payload)
    save_json(active_control_file(), payload)
    record_event(
        MetacognitiveEvent(
            event_type=MetacognitiveEventType.PREDICTION_RECORDED,
            target_id=state.target_id,
            generation=state.generation,
            policy_version=state.policy_version,
            payload={
                "prediction_id": prediction_id,
                "predicted_fitness": state.fitness_prediction.mean,
                "probability_non_regression": state.fitness_prediction.probability_of_non_regression,
            },
            created_at=utc_now(),
        )
    )
    event_type = (
        MetacognitiveEventType.CONTROL_AUTHORIZED
        if decision.authorized
        else MetacognitiveEventType.CONTROL_RECOMMENDED
    )
    record_event(
        MetacognitiveEvent(
            event_type=event_type,
            target_id=state.target_id,
            generation=state.generation,
            policy_version=state.policy_version,
            payload={
                "prediction_id": prediction_id,
                "recommendation": decision.recommendation.value,
                "authorized": decision.authorized,
                "authority_reason": decision.authority_reason,
                "selected_strategy": decision.selected_strategy,
                "requested_allocation": decision.requested_allocation.model_dump(),
                "authorized_allocation": decision.authorized_allocation.model_dump(),
            },
            created_at=utc_now(),
        )
    )
    record_event(
        MetacognitiveEvent(
            event_type=MetacognitiveEventType.INTEROCEPTION_DIAGNOSIS,
            target_id=state.target_id,
            generation=state.generation,
            policy_version=state.policy_version,
            payload=interoception.model_dump(),
            created_at=utc_now(),
        )
    )
    return {
        "classification": "METACOGNITIVE_CYCLE_PREPARED",
        **payload,
    }


def complete_metacognitive_cycle(
    pre_cycle: dict[str, object],
    cycle_result: dict[str, object],
) -> dict[str, object]:
    prediction_id = str(pre_cycle.get("prediction_id") or "")
    if not prediction_id:
        raise ValueError("Metacognitive pre-cycle result has no prediction_id")
    evaluation = evaluate_cycle_outcome(prediction_id, cycle_result)
    deactivate_control("cycle_outcome_recorded")
    return evaluation


def online_termination_reason(scores: list[float], baseline: float) -> str:
    payload = get_active_control()
    if payload is None:
        return ""
    allocation = payload["decision"]["authorized_allocation"]
    if not bool(allocation.get("early_termination_allowed")):
        return ""
    minimum_samples = int_setting("DOOFUS_METACOGNITION_MIN_ONLINE_SAMPLES")
    if len(scores) < minimum_samples:
        return ""
    recent = scores[-4:]
    deltas = [current - previous for previous, current in zip(scores, scores[1:])]
    velocity = fmean(deltas[-4:]) if deltas else 0.0
    if max(recent) <= baseline and velocity <= 0.0:
        return "bounded_metacognitive_marginal_value_exhausted"
    return ""


def record_online_observation(
    target_id: str,
    generation: int,
    scores: list[float],
    termination_reason: str,
) -> None:
    payload = load_json(latest_bundle_file(), default={})
    if not isinstance(payload, dict) or not scores:
        return
    state = payload.get("state")
    if not isinstance(state, dict) or int(state.get("generation", -1)) != generation:
        return
    deltas = [current - previous for previous, current in zip(scores, scores[1:])]
    velocity = fmean(deltas[-4:]) if deltas else 0.0
    record_event(
        MetacognitiveEvent(
            event_type=MetacognitiveEventType.ONLINE_OBSERVATION,
            target_id=target_id,
            generation=generation,
            policy_version=str(state.get("policy_version") or "unknown"),
            payload={
                "samples": len(scores),
                "latest_score": scores[-1],
                "best_score": max(scores),
                "velocity": velocity,
                "termination_reason": termination_reason or None,
            },
            created_at=utc_now(),
        )
    )


def get_metacognitive_snapshot(target_id: str) -> dict[str, object]:
    latest = load_json(latest_bundle_file(), default={})
    active = load_json(active_control_file(), default={})
    return {
        "classification": "METACOGNITIVE_CORTEX_EXPERIMENTAL",
        "mode": metacognition_mode(),
        "policy_version": get_active_meta_policy().policy_id,
        "meta_policy": get_active_meta_policy().model_dump(),
        "experimental": True,
        "latest": latest,
        "active_control": active,
        "calibration": get_calibration_summary(target_id).model_dump(),
        "memory": get_memory_snapshot(target_id),
        "immutable_authority_boundary": {
            "kill_switches": True,
            "protected_roots": True,
            "secret_isolation": True,
            "path_containment": True,
            "budget_hard_caps": True,
            "write_authorization": True,
            "rollback_enforcement": True,
            "promotion_gates": True,
        },
    }
