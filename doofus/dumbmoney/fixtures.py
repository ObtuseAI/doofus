"""Deterministic interoperability fixtures for the Blunder control plane."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from .canonical import canonical_json_bytes, content_hash
from .contracts import (
    AlphaPassportV1,
    AssuranceLevel,
    CourtDecision,
    CourtFindingV1,
    CourtName,
    EvidenceDisposition,
    EvidenceVerdictV1,
)
from .fund_interop import (
    FundEvidenceClass,
    FundInteropBundleV1,
    FundVenue,
    export_fund_interop,
)

FIXTURE_TIME = datetime(2026, 7, 26, 21, 0, 0, tzinfo=timezone.utc)


def _digest(label: str) -> str:
    return content_hash({"schema_id": "dumbmoney.fixture_identity.v1", "label": label})


def alpha_passport_fixture() -> AlphaPassportV1:
    succeeded = _digest("trial-receipt-success")
    failed = _digest("trial-receipt-failure")
    return AlphaPassportV1(
        passport_id="fixture-alpha-passport-v1",
        candidate_hash=_digest("candidate"),
        lineage_cluster_id=_digest("lineage-cluster"),
        parent_candidate_hashes=(_digest("parent-candidate"),),
        research_mandate_hashes=(_digest("research-mandate"),),
        trial_receipt_hashes=(succeeded, failed),
        failed_trial_receipt_hashes=(failed,),
        trial_registry_stream_id="dumbmoney.trial_registry.v1",
        trial_registry_sequence=2,
        trial_registry_head_hash=_digest("trial-registry-head"),
        source_bundle_ref=_digest("source-bundle"),
        assurance_level=AssuranceLevel.REPLAY,
        created_at=FIXTURE_TIME,
    )


def evidence_verdict_fixture(
    passport: AlphaPassportV1 | None = None,
) -> EvidenceVerdictV1:
    passport = passport or alpha_passport_fixture()
    courts: tuple[CourtName, ...] = (
        "integrity",
        "statistics",
        "economics",
        "adversarial_operations",
    )
    findings = tuple(
        CourtFindingV1(
            court=court,
            decision=CourtDecision.PASS,
            check_ids=(f"fixture_{court}",),
            reasons=("deterministic_interoperability_fixture",),
            evidence_hashes=(_digest(f"evidence-{court}"),),
            evaluated_at=FIXTURE_TIME,
            evaluator_id="doofus-fixture-evaluator",
        )
        for court in courts
    )
    return EvidenceVerdictV1(
        verdict_id="fixture-evidence-verdict-v1",
        passport_hash=passport.content_hash,
        court_findings=findings,
        disposition=EvidenceDisposition.ACCEPT,
        required_assurance=AssuranceLevel.REPLAY,
        observed_assurance=AssuranceLevel.REPLAY,
        evaluated_at=FIXTURE_TIME,
    )


def interoperability_fixture_bundle() -> dict[str, object]:
    passport = alpha_passport_fixture()
    verdict = evidence_verdict_fixture(passport)
    return {
        "schema_id": "dumbmoney.doofus_interop_fixtures.v1",
        "alpha_passport": passport.model_dump(mode="json"),
        "alpha_passport_hash": passport.content_hash,
        "evidence_verdict": verdict.model_dump(mode="json"),
        "evidence_verdict_hash": verdict.content_hash,
    }


def export_interoperability_fixtures(output_directory: Path | str) -> tuple[Path, Path, Path]:
    """Write byte-stable fixtures for another repository's contract tests."""

    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    passport = alpha_passport_fixture()
    verdict = evidence_verdict_fixture(passport)
    outputs = (
        (directory / "alpha_passport_v1.json", passport),
        (directory / "evidence_verdict_v1.json", verdict),
        (directory / "doofus_interop_bundle_v1.json", interoperability_fixture_bundle()),
    )
    for path, value in outputs:
        path.write_bytes(canonical_json_bytes(value) + b"\n")
    return tuple(path for path, _ in outputs)  # type: ignore[return-value]


def fund_interop_fixture_bundle() -> FundInteropBundleV1:
    passport = alpha_passport_fixture()
    verdict = evidence_verdict_fixture(passport)
    return export_fund_interop(
        passport=passport,
        verdict=verdict,
        venue=FundVenue.DUMMY_KALSHI,
        strategy_lineage_id="fixture-lineage-doofus-1",
        intended_instruments=("event_contract",),
        maximum_loss_cents=2_500,
        evidence_class=FundEvidenceClass.REPLAY,
        evaluator_id=_digest("registered-evaluator-key"),
        expires_at=FIXTURE_TIME + timedelta(days=7),
    )
