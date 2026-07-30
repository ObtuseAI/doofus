"""Measured Agora outcome attribution and bounded Doofus learning hooks."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from doofus.agora.contracts import (
    DecisionAction,
    DecisionRecord,
    ExperimentResult,
    IdeaCard,
    OutcomeAttribution,
    ProviderOutcome,
    ResponseArtifact,
    SwarmMission,
)
from doofus.agora.storage import AgoraRepository
from doofus.core.doofus_events import utc_now


def quality_diversity_niche(card: IdeaCard) -> str:
    mechanism = hashlib.sha256(card.core_mechanism.lower().encode("utf-8")).hexdigest()[:8]
    domain = hashlib.sha256(card.problem_addressed.lower().encode("utf-8")).hexdigest()[:8]
    risk_bin = min(4, len(card.failure_modes))
    evidence_bin = sum(record.status.value == "SUPPORTED" for record in card.evidence_records)
    complexity = card.complexity.lower().replace(" ", "_")[:24]
    cost_bin = "high" if any(
        token in card.complexity.lower()
        for token in ("distributed", "expensive", "high")
    ) else "bounded"
    return (
        f"mechanism={mechanism}:domain={domain}:novelty={card.novelty_status.value.lower()}:"
        f"risk={risk_bin}:cost={cost_bin}:evidence={evidence_bin}:complexity={complexity}"
    )


def build_attribution(
    mission: SwarmMission,
    decision: DecisionRecord,
    card: IdeaCard,
    experiment: ExperimentResult,
    artifacts: tuple[ResponseArtifact, ...],
) -> OutcomeAttribution:
    relevant_artifacts = tuple(
        artifact for artifact in artifacts if artifact.artifact_id in card.source_artifact_ids
    )
    measured_value = (
        max(0.0, experiment.baseline_score - experiment.benchmark_score)
        if experiment.tests_passed and experiment.differential_match
        else 0.0
    )
    decisive = (
        "independent_implementations_matched",
        "sandbox_contract_tests_passed",
    ) if experiment.tests_passed and experiment.differential_match else ()
    misleading = (
        ("candidate_failed_independent_execution",)
        if not experiment.tests_passed or not experiment.differential_match
        else ()
    )
    return OutcomeAttribution(
        mission_id=mission.mission_id,
        candidate_id=experiment.candidate_id,
        contributing_provider_ids=tuple(
            dict.fromkeys(artifact.provider_id for artifact in relevant_artifacts)
        ),
        contributing_role_ids=tuple(
            dict.fromkeys(artifact.role_id for artifact in relevant_artifacts)
        ),
        contributing_prompt_ids=tuple(
            dict.fromkeys(artifact.packet_id for artifact in relevant_artifacts)
        ),
        debate_topology_id=mission.topology_id,
        test_results={
            "experiment_id": experiment.experiment_id,
            "tests_passed": experiment.tests_passed,
            "differential_match": experiment.differential_match,
            "benchmark_score": experiment.benchmark_score,
            "baseline_score": experiment.baseline_score,
        },
        promotion_result=(
            "ELIGIBLE_FOR_EXISTING_DOOFUS_GATES"
            if decision.action is DecisionAction.ACT
            else "NOT_ELIGIBLE"
        ),
        measured_value=measured_value,
        decisive_contributions=decisive,
        misleading_contributions=misleading,
        created_at=utc_now(),
    )


def record_provider_learning(
    mission: SwarmMission,
    attribution: OutcomeAttribution,
    card: IdeaCard,
    artifacts: tuple[ResponseArtifact, ...],
    repository: AgoraRepository,
) -> tuple[ProviderOutcome, ...]:
    relevant = tuple(
        artifact
        for artifact in artifacts
        if artifact.packet_id in attribution.contributing_prompt_ids
    )
    passed = bool(attribution.test_results.get("tests_passed"))
    reward = 1.0 if passed and attribution.promotion_result == "ELIGIBLE_FOR_EXISTING_DOOFUS_GATES" else 0.0
    evidence_count = max(1, len(card.evidence_records))
    supported_rate = (
        sum(record.status.value == "SUPPORTED" for record in card.evidence_records)
        / evidence_count
    )
    contradicted_rate = (
        sum(record.status.value == "CONTRADICTED" for record in card.evidence_records)
        / evidence_count
    )
    outcomes: list[ProviderOutcome] = []
    for artifact in relevant:
        outcome = ProviderOutcome(
            provider_id=artifact.provider_id,
            mission_type=mission.mission_type,
            role_id=artifact.role_id,
            topology_id=mission.topology_id,
            reward=reward,
            verified_claim_rate=supported_rate,
            novelty_survival_rate=reward,
            critique_rescue_rate=reward if artifact.round_type.value == "CRITIQUE" else 0.0,
            hallucination_rate=contradicted_rate,
            correlation_score=0.0,
            quota_efficiency=min(1.0, reward / max(1, artifact.round_number)),
            created_at=utc_now(),
        )
        repository.record_provider_outcome(outcome)
        outcomes.append(outcome)
    return tuple(outcomes)


def apply_existing_learning_loops(
    attribution: OutcomeAttribution,
    decision: DecisionRecord,
    card: IdeaCard,
    prompt_text: str,
) -> dict[str, Any]:
    """Emit GEPA/GEP learning only from successful measured experiments."""
    result: dict[str, Any] = {
        "gepa": {"skipped": True, "reason": "experiment_not_accepted"},
        "gep": {"skipped": True, "reason": "experiment_not_accepted"},
    }
    accepted = (
        decision.action is DecisionAction.ACT
        and bool(attribution.test_results.get("tests_passed"))
        and bool(attribution.test_results.get("differential_match"))
    )
    if not accepted:
        return result
    from doofus.meta.gep.capsule_store import create_capsule_from_candidate
    from doofus.meta.gepa.trace_collector import record_trace

    result["gepa"] = record_trace(
        cycle_id=0,
        candidate_id=attribution.candidate_id,
        prompt_text=prompt_text,
        rejection_reason="",
        score_delta=attribution.measured_value,
        arena_result=attribution.promotion_result,
        traits_before=[],
        traits_after=[
            "proof_density",
            "generalization_pressure",
            "mechanistic_diversity",
        ],
    )
    capsule = create_capsule_from_candidate(
        {
            "candidate_id": attribution.candidate_id,
            "mutation_type": "agora_validated_mechanism",
            "traits": [
                "proof_density",
                "generalization_pressure",
                "mechanistic_diversity",
            ],
        },
        max(0.0, attribution.measured_value),
        strategy_name=f"agora:{card.novelty_status.value.lower()}",
    )
    result["gep"] = {
        "skipped": False,
        "capsule_id": capsule.capsule_id,
        "fitness": capsule.fitness,
    }
    return result
