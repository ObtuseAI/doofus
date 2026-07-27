from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from doofus.dumbmoney import (
    AdversarialOperationsEvidenceV1,
    ArchiveDimensionV1,
    AssuranceLevel,
    CandidateRecordV1,
    ConsequenceProfileV1,
    CourtContext,
    DailyExternalBudget,
    EconomicEvidenceV1,
    EvidenceCourtSuite,
    LineageArchive,
    MetricObservationV1,
    ResearchAuthorityDenied,
    ResearchMandateV1,
    StatisticalEvidenceV1,
    TrialReceiptV1,
    TrialRegistry,
    TrialStatus,
    assert_research_capabilities,
    capability_manifest,
    content_hash,
    run_mutation_subprocess,
)

NOW = datetime(2026, 7, 26, 21, 0, tzinfo=timezone.utc)


def digest(label: str) -> str:
    return content_hash({"label": label})


def court_context(tmp_path, *, after_cost_edge_bps: int = 5) -> CourtContext:
    lineage = LineageArchive(tmp_path / "lineage.jsonl")
    membership = lineage.register(
        CandidateRecordV1(
            candidate_hash=digest("candidate"),
            origin_fingerprint=digest("origin"),
            mutation_operator="fixture",
            behavior_cell=(ArchiveDimensionV1(name="domain", value="fixture"),),
            source_bundle_ref=digest("bundle"),
            created_at=NOW,
        )
    )
    mandate = ResearchMandateV1(
        mandate_id="mandate",
        objective="Run consequence-proportional evaluation.",
        hypotheses=("Candidate survives replay.",),
        evaluation_protocol_ref=digest("protocol"),
        consequence=ConsequenceProfileV1(maximum_external_loss_cents=100),
        requested_by="test",
        created_at=NOW,
        expires_at=NOW + timedelta(days=1),
    )
    registry = TrialRegistry(tmp_path / "trials.jsonl")
    registry.append(
        TrialReceiptV1(
            trial_id="trial",
            mandate_hash=mandate.content_hash,
            candidate_hash=membership.candidate.candidate_hash,
            lineage_cluster_id=membership.lineage_cluster_id,
            status=TrialStatus.SUCCEEDED,
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=1),
            evaluator_ref=digest("evaluator"),
            metrics=(
                MetricObservationV1(
                    name="score",
                    value="0.1",
                    unit="ratio",
                    sample_size=30,
                ),
            ),
        )
    )
    passport = registry.build_passport(
        passport_id="passport",
        candidate_hash=membership.candidate.candidate_hash,
        lineage_cluster_id=membership.lineage_cluster_id,
        parent_candidate_hashes=(),
        mandates=(mandate,),
        source_bundle_ref=membership.candidate.source_bundle_ref,
        assurance_level=AssuranceLevel.REPLAY,
        created_at=NOW,
    )
    return CourtContext(
        passport=passport,
        mandates=(mandate,),
        trial_registry=registry,
        lineage_archive=lineage,
        statistics=StatisticalEvidenceV1(
            independent_trial_count=2,
            holdout_sample_size=30,
            point_in_time_verified=True,
        ),
        economics=EconomicEvidenceV1(
            costs_complete=True,
            after_cost_edge_bps=after_cost_edge_bps,
            turnover_included=True,
        ),
        operations=AdversarialOperationsEvidenceV1(
            sandbox_containment_passed=True,
            credential_scan_passed=True,
        ),
        evaluated_at=NOW,
        evaluator_id="court-suite-test",
    )


def test_four_courts_accept_replay_evidence_deterministically(tmp_path) -> None:
    context = court_context(tmp_path)
    first = EvidenceCourtSuite().evaluate(context)
    second = EvidenceCourtSuite().evaluate(context)

    assert first == second
    assert first.content_hash == second.content_hash
    assert first.disposition == "accept"
    assert first.required_assurance is AssuranceLevel.REPLAY
    assert {finding.court for finding in first.court_findings} == {
        "integrity",
        "statistics",
        "economics",
        "adversarial_operations",
    }
    assert first.broker_authority == "none"
    assert first.capital_signing_authority == "none"


def test_negative_after_cost_evidence_is_rejected(tmp_path) -> None:
    verdict = EvidenceCourtSuite().evaluate(court_context(tmp_path, after_cost_edge_bps=-1))

    assert verdict.disposition == "reject"
    economics = next(finding for finding in verdict.court_findings if finding.court == "economics")
    assert economics.decision == "fail"
    assert economics.reasons == ("estimated_after_cost_edge_is_negative",)


def test_research_capability_boundary_denies_broker_credentials_and_capital() -> None:
    manifest = capability_manifest()
    assert manifest.broker_authority == "none"
    assert manifest.credential_access == "none"
    assert manifest.capital_signing_authority == "none"
    for forbidden in (
        "broker_order_submit",
        "credential_read",
        "capital_signing",
        "robinhood_access",
        "kalshi_cancel",
    ):
        with pytest.raises(ResearchAuthorityDenied):
            assert_research_capabilities((forbidden,))


def test_mutation_subprocess_has_fresh_pycache_and_no_inherited_secrets(
    tmp_path,
    monkeypatch,
) -> None:
    inherited_keys = (
        "APPDATA",
        "AWS_ACCESS_KEY_ID",
        "GITHUB_TOKEN",
        "LOCALAPPDATA",
        "OPENROUTER_API_KEY",
        "PATH",
        "USERPROFILE",
    )
    for key in inherited_keys:
        monkeypatch.setenv(key, f"{key.lower()}-must-not-cross")
    code = (
        "import json,os;"
        "print(json.dumps({"
        "'cache':os.environ.get('PYTHONPYCACHEPREFIX'),"
        "'environment':dict(os.environ),"
        "'profile':os.environ.get('DUMBMONEY_CAPABILITY_PROFILE')}))"
    )
    first = run_mutation_subprocess(
        (sys.executable, "-c", code),
        cwd=tmp_path,
        timeout_seconds=10,
        environment_overrides={"DUMBMONEY_MUTATION_SEED": "7"},
    )
    second = run_mutation_subprocess(
        (sys.executable, "-c", code),
        cwd=tmp_path,
        timeout_seconds=10,
    )
    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)

    assert first.returncode == second.returncode == 0
    assert first_payload["cache"] != second_payload["cache"]
    assert first_payload["profile"] == "research_only"
    assert not set(inherited_keys).intersection(first_payload["environment"])
    assert set(first_payload["environment"]) == {
        "DUMBMONEY_CAPABILITY_PROFILE",
        "PYTHONHASHSEED",
        "PYTHONIOENCODING",
        "PYTHONNOUSERSITE",
        "PYTHONPYCACHEPREFIX",
        "PYTHONUTF8",
        "DUMBMONEY_MUTATION_SEED",
    }
    assert first_payload["environment"]["DUMBMONEY_MUTATION_SEED"] == "7"
    assert not os.path.exists(first.pycache_prefix)
    with pytest.raises(ResearchAuthorityDenied):
        run_mutation_subprocess(
            (sys.executable, "-c", "print('no')"),
            cwd=tmp_path,
            timeout_seconds=10,
            environment_overrides={"BROKER_TOKEN": "denied"},
        )


def test_mutation_subprocess_rejects_relative_executable_and_path_override(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(ResearchAuthorityDenied, match="absolute path"):
        run_mutation_subprocess(
            (Path(sys.executable).name, "-c", "print('must-not-run')"),
            cwd=tmp_path,
            timeout_seconds=10,
        )
    with pytest.raises(
        ResearchAuthorityDenied,
        match="execution-control environment key",
    ):
        run_mutation_subprocess(
            (sys.executable, "-c", "print('must-not-run')"),
            cwd=tmp_path,
            timeout_seconds=10,
            environment_overrides={"PATH": str(tmp_path)},
        )

    attacker_executable = tmp_path / Path(sys.executable).name
    shutil.copy2(sys.executable, attacker_executable)
    with pytest.raises(ResearchAuthorityDenied, match="explicit SHA-256 pin"):
        run_mutation_subprocess(
            (str(attacker_executable), "-c", "print('must-not-run')"),
            cwd=tmp_path,
            timeout_seconds=10,
        )


def test_mutation_subprocess_bounds_cwd_and_verifies_executable_pin(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()

    with pytest.raises(ResearchAuthorityDenied, match="within workspace_root"):
        run_mutation_subprocess(
            (sys.executable, "-c", "print('must-not-run')"),
            cwd=outside,
            workspace_root=workspace,
            timeout_seconds=10,
        )
    with pytest.raises(ResearchAuthorityDenied, match="pin mismatch"):
        run_mutation_subprocess(
            (sys.executable, "-c", "print('must-not-run')"),
            cwd=workspace,
            workspace_root=workspace,
            executable_sha256="0" * 64,
            timeout_seconds=10,
        )
