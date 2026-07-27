"""Immutable proof-carrying contracts emitted by the Doofus research plane."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from .canonical import CanonicalModel

Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class TrialStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABORTED = "aborted"
    INVALID = "invalid"


class AssuranceLevel(str, Enum):
    IDEA = "idea"
    REPLAY = "replay"
    SHADOW = "shadow"
    EXPLORATORY_LIVE = "exploratory_live"
    SCALED_LIVE = "scaled_live"


class CourtDecision(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INCOMPLETE = "incomplete"


class EvidenceDisposition(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    INCOMPLETE = "incomplete"


class MetricObservationV1(CanonicalModel):
    schema_id: Literal["dumbmoney.metric_observation.v1"] = "dumbmoney.metric_observation.v1"
    name: NonEmpty
    value: Decimal
    unit: NonEmpty
    sample_size: int = Field(ge=0)


class ConsequenceProfileV1(CanonicalModel):
    """Potential downstream consequence; this object grants no authority."""

    schema_id: Literal["dumbmoney.consequence_profile.v1"] = "dumbmoney.consequence_profile.v1"
    maximum_external_loss_cents: int = Field(default=0, ge=0)
    external_side_effects: bool = False
    irreversible_change: bool = False
    live_execution_relevance: bool = False


class ResearchMandateV1(CanonicalModel):
    schema_id: Literal["dumbmoney.research_mandate.v1"] = "dumbmoney.research_mandate.v1"
    mandate_id: NonEmpty
    objective: NonEmpty
    hypotheses: tuple[NonEmpty, ...] = Field(min_length=1)
    evaluation_protocol_ref: Digest
    allowed_data_refs: tuple[Digest, ...] = ()
    consequence: ConsequenceProfileV1 = Field(default_factory=ConsequenceProfileV1)
    requested_by: NonEmpty
    created_at: AwareDatetime
    expires_at: AwareDatetime
    capability_profile: Literal["research_only"] = "research_only"
    broker_authority: Literal["none"] = "none"
    credential_access: Literal["none"] = "none"
    capital_signing_authority: Literal["none"] = "none"

    @model_validator(mode="after")
    def _valid_window(self) -> "ResearchMandateV1":
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        if len(set(self.hypotheses)) != len(self.hypotheses):
            raise ValueError("hypotheses must be unique")
        if len(set(self.allowed_data_refs)) != len(self.allowed_data_refs):
            raise ValueError("allowed_data_refs must be unique")
        return self


class TrialReceiptV1(CanonicalModel):
    schema_id: Literal["dumbmoney.trial_receipt.v1"] = "dumbmoney.trial_receipt.v1"
    trial_id: NonEmpty
    mandate_hash: Digest
    candidate_hash: Digest
    lineage_cluster_id: Digest
    parent_candidate_hashes: tuple[Digest, ...] = ()
    status: TrialStatus
    started_at: AwareDatetime
    completed_at: AwareDatetime
    evaluator_ref: Digest
    metrics: tuple[MetricObservationV1, ...] = ()
    artifact_refs: tuple[Digest, ...] = ()
    failure_class: NonEmpty | None = None
    failure_reason: NonEmpty | None = None
    broker_authority: Literal["none"] = "none"
    credential_access: Literal["none"] = "none"
    capital_signing_authority: Literal["none"] = "none"

    @model_validator(mode="after")
    def _validate_outcome(self) -> "TrialReceiptV1":
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        if self.status is TrialStatus.SUCCEEDED:
            if self.failure_class is not None or self.failure_reason is not None:
                raise ValueError("successful trials cannot declare a failure")
        elif self.failure_class is None or self.failure_reason is None:
            raise ValueError("unsuccessful trials must preserve failure class and reason")
        if len(set(self.parent_candidate_hashes)) != len(self.parent_candidate_hashes):
            raise ValueError("parent_candidate_hashes must be unique")
        if len(set(self.artifact_refs)) != len(self.artifact_refs):
            raise ValueError("artifact_refs must be unique")
        return self


class AlphaPassportV1(CanonicalModel):
    schema_id: Literal["dumbmoney.research_alpha_passport.v1"] = (
        "dumbmoney.research_alpha_passport.v1"
    )
    passport_id: NonEmpty
    candidate_hash: Digest
    lineage_cluster_id: Digest
    parent_candidate_hashes: tuple[Digest, ...] = ()
    research_mandate_hashes: tuple[Digest, ...] = Field(min_length=1)
    trial_receipt_hashes: tuple[Digest, ...] = Field(min_length=1)
    failed_trial_receipt_hashes: tuple[Digest, ...] = ()
    trial_registry_stream_id: NonEmpty
    trial_registry_sequence: int = Field(ge=1)
    trial_registry_head_hash: Digest
    source_bundle_ref: Digest
    assurance_level: AssuranceLevel
    created_at: AwareDatetime
    capability_profile: Literal["candidate_only"] = "candidate_only"
    broker_authority: Literal["none"] = "none"
    credential_access: Literal["none"] = "none"
    capital_signing_authority: Literal["none"] = "none"

    @model_validator(mode="after")
    def _validate_disclosures(self) -> "AlphaPassportV1":
        receipts = set(self.trial_receipt_hashes)
        failures = set(self.failed_trial_receipt_hashes)
        if len(receipts) != len(self.trial_receipt_hashes):
            raise ValueError("trial receipt hashes must be unique")
        if len(failures) != len(self.failed_trial_receipt_hashes):
            raise ValueError("failed trial receipt hashes must be unique")
        if not failures.issubset(receipts):
            raise ValueError("failed trial receipts must be included in all trial receipts")
        return self


CourtName = Literal["integrity", "statistics", "economics", "adversarial_operations"]


class CourtFindingV1(CanonicalModel):
    schema_id: Literal["dumbmoney.court_finding.v1"] = "dumbmoney.court_finding.v1"
    court: CourtName
    decision: CourtDecision
    check_ids: tuple[NonEmpty, ...] = ()
    reasons: tuple[NonEmpty, ...] = ()
    evidence_hashes: tuple[Digest, ...] = ()
    evaluated_at: AwareDatetime
    evaluator_id: NonEmpty


class EvidenceVerdictV1(CanonicalModel):
    schema_id: Literal["dumbmoney.research_evidence_verdict.v1"] = (
        "dumbmoney.research_evidence_verdict.v1"
    )
    verdict_id: NonEmpty
    passport_hash: Digest
    court_findings: tuple[CourtFindingV1, ...] = Field(min_length=4, max_length=4)
    disposition: EvidenceDisposition
    required_assurance: AssuranceLevel
    observed_assurance: AssuranceLevel
    evaluated_at: AwareDatetime
    broker_authority: Literal["none"] = "none"
    credential_access: Literal["none"] = "none"
    capital_signing_authority: Literal["none"] = "none"

    @model_validator(mode="after")
    def _all_courts_once(self) -> "EvidenceVerdictV1":
        expected = {"integrity", "statistics", "economics", "adversarial_operations"}
        actual = {finding.court for finding in self.court_findings}
        if actual != expected or len(actual) != len(self.court_findings):
            raise ValueError("court_findings must contain each deterministic court exactly once")
        return self


def utc_datetime(value: str) -> datetime:
    """Small fixture/helper API that rejects naive timestamps via the models."""

    return datetime.fromisoformat(value.replace("Z", "+00:00"))
