"""Problem Foundry collectors and diverse problem-solution portfolio mechanics."""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from typing import Any

from doofus.agora.contracts import NoveltyClass, ProblemCard
from doofus.agora.storage import AgoraRepository

PROBLEM_CATEGORIES = (
    "rejection",
    "quality_diversity_gap",
    "runtime_failure",
    "proof_debt",
    "bottleneck",
    "unresolved_decision",
)


def problem_from_observation(category: str, observation: dict[str, Any]) -> ProblemCard:
    if category not in PROBLEM_CATEGORIES:
        raise ValueError(f"unsupported Problem Foundry category: {category}")
    condition = str(observation["observed_condition"]).strip()
    if not condition:
        raise ValueError("Problem Foundry observed_condition cannot be empty")
    digest = hashlib.sha256(f"{category}:{condition}".encode("utf-8")).hexdigest()[:12]
    return ProblemCard(
        problem_id=f"PRB_{digest}_{uuid.uuid4().hex[:8]}",
        observed_condition=condition,
        why_it_matters=str(observation["why_it_matters"]),
        evidence=tuple(str(item) for item in observation.get("evidence", [])),
        affected_parties=tuple(str(item) for item in observation.get("affected_parties", ["Doofus operators"])),
        current_approaches=tuple(str(item) for item in observation.get("current_approaches", [])),
        approach_failures=tuple(str(item) for item in observation.get("approach_failures", [])),
        hidden_assumptions=tuple(str(item) for item in observation.get("hidden_assumptions", [])),
        expected_leverage=float(observation["expected_leverage"]),
        tractability=float(observation["tractability"]),
        novelty=NoveltyClass(str(observation.get("novelty", NoveltyClass.NOVELTY_UNVERIFIED.value))),
        proposed_measurement=str(observation["proposed_measurement"]),
        falsification_test=str(observation["falsification_test"]),
        candidate_solution_families=tuple(
            str(item) for item in observation.get("candidate_solution_families", [])
        ),
        category=category,
    )


def preserve_diverse_problem_portfolio(
    cards: tuple[ProblemCard, ...],
    maximum_cards: int,
) -> tuple[ProblemCard, ...]:
    if maximum_cards < 1:
        raise ValueError("maximum_cards must be positive")
    by_category: dict[str, list[ProblemCard]] = defaultdict(list)
    for card in cards:
        by_category[card.category].append(card)
    for category_cards in by_category.values():
        category_cards.sort(
            key=lambda card: (
                -(card.expected_leverage * card.tractability),
                card.problem_id,
            )
        )
    selected: list[ProblemCard] = []
    while len(selected) < maximum_cards and any(by_category.values()):
        for category in sorted(by_category):
            if by_category[category] and len(selected) < maximum_cards:
                selected.append(by_category[category].pop(0))
    return tuple(selected)


def problem_solution_tournament(
    problems: tuple[ProblemCard, ...],
    solution_family_scores: dict[str, dict[str, float]],
) -> tuple[dict[str, Any], ...]:
    """Rank declared solution families; this function has no project write authority."""
    results: list[dict[str, Any]] = []
    for problem in problems:
        ranked: list[tuple[float, str]] = []
        for family in problem.candidate_solution_families:
            score = solution_family_scores.get(family, {})
            evidence = float(score.get("evidence", 0.0))
            feasibility = float(score.get("feasibility", 0.0))
            risk = float(score.get("risk", 1.0))
            ranked.append((0.45 * evidence + 0.4 * feasibility + 0.15 * (1.0 - risk), family))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        results.append(
            {
                "problem_id": problem.problem_id,
                "ranked_solution_families": tuple(
                    {"family": family, "score": score} for score, family in ranked
                ),
                "authority_effect": "PROPOSAL_ONLY_NO_CROSS_PROJECT_WRITE",
            }
        )
    return tuple(results)


def collect_problem_portfolio(
    repository: AgoraRepository,
    observations_by_category: dict[str, tuple[dict[str, Any], ...]],
    maximum_cards: int,
) -> tuple[ProblemCard, ...]:
    """Collect declared problem evidence without assuming authority over its source."""
    cards: list[ProblemCard] = []
    for category in PROBLEM_CATEGORIES:
        observations = observations_by_category.get(category, ())
        cards.extend(
            problem_from_observation(category, observation)
            for observation in observations
        )
    for event in repository.all_events(10000):
        if event["event_type"] != "decision_recorded":
            continue
        decision = dict(event["payload"]["decision"])
        for failure in decision.get("hard_gate_failures", []):
            cards.append(
                problem_from_observation(
                    "rejection",
                    {
                        "observed_condition": str(failure),
                        "why_it_matters": "A measured Agora candidate failed a hard decision gate.",
                        "evidence": (event["event_hash"], decision["decision_id"]),
                        "affected_parties": ("Doofus operators", "candidate authors"),
                        "current_approaches": ("Preserve the rejected candidate receipt.",),
                        "approach_failures": (str(failure),),
                        "hidden_assumptions": ("The gate reflects the intended authority boundary.",),
                        "expected_leverage": 0.7,
                        "tractability": 0.6,
                        "novelty": NoveltyClass.NOVELTY_UNVERIFIED.value,
                        "proposed_measurement": "Re-run the cheapest decisive experiment after one scoped repair.",
                        "falsification_test": "The repaired candidate still fails the same frozen hard gate.",
                        "candidate_solution_families": (
                            "proof_debt_reduction",
                            "mechanism_repair",
                            "simpler_baseline",
                        ),
                    },
                )
            )
    return preserve_diverse_problem_portfolio(tuple(cards), maximum_cards)
