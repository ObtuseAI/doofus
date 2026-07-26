"""Reusable controlled one-cycle policy and preflight helpers for Doofus."""
from __future__ import annotations

from enum import Enum
from typing import Any

AUTHORIZED_LIVE_COMMAND_TEMPLATE = (
    "python -m doofus.supervisor.provider_aware_live_cycle "
    "--operator-approved-one-cycle --max-model-calls 2 --max-cost-usd 0.05"
)
DEFAULT_MODEL = "deepseekv4flash"
DEFAULT_PROVIDER = "openrouter"
DEFAULT_OPENROUTER_MODEL_ALIAS = "deepseekv4flash"
DEFAULT_MAX_MODEL_CALLS = 2
DEFAULT_MAX_COST_USD = 0.05


class ControlledCycleMode(str, Enum):
    PREFLIGHT_ONLY = "preflight_only"
    PREP_ONLY = "prep_only"
    REPAIR_READINESS = "repair_readiness"
    LIVE_VERIFICATION = "live_verification"
    POSTLIVE_CERTIFICATION = "postlive_certification"
    FINALIZE_ONLY = "finalize_only"


def artifact_dir_for_generation(generation: int, *, suffix: str = "live-verification-v1") -> str:
    return f"artifacts/doofus/gen{generation}-{suffix}"


def live_verification_artifact_dir(generation: int) -> str:
    return artifact_dir_for_generation(generation, suffix="live-verification-v1")


def postlive_artifact_dir(generation: int) -> str:
    return artifact_dir_for_generation(generation, suffix="postlive-certification-loop-hardening-v1")


def requires_operator_approval(mode: ControlledCycleMode) -> bool:
    return mode == ControlledCycleMode.LIVE_VERIFICATION


def allows_live_route(mode: ControlledCycleMode) -> bool:
    return mode == ControlledCycleMode.LIVE_VERIFICATION


def allows_live_db_mutation(mode: ControlledCycleMode) -> bool:
    return mode == ControlledCycleMode.LIVE_VERIFICATION


def validate_baseline_for_live_launch(
    *,
    checkpoint: dict[str, Any],
    cycle_checkpoint: dict[str, Any],
    stop_flag: dict[str, Any],
    db_max_generation: int,
    candidates_max_generation: int,
    target_generation: int,
    target_generation_row_count: int,
    next_generation_row_count: int,
    checkpoint_schema_valid: bool,
    cycle_checkpoint_schema_valid: bool,
) -> tuple[bool, list[str]]:
    """Return (ok, refuse_reasons) for launching exactly one live cycle to target_generation."""
    source = target_generation - 1
    cc_data = cycle_checkpoint.get("data") or {}
    cc_class = cc_data.get("classification", cycle_checkpoint.get("classification", ""))
    cc_gen = cc_data.get("generation", cycle_checkpoint.get("generation"))
    reasons: list[str] = []
    if checkpoint.get("generation") != source or checkpoint.get("phase") != "complete":
        reasons.append("checkpoint")
    if cc_gen != source or "B1003_LIVE_MODEL_CYCLE_PASS" not in str(cc_class):
        reasons.append("cycle_checkpoint")
    if not checkpoint_schema_valid or not cycle_checkpoint_schema_valid:
        reasons.append("checkpoint_schema_invalid")
    if not stop_flag.get("stop_requested"):
        reasons.append("stop_flag")
    if db_max_generation != source:
        reasons.append("db_max_generation")
    if candidates_max_generation != source:
        reasons.append("candidates_max_generation")
    if target_generation_row_count != 0:
        reasons.append(f"gen{target_generation}_rows_exist")
    if next_generation_row_count != 0:
        reasons.append(f"gen{target_generation + 1}_rows_exist")
    return len(reasons) == 0, reasons


def validate_baseline_for_postlive(
    *,
    checkpoint: dict[str, Any],
    cycle_checkpoint: dict[str, Any],
    stop_flag: dict[str, Any],
    db_max_generation: int,
    certified_generation: int,
    next_generation_row_count: int,
    checkpoint_schema_valid: bool,
    cycle_checkpoint_schema_valid: bool,
) -> tuple[bool, list[str]]:
    cc_data = cycle_checkpoint.get("data") or {}
    cc_class = cc_data.get("classification", cycle_checkpoint.get("classification", ""))
    cc_gen = cc_data.get("generation", cycle_checkpoint.get("generation"))
    reasons: list[str] = []
    if checkpoint.get("generation") != certified_generation or checkpoint.get("phase") != "complete":
        reasons.append("checkpoint")
    if cc_gen != certified_generation or "B1003_LIVE_MODEL_CYCLE_PASS" not in str(cc_class):
        reasons.append("cycle_checkpoint")
    if not checkpoint_schema_valid or not cycle_checkpoint_schema_valid:
        reasons.append("checkpoint_schema_invalid")
    if not stop_flag.get("stop_requested"):
        reasons.append("stop_flag")
    if db_max_generation != certified_generation:
        reasons.append("db_max_generation")
    if next_generation_row_count != 0:
        reasons.append(f"gen{certified_generation + 1}_rows_exist")
    return len(reasons) == 0, reasons
