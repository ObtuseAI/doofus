"""Append-only trial registry that makes failed experiments non-optional."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .contracts import (
    AlphaPassportV1,
    AssuranceLevel,
    ResearchMandateV1,
    TrialReceiptV1,
    TrialStatus,
)
from .journal import HashChainJournal, JournalIntegrityError


class IncompleteDisclosureError(ValueError):
    pass


class TrialRegistry:
    STREAM_ID = "dumbmoney.trial_registry.v1"

    def __init__(self, path: Path | str) -> None:
        self.journal = HashChainJournal(path, stream_id=self.STREAM_ID)

    def append(self, receipt: TrialReceiptV1) -> dict[str, Any]:
        return self.journal.append(
            receipt.model_dump(mode="json"),
            unique_key="trial_id",
            unique_value=receipt.trial_id,
        )

    def receipts(self, *, through_sequence: int | None = None) -> tuple[TrialReceiptV1, ...]:
        records = self.journal.read_verified()
        if through_sequence is not None:
            if through_sequence < 0 or through_sequence > len(records):
                raise JournalIntegrityError("trial registry sequence is out of range")
            records = records[:through_sequence]
        return tuple(TrialReceiptV1.model_validate(record["payload"]) for record in records)

    def receipts_for_candidate(
        self,
        candidate_hash: str,
        *,
        through_sequence: int | None = None,
    ) -> tuple[TrialReceiptV1, ...]:
        return tuple(
            receipt
            for receipt in self.receipts(through_sequence=through_sequence)
            if receipt.candidate_hash == candidate_hash
        )

    @property
    def head(self) -> tuple[int, str | None]:
        records = self.journal.read_verified()
        return len(records), records[-1]["record_hash"] if records else None

    def build_passport(
        self,
        *,
        passport_id: str,
        candidate_hash: str,
        lineage_cluster_id: str,
        parent_candidate_hashes: tuple[str, ...],
        mandates: tuple[ResearchMandateV1, ...],
        source_bundle_ref: str,
        assurance_level: AssuranceLevel,
        created_at: datetime,
    ) -> AlphaPassportV1:
        receipts = self.receipts_for_candidate(candidate_hash)
        if not receipts:
            raise IncompleteDisclosureError("candidate has no registered trials")
        mandate_hashes = tuple(sorted({mandate.content_hash for mandate in mandates}))
        if not mandate_hashes:
            raise IncompleteDisclosureError("candidate has no research mandate")
        unknown_mandates = {
            receipt.mandate_hash for receipt in receipts
        } - set(mandate_hashes)
        if unknown_mandates:
            raise IncompleteDisclosureError("registered receipt references an undisclosed mandate")
        wrong_clusters = {
            receipt.lineage_cluster_id for receipt in receipts
        } - {lineage_cluster_id}
        if wrong_clusters:
            raise IncompleteDisclosureError("registered receipt lineage does not match candidate")
        sequence, head_hash = self.head
        assert head_hash is not None
        receipt_hashes = tuple(receipt.content_hash for receipt in receipts)
        failed_hashes = tuple(
            receipt.content_hash
            for receipt in receipts
            if receipt.status is not TrialStatus.SUCCEEDED
        )
        passport = AlphaPassportV1(
            passport_id=passport_id,
            candidate_hash=candidate_hash,
            lineage_cluster_id=lineage_cluster_id,
            parent_candidate_hashes=parent_candidate_hashes,
            research_mandate_hashes=mandate_hashes,
            trial_receipt_hashes=receipt_hashes,
            failed_trial_receipt_hashes=failed_hashes,
            trial_registry_stream_id=self.STREAM_ID,
            trial_registry_sequence=sequence,
            trial_registry_head_hash=head_hash,
            source_bundle_ref=source_bundle_ref,
            assurance_level=assurance_level,
            created_at=created_at,
        )
        self.verify_passport(passport)
        return passport

    def verify_passport(self, passport: AlphaPassportV1) -> bool:
        if passport.trial_registry_stream_id != self.STREAM_ID:
            raise IncompleteDisclosureError("passport references a different trial registry")
        records = self.journal.read_verified()
        if passport.trial_registry_sequence > len(records):
            raise IncompleteDisclosureError("passport references a future trial-registry sequence")
        head = records[passport.trial_registry_sequence - 1]["record_hash"]
        if head != passport.trial_registry_head_hash:
            raise IncompleteDisclosureError("passport trial-registry head does not match")
        receipts = self.receipts_for_candidate(
            passport.candidate_hash,
            through_sequence=passport.trial_registry_sequence,
        )
        disclosed = tuple(receipt.content_hash for receipt in receipts)
        failed = tuple(
            receipt.content_hash
            for receipt in receipts
            if receipt.status is not TrialStatus.SUCCEEDED
        )
        if set(disclosed) != set(passport.trial_receipt_hashes):
            raise IncompleteDisclosureError("passport omits or invents trial receipts")
        if set(failed) != set(passport.failed_trial_receipt_hashes):
            raise IncompleteDisclosureError("passport hides or invents failed trials")
        if any(receipt.lineage_cluster_id != passport.lineage_cluster_id for receipt in receipts):
            raise IncompleteDisclosureError("receipt lineage cluster mismatch")
        if not set(receipt.mandate_hash for receipt in receipts).issubset(
            passport.research_mandate_hashes
        ):
            raise IncompleteDisclosureError("passport omits a receipt mandate")
        return True

    def verify(self) -> bool:
        receipts = self.receipts()
        trial_ids = [receipt.trial_id for receipt in receipts]
        if len(trial_ids) != len(set(trial_ids)):
            raise JournalIntegrityError("trial IDs are not unique")
        return self.journal.verify()
