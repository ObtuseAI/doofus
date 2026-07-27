"""Nonfinancial, nonredeemable ProofCredit forecasting market."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, Field

from .canonical import CanonicalModel
from .contracts import Digest, NonEmpty
from .journal import DuplicateRecordError, HashChainJournal
from .lineage import LineageArchive


class InsufficientProofCredit(ValueError):
    pass


class ProofMarketError(ValueError):
    pass


class ProofCreditEventV1(CanonicalModel):
    schema_id: Literal["dumbmoney.proof_credit_event.v1"] = "dumbmoney.proof_credit_event.v1"
    event_id: NonEmpty
    event_type: Literal["endowment", "forecast_opened", "forecast_settled"]
    lineage_cluster_id: Digest
    candidate_hash: Digest
    claim_id: NonEmpty | None = None
    forecast_id: NonEmpty | None = None
    probability_ppm: int | None = Field(default=None, ge=0, le=1_000_000)
    stake_microcredits: int = Field(default=0, ge=0)
    payout_microcredits: int = Field(default=0, ge=0)
    balance_delta_microcredits: int
    outcome: bool | None = None
    occurred_at: AwareDatetime
    unit: Literal["proof_credit"] = "proof_credit"
    redeemable: Literal[False] = False
    transferable: Literal[False] = False
    grants_broker_authority: Literal[False] = False
    grants_capital_authority: Literal[False] = False


class ProofCreditWalletV1(CanonicalModel):
    schema_id: Literal["dumbmoney.proof_credit_wallet.v1"] = "dumbmoney.proof_credit_wallet.v1"
    lineage_cluster_id: Digest
    balance_microcredits: int = Field(ge=0)
    locked_microcredits: int = Field(ge=0)
    unit: Literal["proof_credit"] = "proof_credit"
    redeemable: Literal[False] = False
    transferable: Literal[False] = False
    grants_broker_authority: Literal[False] = False
    grants_capital_authority: Literal[False] = False


class ProofCreditLedger:
    """Hash-chained ledger keyed only by a resolved lineage cluster.

    There is intentionally no transfer, withdrawal, redemption, signing, or
    execution API.  Credits allocate research attention and nothing else.
    """

    STREAM_ID = "dumbmoney.proof_credit.v1"

    def __init__(self, path: Path | str, *, lineage: LineageArchive) -> None:
        self.journal = HashChainJournal(path, stream_id=self.STREAM_ID)
        self.lineage = lineage

    @staticmethod
    def _events_from_records(
        records: list[dict[str, Any]],
    ) -> tuple[ProofCreditEventV1, ...]:
        return tuple(ProofCreditEventV1.model_validate(record["payload"]) for record in records)

    def events(self) -> tuple[ProofCreditEventV1, ...]:
        return self._events_from_records(self.journal.read_verified())

    def _cluster(self, candidate_hash: str) -> str:
        return self.lineage.cluster_for(candidate_hash)

    def wallet_for_candidate(self, candidate_hash: str) -> ProofCreditWalletV1:
        return self.wallet(self._cluster(candidate_hash))

    @staticmethod
    def _wallet_from_events(
        events: tuple[ProofCreditEventV1, ...],
        lineage_cluster_id: str,
    ) -> ProofCreditWalletV1:
        balance = 0
        locked = 0
        for event in events:
            if event.lineage_cluster_id != lineage_cluster_id:
                continue
            balance += event.balance_delta_microcredits
            if event.event_type == "forecast_opened":
                locked += event.stake_microcredits
            elif event.event_type == "forecast_settled":
                locked -= event.stake_microcredits
        if balance < 0 or locked < 0:
            raise ProofMarketError("proof-credit journal derives an impossible wallet state")
        return ProofCreditWalletV1(
            lineage_cluster_id=lineage_cluster_id,
            balance_microcredits=balance,
            locked_microcredits=locked,
        )

    def wallet(self, lineage_cluster_id: str) -> ProofCreditWalletV1:
        return self._wallet_from_events(self.events(), lineage_cluster_id)

    def endow(
        self,
        *,
        event_id: str,
        candidate_hash: str,
        amount_microcredits: int,
        occurred_at: datetime,
    ) -> ProofCreditEventV1:
        if amount_microcredits <= 0:
            raise ProofMarketError("endowment must be positive")
        cluster = self._cluster(candidate_hash)
        event = ProofCreditEventV1(
            event_id=event_id,
            event_type="endowment",
            lineage_cluster_id=cluster,
            candidate_hash=candidate_hash,
            balance_delta_microcredits=amount_microcredits,
            occurred_at=occurred_at,
        )

        def validate_existing(records: list[dict[str, Any]]) -> None:
            if any(
                item.event_type == "endowment" and item.lineage_cluster_id == cluster
                for item in self._events_from_records(records)
            ):
                raise ProofMarketError(
                    "lineage cluster already received its one-time endowment"
                )

        self.journal.append(
            event.model_dump(mode="json"),
            unique_key="event_id",
            unique_value=event_id,
            validate_existing=validate_existing,
        )
        return event

    def open_forecast(
        self,
        *,
        event_id: str,
        forecast_id: str,
        candidate_hash: str,
        claim_id: str,
        probability_ppm: int,
        stake_microcredits: int,
        occurred_at: datetime,
    ) -> ProofCreditEventV1:
        if not 0 <= probability_ppm <= 1_000_000:
            raise ProofMarketError("probability_ppm must be within [0, 1_000_000]")
        if stake_microcredits <= 0:
            raise ProofMarketError("stake must be positive")
        cluster = self._cluster(candidate_hash)
        event = ProofCreditEventV1(
            event_id=event_id,
            event_type="forecast_opened",
            lineage_cluster_id=cluster,
            candidate_hash=candidate_hash,
            claim_id=claim_id,
            forecast_id=forecast_id,
            probability_ppm=probability_ppm,
            stake_microcredits=stake_microcredits,
            balance_delta_microcredits=-stake_microcredits,
            occurred_at=occurred_at,
        )

        def validate_existing(records: list[dict[str, Any]]) -> None:
            events = self._events_from_records(records)
            if any(item.forecast_id == forecast_id for item in events):
                raise DuplicateRecordError(f"duplicate forecast_id: {forecast_id}")
            if any(
                item.event_type == "forecast_opened"
                and item.lineage_cluster_id == cluster
                and item.claim_id == claim_id
                and not any(
                    settlement.event_type == "forecast_settled"
                    and settlement.forecast_id == item.forecast_id
                    for settlement in events
                )
                for item in events
            ):
                raise ProofMarketError(
                    "lineage cluster already has an open forecast for this claim"
                )
            wallet = self._wallet_from_events(events, cluster)
            if wallet.balance_microcredits < stake_microcredits:
                raise InsufficientProofCredit("stake exceeds available proof credits")

        self.journal.append(
            event.model_dump(mode="json"),
            unique_key="event_id",
            unique_value=event_id,
            validate_existing=validate_existing,
        )
        return event

    def settle_forecast(
        self,
        *,
        event_id: str,
        forecast_id: str,
        outcome: bool,
        occurred_at: datetime,
    ) -> ProofCreditEventV1:
        events = self.events()
        opened = [
            event
            for event in events
            if event.event_type == "forecast_opened" and event.forecast_id == forecast_id
        ]
        if len(opened) != 1:
            raise ProofMarketError("forecast does not resolve to one open event")
        if any(
            event.event_type == "forecast_settled" and event.forecast_id == forecast_id
            for event in events
        ):
            raise ProofMarketError("forecast is already settled")
        forecast = opened[0]
        assert forecast.probability_ppm is not None
        target = 1_000_000 if outcome else 0
        error = abs(forecast.probability_ppm - target)
        # Brier score: 1 - (p - y)^2.  It is strictly proper and bounded
        # within [0, 1], so settlement can never create more than the stake.
        score_ppm = max(0, 1_000_000 - ((error * error) // 1_000_000))
        payout = (forecast.stake_microcredits * score_ppm) // 1_000_000
        event = ProofCreditEventV1(
            event_id=event_id,
            event_type="forecast_settled",
            lineage_cluster_id=forecast.lineage_cluster_id,
            candidate_hash=forecast.candidate_hash,
            claim_id=forecast.claim_id,
            forecast_id=forecast.forecast_id,
            probability_ppm=forecast.probability_ppm,
            stake_microcredits=forecast.stake_microcredits,
            payout_microcredits=payout,
            balance_delta_microcredits=payout,
            outcome=outcome,
            occurred_at=occurred_at,
        )

        def validate_existing(records: list[dict[str, Any]]) -> None:
            current = self._events_from_records(records)
            current_opened = [
                item
                for item in current
                if item.event_type == "forecast_opened"
                and item.forecast_id == forecast_id
            ]
            if len(current_opened) != 1 or current_opened[0] != forecast:
                raise ProofMarketError("forecast open event changed before settlement")
            if any(
                item.event_type == "forecast_settled"
                and item.forecast_id == forecast_id
                for item in current
            ):
                raise ProofMarketError("forecast is already settled")

        self.journal.append(
            event.model_dump(mode="json"),
            unique_key="event_id",
            unique_value=event_id,
            validate_existing=validate_existing,
        )
        return event

    def verify(self) -> bool:
        self.lineage.verify()
        events = self.events()
        endowments: set[str] = set()
        open_forecasts: dict[str, ProofCreditEventV1] = {}
        settled: set[str] = set()
        for event in events:
            if self._cluster(event.candidate_hash) != event.lineage_cluster_id:
                raise ProofMarketError("event candidate does not resolve to its wallet")
            if event.event_type == "endowment":
                if event.lineage_cluster_id in endowments:
                    raise ProofMarketError("multiple endowments for one lineage cluster")
                endowments.add(event.lineage_cluster_id)
            elif event.event_type == "forecast_opened":
                assert event.forecast_id is not None
                if event.forecast_id in open_forecasts:
                    raise ProofMarketError("duplicate open forecast")
                open_forecasts[event.forecast_id] = event
            else:
                assert event.forecast_id is not None
                if event.forecast_id not in open_forecasts or event.forecast_id in settled:
                    raise ProofMarketError("invalid forecast settlement")
                if event.payout_microcredits > open_forecasts[event.forecast_id].stake_microcredits:
                    raise ProofMarketError("settlement exceeds bounded stake")
                settled.add(event.forecast_id)
        for cluster in {event.lineage_cluster_id for event in events}:
            self.wallet(cluster)
        return self.journal.verify()
