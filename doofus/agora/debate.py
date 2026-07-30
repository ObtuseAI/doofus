"""Structured blind debate, synthesis, minority preservation, and stop control."""

from __future__ import annotations

import hashlib
import re
import uuid
from collections import Counter
from typing import Any

from doofus.agora.capture import read_response_text
from doofus.agora.contracts import (
    CritiqueCard,
    IdeaCard,
    NoveltyClass,
    PromptPacket,
    ResponseArtifact,
    RoundType,
    SwarmMission,
)
from doofus.agora.mission import CONSTITUTION, new_identifier, prompt_sha256
from doofus.core.doofus_events import utc_now

TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "because",
    "could",
    "from",
    "have",
    "into",
    "should",
    "that",
    "their",
    "there",
    "these",
    "this",
    "through",
    "using",
    "with",
    "would",
}


def _tokens(text: str) -> frozenset[str]:
    return frozenset(
        token.lower()
        for token in TOKEN_PATTERN.findall(text)
        if token.lower() not in STOPWORDS
    )


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left.union(right)
    return len(left.intersection(right)) / len(union) if union else 0.0


def cluster_artifacts(
    artifacts: tuple[ResponseArtifact, ...],
    similarity_threshold: float,
) -> dict[str, str]:
    clusters: list[tuple[str, frozenset[str]]] = []
    mapping: dict[str, str] = {}
    for artifact in sorted(artifacts, key=lambda item: item.artifact_id):
        artifact_tokens = _tokens(" ".join(artifact.extracted_ideas))
        matched_cluster: str | None = None
        for cluster_id, cluster_tokens in clusters:
            if _jaccard(artifact_tokens, cluster_tokens) >= similarity_threshold:
                matched_cluster = cluster_id
                break
        if matched_cluster is None:
            matched_cluster = f"CLUSTER_{len(clusters) + 1:02d}"
            clusters.append((matched_cluster, artifact_tokens))
        mapping[artifact.artifact_id] = matched_cluster
    return mapping


def build_critique_packets(
    mission: SwarmMission,
    artifacts: tuple[ResponseArtifact, ...],
    aliases: dict[str, str],
) -> tuple[tuple[PromptPacket, CritiqueCard], ...]:
    ordered = sorted(artifacts, key=lambda artifact: artifact.provider_id)
    output: list[tuple[PromptPacket, CritiqueCard]] = []
    for reviewer_index, reviewer in enumerate(ordered):
        targets = (
            ordered[(reviewer_index + 1) % len(ordered)],
            ordered[(reviewer_index + 2) % len(ordered)],
        )
        target_sections = "\n\n".join(
            f"{aliases[target.artifact_id]}\n{read_response_text(target)}"
            for target in targets
        )
        prompt_text = f"""{CONSTITUTION}
BLIND CRITIQUE MISSION
{mission.objective}

You are reviewing two anonymized proposals. Provider identities are intentionally withheld.

{target_sections}

For each proposal:
1. Steelman its strongest mechanism.
2. Construct its most likely fatal flaw.
3. Identify unsupported factual claims and hidden assumptions.
4. Supply a concrete counterexample.
5. Name the cheapest decisive falsification test.
6. State what can be salvaged if it fails.
7. Identify evidence that would reverse your judgment.

Do not vote and do not reward agreement or verbosity.
"""
        packet = PromptPacket(
            packet_id=new_identifier("PKT"),
            mission_id=mission.mission_id,
            provider_id=reviewer.provider_id,
            role_id="adversarial_auditor",
            round_type=RoundType.CRITIQUE,
            round_number=2,
            prompt_text=prompt_text,
            prompt_sha256=prompt_sha256(prompt_text),
            source_artifact_ids=tuple(target.artifact_id for target in targets),
            created_at=utc_now(),
        )
        card = CritiqueCard(
            critique_id=f"CRT_{uuid.uuid4().hex}",
            mission_id=mission.mission_id,
            reviewer_provider_id=reviewer.provider_id,
            proposal_aliases=tuple(aliases[target.artifact_id] for target in targets),
            packet_id=packet.packet_id,
            created_at=utc_now(),
        )
        output.append((packet, card))
    return tuple(output)


def build_synthesis_packets(
    mission: SwarmMission,
    divergence: tuple[ResponseArtifact, ...],
    critiques: tuple[ResponseArtifact, ...],
    aliases: dict[str, str],
) -> tuple[PromptPacket, ...]:
    proposal_text = "\n\n".join(
        f"{aliases[artifact.artifact_id]}\n{read_response_text(artifact)}"
        for artifact in divergence
    )
    critique_text = "\n\n".join(
        f"Critique {index + 1}\n{read_response_text(artifact)}"
        for index, artifact in enumerate(critiques)
    )
    reviewers = sorted(divergence, key=lambda artifact: (-artifact.confidence, artifact.provider_id))[:3]
    packets: list[PromptPacket] = []
    for reviewer in reviewers:
        prompt_text = f"""{CONSTITUTION}
MINORITY-PRESERVING SYNTHESIS
{mission.objective}

ANONYMIZED PROPOSALS
{proposal_text}

ANONYMIZED CRITIQUES
{critique_text}

Do not collapse all proposals into one compromise. Produce:
1. The strongest standalone candidate.
2. The strongest hybrid candidate.
3. The strongest supported minority candidate.
4. The simplest viable candidate.
5. The highest-upside speculative candidate.

For every candidate include mechanism, assumptions, failure modes, falsification test,
evidence needed, closest prior art, confidence, and what would reverse the conclusion.
Consensus receives no score bonus.
"""
        packets.append(
            PromptPacket(
                packet_id=new_identifier("PKT"),
                mission_id=mission.mission_id,
                provider_id=reviewer.provider_id,
                role_id="calibrated_judge",
                round_type=RoundType.SYNTHESIS,
                round_number=3,
                prompt_text=prompt_text,
                prompt_sha256=prompt_sha256(prompt_text),
                source_artifact_ids=tuple(
                    artifact.artifact_id for artifact in divergence + critiques
                ),
                created_at=utc_now(),
            )
        )
    return tuple(packets)


def build_idea_cards(
    mission: SwarmMission,
    divergence: tuple[ResponseArtifact, ...],
    synthesis: tuple[ResponseArtifact, ...],
    similarity_threshold: float,
) -> tuple[IdeaCard, ...]:
    source = synthesis if synthesis else divergence
    clusters = cluster_artifacts(source, similarity_threshold)
    cluster_counts = Counter(clusters.values())
    smallest_cluster_size = min(cluster_counts.values())
    cards: list[IdeaCard] = []
    for artifact in source:
        ideas = artifact.extracted_ideas
        mechanism = ideas[0] if ideas else read_response_text(artifact).splitlines()[0]
        cluster_id = clusters[artifact.artifact_id]
        minority = cluster_counts[cluster_id] == smallest_cluster_size and len(cluster_counts) > 1
        cards.append(
            IdeaCard(
                idea_id=f"IDEA_{uuid.uuid4().hex}",
                mission_id=mission.mission_id,
                problem_addressed=mission.objective,
                core_mechanism=mechanism[:1200],
                rationale=ideas[1][:1200] if len(ideas) > 1 else mechanism[:1200],
                closest_prior_art=artifact.citations,
                prior_art_difference="UNVERIFIED until the evidence fabric completes prior-art checks",
                required_assumptions=tuple(artifact.extracted_claims[:4]),
                expected_benefit=mission.success_metrics[0] if mission.success_metrics else "Measured mission improvement",
                complexity="UNVERIFIED",
                failure_modes=tuple(artifact.extracted_claims[-3:]) or ("Hidden failure modes require critique evidence.",),
                falsification_condition=(
                    mission.falsification_conditions[0]
                    if mission.falsification_conditions
                    else "Fail the cheapest decisive experiment."
                ),
                minimum_viable_experiment="Compile a bounded candidate and compare it against the declared baseline.",
                source_artifact_ids=(artifact.artifact_id,),
                confidence=artifact.confidence,
                novelty_status=NoveltyClass.NOVELTY_UNVERIFIED,
                evidence_records=(),
                cluster_id=cluster_id,
                minority_preserved=minority,
            )
        )
    cards.sort(key=lambda card: (not card.minority_preserved, -card.confidence, card.idea_id))
    return tuple(cards)


def stop_decision(
    current_round: int,
    maximum_rounds: int,
    new_mechanisms: int,
    contradiction_reduction: float,
    decisive_experiment_available: bool,
    quota_exhausted: bool,
    expected_value_next_round: float,
) -> dict[str, Any]:
    reasons: list[str] = []
    if current_round >= maximum_rounds:
        reasons.append("maximum_rounds_reached")
    if new_mechanisms == 0 and current_round >= 2:
        reasons.append("no_material_new_mechanism")
    if contradiction_reduction <= 0.0 and current_round >= 2:
        reasons.append("contradiction_reduction_stalled")
    if decisive_experiment_available:
        reasons.append("decisive_experiment_available")
    if quota_exhausted:
        reasons.append("provider_quota_exhausted")
    if expected_value_next_round < 0.0:
        reasons.append("negative_expected_value")
    return {
        "stop": bool(reasons),
        "reasons": reasons,
        "information_gain": max(0.0, float(new_mechanisms) + contradiction_reduction),
    }
