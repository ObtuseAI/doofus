"""Tamper-evident candidate lineage and quality-diversity archive primitives."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from .canonical import CanonicalModel, content_hash
from .contracts import AlphaPassportV1, Digest, NonEmpty
from .journal import DuplicateRecordError, HashChainJournal


class LineageConflictError(ValueError):
    pass


class ArchiveDimensionV1(CanonicalModel):
    schema_id: Literal["dumbmoney.archive_dimension.v1"] = "dumbmoney.archive_dimension.v1"
    name: NonEmpty
    value: NonEmpty


class CandidateRecordV1(CanonicalModel):
    schema_id: Literal["dumbmoney.candidate_record.v1"] = "dumbmoney.candidate_record.v1"
    candidate_hash: Digest
    origin_fingerprint: Digest
    parent_candidate_hashes: tuple[Digest, ...] = ()
    mutation_operator: NonEmpty
    behavior_cell: tuple[ArchiveDimensionV1, ...] = Field(min_length=1)
    source_bundle_ref: Digest
    created_at: AwareDatetime
    capability_profile: Literal["candidate_only"] = "candidate_only"
    broker_authority: Literal["none"] = "none"
    credential_access: Literal["none"] = "none"
    capital_signing_authority: Literal["none"] = "none"

    @model_validator(mode="after")
    def _unique_dimensions(self) -> "CandidateRecordV1":
        names = [dimension.name for dimension in self.behavior_cell]
        if len(names) != len(set(names)):
            raise ValueError("behavior dimension names must be unique")
        if len(self.parent_candidate_hashes) != len(set(self.parent_candidate_hashes)):
            raise ValueError("parent candidates must be unique")
        if self.candidate_hash in self.parent_candidate_hashes:
            raise ValueError("candidate cannot be its own parent")
        return self


class LineageMembershipV1(CanonicalModel):
    schema_id: Literal["dumbmoney.lineage_membership.v1"] = "dumbmoney.lineage_membership.v1"
    candidate: CandidateRecordV1
    lineage_cluster_id: Digest
    related_cluster_ids: tuple[Digest, ...]
    lineage_depth: int = Field(ge=0)


class LineageArchive:
    """Append-only candidate graph with deterministic anti-Sybil clustering.

    A clone that changes its candidate identifier but preserves the same
    independently attested origin fingerprint receives the same wallet cluster.
    Descendants inherit a parent wallet.  Cross-cluster children are assigned
    the lexicographically first parent cluster, so recombination cannot mint a
    fresh ProofCredit wallet.
    """

    STREAM_ID = "dumbmoney.candidate_lineage.v1"

    def __init__(self, path: Path | str) -> None:
        self.journal = HashChainJournal(path, stream_id=self.STREAM_ID)

    def memberships(self) -> tuple[LineageMembershipV1, ...]:
        return tuple(
            LineageMembershipV1.model_validate(record["payload"])
            for record in self.journal.read_verified()
        )

    def membership_for(self, candidate_hash: str) -> LineageMembershipV1:
        for membership in self.memberships():
            if membership.candidate.candidate_hash == candidate_hash:
                return membership
        raise KeyError(f"unknown candidate: {candidate_hash}")

    def cluster_for(self, candidate_hash: str) -> str:
        return self.membership_for(candidate_hash).lineage_cluster_id

    def register(self, candidate: CandidateRecordV1) -> LineageMembershipV1:
        existing = self.memberships()
        by_candidate = {item.candidate.candidate_hash: item for item in existing}
        by_origin: dict[str, str] = {}
        for item in existing:
            by_origin.setdefault(item.candidate.origin_fingerprint, item.lineage_cluster_id)
        if candidate.candidate_hash in by_candidate:
            raise DuplicateRecordError(f"duplicate candidate_hash: {candidate.candidate_hash}")

        parents: list[LineageMembershipV1] = []
        for parent_hash in candidate.parent_candidate_hashes:
            if parent_hash not in by_candidate:
                raise LineageConflictError(f"parent is not registered: {parent_hash}")
            parents.append(by_candidate[parent_hash])

        origin_cluster = by_origin.get(candidate.origin_fingerprint)
        parent_clusters = sorted({parent.lineage_cluster_id for parent in parents})
        if parents:
            # Do not create a fresh wallet through cross-lineage recombination.
            lineage_cluster = parent_clusters[0]
            if origin_cluster is not None and origin_cluster not in parent_clusters:
                raise LineageConflictError(
                    "origin fingerprint is already attributed to an unrelated lineage"
                )
            related = tuple(parent_clusters)
            depth = max(parent.lineage_depth for parent in parents) + 1
        elif origin_cluster is not None:
            lineage_cluster = origin_cluster
            related = (origin_cluster,)
            depth = 0
        else:
            lineage_cluster = content_hash(
                {
                    "schema_id": "dumbmoney.lineage_root.v1",
                    "origin_fingerprint": candidate.origin_fingerprint,
                }
            )
            related = (lineage_cluster,)
            depth = 0

        membership = LineageMembershipV1(
            candidate=candidate,
            lineage_cluster_id=lineage_cluster,
            related_cluster_ids=related,
            lineage_depth=depth,
        )
        self.journal.append(
            membership.model_dump(mode="json"),
            unique_key="candidate",
            unique_value=candidate.candidate_hash,
        )
        return membership

    def verify(self) -> bool:
        memberships = self.memberships()
        seen: set[str] = set()
        for membership in memberships:
            candidate = membership.candidate
            if candidate.candidate_hash in seen:
                raise LineageConflictError(f"duplicate candidate: {candidate.candidate_hash}")
            if not set(candidate.parent_candidate_hashes).issubset(seen):
                raise LineageConflictError("parent appears after child or is absent")
            seen.add(candidate.candidate_hash)
        return self.journal.verify()


class ArchiveAdmissionV1(CanonicalModel):
    schema_id: Literal["dumbmoney.archive_admission.v1"] = "dumbmoney.archive_admission.v1"
    admission_id: NonEmpty
    candidate_hash: Digest
    passport_hash: Digest
    lineage_cluster_id: Digest
    cell_key: NonEmpty
    quality_micros: int
    novelty_micros: int = Field(ge=0)
    decision: Literal["champion", "retained_nonchampion"]
    displaced_candidate_hash: Digest | None = None
    admitted_at: AwareDatetime


class QualityDiversityArchive:
    """Append every admission and derive current champions without overwrites."""

    STREAM_ID = "dumbmoney.quality_diversity.v1"

    def __init__(self, path: Path | str, *, lineage: LineageArchive) -> None:
        self.journal = HashChainJournal(path, stream_id=self.STREAM_ID)
        self.lineage = lineage

    def admissions(self) -> tuple[ArchiveAdmissionV1, ...]:
        return tuple(
            ArchiveAdmissionV1.model_validate(record["payload"])
            for record in self.journal.read_verified()
        )

    @staticmethod
    def cell_key(candidate: CandidateRecordV1) -> str:
        dimensions = sorted(
            ((item.name, item.value) for item in candidate.behavior_cell),
            key=lambda pair: pair[0],
        )
        return "|".join(f"{name}={value}" for name, value in dimensions)

    def champions(self) -> dict[str, ArchiveAdmissionV1]:
        champions: dict[str, ArchiveAdmissionV1] = {}
        for admission in self.admissions():
            if admission.decision != "champion":
                continue
            current = champions.get(admission.cell_key)
            if current is None or (
                admission.quality_micros,
                admission.novelty_micros,
                admission.candidate_hash,
            ) > (
                current.quality_micros,
                current.novelty_micros,
                current.candidate_hash,
            ):
                champions[admission.cell_key] = admission
        return champions

    def admit(
        self,
        *,
        admission_id: str,
        passport: AlphaPassportV1,
        quality_micros: int,
        novelty_micros: int,
        admitted_at: datetime,
    ) -> ArchiveAdmissionV1:
        membership = self.lineage.membership_for(passport.candidate_hash)
        if passport.lineage_cluster_id != membership.lineage_cluster_id:
            raise LineageConflictError("passport lineage cluster does not resolve")
        cell = self.cell_key(membership.candidate)
        current = self.champions().get(cell)
        candidate_key = (quality_micros, novelty_micros, passport.candidate_hash)
        current_key = (
            (current.quality_micros, current.novelty_micros, current.candidate_hash)
            if current is not None
            else None
        )
        wins = current_key is None or candidate_key > current_key
        admission = ArchiveAdmissionV1(
            admission_id=admission_id,
            candidate_hash=passport.candidate_hash,
            passport_hash=passport.content_hash,
            lineage_cluster_id=membership.lineage_cluster_id,
            cell_key=cell,
            quality_micros=quality_micros,
            novelty_micros=novelty_micros,
            decision="champion" if wins else "retained_nonchampion",
            displaced_candidate_hash=current.candidate_hash if wins and current else None,
            admitted_at=admitted_at,
        )
        self.journal.append(
            admission.model_dump(mode="json"),
            unique_key="admission_id",
            unique_value=admission_id,
        )
        return admission
