"""Bounded, restartable autonomous research loop for DumbMoney.

The loop can autonomously retain, demote, or quarantine *research* candidates.
It cannot promote a candidate to live trading, sign capital, access credentials,
or call a broker.  Model and trial execution are injected protocols, allowing
the authority plane to keep all provider and sandbox machinery outside Doofus.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Protocol

from pydantic import AwareDatetime, Field, model_validator

from .assurance import required_assurance
from .budget import (
    BudgetExceeded,
    BudgetStateError,
    BudgetCategory,
    DailyExternalBudget,
    ExternalBudgetLeaseV1,
)
from .canonical import CanonicalModel, canonical_json, content_hash
from .contracts import (
    AssuranceLevel,
    Digest,
    EvidenceDisposition,
    EvidenceVerdictV1,
    MetricObservationV1,
    NonEmpty,
    ResearchMandateV1,
    TrialReceiptV1,
    TrialStatus,
)
from .courts import (
    AdversarialOperationsEvidenceV1,
    CourtContext,
    EconomicEvidenceV1,
    EvidenceCourtSuite,
    StatisticalEvidenceV1,
)
from .journal import DuplicateRecordError, HashChainJournal
from .lineage import (
    ArchiveAdmissionV1,
    ArchiveDimensionV1,
    CandidateRecordV1,
    LineageMembershipV1,
    LineageArchive,
    QualityDiversityArchive,
)
from .registry import TrialRegistry


class ResearchLoopError(RuntimeError):
    pass


class CycleIdempotencyConflict(ResearchLoopError):
    pass


class ResearchObservationV1(CanonicalModel):
    schema_id: Literal["dumbmoney.research_observation.v1"] = (
        "dumbmoney.research_observation.v1"
    )
    observation_id: NonEmpty
    mandate_hash: Digest
    as_of: AwareDatetime
    source_refs: tuple[Digest, ...]
    observation_artifact_ref: Digest
    point_in_time: bool
    capability_profile: Literal["read_only_research"] = "read_only_research"
    broker_authority: Literal["none"] = "none"
    credential_access: Literal["none"] = "none"
    capital_signing_authority: Literal["none"] = "none"


class ObservationRequestV1(CanonicalModel):
    schema_id: Literal["dumbmoney.observation_request.v1"] = (
        "dumbmoney.observation_request.v1"
    )
    request_id: NonEmpty
    cycle_id: NonEmpty
    mandate_hash: Digest
    as_of: AwareDatetime
    capability_profile: Literal["read_only_research"] = "read_only_research"
    broker_authority: Literal["none"] = "none"
    credential_access: Literal["none"] = "none"
    capital_signing_authority: Literal["none"] = "none"


class ProposalRequestV1(CanonicalModel):
    schema_id: Literal["dumbmoney.proposal_request.v1"] = "dumbmoney.proposal_request.v1"
    request_id: NonEmpty
    cycle_id: NonEmpty
    mandate_hash: Digest
    observation_hash: Digest
    parent_candidate_hashes: tuple[Digest, ...] = ()
    budget_category: BudgetCategory
    maximum_model_cost_microusd: int = Field(gt=0)
    capability_profile: Literal["candidate_generation_only"] = "candidate_generation_only"
    broker_authority: Literal["none"] = "none"
    credential_access: Literal["none"] = "none"
    capital_signing_authority: Literal["none"] = "none"


class CandidateProposalV1(CanonicalModel):
    schema_id: Literal["dumbmoney.candidate_proposal.v1"] = (
        "dumbmoney.candidate_proposal.v1"
    )
    proposal_id: NonEmpty
    request_hash: Digest
    source_bundle_ref: Digest
    origin_fingerprint: Digest
    parent_candidate_hashes: tuple[Digest, ...] = ()
    mutation_operator: NonEmpty
    behavior_cell: tuple[ArchiveDimensionV1, ...] = Field(min_length=1)
    rationale_artifact_ref: Digest
    actual_model_cost_microusd: int = Field(ge=0)
    generated_at: AwareDatetime
    capability_profile: Literal["candidate_only"] = "candidate_only"
    broker_authority: Literal["none"] = "none"
    credential_access: Literal["none"] = "none"
    capital_signing_authority: Literal["none"] = "none"

    @property
    def candidate_hash(self) -> str:
        # The source bundle is content-addressed, so it is the candidate identity.
        return self.source_bundle_ref


class TrialRunRequestV1(CanonicalModel):
    schema_id: Literal["dumbmoney.trial_run_request.v1"] = (
        "dumbmoney.trial_run_request.v1"
    )
    request_id: NonEmpty
    cycle_id: NonEmpty
    trial_id: NonEmpty
    mandate_hash: Digest
    proposal_hash: Digest
    candidate_hash: Digest
    lineage_cluster_id: Digest
    timeout_seconds: int = Field(gt=0, le=3_600)
    capability_profile: Literal["sealed_sandbox_research"] = "sealed_sandbox_research"
    network_access: Literal["none"] = "none"
    broker_authority: Literal["none"] = "none"
    credential_access: Literal["none"] = "none"
    capital_signing_authority: Literal["none"] = "none"


class TrialExecutionV1(CanonicalModel):
    schema_id: Literal["dumbmoney.trial_execution.v1"] = "dumbmoney.trial_execution.v1"
    request_hash: Digest
    status: TrialStatus
    started_at: AwareDatetime
    completed_at: AwareDatetime
    evaluator_ref: Digest
    metrics: tuple[MetricObservationV1, ...] = ()
    artifact_refs: tuple[Digest, ...] = ()
    failure_class: NonEmpty | None = None
    failure_reason: NonEmpty | None = None
    statistics: StatisticalEvidenceV1
    economics: EconomicEvidenceV1
    operations: AdversarialOperationsEvidenceV1
    quality_micros: int
    novelty_micros: int = Field(ge=0)
    broker_authority: Literal["none"] = "none"
    credential_access: Literal["none"] = "none"
    capital_signing_authority: Literal["none"] = "none"

    @model_validator(mode="after")
    def _outcome_is_complete(self) -> "TrialExecutionV1":
        if self.completed_at < self.started_at:
            raise ValueError("trial completion cannot precede its start")
        if self.status is TrialStatus.SUCCEEDED:
            if self.failure_class is not None or self.failure_reason is not None:
                raise ValueError("successful execution cannot include failure details")
        elif self.failure_class is None or self.failure_reason is None:
            raise ValueError("unsuccessful execution must preserve failure details")
        return self


class ResearchCycleRequestV1(CanonicalModel):
    schema_id: Literal["dumbmoney.research_cycle_request.v1"] = (
        "dumbmoney.research_cycle_request.v1"
    )
    cycle_id: NonEmpty
    mandate: ResearchMandateV1
    budget_category: BudgetCategory
    maximum_model_cost_microusd: int = Field(gt=0)
    parent_candidate_hashes: tuple[Digest, ...] = ()
    logical_started_at: AwareDatetime
    trial_timeout_seconds: int = Field(default=300, gt=0, le=3_600)
    capability_profile: Literal["bounded_research_loop"] = "bounded_research_loop"
    broker_authority: Literal["none"] = "none"
    credential_access: Literal["none"] = "none"
    capital_signing_authority: Literal["none"] = "none"

    @model_validator(mode="after")
    def _mandate_is_current(self) -> "ResearchCycleRequestV1":
        if not self.mandate.created_at <= self.logical_started_at < self.mandate.expires_at:
            raise ValueError("research mandate is not active at cycle start")
        return self


CandidateAutomaticAction = Literal["retain_research_only", "demote", "quarantine"]


class CandidateGovernanceV1(CanonicalModel):
    schema_id: Literal["dumbmoney.candidate_governance.v1"] = (
        "dumbmoney.candidate_governance.v1"
    )
    candidate_hash: Digest
    passport_hash: Digest
    verdict_hash: Digest
    automatic_action: CandidateAutomaticAction
    reasons: tuple[NonEmpty, ...]
    eligible_for_live_promotion: Literal[False] = False
    broker_authority: Literal["none"] = "none"
    credential_access: Literal["none"] = "none"
    capital_signing_authority: Literal["none"] = "none"


CycleStatus = Literal[
    "research_retained",
    "demoted",
    "quarantined",
    "budget_exhausted",
    "stopped",
    "failed",
]

ResearchCycleStage = Literal[
    "started",
    "observation_recorded",
    "proposal_request_recorded",
    "budget_reserved",
    "proposal_recorded",
    "budget_settled",
    "candidate_registered",
    "trial_recorded",
    "passport_issued",
    "verdict_recorded",
    "archive_recorded",
    "governance_recorded",
    "terminal",
]


class ResearchCycleResultV1(CanonicalModel):
    schema_id: Literal["dumbmoney.research_cycle_result.v1"] = (
        "dumbmoney.research_cycle_result.v1"
    )
    cycle_id: NonEmpty
    status: CycleStatus
    request_hash: Digest
    observation_hash: Digest | None = None
    proposal_hash: Digest | None = None
    trial_receipt_hash: Digest | None = None
    passport_hash: Digest | None = None
    verdict_hash: Digest | None = None
    archive_admission_hash: Digest | None = None
    governance: CandidateGovernanceV1 | None = None
    reasons: tuple[NonEmpty, ...]
    started_at: AwareDatetime
    completed_at: AwareDatetime
    eligible_for_live_promotion: Literal[False] = False
    broker_authority: Literal["none"] = "none"
    credential_access: Literal["none"] = "none"
    capital_signing_authority: Literal["none"] = "none"


class ResearchCycleEventV1(CanonicalModel):
    schema_id: Literal["dumbmoney.research_cycle_event.v1"] = (
        "dumbmoney.research_cycle_event.v1"
    )
    event_id: NonEmpty
    cycle_id: NonEmpty
    stage: ResearchCycleStage
    payload_json: NonEmpty
    payload_hash: Digest
    logical_at: AwareDatetime
    eligible_for_live_promotion: Literal[False] = False
    broker_authority: Literal["none"] = "none"
    credential_access: Literal["none"] = "none"
    capital_signing_authority: Literal["none"] = "none"

    @model_validator(mode="after")
    def _payload_matches(self) -> "ResearchCycleEventV1":
        try:
            payload = json.loads(self.payload_json)
        except json.JSONDecodeError as exc:
            raise ValueError("payload_json must be valid JSON") from exc
        if content_hash(payload) != self.payload_hash:
            raise ValueError("payload hash mismatch")
        return self


class ResearchCycleJournal:
    STREAM_ID = "dumbmoney.autonomous_research_loop.v1"

    def __init__(self, path: Path | str) -> None:
        self.journal = HashChainJournal(path, stream_id=self.STREAM_ID)

    def events(self, cycle_id: str | None = None) -> tuple[ResearchCycleEventV1, ...]:
        events = tuple(
            ResearchCycleEventV1.model_validate(record["payload"])
            for record in self.journal.read_verified()
        )
        if cycle_id is None:
            return events
        return tuple(event for event in events if event.cycle_id == cycle_id)

    def stage(
        self,
        cycle_id: str,
        stage: ResearchCycleStage,
    ) -> ResearchCycleEventV1 | None:
        matches = [event for event in self.events(cycle_id) if event.stage == stage]
        if len(matches) > 1:
            raise CycleIdempotencyConflict(f"cycle has duplicate stage: {stage}")
        return matches[0] if matches else None

    def payload(
        self,
        cycle_id: str,
        stage: ResearchCycleStage,
    ) -> dict[str, Any] | None:
        event = self.stage(cycle_id, stage)
        return json.loads(event.payload_json) if event else None

    def record(
        self,
        *,
        cycle_id: str,
        stage: ResearchCycleStage,
        value: CanonicalModel | dict[str, Any],
        logical_at: datetime,
    ) -> ResearchCycleEventV1:
        payload = value.model_dump(mode="json") if isinstance(value, CanonicalModel) else value
        payload_json = canonical_json(payload)
        existing = self.stage(cycle_id, stage)
        if existing is not None:
            if existing.payload_json != payload_json:
                raise CycleIdempotencyConflict(f"cycle stage changed on replay: {stage}")
            return existing
        event = ResearchCycleEventV1(
            event_id=f"{cycle_id}:{stage}",
            cycle_id=cycle_id,
            stage=stage,
            payload_json=payload_json,
            payload_hash=content_hash(payload),
            logical_at=logical_at,
        )
        self.journal.append(
            event.model_dump(mode="json"),
            unique_key="event_id",
            unique_value=event.event_id,
        )
        return event


class ObservationSource(Protocol):
    def observe(self, request: ObservationRequestV1) -> ResearchObservationV1:
        """Return one point-in-time, read-only observation."""


class BudgetedModelGateway(Protocol):
    def propose(self, request: ProposalRequestV1) -> CandidateProposalV1:
        """Honor request_id idempotently and never exceed its cost ceiling."""


class SealedTrialRunner(Protocol):
    def run(self, request: TrialRunRequestV1) -> TrialExecutionV1:
        """Honor request_id idempotently inside a credential-free sandbox."""


class AutonomousResearchLoop:
    """One-candidate-per-cycle autonomous harness with deterministic recovery."""

    def __init__(
        self,
        *,
        cycle_journal: ResearchCycleJournal,
        budget: DailyExternalBudget,
        lineage: LineageArchive,
        trials: TrialRegistry,
        archive: QualityDiversityArchive,
        observations: ObservationSource,
        model_gateway: BudgetedModelGateway,
        trial_runner: SealedTrialRunner,
        courts: EvidenceCourtSuite | None = None,
        sealed_evaluator_ref: str,
        court_evaluator_id: str = "dumbmoney-deterministic-courts-v1",
        monotonic_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cycle_journal = cycle_journal
        self.budget = budget
        self.lineage = lineage
        self.trials = trials
        self.archive = archive
        self.observations = observations
        self.model_gateway = model_gateway
        self.trial_runner = trial_runner
        self.courts = courts or EvidenceCourtSuite()
        self.sealed_evaluator_ref = sealed_evaluator_ref
        self.court_evaluator_id = court_evaluator_id
        self.monotonic_fn = monotonic_fn

    @staticmethod
    def _stopped(
        *,
        stop_requested: Callable[[], bool],
        deadline_monotonic: float | None,
        monotonic_fn: Callable[[], float],
    ) -> str | None:
        if stop_requested():
            return "operator_stop_requested"
        if deadline_monotonic is not None and monotonic_fn() >= deadline_monotonic:
            return "cycle_deadline_exhausted"
        return None

    def _terminal(
        self,
        request: ResearchCycleRequestV1,
        *,
        status: CycleStatus,
        reasons: tuple[str, ...],
        completed_at: datetime,
        observation_hash: str | None = None,
        proposal_hash: str | None = None,
        trial_receipt_hash: str | None = None,
        passport_hash: str | None = None,
        verdict_hash: str | None = None,
        archive_admission_hash: str | None = None,
        governance: CandidateGovernanceV1 | None = None,
    ) -> ResearchCycleResultV1:
        result = ResearchCycleResultV1(
            cycle_id=request.cycle_id,
            status=status,
            request_hash=request.content_hash,
            observation_hash=observation_hash,
            proposal_hash=proposal_hash,
            trial_receipt_hash=trial_receipt_hash,
            passport_hash=passport_hash,
            verdict_hash=verdict_hash,
            archive_admission_hash=archive_admission_hash,
            governance=governance,
            reasons=reasons,
            started_at=request.logical_started_at,
            completed_at=completed_at,
        )
        self.cycle_journal.record(
            cycle_id=request.cycle_id,
            stage="terminal",
            value=result,
            logical_at=completed_at,
        )
        return result

    def _terminal_if_present(
        self,
        request: ResearchCycleRequestV1,
    ) -> ResearchCycleResultV1 | None:
        payload = self.cycle_journal.payload(request.cycle_id, "terminal")
        if payload is None:
            return None
        result = ResearchCycleResultV1.model_validate(payload)
        if result.request_hash != request.content_hash:
            raise CycleIdempotencyConflict("cycle ID was reused with a different request")
        return result

    def _ensure_started(self, request: ResearchCycleRequestV1) -> None:
        existing = self.cycle_journal.payload(request.cycle_id, "started")
        if existing is not None and existing != request.model_dump(mode="json"):
            raise CycleIdempotencyConflict("cycle ID was reused with a different request")
        self.cycle_journal.record(
            cycle_id=request.cycle_id,
            stage="started",
            value=request,
            logical_at=request.logical_started_at,
        )

    def _ensure_budget_reservation(
        self,
        request: ResearchCycleRequestV1,
        lease: ExternalBudgetLeaseV1,
    ) -> None:
        lease_events = tuple(
            event for event in self.budget.events() if event.lease_id == lease.lease_id
        )
        if not lease_events:
            reservation = self.budget.reserve(
                lease,
                event_id=f"{request.cycle_id}:budget:reserved",
                occurred_at=request.logical_started_at,
            )
        else:
            reservation = lease_events[0]
            if (
                reservation.event_type != "reserved"
                or reservation.category != lease.category
                or reservation.reserved_microusd != lease.maximum_microusd
            ):
                raise CycleIdempotencyConflict("budget reservation differs on replay")
        self.cycle_journal.record(
            cycle_id=request.cycle_id,
            stage="budget_reserved",
            value=reservation,
            logical_at=request.logical_started_at,
        )

    def _ensure_budget_settled(
        self,
        request: ResearchCycleRequestV1,
        proposal: CandidateProposalV1,
    ) -> None:
        lease_id = f"{request.cycle_id}:model-budget"
        lease_events = tuple(event for event in self.budget.events() if event.lease_id == lease_id)
        settlements = [event for event in lease_events if event.event_type == "settled"]
        if not settlements:
            settlement = self.budget.settle(
                lease_id=lease_id,
                event_id=f"{request.cycle_id}:budget:settled",
                actual_microusd=proposal.actual_model_cost_microusd,
                occurred_at=proposal.generated_at,
            )
        else:
            settlement = settlements[0]
            if settlement.actual_microusd != proposal.actual_model_cost_microusd:
                raise CycleIdempotencyConflict("model cost differs on replay")
        self.cycle_journal.record(
            cycle_id=request.cycle_id,
            stage="budget_settled",
            value=settlement,
            logical_at=proposal.generated_at,
        )

    def _ensure_candidate(
        self,
        request: ResearchCycleRequestV1,
        proposal: CandidateProposalV1,
    ) -> LineageMembershipV1:
        candidate = CandidateRecordV1(
            candidate_hash=proposal.candidate_hash,
            origin_fingerprint=proposal.origin_fingerprint,
            parent_candidate_hashes=proposal.parent_candidate_hashes,
            mutation_operator=proposal.mutation_operator,
            behavior_cell=proposal.behavior_cell,
            source_bundle_ref=proposal.source_bundle_ref,
            created_at=proposal.generated_at,
        )
        try:
            membership = self.lineage.membership_for(candidate.candidate_hash)
            if membership.candidate != candidate:
                raise CycleIdempotencyConflict("candidate content differs on replay")
        except KeyError:
            membership = self.lineage.register(candidate)
        self.cycle_journal.record(
            cycle_id=request.cycle_id,
            stage="candidate_registered",
            value=membership,
            logical_at=proposal.generated_at,
        )
        return membership

    def _ensure_trial_receipt(
        self,
        request: ResearchCycleRequestV1,
        membership: LineageMembershipV1,
        execution: TrialExecutionV1,
    ) -> TrialReceiptV1:
        receipt = TrialReceiptV1(
            trial_id=f"{request.cycle_id}:trial",
            mandate_hash=request.mandate.content_hash,
            candidate_hash=membership.candidate.candidate_hash,
            lineage_cluster_id=membership.lineage_cluster_id,
            parent_candidate_hashes=membership.candidate.parent_candidate_hashes,
            status=execution.status,
            started_at=execution.started_at,
            completed_at=execution.completed_at,
            evaluator_ref=execution.evaluator_ref,
            metrics=execution.metrics,
            artifact_refs=execution.artifact_refs,
            failure_class=execution.failure_class,
            failure_reason=execution.failure_reason,
        )
        existing = [
            item for item in self.trials.receipts() if item.trial_id == receipt.trial_id
        ]
        if existing:
            if len(existing) != 1 or existing[0] != receipt:
                raise CycleIdempotencyConflict("trial receipt differs on replay")
            receipt = existing[0]
        else:
            self.trials.append(receipt)
        self.cycle_journal.record(
            cycle_id=request.cycle_id,
            stage="trial_recorded",
            value={"receipt": receipt.model_dump(mode="json"), "execution": execution.model_dump(mode="json")},
            logical_at=execution.completed_at,
        )
        return receipt

    def _aborted_execution(
        self,
        trial_request: TrialRunRequestV1,
        *,
        logical_at: datetime,
        reason: str,
    ) -> TrialExecutionV1:
        return TrialExecutionV1(
            request_hash=trial_request.content_hash,
            status=TrialStatus.ABORTED,
            started_at=logical_at,
            completed_at=logical_at,
            evaluator_ref=self.sealed_evaluator_ref,
            failure_class="loop_control_stop",
            failure_reason=reason,
            statistics=StatisticalEvidenceV1(
                independent_trial_count=0,
                holdout_sample_size=0,
            ),
            economics=EconomicEvidenceV1(),
            operations=AdversarialOperationsEvidenceV1(),
            quality_micros=0,
            novelty_micros=0,
        )

    def _failed_execution(
        self,
        trial_request: TrialRunRequestV1,
        *,
        logical_at: datetime,
        exc: Exception,
    ) -> TrialExecutionV1:
        return TrialExecutionV1(
            request_hash=trial_request.content_hash,
            status=TrialStatus.FAILED,
            started_at=logical_at,
            completed_at=logical_at,
            evaluator_ref=self.sealed_evaluator_ref,
            failure_class=f"sealed_runner_{type(exc).__name__}",
            failure_reason="sealed trial runner failed; exception details remain in sandbox logs",
            statistics=StatisticalEvidenceV1(
                independent_trial_count=0,
                holdout_sample_size=0,
            ),
            economics=EconomicEvidenceV1(),
            operations=AdversarialOperationsEvidenceV1(
                sandbox_containment_passed=True,
                credential_scan_passed=True,
            ),
            quality_micros=0,
            novelty_micros=0,
        )

    def _complete_candidate(
        self,
        request: ResearchCycleRequestV1,
        *,
        observation: ResearchObservationV1,
        proposal: CandidateProposalV1,
        membership: LineageMembershipV1,
        execution: TrialExecutionV1,
    ) -> ResearchCycleResultV1:
        receipt = self._ensure_trial_receipt(request, membership, execution)
        passport_payload = self.cycle_journal.payload(request.cycle_id, "passport_issued")
        if passport_payload is None:
            passport = self.trials.build_passport(
                passport_id=f"{request.cycle_id}:passport",
                candidate_hash=membership.candidate.candidate_hash,
                lineage_cluster_id=membership.lineage_cluster_id,
                parent_candidate_hashes=membership.candidate.parent_candidate_hashes,
                mandates=(request.mandate,),
                source_bundle_ref=membership.candidate.source_bundle_ref,
                assurance_level=required_assurance(request.mandate.consequence),
                created_at=execution.completed_at,
            )
            self.cycle_journal.record(
                cycle_id=request.cycle_id,
                stage="passport_issued",
                value=passport,
                logical_at=execution.completed_at,
            )
        else:
            from .contracts import AlphaPassportV1

            passport = AlphaPassportV1.model_validate(passport_payload)
            self.trials.verify_passport(passport)

        verdict_payload = self.cycle_journal.payload(request.cycle_id, "verdict_recorded")
        if verdict_payload is None:
            context = CourtContext(
                passport=passport,
                mandates=(request.mandate,),
                trial_registry=self.trials,
                lineage_archive=self.lineage,
                statistics=execution.statistics,
                economics=execution.economics,
                operations=execution.operations,
                evaluated_at=execution.completed_at,
                evaluator_id=self.court_evaluator_id,
            )
            verdict = self.courts.evaluate(context)
            self.cycle_journal.record(
                cycle_id=request.cycle_id,
                stage="verdict_recorded",
                value=verdict,
                logical_at=execution.completed_at,
            )
        else:
            verdict = EvidenceVerdictV1.model_validate(verdict_payload)

        admission: ArchiveAdmissionV1 | None = None
        if (
            execution.status is TrialStatus.SUCCEEDED
            and verdict.disposition is EvidenceDisposition.ACCEPT
        ):
            archive_payload = self.cycle_journal.payload(request.cycle_id, "archive_recorded")
            if archive_payload is None:
                admission_id = f"{request.cycle_id}:archive"
                existing = [
                    item
                    for item in self.archive.admissions()
                    if item.admission_id == admission_id
                ]
                if existing:
                    admission = existing[0]
                else:
                    admission = self.archive.admit(
                        admission_id=admission_id,
                        passport=passport,
                        quality_micros=execution.quality_micros,
                        novelty_micros=execution.novelty_micros,
                        admitted_at=execution.completed_at,
                    )
                self.cycle_journal.record(
                    cycle_id=request.cycle_id,
                    stage="archive_recorded",
                    value=admission,
                    logical_at=execution.completed_at,
                )
            else:
                admission = ArchiveAdmissionV1.model_validate(archive_payload)

        if verdict.disposition is EvidenceDisposition.REJECT:
            action: CandidateAutomaticAction = "demote"
            status: CycleStatus = "demoted"
            reasons: tuple[str, ...] = (
                "deterministic_evidence_court_rejected_candidate",
            )
        elif (
            verdict.disposition is EvidenceDisposition.INCOMPLETE
            or execution.status is not TrialStatus.SUCCEEDED
        ):
            action = "quarantine"
            status = "quarantined"
            reasons = (
                f"trial_status={execution.status.value}",
                f"evidence_disposition={verdict.disposition.value}",
            )
        else:
            action = "retain_research_only"
            status = "research_retained"
            reasons = ("retained_in_research_archive_without_live_or_capital_authority",)
        governance = CandidateGovernanceV1(
            candidate_hash=membership.candidate.candidate_hash,
            passport_hash=passport.content_hash,
            verdict_hash=verdict.content_hash,
            automatic_action=action,
            reasons=reasons,
        )
        self.cycle_journal.record(
            cycle_id=request.cycle_id,
            stage="governance_recorded",
            value=governance,
            logical_at=execution.completed_at,
        )
        return self._terminal(
            request,
            status=status,
            reasons=reasons,
            completed_at=execution.completed_at,
            observation_hash=observation.content_hash,
            proposal_hash=proposal.content_hash,
            trial_receipt_hash=receipt.content_hash,
            passport_hash=passport.content_hash,
            verdict_hash=verdict.content_hash,
            archive_admission_hash=admission.content_hash if admission else None,
            governance=governance,
        )

    def run_cycle(
        self,
        request: ResearchCycleRequestV1,
        *,
        deadline_monotonic: float | None = None,
        stop_requested: Callable[[], bool] = lambda: False,
    ) -> ResearchCycleResultV1:
        terminal = self._terminal_if_present(request)
        if terminal is not None:
            return terminal
        self._ensure_started(request)
        stopped = self._stopped(
            stop_requested=stop_requested,
            deadline_monotonic=deadline_monotonic,
            monotonic_fn=self.monotonic_fn,
        )
        if stopped:
            return self._terminal(
                request,
                status="stopped",
                reasons=(stopped,),
                completed_at=request.logical_started_at,
            )

        observation_payload = self.cycle_journal.payload(
            request.cycle_id, "observation_recorded"
        )
        if observation_payload is None:
            observation_request = ObservationRequestV1(
                request_id=f"{request.cycle_id}:observe",
                cycle_id=request.cycle_id,
                mandate_hash=request.mandate.content_hash,
                as_of=request.logical_started_at,
            )
            try:
                observation = self.observations.observe(observation_request)
            except Exception as exc:
                return self._terminal(
                    request,
                    status="failed",
                    reasons=(f"observation_source_{type(exc).__name__}",),
                    completed_at=request.logical_started_at,
                )
            if observation.mandate_hash != request.mandate.content_hash:
                raise ResearchLoopError("observation references the wrong mandate")
            self.cycle_journal.record(
                cycle_id=request.cycle_id,
                stage="observation_recorded",
                value=observation,
                logical_at=observation.as_of,
            )
        else:
            observation = ResearchObservationV1.model_validate(observation_payload)

        stopped = self._stopped(
            stop_requested=stop_requested,
            deadline_monotonic=deadline_monotonic,
            monotonic_fn=self.monotonic_fn,
        )
        if stopped:
            return self._terminal(
                request,
                status="stopped",
                reasons=(stopped,),
                completed_at=observation.as_of,
                observation_hash=observation.content_hash,
            )

        proposal_request_payload = self.cycle_journal.payload(
            request.cycle_id, "proposal_request_recorded"
        )
        if proposal_request_payload is None:
            proposal_request = ProposalRequestV1(
                request_id=f"{request.cycle_id}:propose",
                cycle_id=request.cycle_id,
                mandate_hash=request.mandate.content_hash,
                observation_hash=observation.content_hash,
                parent_candidate_hashes=request.parent_candidate_hashes,
                budget_category=request.budget_category,
                maximum_model_cost_microusd=request.maximum_model_cost_microusd,
            )
            self.cycle_journal.record(
                cycle_id=request.cycle_id,
                stage="proposal_request_recorded",
                value=proposal_request,
                logical_at=observation.as_of,
            )
        else:
            proposal_request = ProposalRequestV1.model_validate(proposal_request_payload)

        lease = ExternalBudgetLeaseV1(
            lease_id=f"{request.cycle_id}:model-budget",
            budget_day=request.logical_started_at.date(),
            category=request.budget_category,
            maximum_microusd=request.maximum_model_cost_microusd,
            expires_at=request.logical_started_at + timedelta(hours=1),
            purpose=f"bounded candidate proposal for {request.cycle_id}",
        )
        try:
            self._ensure_budget_reservation(request, lease)
        except BudgetExceeded:
            return self._terminal(
                request,
                status="budget_exhausted",
                reasons=("daily_or_category_external_model_budget_exhausted",),
                completed_at=observation.as_of,
                observation_hash=observation.content_hash,
            )

        stopped = self._stopped(
            stop_requested=stop_requested,
            deadline_monotonic=deadline_monotonic,
            monotonic_fn=self.monotonic_fn,
        )
        if stopped:
            lease_events = [
                event
                for event in self.budget.events()
                if event.lease_id == lease.lease_id
            ]
            if len(lease_events) == 1:
                self.budget.cancel(
                    lease_id=lease.lease_id,
                    event_id=f"{request.cycle_id}:budget:cancelled",
                    occurred_at=observation.as_of,
                )
            return self._terminal(
                request,
                status="stopped",
                reasons=(stopped,),
                completed_at=observation.as_of,
                observation_hash=observation.content_hash,
            )

        proposal_payload = self.cycle_journal.payload(request.cycle_id, "proposal_recorded")
        if proposal_payload is None:
            try:
                proposal = self.model_gateway.propose(proposal_request)
            except Exception as exc:
                # Unknown provider outcomes consume the whole reservation.  This
                # is conservative and prevents retries from exceeding $10/day.
                try:
                    self.budget.settle(
                        lease_id=lease.lease_id,
                        event_id=f"{request.cycle_id}:budget:unknown-settlement",
                        actual_microusd=lease.maximum_microusd,
                        occurred_at=observation.as_of,
                    )
                except BudgetStateError:
                    pass
                return self._terminal(
                    request,
                    status="failed",
                    reasons=(f"model_gateway_{type(exc).__name__}",),
                    completed_at=observation.as_of,
                    observation_hash=observation.content_hash,
                )
            if proposal.request_hash != proposal_request.content_hash:
                raise ResearchLoopError("model proposal references the wrong request")
            if proposal.parent_candidate_hashes != request.parent_candidate_hashes:
                raise ResearchLoopError("model proposal changed registered parent lineage")
            if proposal.actual_model_cost_microusd > request.maximum_model_cost_microusd:
                # A gateway violating the injected protocol is quarantined and
                # consumes the full lease.  It never reaches lineage or trials.
                self.budget.settle(
                    lease_id=lease.lease_id,
                    event_id=f"{request.cycle_id}:budget:ceiling-violation",
                    actual_microusd=lease.maximum_microusd,
                    occurred_at=proposal.generated_at,
                )
                return self._terminal(
                    request,
                    status="budget_exhausted",
                    reasons=("model_gateway_exceeded_request_cost_ceiling",),
                    completed_at=proposal.generated_at,
                    observation_hash=observation.content_hash,
                )
            self.cycle_journal.record(
                cycle_id=request.cycle_id,
                stage="proposal_recorded",
                value=proposal,
                logical_at=proposal.generated_at,
            )
        else:
            proposal = CandidateProposalV1.model_validate(proposal_payload)
        self._ensure_budget_settled(request, proposal)
        membership = self._ensure_candidate(request, proposal)

        trial_stage = self.cycle_journal.payload(request.cycle_id, "trial_recorded")
        if trial_stage is not None:
            execution = TrialExecutionV1.model_validate(trial_stage["execution"])
            return self._complete_candidate(
                request,
                observation=observation,
                proposal=proposal,
                membership=membership,
                execution=execution,
            )

        trial_request = TrialRunRequestV1(
            request_id=f"{request.cycle_id}:sealed-trial",
            cycle_id=request.cycle_id,
            trial_id=f"{request.cycle_id}:trial",
            mandate_hash=request.mandate.content_hash,
            proposal_hash=proposal.content_hash,
            candidate_hash=membership.candidate.candidate_hash,
            lineage_cluster_id=membership.lineage_cluster_id,
            timeout_seconds=request.trial_timeout_seconds,
        )
        stopped = self._stopped(
            stop_requested=stop_requested,
            deadline_monotonic=deadline_monotonic,
            monotonic_fn=self.monotonic_fn,
        )
        if stopped:
            execution = self._aborted_execution(
                trial_request,
                logical_at=proposal.generated_at,
                reason=stopped,
            )
        else:
            try:
                execution = self.trial_runner.run(trial_request)
                if execution.request_hash != trial_request.content_hash:
                    raise ResearchLoopError("trial result references the wrong request")
            except Exception as exc:
                execution = self._failed_execution(
                    trial_request,
                    logical_at=proposal.generated_at,
                    exc=exc,
                )
        return self._complete_candidate(
            request,
            observation=observation,
            proposal=proposal,
            membership=membership,
            execution=execution,
        )

    def run(
        self,
        requests: Iterable[ResearchCycleRequestV1],
        *,
        max_cycles: int,
        deadline_monotonic: float | None = None,
        stop_requested: Callable[[], bool] = lambda: False,
    ) -> tuple[ResearchCycleResultV1, ...]:
        """Run a bounded number of cycles; there is no unbounded hidden loop."""

        if max_cycles < 0:
            raise ValueError("max_cycles cannot be negative")
        results: list[ResearchCycleResultV1] = []
        for request in requests:
            if len(results) >= max_cycles:
                break
            if self._stopped(
                stop_requested=stop_requested,
                deadline_monotonic=deadline_monotonic,
                monotonic_fn=self.monotonic_fn,
            ):
                break
            results.append(
                self.run_cycle(
                    request,
                    deadline_monotonic=deadline_monotonic,
                    stop_requested=stop_requested,
                )
            )
        return tuple(results)
