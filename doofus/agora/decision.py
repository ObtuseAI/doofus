"""Candidate formalization and evidence-first decision mechanics."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any

from doofus.agora.contracts import (
    CandidateSpec,
    DecisionAction,
    DecisionRecord,
    EvidenceStatus,
    ExperimentResult,
    IdeaCard,
)
from doofus.core.doofus_events import utc_now


@dataclass(frozen=True)
class CandidateScore:
    candidate_id: str
    evidence_strength: float
    confidence: float
    novelty: float
    feasibility: float
    risk: float
    cost: float


def compile_candidate_spec(
    card: IdeaCard,
    test_cases: tuple[dict[str, Any], ...],
    benchmark_baseline_score: float,
    source_artifact_ids: tuple[str, ...],
) -> CandidateSpec:
    """Compile a surviving idea into an explicit, testable handoff contract."""
    mechanism_slug = hashlib.sha256(card.core_mechanism.encode("utf-8")).hexdigest()[:10]
    return CandidateSpec(
        candidate_id=f"CAN_{mechanism_slug}_{uuid.uuid4().hex[:12]}",
        mission_id=card.mission_id,
        idea_id=card.idea_id,
        algorithm_name=f"AgoraCandidate_{mechanism_slug}",
        problem_definition=card.problem_addressed,
        input_contract="A JSON object accepted as keyword arguments by solve(**input).",
        output_contract="A deterministic JSON-serializable value returned by solve.",
        state_representation="Pure local values; no ambient, persistent, network, or repository state.",
        invariants=(
            "solve is deterministic for identical JSON inputs",
            "solve does not mutate its input arguments",
            "solve performs no network, process, filesystem, credential, or repository access",
            f"the falsification condition remains binding: {card.falsification_condition}",
        ),
        pseudocode=(
            f"1. Validate the declared input contract.\n"
            f"2. Apply this mechanism: {card.core_mechanism}\n"
            "3. Return the declared JSON-serializable output.\n"
            "4. Fail explicitly on invalid input."
        ),
        time_complexity="Must be stated and measured by each independent implementation.",
        space_complexity="Must be stated and measured by each independent implementation.",
        concurrency_model="Single-process deterministic execution.",
        expected_failure_modes=card.failure_modes,
        test_cases=test_cases,
        benchmark_baseline="Median wall-clock milliseconds per declared test case.",
        benchmark_baseline_score=benchmark_baseline_score,
        ablation_plan=(
            "Remove the mechanism-specific transformation and compare correctness.",
            "Replace the mechanism with the simplest declared baseline and compare latency.",
        ),
        external_dependencies=(),
        license_concerns=(),
        source_artifact_ids=tuple(dict.fromkeys(card.source_artifact_ids + source_artifact_ids)),
    )


def _idea_score(card: IdeaCard) -> CandidateScore:
    statuses = [record.status for record in card.evidence_records]
    supported = statuses.count(EvidenceStatus.SUPPORTED)
    contradicted = statuses.count(EvidenceStatus.CONTRADICTED)
    total = max(1, len(statuses))
    evidence_strength = max(0.0, (supported - contradicted) / total)
    novelty_map = {
        "REDISCOVERY": 0.05,
        "KNOWN_COMBINATION": 0.25,
        "NOVEL_ADAPTATION": 0.5,
        "NOVEL_COMBINATION": 0.7,
        "POSSIBLY_NOVEL_MECHANISM": 0.9,
        "NOVELTY_UNVERIFIED": 0.2,
    }
    complexity = card.complexity.lower()
    cost = 0.8 if any(token in complexity for token in ("high", "expensive", "distributed")) else 0.35
    risk = min(1.0, 0.15 * len(card.failure_modes) + contradicted / total)
    feasibility = max(0.0, 1.0 - cost - 0.25 * risk)
    return CandidateScore(
        candidate_id=card.idea_id,
        evidence_strength=evidence_strength,
        confidence=card.confidence,
        novelty=novelty_map[card.novelty_status.value],
        feasibility=feasibility,
        risk=risk,
        cost=cost,
    )


def _dominates(left: CandidateScore, right: CandidateScore) -> bool:
    benefits_left = (
        left.evidence_strength,
        left.confidence,
        left.novelty,
        left.feasibility,
        1.0 - left.risk,
        1.0 - left.cost,
    )
    benefits_right = (
        right.evidence_strength,
        right.confidence,
        right.novelty,
        right.feasibility,
        1.0 - right.risk,
        1.0 - right.cost,
    )
    return all(a >= b for a, b in zip(benefits_left, benefits_right, strict=True)) and any(
        a > b for a, b in zip(benefits_left, benefits_right, strict=True)
    )


def pareto_frontier(cards: tuple[IdeaCard, ...]) -> tuple[str, ...]:
    scores = tuple(_idea_score(card) for card in cards)
    return tuple(
        score.candidate_id
        for score in scores
        if not any(_dominates(other, score) for other in scores if other.candidate_id != score.candidate_id)
    )


def build_decision_analysis(cards: tuple[IdeaCard, ...]) -> dict[str, Any]:
    scores = {_score.candidate_id: _score for _score in (_idea_score(card) for card in cards)}
    pairwise: list[dict[str, Any]] = []
    ordered_ids = sorted(scores)
    for left_index, left_id in enumerate(ordered_ids):
        for right_id in ordered_ids[left_index + 1 :]:
            left = scores[left_id]
            right = scores[right_id]
            left_utility = (
                0.3 * left.evidence_strength
                + 0.2 * left.confidence
                + 0.15 * left.novelty
                + 0.2 * left.feasibility
                + 0.1 * (1.0 - left.risk)
                + 0.05 * (1.0 - left.cost)
            )
            right_utility = (
                0.3 * right.evidence_strength
                + 0.2 * right.confidence
                + 0.15 * right.novelty
                + 0.2 * right.feasibility
                + 0.1 * (1.0 - right.risk)
                + 0.05 * (1.0 - right.cost)
            )
            winner = left_id if left_utility >= right_utility else right_id
            pairwise.append(
                {
                    "left_alias": f"Blind candidate {left_index + 1}",
                    "right_alias": f"Blind candidate {ordered_ids.index(right_id) + 1}",
                    "winner_id": winner,
                    "utility_gap": abs(left_utility - right_utility),
                }
            )
    scenarios = {
        candidate_id: {
            "adverse": max(0.0, score.evidence_strength * score.confidence * (1.0 - score.risk)),
            "base": max(0.0, score.confidence * score.feasibility),
            "upside": min(1.0, score.novelty * score.confidence + 0.2 * score.evidence_strength),
        }
        for candidate_id, score in scores.items()
    }
    return {
        "blind_pairwise_evidence": pairwise,
        "scenarios": scenarios,
        "pareto_frontier": pareto_frontier(cards),
        "minority_review_required": any(card.minority_preserved for card in cards),
        "majority_vote_used": False,
    }


def _hard_gate_failures(
    cards: tuple[IdeaCard, ...],
    candidates: tuple[CandidateSpec, ...],
    experiments: tuple[ExperimentResult, ...],
) -> tuple[str, ...]:
    failures: list[str] = []
    if not cards:
        failures.append("no_surviving_idea_cards")
    if not candidates:
        failures.append("no_formal_candidate_specs")
    for card in cards:
        if any(record.status is EvidenceStatus.CONTRADICTED for record in card.evidence_records):
            failures.append(f"contradicted_claim:{card.idea_id}")
    for candidate in candidates:
        if candidate.external_dependencies:
            failures.append(f"unverified_external_dependencies:{candidate.candidate_id}")
    for result in experiments:
        if not result.network_disabled or not result.source_repo_untouched:
            failures.append(f"sandbox_boundary_not_proven:{result.candidate_id}")
        if not result.dependencies_verified:
            failures.append(f"dependency_gate_failed:{result.candidate_id}")
    return tuple(sorted(set(failures)))


def build_decision(
    mission_id: str,
    cards: tuple[IdeaCard, ...],
    candidates: tuple[CandidateSpec, ...],
    experiments: tuple[ExperimentResult, ...],
    value_of_information: float,
) -> DecisionRecord:
    """Choose an authority-bounded action without majority voting."""
    failures = _hard_gate_failures(cards, candidates, experiments)
    frontier_idea_ids = set(pareto_frontier(cards))
    frontier = tuple(
        candidate.candidate_id
        for candidate in candidates
        if candidate.idea_id in frontier_idea_ids
    )
    card_by_id = {card.idea_id: card for card in cards}
    experiment_by_candidate = {result.candidate_id: result for result in experiments}
    viable_candidates = tuple(
        candidate.candidate_id
        for candidate in candidates
        if (
            not candidate.external_dependencies
            and not any(
                record.status is EvidenceStatus.CONTRADICTED
                for record in card_by_id[candidate.idea_id].evidence_records
            )
            and candidate.candidate_id in experiment_by_candidate
            and experiment_by_candidate[candidate.candidate_id].tests_passed
            and experiment_by_candidate[candidate.candidate_id].differential_match
            and experiment_by_candidate[candidate.candidate_id].benchmark_score
            <= experiment_by_candidate[candidate.candidate_id].baseline_score
        )
    )
    if viable_candidates:
        action = DecisionAction.ACT
        selected = viable_candidates
    elif failures:
        action = DecisionAction.REJECT if experiments else DecisionAction.RUN_EXPERIMENT
        selected = ()
    elif candidates and not experiments:
        action = DecisionAction.RUN_EXPERIMENT
        selected = ()
    elif experiments:
        action = DecisionAction.REJECT
        selected = ()
    elif cards:
        action = DecisionAction.BUILD_PROTOTYPE
        selected = ()
    else:
        action = DecisionAction.ABSTAIN
        selected = ()
    minority_idea_ids = {
        card.idea_id for card in cards if card.minority_preserved
    }
    minority_ids = tuple(
        candidate.candidate_id
        for candidate in candidates
        if candidate.idea_id in minority_idea_ids
    )
    candidate_idea_ids = {candidate.idea_id for candidate in candidates}
    rejected = tuple(
        candidate.candidate_id
        for candidate in candidates
        if candidate.candidate_id not in selected
    )
    confidence = (
        sum(card.confidence for card in cards if card.idea_id in candidate_idea_ids) / len(cards)
        if cards
        else 0.0
    )
    expected_regret = max(0.0, 1.0 - confidence + (0.2 if not minority_ids else 0.0))
    return DecisionRecord(
        decision_id=f"DEC_{uuid.uuid4().hex}",
        mission_id=mission_id,
        action=action,
        selected_candidate_ids=selected,
        minority_candidate_ids=minority_ids,
        rejected_candidate_ids=rejected,
        hard_gate_failures=failures,
        pareto_frontier=frontier,
        expected_regret=expected_regret,
        value_of_information=max(0.0, value_of_information),
        confidence=min(1.0, max(0.0, confidence)),
        authority_effect="SUBMIT_TO_EXISTING_DOOFUS_GATES_ONLY",
        created_at=utc_now(),
    )
