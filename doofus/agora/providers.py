"""Provider policy enforcement and correlation-aware routing."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from doofus.agora.contracts import (
    ExecutionMode,
    PromptPacket,
    ProviderNode,
    TermsStatus,
)
from doofus.agora.errors import AgoraPolicyError, TermsReviewRequiredError
from doofus.agora.storage import AgoraRepository


def assert_attended_operation(provider: ProviderNode) -> None:
    if provider.execution_mode not in {ExecutionMode.ATTENDED, ExecutionMode.ASSISTED}:
        raise AgoraPolicyError(
            f"provider {provider.provider_id} is not configured for attended local workflow: "
            f"{provider.execution_mode.value}"
        )
    if provider.automated_submit_allowed or provider.automated_extract_allowed:
        raise AgoraPolicyError(
            f"provider {provider.provider_id} attended policy cannot grant automated submit or extraction"
        )


def assert_automation_allowed(
    provider: ProviderNode,
    repository: AgoraRepository,
    adapter_registered: bool,
    operator_approved: bool,
    budget_gates_passed: bool,
) -> None:
    if not adapter_registered:
        raise AgoraPolicyError(
            f"provider {provider.provider_id} has no separately registered automation adapter"
        )
    if not operator_approved:
        raise AgoraPolicyError(
            f"provider {provider.provider_id} automation lacks explicit operator approval"
        )
    if not budget_gates_passed:
        raise AgoraPolicyError(
            f"provider {provider.provider_id} automation failed existing Doofus budget gates"
        )
    decision = repository.latest_terms_decision(provider.provider_id)
    if decision is None:
        raise TermsReviewRequiredError(
            f"provider {provider.provider_id} has no recorded terms review; automation remains blocked"
        )
    if decision.status is not TermsStatus.CURRENT:
        raise TermsReviewRequiredError(
            f"provider {provider.provider_id} terms status is {decision.status.value}; automation remains blocked"
        )
    if not decision.automated_submit_allowed or not decision.automated_extract_allowed:
        raise TermsReviewRequiredError(
            f"provider {provider.provider_id} terms decision does not permit both submit and extraction"
        )
    if provider.execution_mode not in {
        ExecutionMode.AUTONOMOUS_ALLOWED,
        ExecutionMode.API_OPTIONAL,
    }:
        raise AgoraPolicyError(
            f"provider {provider.provider_id} execution mode is {provider.execution_mode.value}, "
            "not AUTONOMOUS_ALLOWED or API_OPTIONAL"
        )


def _capability_bonus(provider: ProviderNode, role: dict[str, Any]) -> float:
    tags = {str(tag).lower() for tag in role.get("capability_tags", [])}
    capabilities = {capability.lower() for capability in provider.capabilities}
    return min(0.25, 0.05 * len(tags.intersection(capabilities)))


def _correlation_penalty(provider: ProviderNode, selected: list[ProviderNode]) -> float:
    groups = set(provider.correlation_groups)
    overlaps = sum(bool(groups.intersection(selected_provider.correlation_groups)) for selected_provider in selected)
    return min(0.35, overlaps * 0.12)


def route_providers(
    providers: tuple[ProviderNode, ...],
    roles: dict[str, dict[str, Any]],
    required_roles: tuple[str, ...],
    mission_type: str,
    topology_id: str,
    maximum_nodes: int,
    routing_seed: int,
    repository: AgoraRepository,
) -> tuple[tuple[ProviderNode, str], ...]:
    eligible = [
        provider
        for provider in providers
        if provider.core_enabled
        and provider.quota_state.upper() not in {"EXHAUSTED", "BLOCKED"}
        and provider.cooldown_until is None
    ]
    if len(eligible) < minimum_required_nodes(maximum_nodes):
        raise AgoraPolicyError(
            f"insufficient attended providers: eligible={len(eligible)} requested={maximum_nodes}"
        )
    if maximum_nodes > len(eligible):
        raise AgoraPolicyError(
            f"requested nodes exceed dynamically eligible attended providers: "
            f"eligible={len(eligible)} requested={maximum_nodes}"
        )
    rng = random.Random(routing_seed)
    selected: list[ProviderNode] = []
    assignments: list[tuple[ProviderNode, str]] = []
    role_cycle = required_roles[:maximum_nodes]
    for role_id in role_cycle:
        if role_id not in roles:
            raise AgoraPolicyError(f"topology references unknown role: {role_id}")
        candidates = [provider for provider in eligible if provider not in selected]
        scored: list[tuple[float, str, ProviderNode]] = []
        for provider in candidates:
            profile = repository.provider_profile(provider.provider_id, mission_type, role_id, topology_id)
            sampled_reward = rng.betavariate(profile["alpha"], profile["beta"])
            historical_bonus = float(provider.historical_quality.get(role_id, 0.0)) * 0.15
            score = (
                sampled_reward
                + _capability_bonus(provider, roles[role_id])
                + historical_bonus
                - _correlation_penalty(provider, selected)
            )
            scored.append((score, provider.provider_id, provider))
        _, _, chosen = max(scored, key=lambda item: (item[0], item[1]))
        assert_attended_operation(chosen)
        selected.append(chosen)
        assignments.append((chosen, role_id))
    return tuple(assignments)


def minimum_required_nodes(maximum_nodes: int) -> int:
    return max(1, min(4, maximum_nodes))


def select_topology(
    topology_ids: tuple[str, ...],
    mission_type: str,
    routing_seed: int,
    repository: AgoraRepository,
) -> str:
    if not topology_ids:
        raise AgoraPolicyError("no debate topologies are registered")
    rng = random.Random(routing_seed)
    scored = []
    for topology_id in sorted(topology_ids):
        profile = repository.topology_profile(mission_type, topology_id)
        score = rng.betavariate(profile["alpha"], profile["beta"])
        scored.append((score, topology_id))
    return max(scored, key=lambda item: (item[0], item[1]))[1]


class AttendedAdapter:
    """Local file connector; it never opens or controls a provider interface."""

    def export_packet(self, packet: PromptPacket, destination_dir: Path) -> tuple[Path, Path]:
        destination_dir.mkdir(parents=True, exist_ok=True)
        safe_stem = f"{packet.round_number:02d}-{packet.round_type.value.lower()}-{packet.provider_id}-{packet.packet_id}"
        prompt_path = destination_dir / f"{safe_stem}.md"
        manifest_path = destination_dir / f"{safe_stem}.json"
        prompt_path.write_text(packet.prompt_text, encoding="utf-8")
        manifest_path.write_text(
            json.dumps(packet.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return prompt_path, manifest_path


class AssistedAdapter(AttendedAdapter):
    """Attended connector that may stage clipboard-ready local text only."""

    def stage_clipboard_text(self, packet: PromptPacket, destination_dir: Path) -> Path:
        destination_dir.mkdir(parents=True, exist_ok=True)
        path = destination_dir / f"clipboard-{packet.packet_id}.txt"
        path.write_text(packet.prompt_text, encoding="utf-8")
        return path
