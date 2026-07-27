"""Unsigned, exact-shape export to Blunder's strict Fund contracts.

These models intentionally contain no signature or authority mechanism.  The
Blunder authority plane may parse, independently evaluate, and later sign the
wire objects.  Doofus cannot perform that signing.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from .canonical import CanonicalModel, canonical_json_bytes, content_hash
from .contracts import (
    AlphaPassportV1,
    CourtDecision,
    EvidenceVerdictV1,
)

RawDigest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
FundIdentifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$"),
]


class FundVenue(str, Enum):
    DUMMY_KALSHI = "dummy_kalshi"
    DOPEY_ROBINHOOD = "dopey_robinhood"


class FundEvidenceClass(str, Enum):
    SYNTHETIC = "SYNTHETIC"
    REPLAY = "REPLAY"
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    FORWARD = "FORWARD"
    REALIZED = "REALIZED"


class FundEvidenceDecision(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


def raw_digest(value: str) -> str:
    if value.startswith("sha256:"):
        value = value.split(":", 1)[1]
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("digest must be raw lowercase SHA-256 or sha256-prefixed SHA-256")
    return value


def fund_digest(value: CanonicalModel | dict[str, object]) -> str:
    return raw_digest(content_hash(value))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Fund timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


class FundAlphaPassportV1(CanonicalModel):
    """Byte-for-byte wire shape parsed by Blunder ``AlphaPassportV1``."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_by_alias=True,
        validate_by_name=True,
        serialize_by_alias=True,
    )

    schema_id: Literal["dumbmoney.alpha_passport.v1"] = Field(
        default="dumbmoney.alpha_passport.v1",
        validation_alias="schema",
        serialization_alias="schema",
    )
    passport_id: FundIdentifier
    strategy_lineage_id: FundIdentifier
    venue: FundVenue
    strategy_hash: RawDigest
    artifact_hashes: tuple[RawDigest, ...] = Field(min_length=1)
    evidence_verdict_hashes: tuple[RawDigest, ...] = ()
    intended_instruments: tuple[FundIdentifier, ...] = Field(min_length=1)
    maximum_loss_cents: int = Field(gt=0)
    evidence_class: FundEvidenceClass
    created_at: AwareDatetime
    expires_at: AwareDatetime

    _normalize_created = field_validator("created_at", mode="after")(_utc)
    _normalize_expires = field_validator("expires_at", mode="after")(_utc)

    @model_validator(mode="after")
    def _fund_invariants(self) -> "FundAlphaPassportV1":
        for name in (
            "artifact_hashes",
            "evidence_verdict_hashes",
            "intended_instruments",
        ):
            values = getattr(self, name)
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{name} must be sorted and unique")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        return self

    @property
    def digest(self) -> str:
        return fund_digest(self)


class FundEvidenceVerdictV1(CanonicalModel):
    """One independent court verdict in Blunder's exact public wire shape."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_by_alias=True,
        validate_by_name=True,
        serialize_by_alias=True,
    )

    schema_id: Literal["dumbmoney.evidence_verdict.v1"] = Field(
        default="dumbmoney.evidence_verdict.v1",
        validation_alias="schema",
        serialization_alias="schema",
    )
    verdict_id: FundIdentifier
    passport_digest: RawDigest
    evaluator_id: RawDigest
    court: Literal["integrity", "statistics", "economics", "adversarial_operations"]
    decision: FundEvidenceDecision
    evidence_class: FundEvidenceClass
    artifact_hashes: tuple[RawDigest, ...] = Field(min_length=1)
    reason_codes: tuple[FundIdentifier, ...]
    effective_trial_count: int = Field(ge=0)
    evaluated_at: AwareDatetime
    expires_at: AwareDatetime

    _normalize_evaluated = field_validator("evaluated_at", mode="after")(_utc)
    _normalize_expires = field_validator("expires_at", mode="after")(_utc)

    @model_validator(mode="after")
    def _fund_invariants(self) -> "FundEvidenceVerdictV1":
        for name in ("artifact_hashes", "reason_codes"):
            values = getattr(self, name)
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{name} must be sorted and unique")
        if self.expires_at <= self.evaluated_at:
            raise ValueError("expires_at must be after evaluated_at")
        return self

    @property
    def digest(self) -> str:
        return fund_digest(self)


class FundInteropBundleV1(CanonicalModel):
    """Unsigned parse-ready objects; not itself a Blunder public contract."""

    schema_id: Literal["dumbmoney.doofus_fund_interop_bundle.v1"] = (
        "dumbmoney.doofus_fund_interop_bundle.v1"
    )
    alpha_passport: FundAlphaPassportV1
    evidence_verdicts: tuple[FundEvidenceVerdictV1, ...] = Field(min_length=4, max_length=4)
    signed: Literal[False] = False
    grants_live_authority: Literal[False] = False
    grants_capital_authority: Literal[False] = False


_DECISION_MAP = {
    CourtDecision.PASS: FundEvidenceDecision.PASS,
    CourtDecision.FAIL: FundEvidenceDecision.FAIL,
    CourtDecision.INCOMPLETE: FundEvidenceDecision.INCONCLUSIVE,
}


def _reason_code(court: str, decision: FundEvidenceDecision, index: int) -> str:
    return f"DOOFUS_{court.upper()}_{decision.value}_{index:02d}"


def export_fund_interop(
    *,
    passport: AlphaPassportV1,
    verdict: EvidenceVerdictV1,
    venue: FundVenue,
    strategy_lineage_id: str,
    intended_instruments: tuple[str, ...],
    maximum_loss_cents: int,
    evidence_class: FundEvidenceClass,
    evaluator_id: str,
    expires_at: datetime,
) -> FundInteropBundleV1:
    """Convert native research evidence into strict, unsigned Fund contracts."""

    if verdict.passport_hash != passport.content_hash:
        raise ValueError("native verdict does not resolve to native passport")
    artifacts = tuple(
        sorted(
            {
                raw_digest(passport.source_bundle_ref),
                raw_digest(passport.trial_registry_head_hash),
                *(raw_digest(item) for item in passport.trial_receipt_hashes),
            }
        )
    )
    fund_passport = FundAlphaPassportV1(
        passport_id=passport.passport_id,
        strategy_lineage_id=strategy_lineage_id,
        venue=venue,
        strategy_hash=raw_digest(passport.candidate_hash),
        artifact_hashes=artifacts,
        # Verdicts are issued after Blunder resolves the passport, avoiding a
        # circular passport-digest/verdict-digest dependency.
        evidence_verdict_hashes=(),
        intended_instruments=tuple(sorted(set(intended_instruments))),
        maximum_loss_cents=maximum_loss_cents,
        evidence_class=evidence_class,
        created_at=passport.created_at,
        expires_at=expires_at,
    )
    trial_count = len(passport.trial_receipt_hashes)
    fund_verdicts = tuple(
        FundEvidenceVerdictV1(
            verdict_id=f"{verdict.verdict_id}-{finding.court}",
            passport_digest=fund_passport.digest,
            evaluator_id=raw_digest(evaluator_id),
            court=finding.court,
            decision=_DECISION_MAP[finding.decision],
            evidence_class=evidence_class,
            artifact_hashes=tuple(
                sorted({raw_digest(item) for item in finding.evidence_hashes})
            ),
            reason_codes=(
                _reason_code(
                    finding.court,
                    _DECISION_MAP[finding.decision],
                    1,
                ),
            ),
            effective_trial_count=trial_count,
            evaluated_at=finding.evaluated_at,
            expires_at=expires_at,
        )
        for finding in verdict.court_findings
    )
    return FundInteropBundleV1(
        alpha_passport=fund_passport,
        evidence_verdicts=fund_verdicts,
    )


def export_fund_interop_files(
    bundle: FundInteropBundleV1,
    output_directory: Path | str,
) -> tuple[Path, ...]:
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    outputs: list[tuple[Path, CanonicalModel]] = [
        (directory / "alpha_passport_v1.json", bundle.alpha_passport),
    ]
    outputs.extend(
        (
            directory / f"evidence_verdict_{verdict.court}_v1.json",
            verdict,
        )
        for verdict in bundle.evidence_verdicts
    )
    for path, contract in outputs:
        path.write_bytes(canonical_json_bytes(contract) + b"\n")
    return tuple(path for path, _ in outputs)
