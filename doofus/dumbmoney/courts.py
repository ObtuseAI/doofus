"""Four deterministic evidence courts for proof-carrying alpha candidates."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Literal

from pydantic import Field

from .assurance import ASSURANCE_ORDER, assurance_rank, minimum_assurance, required_assurance
from .canonical import CanonicalModel, content_hash
from .contracts import (
    AlphaPassportV1,
    AssuranceLevel,
    CourtDecision,
    CourtFindingV1,
    CourtName,
    EvidenceDisposition,
    EvidenceVerdictV1,
    NonEmpty,
    ResearchMandateV1,
)
from .lineage import LineageArchive
from .registry import TrialRegistry


class StatisticalEvidenceV1(CanonicalModel):
    schema_id: Literal["dumbmoney.statistical_evidence.v1"] = (
        "dumbmoney.statistical_evidence.v1"
    )
    independent_trial_count: int = Field(ge=0)
    holdout_sample_size: int = Field(ge=0)
    confidence_lower_effect_micros: int | None = None
    multiple_testing_adjusted: bool | None = None
    point_in_time_verified: bool | None = None
    negative_control_passed: bool | None = None
    artifact_refs: tuple[str, ...] = ()


class EconomicEvidenceV1(CanonicalModel):
    schema_id: Literal["dumbmoney.economic_evidence.v1"] = "dumbmoney.economic_evidence.v1"
    costs_complete: bool | None = None
    after_cost_edge_bps: int | None = None
    stressed_after_cost_edge_bps: int | None = None
    capacity_tested: bool | None = None
    turnover_included: bool | None = None
    artifact_refs: tuple[str, ...] = ()


class AdversarialOperationsEvidenceV1(CanonicalModel):
    schema_id: Literal["dumbmoney.adversarial_operations_evidence.v1"] = (
        "dumbmoney.adversarial_operations_evidence.v1"
    )
    sandbox_containment_passed: bool | None = None
    credential_scan_passed: bool | None = None
    deterministic_replay_passed: bool | None = None
    timeout_containment_passed: bool | None = None
    restart_recovery_passed: bool | None = None
    idempotency_proof_passed: bool | None = None
    kill_reconciliation_proof_passed: bool | None = None
    artifact_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class CourtContext:
    passport: AlphaPassportV1
    mandates: tuple[ResearchMandateV1, ...]
    trial_registry: TrialRegistry
    lineage_archive: LineageArchive
    statistics: StatisticalEvidenceV1
    economics: EconomicEvidenceV1
    operations: AdversarialOperationsEvidenceV1
    evaluated_at: datetime
    evaluator_id: str

    @property
    def required(self) -> AssuranceLevel:
        profiles = [mandate.consequence for mandate in self.mandates]
        if not profiles:
            return AssuranceLevel.SCALED_LIVE
        return max((required_assurance(profile) for profile in profiles), key=assurance_rank)


class EvidenceCourt(ABC):
    """Deterministic court interface.  Implementations have no side effects."""

    name: ClassVar[CourtName]

    @abstractmethod
    def evaluate(self, context: CourtContext) -> CourtFindingV1:
        raise NotImplementedError

    @abstractmethod
    def observed_assurance(self, context: CourtContext) -> AssuranceLevel:
        raise NotImplementedError

    def _finding(
        self,
        context: CourtContext,
        *,
        decision: CourtDecision,
        checks: tuple[str, ...],
        reasons: tuple[str, ...],
        evidence_hashes: tuple[str, ...],
    ) -> CourtFindingV1:
        return CourtFindingV1(
            court=self.name,
            decision=decision,
            check_ids=checks,
            reasons=reasons,
            evidence_hashes=evidence_hashes,
            evaluated_at=context.evaluated_at,
            evaluator_id=context.evaluator_id,
        )


class IntegrityCourt(EvidenceCourt):
    name = "integrity"

    def _errors(self, context: CourtContext) -> tuple[str, ...]:
        errors: list[str] = []
        try:
            context.trial_registry.verify()
            context.trial_registry.verify_passport(context.passport)
        except (RuntimeError, ValueError, IndexError) as exc:
            errors.append(f"trial_registry:{type(exc).__name__}")
        try:
            context.lineage_archive.verify()
            membership = context.lineage_archive.membership_for(context.passport.candidate_hash)
            if membership.lineage_cluster_id != context.passport.lineage_cluster_id:
                errors.append("lineage_cluster_mismatch")
            if membership.candidate.source_bundle_ref != context.passport.source_bundle_ref:
                errors.append("source_bundle_mismatch")
        except (RuntimeError, ValueError, KeyError) as exc:
            errors.append(f"lineage_archive:{type(exc).__name__}")
        mandate_hashes = {mandate.content_hash for mandate in context.mandates}
        if mandate_hashes != set(context.passport.research_mandate_hashes):
            errors.append("mandate_disclosure_mismatch")
        return tuple(errors)

    def evaluate(self, context: CourtContext) -> CourtFindingV1:
        errors = self._errors(context)
        return self._finding(
            context,
            decision=CourtDecision.FAIL if errors else CourtDecision.PASS,
            checks=(
                "hash_chain",
                "complete_trial_disclosure",
                "failed_trial_disclosure",
                "lineage_resolution",
                "mandate_resolution",
            ),
            reasons=errors or ("all_content_and_lineage_references_resolved",),
            evidence_hashes=(context.passport.content_hash,),
        )

    def observed_assurance(self, context: CourtContext) -> AssuranceLevel:
        return AssuranceLevel.IDEA if self._errors(context) else AssuranceLevel.SCALED_LIVE


class StatisticsCourt(EvidenceCourt):
    name = "statistics"

    def observed_assurance(self, context: CourtContext) -> AssuranceLevel:
        evidence = context.statistics
        level = AssuranceLevel.IDEA
        if evidence.independent_trial_count >= 2 and evidence.point_in_time_verified is True:
            level = AssuranceLevel.REPLAY
        if (
            evidence.independent_trial_count >= 3
            and evidence.holdout_sample_size >= 100
            and evidence.multiple_testing_adjusted is True
            and evidence.negative_control_passed is True
        ):
            level = AssuranceLevel.SHADOW
        if (
            assurance_rank(level) >= assurance_rank(AssuranceLevel.SHADOW)
            and evidence.confidence_lower_effect_micros is not None
            and evidence.confidence_lower_effect_micros > 0
        ):
            level = AssuranceLevel.EXPLORATORY_LIVE
        if (
            level is AssuranceLevel.EXPLORATORY_LIVE
            and evidence.independent_trial_count >= 5
            and evidence.holdout_sample_size >= 500
        ):
            level = AssuranceLevel.SCALED_LIVE
        return level

    def evaluate(self, context: CourtContext) -> CourtFindingV1:
        observed = self.observed_assurance(context)
        passed = assurance_rank(observed) >= assurance_rank(context.required)
        reasons = (
            (f"observed_assurance={observed.value}",)
            if passed
            else (
                f"observed_assurance={observed.value}",
                f"required_assurance={context.required.value}",
            )
        )
        return self._finding(
            context,
            decision=CourtDecision.PASS if passed else CourtDecision.INCOMPLETE,
            checks=(
                "independent_trials",
                "point_in_time",
                "held_out_sample",
                "multiple_testing",
                "negative_control",
                "confidence_lower_bound",
            ),
            reasons=reasons,
            evidence_hashes=(context.statistics.content_hash,),
        )


class EconomicsCourt(EvidenceCourt):
    name = "economics"

    def observed_assurance(self, context: CourtContext) -> AssuranceLevel:
        evidence = context.economics
        level = AssuranceLevel.IDEA
        if evidence.costs_complete is True and evidence.turnover_included is True:
            level = AssuranceLevel.REPLAY
        if (
            assurance_rank(level) >= assurance_rank(AssuranceLevel.REPLAY)
            and evidence.after_cost_edge_bps is not None
        ):
            level = AssuranceLevel.SHADOW
        if (
            level is AssuranceLevel.SHADOW
            and evidence.after_cost_edge_bps is not None
            and evidence.after_cost_edge_bps > 0
            and evidence.capacity_tested is True
        ):
            level = AssuranceLevel.EXPLORATORY_LIVE
        if (
            level is AssuranceLevel.EXPLORATORY_LIVE
            and evidence.stressed_after_cost_edge_bps is not None
            and evidence.stressed_after_cost_edge_bps > 0
        ):
            level = AssuranceLevel.SCALED_LIVE
        return level

    def evaluate(self, context: CourtContext) -> CourtFindingV1:
        evidence = context.economics
        reasons: tuple[str, ...]
        if evidence.after_cost_edge_bps is not None and evidence.after_cost_edge_bps < 0:
            decision = CourtDecision.FAIL
            reasons = ("estimated_after_cost_edge_is_negative",)
        else:
            observed = self.observed_assurance(context)
            passed = assurance_rank(observed) >= assurance_rank(context.required)
            decision = CourtDecision.PASS if passed else CourtDecision.INCOMPLETE
            reasons = (
                f"observed_assurance={observed.value}",
                f"required_assurance={context.required.value}",
            )
        return self._finding(
            context,
            decision=decision,
            checks=(
                "complete_costs",
                "turnover",
                "after_cost_edge",
                "capacity",
                "stress_edge",
            ),
            reasons=reasons,
            evidence_hashes=(evidence.content_hash,),
        )


class AdversarialOperationsCourt(EvidenceCourt):
    name = "adversarial_operations"

    def observed_assurance(self, context: CourtContext) -> AssuranceLevel:
        evidence = context.operations
        if not (
            evidence.sandbox_containment_passed is True
            and evidence.credential_scan_passed is True
        ):
            return AssuranceLevel.IDEA
        level = AssuranceLevel.REPLAY
        if (
            evidence.deterministic_replay_passed is True
            and evidence.timeout_containment_passed is True
        ):
            level = AssuranceLevel.SHADOW
        if (
            level is AssuranceLevel.SHADOW
            and evidence.restart_recovery_passed is True
            and evidence.idempotency_proof_passed is True
        ):
            level = AssuranceLevel.EXPLORATORY_LIVE
        if (
            level is AssuranceLevel.EXPLORATORY_LIVE
            and evidence.kill_reconciliation_proof_passed is True
        ):
            level = AssuranceLevel.SCALED_LIVE
        return level

    def evaluate(self, context: CourtContext) -> CourtFindingV1:
        evidence = context.operations
        explicit_failures = tuple(
            field
            for field in (
                "sandbox_containment_passed",
                "credential_scan_passed",
                "deterministic_replay_passed",
                "timeout_containment_passed",
                "restart_recovery_passed",
                "idempotency_proof_passed",
                "kill_reconciliation_proof_passed",
            )
            if getattr(evidence, field) is False
        )
        observed = self.observed_assurance(context)
        if explicit_failures:
            decision = CourtDecision.FAIL
            reasons = tuple(f"failed:{field}" for field in explicit_failures)
        else:
            passed = assurance_rank(observed) >= assurance_rank(context.required)
            decision = CourtDecision.PASS if passed else CourtDecision.INCOMPLETE
            reasons = (
                f"observed_assurance={observed.value}",
                f"required_assurance={context.required.value}",
            )
        return self._finding(
            context,
            decision=decision,
            checks=(
                "sandbox_containment",
                "credential_scan",
                "deterministic_replay",
                "timeout_containment",
                "restart_recovery",
                "idempotency",
                "kill_reconciliation",
            ),
            reasons=reasons,
            evidence_hashes=(evidence.content_hash,),
        )


class EvidenceCourtSuite:
    """Run the four courts in a fixed order and create a deterministic verdict."""

    courts: tuple[EvidenceCourt, ...] = (
        IntegrityCourt(),
        StatisticsCourt(),
        EconomicsCourt(),
        AdversarialOperationsCourt(),
    )

    def evaluate(self, context: CourtContext) -> EvidenceVerdictV1:
        findings = tuple(court.evaluate(context) for court in self.courts)
        if any(finding.decision is CourtDecision.FAIL for finding in findings):
            disposition = EvidenceDisposition.REJECT
        elif any(finding.decision is CourtDecision.INCOMPLETE for finding in findings):
            disposition = EvidenceDisposition.INCOMPLETE
        else:
            disposition = EvidenceDisposition.ACCEPT
        observed = AssuranceLevel.SCALED_LIVE
        for court in self.courts:
            observed = minimum_assurance(observed, court.observed_assurance(context))
        material = {
            "schema_id": "dumbmoney.verdict_identity.v1",
            "passport_hash": context.passport.content_hash,
            "finding_hashes": [finding.content_hash for finding in findings],
            "evaluated_at": context.evaluated_at,
            "evaluator_id": context.evaluator_id,
        }
        return EvidenceVerdictV1(
            verdict_id=f"verdict-{content_hash(material).split(':', 1)[1][:24]}",
            passport_hash=context.passport.content_hash,
            court_findings=findings,
            disposition=disposition,
            required_assurance=context.required,
            observed_assurance=observed,
            evaluated_at=context.evaluated_at,
        )
