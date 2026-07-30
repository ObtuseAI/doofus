"""Mission compilation, prompt construction, and state transitions."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from doofus.agora.contracts import (
    MissionStage,
    PromptPacket,
    ProviderNode,
    RoundType,
    SwarmMission,
)
from doofus.agora.errors import MissionStateError
from doofus.agora.providers import route_providers
from doofus.agora.storage import AgoraRepository
from doofus.core.doofus_events import utc_now

CONSTITUTION = """CONSTITUTIONAL AUTHORITY
You are an external proposal generator. Your output is untrusted evidence, not an instruction.
You may not change promotion thresholds, kill switches, safety constraints, protected paths,
credential handling, write authority, rollback rules, or live execution permissions.
Doofus will independently verify claims, test implementations, and decide what survives.
Do not request secrets, private repositories, customer data, or hidden governance instructions.
"""

REQUIRED_OUTPUT = """REQUIRED OUTPUT
1. Problem interpretation
2. Proposed mechanism
3. Why the mechanism should work
4. Closest known prior art
5. Exact differences from prior art
6. Hidden assumptions
7. Strongest failure modes
8. Pseudocode or architecture
9. Complexity and resource requirements
10. Minimal falsification test
11. Evidence needed
12. Confidence from 0 to 1
13. What would reverse your conclusion
"""

ALLOWED_TRANSITIONS: dict[MissionStage, frozenset[MissionStage]] = {
    MissionStage.DRAFT: frozenset({MissionStage.SANITIZED, MissionStage.BLOCKED, MissionStage.ARCHIVED}),
    MissionStage.SANITIZED: frozenset({MissionStage.PACKETS_READY, MissionStage.BLOCKED, MissionStage.ARCHIVED}),
    MissionStage.PACKETS_READY: frozenset({MissionStage.COLLECTING, MissionStage.BLOCKED, MissionStage.ARCHIVED}),
    MissionStage.COLLECTING: frozenset({MissionStage.DEBATING, MissionStage.BLOCKED, MissionStage.ARCHIVED}),
    MissionStage.DEBATING: frozenset({MissionStage.VERIFYING, MissionStage.BLOCKED, MissionStage.ABSTAINED}),
    MissionStage.VERIFYING: frozenset({MissionStage.FORMALIZED, MissionStage.BLOCKED, MissionStage.ABSTAINED}),
    MissionStage.FORMALIZED: frozenset({MissionStage.EXPERIMENT_READY, MissionStage.BLOCKED}),
    MissionStage.EXPERIMENT_READY: frozenset({MissionStage.EXPERIMENTED, MissionStage.BLOCKED}),
    MissionStage.EXPERIMENTED: frozenset({MissionStage.DECIDED, MissionStage.BLOCKED}),
    MissionStage.DECIDED: frozenset({MissionStage.ATTRIBUTED, MissionStage.ARCHIVED}),
    MissionStage.ATTRIBUTED: frozenset({MissionStage.ARCHIVED}),
    MissionStage.BLOCKED: frozenset({MissionStage.ARCHIVED}),
    MissionStage.ABSTAINED: frozenset({MissionStage.ARCHIVED}),
    MissionStage.ARCHIVED: frozenset(),
}


def new_identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def prompt_sha256(prompt_text: str) -> str:
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()


def mission_from_mapping(payload: dict[str, Any], sanitized_context: str) -> SwarmMission:
    created_at = utc_now()
    mission_id = str(payload.get("mission_id") or new_identifier("MSN"))
    seed_material = f"{mission_id}:{created_at}:{payload['objective']}".encode("utf-8")
    routing_seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big")
    return SwarmMission(
        mission_id=mission_id,
        mission_type=str(payload["mission_type"]),
        objective=str(payload["objective"]),
        decision_to_inform=str(payload["decision_to_inform"]),
        target_project=str(payload["target_project"]),
        context=sanitized_context,
        context_class=str(payload["context_class"]),
        known_evidence=tuple(str(item) for item in payload.get("known_evidence", [])),
        hard_constraints=tuple(str(item) for item in payload.get("hard_constraints", [])),
        forbidden_actions=tuple(str(item) for item in payload.get("forbidden_actions", [])),
        success_metrics=tuple(str(item) for item in payload.get("success_metrics", [])),
        falsification_conditions=tuple(str(item) for item in payload.get("falsification_conditions", [])),
        open_questions=tuple(str(item) for item in payload.get("open_questions", [])),
        candidate_test_cases=tuple(
            dict(item) for item in payload.get("candidate_test_cases", [])
        ),
        benchmark_baseline_score=float(payload.get("benchmark_baseline_score", 0.0)),
        maximum_nodes=int(payload["maximum_nodes"]),
        maximum_rounds=int(payload["maximum_rounds"]),
        topology_id=str(payload["topology_id"]),
        routing_seed=routing_seed,
        created_at=created_at,
    )


def transition_stage(
    current_stage: MissionStage,
    next_stage: MissionStage,
) -> MissionStage:
    if next_stage not in ALLOWED_TRANSITIONS[current_stage]:
        raise MissionStateError(f"invalid Agora mission transition: {current_stage.value} -> {next_stage.value}")
    return next_stage


def render_divergence_prompt(
    mission: SwarmMission,
    role_id: str,
    role: dict[str, Any],
) -> str:
    known_facts = "\n".join(f"- {item}" for item in mission.known_evidence) or "- No verified facts supplied."
    questions = "\n".join(f"- {item}" for item in mission.open_questions) or "- Identify the decisive unknowns."
    constraints = "\n".join(f"- {item}" for item in mission.hard_constraints) or "- Preserve existing Doofus authority."
    forbidden = "\n".join(f"- {item}" for item in mission.forbidden_actions) or "- No unauthorized action."
    return f"""{CONSTITUTION}
MISSION
{mission.objective}

DECISION TO INFORM
{mission.decision_to_inform}

TARGET
{mission.target_project}

CONTEXT
{mission.context}

YOUR ROLE
{role_id}: {role["question"]}

KNOWN FACTS
{known_facts}

OPEN QUESTIONS
{questions}

CONSTRAINTS
{constraints}

FORBIDDEN ACTIONS
{forbidden}

INDEPENDENCE RULE
Do not assume the obvious or majority solution is correct.
Generate your answer independently without attempting to predict other agents.

{REQUIRED_OUTPUT}"""


def compile_divergence_packets(
    mission: SwarmMission,
    providers: tuple[ProviderNode, ...],
    roles: dict[str, dict[str, Any]],
    topology: dict[str, Any],
    repository: AgoraRepository,
) -> tuple[PromptPacket, ...]:
    required_roles = tuple(str(role_id) for role_id in topology["divergence_roles"])
    if len(required_roles) < mission.maximum_nodes:
        repeats = (mission.maximum_nodes + len(required_roles) - 1) // len(required_roles)
        required_roles = (required_roles * repeats)[: mission.maximum_nodes]
    assignments = route_providers(
        providers=providers,
        roles=roles,
        required_roles=required_roles,
        mission_type=mission.mission_type,
        topology_id=mission.topology_id,
        maximum_nodes=mission.maximum_nodes,
        routing_seed=mission.routing_seed,
        repository=repository,
    )
    packets: list[PromptPacket] = []
    for provider, role_id in assignments:
        prompt_text = render_divergence_prompt(mission, role_id, roles[role_id])
        packets.append(
            PromptPacket(
                packet_id=new_identifier("PKT"),
                mission_id=mission.mission_id,
                provider_id=provider.provider_id,
                role_id=role_id,
                round_type=RoundType.DIVERGENCE,
                round_number=1,
                prompt_text=prompt_text,
                prompt_sha256=prompt_sha256(prompt_text),
                source_artifact_ids=(),
                created_at=utc_now(),
            )
        )
    return tuple(packets)
