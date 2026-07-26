"""Inline rescue sub-budget policy during cycle init."""
from __future__ import annotations

import os
import time

# Classifications
SHADOW_UPGRADE_DEFERRED_DEADLINE = "SHADOW_UPGRADE_DEFERRED_DEADLINE"
SHADOW_UPGRADE_ITEM_TIMEOUT = "SHADOW_UPGRADE_ITEM_TIMEOUT"
SHADOW_UPGRADE_PARTIAL = "SHADOW_UPGRADE_PARTIAL"
INLINE_RESCUE_SHADOW_UPGRADE_DEFERRED = "INLINE_RESCUE_SHADOW_UPGRADE_DEFERRED"


def init_watchdog_seconds() -> float:
    return float(os.environ.get("DOOFUS_CYCLE_INIT_WATCHDOG_SECONDS", "180"))


def candidate_gen_reserve_seconds() -> float:
    return float(os.environ.get("DOOFUS_INLINE_RESCUE_CANDIDATE_RESERVE_SECONDS", "60"))


def high_score_max_seconds() -> float:
    return float(os.environ.get("DOOFUS_INLINE_RESCUE_HIGH_SCORE_MAX_SECONDS", "15"))


def shadow_upgrade_max_seconds() -> float:
    return float(os.environ.get("DOOFUS_INLINE_RESCUE_SHADOW_UPGRADE_MAX_SECONDS", "30"))


def shadow_upgrade_init_item_limit() -> int:
    return int(os.environ.get("DOOFUS_SHADOW_UPGRADE_INIT_ITEM_LIMIT", "1"))


def shadow_upgrade_max_item_seconds() -> float:
    return float(os.environ.get("DOOFUS_SHADOW_UPGRADE_MAX_ITEM_SECONDS", "25"))


def shadow_upgrade_min_budget_seconds() -> float:
    return float(os.environ.get("DOOFUS_SHADOW_UPGRADE_MIN_BUDGET_SECONDS", "5"))


def proof_builder_enqueue_max_seconds() -> float:
    return float(os.environ.get("DOOFUS_INLINE_RESCUE_PROOF_ENQUEUE_MAX_SECONDS", "10"))


def artifact_flush_max_seconds() -> float:
    return float(os.environ.get("DOOFUS_INLINE_RESCUE_ARTIFACT_FLUSH_MAX_SECONDS", "5"))


def inline_rescue_init_max_seconds() -> float:
    return float(os.environ.get("DOOFUS_INLINE_RESCUE_INIT_MAX_SECONDS", "90"))


def remaining_seconds(deadline_monotonic: float | None) -> float | None:
    if deadline_monotonic is None:
        return None
    return max(0.0, deadline_monotonic - time.monotonic())


def remaining_ms(deadline_monotonic: float | None) -> float | None:
    rem = remaining_seconds(deadline_monotonic)
    return None if rem is None else rem * 1000.0


def shadow_upgrade_sub_deadline(
    deadline_monotonic: float | None,
    *,
    init_phase: bool = False,
) -> float | None:
    if deadline_monotonic is None:
        return None
    cap = shadow_upgrade_max_seconds()
    sub = time.monotonic() + cap
    if init_phase:
        inline_cap = time.monotonic() + inline_rescue_init_max_seconds()
        sub = min(sub, inline_cap)
    return min(deadline_monotonic, sub)


def should_defer_shadow_upgrade(
    deadline_monotonic: float | None,
    *,
    init_phase: bool = False,
) -> tuple[bool, str]:
    rem = remaining_seconds(deadline_monotonic)
    if rem is None:
        return False, "no_deadline"
    min_budget = shadow_upgrade_min_budget_seconds()
    if init_phase and rem < candidate_gen_reserve_seconds() + min_budget:
        return True, "init_candidate_reserve_low"
    if rem < min_budget:
        return True, "insufficient_budget"
    sub = shadow_upgrade_sub_deadline(deadline_monotonic, init_phase=init_phase)
    if sub is not None and remaining_seconds(sub) is not None and remaining_seconds(sub) < min_budget:
        return True, "shadow_sub_budget_low"
    return False, "proceed"


def effective_item_limit(*, init_phase: bool, requested_limit: int) -> int:
    if init_phase:
        return min(requested_limit, shadow_upgrade_init_item_limit())
    return requested_limit


def effective_item_timeout_seconds(
    deadline_monotonic: float | None,
    *,
    init_phase: bool = False,
) -> float:
    cap = shadow_upgrade_max_item_seconds()
    if deadline_monotonic is None:
        return cap
    rem = remaining_seconds(deadline_monotonic)
    if rem is None:
        return cap
    return max(0.1, min(cap, rem - 1.0))


def policy_snapshot() -> dict:
    return {
        "init_watchdog_seconds": init_watchdog_seconds(),
        "candidate_gen_reserve_seconds": candidate_gen_reserve_seconds(),
        "high_score_max_seconds": high_score_max_seconds(),
        "shadow_upgrade_max_seconds": shadow_upgrade_max_seconds(),
        "shadow_upgrade_init_item_limit": shadow_upgrade_init_item_limit(),
        "shadow_upgrade_max_item_seconds": shadow_upgrade_max_item_seconds(),
        "shadow_upgrade_min_budget_seconds": shadow_upgrade_min_budget_seconds(),
        "proof_builder_enqueue_max_seconds": proof_builder_enqueue_max_seconds(),
        "artifact_flush_max_seconds": artifact_flush_max_seconds(),
        "inline_rescue_init_max_seconds": inline_rescue_init_max_seconds(),
    }
