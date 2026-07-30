"""Frozen, versioned data contracts for Doofus Agora."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0.0"


class AgoraModel(BaseModel):
    """Strict immutable base model used by every public Agora contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ExecutionMode(StrEnum):
    ATTENDED = "ATTENDED"
    ASSISTED = "ASSISTED"
    AUTONOMOUS_ALLOWED = "AUTONOMOUS_ALLOWED"
    API_OPTIONAL = "API_OPTIONAL"


class TermsStatus(StrEnum):
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    CURRENT = "CURRENT"
    STALE = "STALE"
    BLOCKED = "BLOCKED"


class ContextClass(StrEnum):
    PUBLIC = "PUBLIC"
    SANITIZED_INTERNAL = "SANITIZED_INTERNAL"
    SECRET = "SECRET"


class MissionStage(StrEnum):
    DRAFT = "DRAFT"
    SANITIZED = "SANITIZED"
    PACKETS_READY = "PACKETS_READY"
    COLLECTING = "COLLECTING"
    DEBATING = "DEBATING"
    VERIFYING = "VERIFYING"
    FORMALIZED = "FORMALIZED"
    EXPERIMENT_READY = "EXPERIMENT_READY"
    EXPERIMENTED = "EXPERIMENTED"
    DECIDED = "DECIDED"
    ATTRIBUTED = "ATTRIBUTED"
    BLOCKED = "BLOCKED"
    ABSTAINED = "ABSTAINED"
    ARCHIVED = "ARCHIVED"


class RoundType(StrEnum):
    DIVERGENCE = "DIVERGENCE"
    CRITIQUE = "CRITIQUE"
    SYNTHESIS = "SYNTHESIS"


class EvidenceStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNVERIFIED = "UNVERIFIED"
    MISSING = "MISSING"
    AMBIGUOUS = "AMBIGUOUS"


class NoveltyClass(StrEnum):
    REDISCOVERY = "REDISCOVERY"
    KNOWN_COMBINATION = "KNOWN_COMBINATION"
    NOVEL_ADAPTATION = "NOVEL_ADAPTATION"
    NOVEL_COMBINATION = "NOVEL_COMBINATION"
    POSSIBLY_NOVEL_MECHANISM = "POSSIBLY_NOVEL_MECHANISM"
    NOVELTY_UNVERIFIED = "NOVELTY_UNVERIFIED"


class DecisionAction(StrEnum):
    ACT = "ACT"
    BUILD_PROTOTYPE = "BUILD_PROTOTYPE"
    RUN_EXPERIMENT = "RUN_EXPERIMENT"
    DEFER = "DEFER"
    REJECT = "REJECT"
    ABSTAIN = "ABSTAIN"


class ProviderNode(AgoraModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    provider_id: str
    display_name: str
    execution_mode: ExecutionMode
    capabilities: tuple[str, ...]
    weaknesses: tuple[str, ...]
    terms_status: TermsStatus
    automated_submit_allowed: bool
    automated_extract_allowed: bool
    free_access_status: str
    quota_state: str
    cooldown_until: str | None
    core_enabled: bool
    historical_quality: dict[str, float] = Field(default_factory=dict)
    correlation_groups: tuple[str, ...] = ()


class TermsDecision(AgoraModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    provider_id: str
    source_url: str
    document_sha256: str
    reviewed_at: str
    reviewer: str
    status: TermsStatus
    automated_submit_allowed: bool
    automated_extract_allowed: bool
    notes: str

    @field_validator("document_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value.lower()):
            raise ValueError("document_sha256 must be a 64-character hexadecimal SHA-256 digest")
        return value.lower()


class SanitizationFinding(AgoraModel):
    category: str
    match_sha256: str
    start: int
    end: int


class SanitizationReceipt(AgoraModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    receipt_id: str
    context_class: ContextClass
    original_sha256: str
    sanitized_sha256: str
    findings: tuple[SanitizationFinding, ...]
    operator_approved: bool
    created_at: str


class SwarmMission(AgoraModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    mission_id: str
    mission_type: str
    objective: str
    decision_to_inform: str
    target_project: str
    context: str
    context_class: ContextClass
    known_evidence: tuple[str, ...]
    hard_constraints: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    success_metrics: tuple[str, ...]
    falsification_conditions: tuple[str, ...]
    open_questions: tuple[str, ...]
    candidate_test_cases: tuple[dict[str, Any], ...]
    benchmark_baseline_score: float = Field(ge=0.0)
    maximum_nodes: int = Field(ge=3, le=10)
    maximum_rounds: int = Field(ge=1, le=8)
    topology_id: str
    routing_seed: int
    created_at: str

    @field_validator(
        "mission_type",
        "objective",
        "decision_to_inform",
        "target_project",
        "topology_id",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("required mission text fields cannot be empty")
        return value

    @field_validator("candidate_test_cases")
    @classmethod
    def validate_candidate_test_cases(
        cls,
        value: tuple[dict[str, Any], ...],
    ) -> tuple[dict[str, Any], ...]:
        for index, case in enumerate(value):
            if not isinstance(case.get("input"), dict) or "expected" not in case:
                raise ValueError(
                    f"candidate_test_cases[{index}] requires an input mapping and expected value"
                )
        return value


class PromptPacket(AgoraModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    packet_id: str
    mission_id: str
    provider_id: str
    role_id: str
    round_type: RoundType
    round_number: int = Field(ge=1)
    prompt_text: str
    prompt_sha256: str
    source_artifact_ids: tuple[str, ...]
    created_at: str


class ResponseArtifact(AgoraModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    artifact_id: str
    packet_id: str
    mission_id: str
    provider_id: str
    role_id: str
    round_type: RoundType
    round_number: int
    prompt_sha256: str
    output_sha256: str
    created_at: str
    raw_output_path: str
    extracted_claims: tuple[str, ...]
    extracted_ideas: tuple[str, ...]
    citations: tuple[str, ...]
    code_blocks: tuple[str, ...]
    confidence: float = Field(ge=0.0, le=1.0)
    provider_identity_hidden_from_judges: bool
    untrusted_external_content: Literal[True] = True


class CritiqueCard(AgoraModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    critique_id: str
    mission_id: str
    reviewer_provider_id: str
    proposal_aliases: tuple[str, ...]
    packet_id: str
    created_at: str


class EvidenceRecord(AgoraModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    evidence_id: str
    claim: str
    status: EvidenceStatus
    source_url: str | None
    source_sha256: str | None
    excerpt_sha256: str | None
    source_kind: str
    detail: str
    checked_at: str


class IdeaCard(AgoraModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    idea_id: str
    mission_id: str
    problem_addressed: str
    core_mechanism: str
    rationale: str
    closest_prior_art: tuple[str, ...]
    prior_art_difference: str
    required_assumptions: tuple[str, ...]
    expected_benefit: str
    complexity: str
    failure_modes: tuple[str, ...]
    falsification_condition: str
    minimum_viable_experiment: str
    source_artifact_ids: tuple[str, ...]
    confidence: float = Field(ge=0.0, le=1.0)
    novelty_status: NoveltyClass
    evidence_records: tuple[EvidenceRecord, ...]
    cluster_id: str
    minority_preserved: bool


class ProblemCard(AgoraModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    problem_id: str
    observed_condition: str
    why_it_matters: str
    evidence: tuple[str, ...]
    affected_parties: tuple[str, ...]
    current_approaches: tuple[str, ...]
    approach_failures: tuple[str, ...]
    hidden_assumptions: tuple[str, ...]
    expected_leverage: float = Field(ge=0.0, le=1.0)
    tractability: float = Field(ge=0.0, le=1.0)
    novelty: NoveltyClass
    proposed_measurement: str
    falsification_test: str
    candidate_solution_families: tuple[str, ...]
    category: str


class CandidateSpec(AgoraModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    candidate_id: str
    mission_id: str
    idea_id: str
    algorithm_name: str
    problem_definition: str
    input_contract: str
    output_contract: str
    state_representation: str
    invariants: tuple[str, ...]
    pseudocode: str
    time_complexity: str
    space_complexity: str
    concurrency_model: str
    expected_failure_modes: tuple[str, ...]
    test_cases: tuple[dict[str, Any], ...]
    benchmark_baseline: str
    benchmark_baseline_score: float = Field(ge=0.0)
    ablation_plan: tuple[str, ...]
    external_dependencies: tuple[str, ...]
    license_concerns: tuple[str, ...]
    source_artifact_ids: tuple[str, ...]

    @field_validator("test_cases")
    @classmethod
    def validate_test_cases(
        cls,
        value: tuple[dict[str, Any], ...],
    ) -> tuple[dict[str, Any], ...]:
        for index, case in enumerate(value):
            if not isinstance(case.get("input"), dict) or "expected" not in case:
                raise ValueError(
                    f"test_cases[{index}] requires an input mapping and expected value"
                )
        return value


class ExperimentResult(AgoraModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    experiment_id: str
    candidate_id: str
    implementation_hashes: tuple[str, str]
    test_provider_independent: bool
    sandbox_kind: str
    network_disabled: bool
    source_repo_untouched: bool
    dependencies_verified: bool
    compile_passed: bool
    tests_passed: bool
    differential_match: bool
    benchmark_score: float
    baseline_score: float
    ablation_results: tuple[dict[str, Any], ...]
    stdout_sha256: str
    stderr_sha256: str
    duration_ms: float
    status: str
    created_at: str


class DecisionRecord(AgoraModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    decision_id: str
    mission_id: str
    action: DecisionAction
    selected_candidate_ids: tuple[str, ...]
    minority_candidate_ids: tuple[str, ...]
    rejected_candidate_ids: tuple[str, ...]
    hard_gate_failures: tuple[str, ...]
    pareto_frontier: tuple[str, ...]
    expected_regret: float = Field(ge=0.0)
    value_of_information: float = Field(ge=0.0)
    confidence: float = Field(ge=0.0, le=1.0)
    authority_effect: Literal["SUBMIT_TO_EXISTING_DOOFUS_GATES_ONLY"]
    created_at: str


class OutcomeAttribution(AgoraModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    mission_id: str
    candidate_id: str
    contributing_provider_ids: tuple[str, ...]
    contributing_role_ids: tuple[str, ...]
    contributing_prompt_ids: tuple[str, ...]
    debate_topology_id: str
    test_results: dict[str, Any]
    promotion_result: str
    measured_value: float
    decisive_contributions: tuple[str, ...]
    misleading_contributions: tuple[str, ...]
    created_at: str


class ProviderOutcome(AgoraModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    provider_id: str
    mission_type: str
    role_id: str
    topology_id: str
    reward: float = Field(ge=0.0, le=1.0)
    verified_claim_rate: float = Field(ge=0.0, le=1.0)
    novelty_survival_rate: float = Field(ge=0.0, le=1.0)
    critique_rescue_rate: float = Field(ge=0.0, le=1.0)
    hallucination_rate: float = Field(ge=0.0, le=1.0)
    correlation_score: float = Field(ge=0.0, le=1.0)
    quota_efficiency: float = Field(ge=0.0, le=1.0)
    created_at: str
