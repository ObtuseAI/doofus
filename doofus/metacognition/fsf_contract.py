"""Sealed Doofus-to-Blunder contract; Blunder remains the authority owner."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


PROTECTED_AUTHORITY_SURFACES = frozenset({
    "kill_switches",
    "protected_roots",
    "secret_isolation",
    "path_containment",
    "budget_hard_caps",
    "write_authorization",
    "rollback_enforcement",
    "promotion_gates",
})


class BoundedMutationMandate(BaseModel):
    model_config = ConfigDict(frozen=True)

    mandate_id: str
    target_id: str
    isolated_worktree: str
    allowed_relative_paths: tuple[str, ...]
    forbidden_authority_surfaces: frozenset[str]
    maximum_candidates: int = Field(ge=0)
    maximum_provider_calls: int = Field(ge=0)
    required_evidence: tuple[str, ...]
    expires_at_utc: str
    operator_approved: bool


class MutationProposalEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True)

    mandate_id: str
    target_id: str
    strategy_id: str
    candidate_ids: tuple[str, ...]
    prediction_ids: tuple[str, ...]
    requested_paths: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    metacognitive_policy_id: str


class VerifiedOutcomeEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True)

    mandate_id: str
    target_id: str
    candidate_id: str
    deterministic_court_passed: bool
    independent_review_passed: bool
    rollback_verified: bool
    observed_fitness: float = Field(ge=0.0, le=1.0)
    evidence_refs: tuple[str, ...]
    authority_decision: str


def _expires_in_future(expires_at_utc: str) -> bool:
    expires = datetime.fromisoformat(expires_at_utc.replace("Z", "+00:00"))
    return expires.astimezone(timezone.utc) > datetime.now(timezone.utc)


def validate_mandate(mandate: BoundedMutationMandate) -> tuple[bool, tuple[str, ...]]:
    violations: list[str] = []
    root = Path(mandate.isolated_worktree).resolve()
    if not mandate.operator_approved:
        violations.append("operator_approval_missing")
    if not _expires_in_future(mandate.expires_at_utc):
        violations.append("mandate_expired")
    if mandate.forbidden_authority_surfaces != PROTECTED_AUTHORITY_SURFACES:
        violations.append("authority_surface_contract_incomplete")
    for relative_path in mandate.allowed_relative_paths:
        candidate = (root / relative_path).resolve()
        if not candidate.is_relative_to(root):
            violations.append(f"path_outside_isolated_worktree:{relative_path}")
    return not violations, tuple(violations)


def validate_proposal(
    mandate: BoundedMutationMandate,
    proposal: MutationProposalEnvelope,
) -> tuple[bool, tuple[str, ...]]:
    mandate_valid, violations = validate_mandate(mandate)
    errors = list(violations)
    if proposal.mandate_id != mandate.mandate_id or proposal.target_id != mandate.target_id:
        errors.append("proposal_mandate_identity_mismatch")
    if len(proposal.candidate_ids) > mandate.maximum_candidates:
        errors.append("candidate_hard_cap_exceeded")
    allowed = set(mandate.allowed_relative_paths)
    for requested_path in proposal.requested_paths:
        if requested_path not in allowed:
            errors.append(f"requested_path_not_allowlisted:{requested_path}")
    missing_evidence = set(mandate.required_evidence) - set(proposal.evidence_refs)
    if missing_evidence:
        errors.append("required_evidence_missing:" + ",".join(sorted(missing_evidence)))
    return mandate_valid and not errors, tuple(errors)


def outcome_is_learning_eligible(outcome: VerifiedOutcomeEnvelope) -> bool:
    return (
        outcome.deterministic_court_passed
        and outcome.independent_review_passed
        and outcome.rollback_verified
        and outcome.authority_decision in {"accepted", "accepted_with_notes"}
    )
