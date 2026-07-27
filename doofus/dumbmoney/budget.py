"""Hard daily external-research budget with a fixed 60/20/20 split."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from .canonical import CanonicalModel
from .contracts import NonEmpty
from .journal import HashChainJournal

BudgetCategory = Literal[
    "evidence_exploitation",
    "adversarial_falsification",
    "novel_lineage",
]

DAILY_LIMIT_MICROUSD: Literal[10_000_000] = 10_000_000
CATEGORY_LIMITS_MICROUSD: dict[BudgetCategory, int] = {
    "evidence_exploitation": 6_000_000,
    "adversarial_falsification": 2_000_000,
    "novel_lineage": 2_000_000,
}


class BudgetExceeded(RuntimeError):
    pass


class BudgetStateError(ValueError):
    pass


class BudgetEventV1(CanonicalModel):
    schema_id: Literal["dumbmoney.external_budget_event.v1"] = (
        "dumbmoney.external_budget_event.v1"
    )
    event_id: NonEmpty
    lease_id: NonEmpty
    event_type: Literal["reserved", "settled", "cancelled"]
    budget_day: date
    category: BudgetCategory
    reserved_microusd: int = Field(default=0, ge=0)
    actual_microusd: int = Field(default=0, ge=0)
    occurred_at: AwareDatetime
    external_budget_only: Literal[True] = True
    grants_broker_authority: Literal[False] = False
    grants_capital_authority: Literal[False] = False


class ExternalBudgetLeaseV1(CanonicalModel):
    schema_id: Literal["dumbmoney.external_budget_lease.v1"] = (
        "dumbmoney.external_budget_lease.v1"
    )
    lease_id: NonEmpty
    budget_day: date
    category: BudgetCategory
    maximum_microusd: int = Field(gt=0)
    expires_at: AwareDatetime
    purpose: NonEmpty
    model_gateway_only: Literal[True] = True
    grants_broker_authority: Literal[False] = False
    grants_capital_authority: Literal[False] = False


class BudgetSnapshotV1(CanonicalModel):
    schema_id: Literal["dumbmoney.external_budget_snapshot.v1"] = (
        "dumbmoney.external_budget_snapshot.v1"
    )
    budget_day: date
    daily_limit_microusd: Literal[10_000_000] = DAILY_LIMIT_MICROUSD
    spent_microusd: int = Field(ge=0)
    reserved_microusd: int = Field(ge=0)
    exploitation_spent_or_reserved_microusd: int = Field(ge=0)
    falsification_spent_or_reserved_microusd: int = Field(ge=0)
    novelty_spent_or_reserved_microusd: int = Field(ge=0)


class DailyExternalBudget:
    STREAM_ID = "dumbmoney.external_budget.v1"

    def __init__(self, path: Path | str) -> None:
        self.journal = HashChainJournal(path, stream_id=self.STREAM_ID)

    @staticmethod
    def _events_from_records(records: list[dict[str, object]]) -> tuple[BudgetEventV1, ...]:
        return tuple(BudgetEventV1.model_validate(record["payload"]) for record in records)

    def events(self) -> tuple[BudgetEventV1, ...]:
        return self._events_from_records(self.journal.read_verified())

    def _lease_events(self, lease_id: str) -> tuple[BudgetEventV1, ...]:
        return tuple(event for event in self.events() if event.lease_id == lease_id)

    @staticmethod
    def _active_and_spent_from_events(
        events: tuple[BudgetEventV1, ...],
        budget_day: date,
    ) -> tuple[dict[BudgetCategory, int], dict[BudgetCategory, int]]:
        active: dict[str, int] = {}
        categories: dict[str, BudgetCategory] = {}
        spent = {category: 0 for category in CATEGORY_LIMITS_MICROUSD}
        for event in events:
            if event.budget_day != budget_day:
                continue
            if event.event_type == "reserved":
                active[event.lease_id] = event.reserved_microusd
                categories[event.lease_id] = event.category
            elif event.event_type == "settled":
                if event.lease_id not in active:
                    raise BudgetStateError("settlement has no active reservation")
                active.pop(event.lease_id)
                categories.pop(event.lease_id)
                spent[event.category] += event.actual_microusd
            else:
                if event.lease_id not in active:
                    raise BudgetStateError("cancellation has no active reservation")
                active.pop(event.lease_id)
                categories.pop(event.lease_id)
        reserved = {category: 0 for category in CATEGORY_LIMITS_MICROUSD}
        for lease_id, amount in active.items():
            reserved[categories[lease_id]] += amount
        return spent, reserved

    def _active_and_spent(
        self,
        budget_day: date,
    ) -> tuple[dict[BudgetCategory, int], dict[BudgetCategory, int]]:
        return self._active_and_spent_from_events(self.events(), budget_day)

    def snapshot(self, budget_day: date) -> BudgetSnapshotV1:
        spent, reserved = self._active_and_spent(budget_day)
        combined = {
            category: spent[category] + reserved[category]
            for category in CATEGORY_LIMITS_MICROUSD
        }
        return BudgetSnapshotV1(
            budget_day=budget_day,
            spent_microusd=sum(spent.values()),
            reserved_microusd=sum(reserved.values()),
            exploitation_spent_or_reserved_microusd=combined["evidence_exploitation"],
            falsification_spent_or_reserved_microusd=combined["adversarial_falsification"],
            novelty_spent_or_reserved_microusd=combined["novel_lineage"],
        )

    def reserve(
        self,
        lease: ExternalBudgetLeaseV1,
        *,
        event_id: str,
        occurred_at: datetime,
    ) -> BudgetEventV1:
        if lease.expires_at <= occurred_at:
            raise BudgetStateError("cannot reserve an expired lease")
        event = BudgetEventV1(
            event_id=event_id,
            lease_id=lease.lease_id,
            event_type="reserved",
            budget_day=lease.budget_day,
            category=lease.category,
            reserved_microusd=lease.maximum_microusd,
            occurred_at=occurred_at,
        )

        def validate_existing(records: list[dict[str, object]]) -> None:
            events = self._events_from_records(records)
            if any(item.lease_id == lease.lease_id for item in events):
                raise BudgetStateError("lease_id already exists")
            spent, reserved = self._active_and_spent_from_events(events, lease.budget_day)
            category_used = spent[lease.category] + reserved[lease.category]
            if (
                category_used + lease.maximum_microusd
                > CATEGORY_LIMITS_MICROUSD[lease.category]
            ):
                raise BudgetExceeded(f"{lease.category} 60/20/20 allocation exhausted")
            if (
                sum(spent.values())
                + sum(reserved.values())
                + lease.maximum_microusd
                > DAILY_LIMIT_MICROUSD
            ):
                raise BudgetExceeded("$10 daily external budget exhausted")

        self.journal.append(
            event.model_dump(mode="json"),
            unique_key="event_id",
            unique_value=event_id,
            validate_existing=validate_existing,
        )
        return event

    def settle(
        self,
        *,
        lease_id: str,
        event_id: str,
        actual_microusd: int,
        occurred_at: datetime,
    ) -> BudgetEventV1:
        if actual_microusd < 0:
            raise BudgetStateError("actual cost cannot be negative")
        events = self._lease_events(lease_id)
        if len(events) != 1 or events[0].event_type != "reserved":
            raise BudgetStateError("lease is not active")
        reservation = events[0]
        if actual_microusd > reservation.reserved_microusd:
            raise BudgetExceeded("actual cost exceeds reserved hard ceiling")
        event = BudgetEventV1(
            event_id=event_id,
            lease_id=lease_id,
            event_type="settled",
            budget_day=reservation.budget_day,
            category=reservation.category,
            actual_microusd=actual_microusd,
            occurred_at=occurred_at,
        )

        def validate_existing(records: list[dict[str, object]]) -> None:
            current = tuple(
                item
                for item in self._events_from_records(records)
                if item.lease_id == lease_id
            )
            if len(current) != 1 or current[0].event_type != "reserved":
                raise BudgetStateError("lease is not active")
            if (
                current[0].budget_day != reservation.budget_day
                or current[0].category != reservation.category
                or current[0].reserved_microusd != reservation.reserved_microusd
            ):
                raise BudgetStateError("reservation changed before settlement")

        self.journal.append(
            event.model_dump(mode="json"),
            unique_key="event_id",
            unique_value=event_id,
            validate_existing=validate_existing,
        )
        return event

    def cancel(
        self,
        *,
        lease_id: str,
        event_id: str,
        occurred_at: datetime,
    ) -> BudgetEventV1:
        events = self._lease_events(lease_id)
        if len(events) != 1 or events[0].event_type != "reserved":
            raise BudgetStateError("lease is not active")
        reservation = events[0]
        event = BudgetEventV1(
            event_id=event_id,
            lease_id=lease_id,
            event_type="cancelled",
            budget_day=reservation.budget_day,
            category=reservation.category,
            occurred_at=occurred_at,
        )

        def validate_existing(records: list[dict[str, object]]) -> None:
            current = tuple(
                item
                for item in self._events_from_records(records)
                if item.lease_id == lease_id
            )
            if len(current) != 1 or current[0].event_type != "reserved":
                raise BudgetStateError("lease is not active")
            if (
                current[0].budget_day != reservation.budget_day
                or current[0].category != reservation.category
            ):
                raise BudgetStateError("reservation changed before cancellation")

        self.journal.append(
            event.model_dump(mode="json"),
            unique_key="event_id",
            unique_value=event_id,
            validate_existing=validate_existing,
        )
        return event

    def verify(self) -> bool:
        days = {event.budget_day for event in self.events()}
        for day in days:
            spent, reserved = self._active_and_spent(day)
            for category, limit in CATEGORY_LIMITS_MICROUSD.items():
                if spent[category] + reserved[category] > limit:
                    raise BudgetExceeded("recorded category allocation exceeds its hard limit")
            if sum(spent.values()) + sum(reserved.values()) > DAILY_LIMIT_MICROUSD:
                raise BudgetExceeded("recorded daily spend exceeds $10 hard limit")
        return self.journal.verify()
