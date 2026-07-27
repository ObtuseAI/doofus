from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import pytest

from doofus.dumbmoney import (
    ArchiveDimensionV1,
    BudgetExceeded,
    CandidateRecordV1,
    DailyExternalBudget,
    ExternalBudgetLeaseV1,
    LineageArchive,
    ProofCreditLedger,
    content_hash,
)
from doofus.dumbmoney.budget import CATEGORY_LIMITS_MICROUSD
from doofus.dumbmoney.journal import HashChainJournal
from doofus.dumbmoney.proof_credit import InsufficientProofCredit, ProofMarketError

NOW = datetime(2026, 7, 26, 21, 0, tzinfo=timezone.utc)


def digest(label: str) -> str:
    return content_hash({"label": label})


def record(label: str, origin: str) -> CandidateRecordV1:
    return CandidateRecordV1(
        candidate_hash=digest(f"candidate:{label}"),
        origin_fingerprint=digest(f"origin:{origin}"),
        mutation_operator="fixture",
        behavior_cell=(ArchiveDimensionV1(name="domain", value="fixture"),),
        source_bundle_ref=digest(f"bundle:{label}"),
        created_at=NOW,
    )


def lease(lease_id: str, category, amount: int, day: date | None = None) -> ExternalBudgetLeaseV1:
    return ExternalBudgetLeaseV1(
        lease_id=lease_id,
        budget_day=day or NOW.date(),
        category=category,
        maximum_microusd=amount,
        expires_at=NOW + timedelta(hours=1),
        purpose="deterministic fixture",
    )


def test_clone_cannot_mint_second_wallet_or_duplicate_claim(tmp_path) -> None:
    lineage = LineageArchive(tmp_path / "lineage.jsonl")
    root = lineage.register(record("root", "same"))
    clone = lineage.register(record("clone", "same"))
    ledger = ProofCreditLedger(tmp_path / "credits.jsonl", lineage=lineage)
    ledger.endow(
        event_id="grant-1",
        candidate_hash=root.candidate.candidate_hash,
        amount_microcredits=1_000_000,
        occurred_at=NOW,
    )

    assert ledger.wallet_for_candidate(clone.candidate.candidate_hash).balance_microcredits == 1_000_000
    with pytest.raises(ProofMarketError, match="already received"):
        ledger.endow(
            event_id="grant-2",
            candidate_hash=clone.candidate.candidate_hash,
            amount_microcredits=1_000_000,
            occurred_at=NOW,
        )

    ledger.open_forecast(
        event_id="open-1",
        forecast_id="forecast-1",
        candidate_hash=root.candidate.candidate_hash,
        claim_id="claim-1",
        probability_ppm=800_000,
        stake_microcredits=100_000,
        occurred_at=NOW,
    )
    with pytest.raises(ProofMarketError, match="already has an open forecast"):
        ledger.open_forecast(
            event_id="open-clone",
            forecast_id="forecast-clone",
            candidate_hash=clone.candidate.candidate_hash,
            claim_id="claim-1",
            probability_ppm=900_000,
            stake_microcredits=100_000,
            occurred_at=NOW,
        )


def test_brier_settlement_is_proper_bounded_and_nonredeemable(tmp_path) -> None:
    lineage = LineageArchive(tmp_path / "lineage.jsonl")
    root = lineage.register(record("root", "root"))
    ledger = ProofCreditLedger(tmp_path / "credits.jsonl", lineage=lineage)
    ledger.endow(
        event_id="grant",
        candidate_hash=root.candidate.candidate_hash,
        amount_microcredits=1_000_000,
        occurred_at=NOW,
    )
    payouts = []
    for probability, suffix in ((900_000, "good"), (600_000, "weak")):
        ledger.open_forecast(
            event_id=f"open-{suffix}",
            forecast_id=f"forecast-{suffix}",
            candidate_hash=root.candidate.candidate_hash,
            claim_id=f"claim-{suffix}",
            probability_ppm=probability,
            stake_microcredits=100_000,
            occurred_at=NOW,
        )
        settled = ledger.settle_forecast(
            event_id=f"settle-{suffix}",
            forecast_id=f"forecast-{suffix}",
            outcome=True,
            occurred_at=NOW,
        )
        payouts.append(settled.payout_microcredits)
        assert settled.payout_microcredits <= settled.stake_microcredits
        assert settled.redeemable is False
        assert settled.transferable is False
        assert settled.grants_broker_authority is False
        assert settled.grants_capital_authority is False

    assert payouts[0] > payouts[1]
    assert not hasattr(ledger, "withdraw")
    assert not hasattr(ledger, "transfer")
    assert not hasattr(ledger, "redeem")
    assert ledger.verify() is True


def test_daily_budget_enforces_exact_60_20_20_and_ten_dollar_stop(tmp_path) -> None:
    budget = DailyExternalBudget(tmp_path / "budget.jsonl")
    allocations = (
        ("exploit", "evidence_exploitation", 6_000_000),
        ("falsify", "adversarial_falsification", 2_000_000),
        ("novel", "novel_lineage", 2_000_000),
    )
    for suffix, category, amount in allocations:
        budget.reserve(
            lease(suffix, category, amount),
            event_id=f"reserve-{suffix}",
            occurred_at=NOW,
        )

    snapshot = budget.snapshot(NOW.date())
    assert snapshot.spent_microusd == 0
    assert snapshot.reserved_microusd == 10_000_000
    assert CATEGORY_LIMITS_MICROUSD == {
        "evidence_exploitation": 6_000_000,
        "adversarial_falsification": 2_000_000,
        "novel_lineage": 2_000_000,
    }
    with pytest.raises(BudgetExceeded):
        budget.reserve(
            lease("over", "novel_lineage", 1),
            event_id="reserve-over",
            occurred_at=NOW,
        )
    assert budget.verify() is True


def test_budget_cannot_settle_above_reserved_and_resets_by_day(tmp_path) -> None:
    budget = DailyExternalBudget(tmp_path / "budget.jsonl")
    budget.reserve(
        lease("lease-1", "evidence_exploitation", 1_000_000),
        event_id="reserve-1",
        occurred_at=NOW,
    )
    with pytest.raises(BudgetExceeded, match="exceeds reserved"):
        budget.settle(
            lease_id="lease-1",
            event_id="settle-too-much",
            actual_microusd=1_000_001,
            occurred_at=NOW,
        )
    budget.settle(
        lease_id="lease-1",
        event_id="settle-1",
        actual_microusd=900_000,
        occurred_at=NOW,
    )
    tomorrow = NOW.date() + timedelta(days=1)
    budget.reserve(
        ExternalBudgetLeaseV1(
            lease_id="tomorrow",
            budget_day=tomorrow,
            category="evidence_exploitation",
            maximum_microusd=6_000_000,
            expires_at=NOW + timedelta(days=2),
            purpose="tomorrow",
        ),
        event_id="reserve-tomorrow",
        occurred_at=NOW,
    )

    assert budget.snapshot(NOW.date()).spent_microusd == 900_000
    assert budget.snapshot(tomorrow).reserved_microusd == 6_000_000


def test_hash_chain_serializes_preinitialized_instances(tmp_path) -> None:
    path = tmp_path / "shared.jsonl"
    journals = (
        HashChainJournal(path, stream_id="dumbmoney.concurrent-test.v1"),
        HashChainJournal(path, stream_id="dumbmoney.concurrent-test.v1"),
    )
    barrier = threading.Barrier(2)

    def append(index: int) -> dict[str, object]:
        barrier.wait()
        return journals[index].append(
            {"event_id": f"event-{index}"},
            unique_key="event_id",
            unique_value=f"event-{index}",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        records = list(executor.map(append, range(2)))

    assert sorted(record["sequence"] for record in records) == [1, 2]
    verified = HashChainJournal(
        path, stream_id="dumbmoney.concurrent-test.v1"
    ).read_verified()
    assert [record["sequence"] for record in verified] == [1, 2]
    assert verified[1]["previous_record_hash"] == verified[0]["record_hash"]


def test_budget_check_and_append_are_atomic_across_instances(tmp_path) -> None:
    path = tmp_path / "budget.jsonl"
    budgets = (DailyExternalBudget(path), DailyExternalBudget(path))
    barrier = threading.Barrier(2)

    def reserve(index: int) -> str:
        barrier.wait()
        try:
            budgets[index].reserve(
                lease(
                    f"lease-{index}",
                    "novel_lineage",
                    1_500_000,
                ),
                event_id=f"reserve-{index}",
                occurred_at=NOW,
            )
        except BudgetExceeded:
            return "DENIED"
        return "RESERVED"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(reserve, range(2)))

    assert sorted(outcomes) == ["DENIED", "RESERVED"]
    snapshot = DailyExternalBudget(path).snapshot(NOW.date())
    assert snapshot.reserved_microusd == 1_500_000
    assert snapshot.novelty_spent_or_reserved_microusd == 1_500_000


def test_proof_credit_checks_are_atomic_across_instances(tmp_path) -> None:
    lineage = LineageArchive(tmp_path / "lineage.jsonl")
    candidate = lineage.register(record("atomic-root", "atomic-root")).candidate
    path = tmp_path / "credits.jsonl"
    ledgers = (
        ProofCreditLedger(path, lineage=lineage),
        ProofCreditLedger(path, lineage=lineage),
    )
    ledgers[0].endow(
        event_id="atomic-endowment",
        candidate_hash=candidate.candidate_hash,
        amount_microcredits=1_000_000,
        occurred_at=NOW,
    )
    barrier = threading.Barrier(2)

    def open_forecast(index: int) -> str:
        barrier.wait()
        try:
            ledgers[index].open_forecast(
                event_id=f"atomic-open-{index}",
                forecast_id=f"atomic-forecast-{index}",
                candidate_hash=candidate.candidate_hash,
                claim_id=f"atomic-claim-{index}",
                probability_ppm=700_000,
                stake_microcredits=700_000,
                occurred_at=NOW,
            )
        except InsufficientProofCredit:
            return "DENIED"
        return "OPENED"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(open_forecast, range(2)))

    assert sorted(outcomes) == ["DENIED", "OPENED"]
    wallet = ProofCreditLedger(path, lineage=lineage).wallet_for_candidate(
        candidate.candidate_hash
    )
    assert wallet.balance_microcredits == 300_000
    assert wallet.locked_microcredits == 700_000
