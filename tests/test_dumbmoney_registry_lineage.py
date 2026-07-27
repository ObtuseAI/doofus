from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from doofus.dumbmoney import (
    AlphaPassportV1,
    ArchiveDimensionV1,
    AssuranceLevel,
    CandidateRecordV1,
    LineageArchive,
    MetricObservationV1,
    QualityDiversityArchive,
    ResearchMandateV1,
    TrialReceiptV1,
    TrialRegistry,
    TrialStatus,
    content_hash,
)
from doofus.dumbmoney.journal import JournalIntegrityError
from doofus.dumbmoney.registry import IncompleteDisclosureError

NOW = datetime(2026, 7, 26, 21, 0, tzinfo=timezone.utc)


def digest(label: str) -> str:
    return content_hash({"label": label})


def candidate(
    label: str,
    *,
    origin: str,
    parents: tuple[str, ...] = (),
    cell_value: str = "binary",
) -> CandidateRecordV1:
    return CandidateRecordV1(
        candidate_hash=digest(f"candidate:{label}"),
        origin_fingerprint=digest(f"origin:{origin}"),
        parent_candidate_hashes=parents,
        mutation_operator="fixture",
        behavior_cell=(ArchiveDimensionV1(name="domain", value=cell_value),),
        source_bundle_ref=digest(f"bundle:{label}"),
        created_at=NOW,
    )


def mandate() -> ResearchMandateV1:
    return ResearchMandateV1(
        mandate_id="m-1",
        objective="Evaluate all attempts.",
        hypotheses=("Held-out score improves.",),
        evaluation_protocol_ref=digest("protocol"),
        requested_by="test",
        created_at=NOW,
        expires_at=NOW + timedelta(days=1),
    )


def receipt(
    trial_id: str,
    *,
    candidate_hash: str,
    cluster: str,
    mandate_hash: str,
    status: TrialStatus,
) -> TrialReceiptV1:
    failed = status is not TrialStatus.SUCCEEDED
    return TrialReceiptV1(
        trial_id=trial_id,
        mandate_hash=mandate_hash,
        candidate_hash=candidate_hash,
        lineage_cluster_id=cluster,
        status=status,
        started_at=NOW,
        completed_at=NOW + timedelta(minutes=1),
        evaluator_ref=digest("evaluator"),
        metrics=(
            MetricObservationV1(
                name="heldout_score",
                value="0.5",
                unit="ratio",
                sample_size=50,
            ),
        ),
        failure_class="assertion" if failed else None,
        failure_reason="heldout did not improve" if failed else None,
    )


def test_origin_clones_and_descendants_share_one_lineage_wallet(tmp_path) -> None:
    archive = LineageArchive(tmp_path / "lineage.jsonl")
    root = archive.register(candidate("root", origin="same-source"))
    clone = archive.register(candidate("clone", origin="same-source"))
    child = archive.register(
        candidate(
            "child",
            origin="mutated-source",
            parents=(root.candidate.candidate_hash,),
        )
    )

    assert clone.lineage_cluster_id == root.lineage_cluster_id
    assert child.lineage_cluster_id == root.lineage_cluster_id
    assert child.lineage_depth == 1
    assert archive.verify() is True


def test_trial_registry_preserves_and_discloses_failures(tmp_path) -> None:
    lineage = LineageArchive(tmp_path / "lineage.jsonl")
    membership = lineage.register(candidate("root", origin="root"))
    research_mandate = mandate()
    registry = TrialRegistry(tmp_path / "trials.jsonl")
    failed = receipt(
        "trial-failed",
        candidate_hash=membership.candidate.candidate_hash,
        cluster=membership.lineage_cluster_id,
        mandate_hash=research_mandate.content_hash,
        status=TrialStatus.FAILED,
    )
    passed = receipt(
        "trial-passed",
        candidate_hash=membership.candidate.candidate_hash,
        cluster=membership.lineage_cluster_id,
        mandate_hash=research_mandate.content_hash,
        status=TrialStatus.SUCCEEDED,
    )
    registry.append(failed)
    registry.append(passed)
    passport = registry.build_passport(
        passport_id="passport-1",
        candidate_hash=membership.candidate.candidate_hash,
        lineage_cluster_id=membership.lineage_cluster_id,
        parent_candidate_hashes=(),
        mandates=(research_mandate,),
        source_bundle_ref=membership.candidate.source_bundle_ref,
        assurance_level=AssuranceLevel.IDEA,
        created_at=NOW,
    )

    assert set(passport.trial_receipt_hashes) == {failed.content_hash, passed.content_hash}
    assert passport.failed_trial_receipt_hashes == (failed.content_hash,)
    assert registry.verify_passport(passport) is True

    hidden_failure = AlphaPassportV1(
        **{
            **passport.model_dump(),
            "trial_receipt_hashes": (passed.content_hash,),
            "failed_trial_receipt_hashes": (),
        }
    )
    with pytest.raises(IncompleteDisclosureError, match="omits or invents"):
        registry.verify_passport(hidden_failure)


def test_registry_passport_binds_historical_head_not_future_trials(tmp_path) -> None:
    lineage = LineageArchive(tmp_path / "lineage.jsonl")
    membership = lineage.register(candidate("root", origin="root"))
    research_mandate = mandate()
    registry = TrialRegistry(tmp_path / "trials.jsonl")
    first = receipt(
        "trial-1",
        candidate_hash=membership.candidate.candidate_hash,
        cluster=membership.lineage_cluster_id,
        mandate_hash=research_mandate.content_hash,
        status=TrialStatus.SUCCEEDED,
    )
    registry.append(first)
    passport = registry.build_passport(
        passport_id="passport-1",
        candidate_hash=membership.candidate.candidate_hash,
        lineage_cluster_id=membership.lineage_cluster_id,
        parent_candidate_hashes=(),
        mandates=(research_mandate,),
        source_bundle_ref=membership.candidate.source_bundle_ref,
        assurance_level=AssuranceLevel.IDEA,
        created_at=NOW,
    )
    registry.append(
        receipt(
            "trial-2",
            candidate_hash=membership.candidate.candidate_hash,
            cluster=membership.lineage_cluster_id,
            mandate_hash=research_mandate.content_hash,
            status=TrialStatus.FAILED,
        )
    )

    assert registry.verify_passport(passport) is True
    assert passport.trial_registry_sequence == 1


def test_hash_chain_detects_rewritten_failure(tmp_path) -> None:
    path = tmp_path / "trials.jsonl"
    registry = TrialRegistry(path)
    trial = receipt(
        "trial-1",
        candidate_hash=digest("candidate"),
        cluster=digest("cluster"),
        mandate_hash=digest("mandate"),
        status=TrialStatus.FAILED,
    )
    registry.append(trial)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["payload"]["failure_reason"] = "silently rewritten"
    path.write_text(json.dumps(raw) + "\n", encoding="utf-8")

    with pytest.raises(JournalIntegrityError, match="payload hash mismatch"):
        registry.verify()


def test_quality_diversity_archive_retains_losers_and_derives_champion(tmp_path) -> None:
    lineage = LineageArchive(tmp_path / "lineage.jsonl")
    first = lineage.register(candidate("one", origin="one"))
    second = lineage.register(candidate("two", origin="two"))
    registry = TrialRegistry(tmp_path / "trials.jsonl")
    research_mandate = mandate()
    passports = []
    for index, membership in enumerate((first, second), start=1):
        registry.append(
            receipt(
                f"trial-{index}",
                candidate_hash=membership.candidate.candidate_hash,
                cluster=membership.lineage_cluster_id,
                mandate_hash=research_mandate.content_hash,
                status=TrialStatus.SUCCEEDED,
            )
        )
        passports.append(
            registry.build_passport(
                passport_id=f"passport-{index}",
                candidate_hash=membership.candidate.candidate_hash,
                lineage_cluster_id=membership.lineage_cluster_id,
                parent_candidate_hashes=(),
                mandates=(research_mandate,),
                source_bundle_ref=membership.candidate.source_bundle_ref,
                assurance_level=AssuranceLevel.IDEA,
                created_at=NOW,
            )
        )
    archive = QualityDiversityArchive(tmp_path / "qd.jsonl", lineage=lineage)
    archive.admit(
        admission_id="a-1",
        passport=passports[0],
        quality_micros=100,
        novelty_micros=100,
        admitted_at=NOW,
    )
    archive.admit(
        admission_id="a-2",
        passport=passports[1],
        quality_micros=50,
        novelty_micros=500,
        admitted_at=NOW,
    )

    assert len(archive.admissions()) == 2
    assert archive.admissions()[1].decision == "retained_nonchampion"
    assert next(iter(archive.champions().values())).candidate_hash == first.candidate.candidate_hash
