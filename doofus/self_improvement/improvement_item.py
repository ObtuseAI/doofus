"""Improvement item schema for Doofus self-improvement kernel."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

ALLOWED_TYPES = frozenset({
    "mutation_method",
    "repair_recipe",
    "guard_pattern",
    "telemetry_improvement",
    "proof_builder_improvement",
    "scoring_improvement",
    "cycle_quality_improvement",
    "artifact_feed_improvement",
    "operator_packet_improvement",
    "runtime_isolation_improvement",
})

ALLOWED_STATUSES = frozenset({
    "candidate",
    "queued_for_validation",
    "validated",
    "deferred",
    "rejected",
    "implemented",
})


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_dedupe_key(title: str, type_: str, source_generation: int) -> str:
    raw = f"{type_}:{source_generation}:{title.lower().strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class ImprovementItem:
    id: str
    created_at_utc: str
    source_generation: int
    source_artifacts: list[str]
    type: str
    title: str
    summary: str
    problem: str
    recommendation: str
    implementation_hint: str
    expected_value: str
    risk_level: str
    validation_method: str
    required_tests: list[str]
    affected_subsystems: list[str]
    blocked_by: list[str]
    do_not_use_when: list[str]
    status: str
    dedupe_key: str
    score: int = 0
    promotion_requirements: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImprovementItem:
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})

    @classmethod
    def create(
        cls,
        *,
        type_: str,
        title: str,
        summary: str,
        problem: str,
        recommendation: str,
        implementation_hint: str = "",
        expected_value: str = "medium",
        risk_level: str = "low",
        validation_method: str = "",
        required_tests: list[str] | None = None,
        affected_subsystems: list[str] | None = None,
        blocked_by: list[str] | None = None,
        do_not_use_when: list[str] | None = None,
        status: str = "candidate",
        source_generation: int = 1639,
        source_artifacts: list[str] | None = None,
        promotion_requirements: list[str] | None = None,
    ) -> ImprovementItem:
        dedupe = stable_dedupe_key(title, type_, source_generation)
        return cls(
            id=f"doofus-{dedupe}",
            created_at_utc=utc_now(),
            source_generation=source_generation,
            source_artifacts=source_artifacts or [],
            type=type_,
            title=title,
            summary=summary,
            problem=problem,
            recommendation=recommendation,
            implementation_hint=implementation_hint,
            expected_value=expected_value,
            risk_level=risk_level,
            validation_method=validation_method,
            required_tests=required_tests or [],
            affected_subsystems=affected_subsystems or [],
            blocked_by=blocked_by or [],
            do_not_use_when=do_not_use_when or [],
            status=status,
            dedupe_key=dedupe,
            promotion_requirements=promotion_requirements or [],
        )
