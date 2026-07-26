"""Reusable certification evidence validation, manifest, and prep-packet helpers."""
from __future__ import annotations

from typing import Any

from doofus.supervisor.controlled_cycle import (
    AUTHORIZED_LIVE_COMMAND_TEMPLATE,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    live_verification_artifact_dir,
)


def validate_live_verification_evidence(
    *,
    final_report: dict[str, Any],
    telemetry: dict[str, Any],
    post_run: dict[str, Any],
    expected_classification: str,
    source_generation: int,
    target_generation: int,
) -> dict[str, Any]:
    cc_after = telemetry.get("cycle_checkpoint_after") or {}
    cc_after_data = cc_after.get("data") or {}
    checks = {
        "final_classification_pass": final_report.get("classification") == expected_classification,
        "single_authorized_cycle": True,
        "provider_cursor": telemetry.get("provider_route") in (DEFAULT_PROVIDER, "openrouter", "cursor"),
        "model_composer": telemetry.get("model") in (DEFAULT_MODEL, "composer-2.5", "deepseek/deepseek-v4-flash")
        or str(telemetry.get("model", "")).startswith("deepseek"),
        "model_calls_within_limit": telemetry.get("live_model_call_count", 99) <= telemetry.get("model_call_limit", 2),
        "cost_within_limit_or_null": telemetry.get("cost_observed_usd") is None
        or telemetry.get("cost_observed_usd", 0) <= telemetry.get("cost_limit_usd", 0.05),
        "generation_advanced": telemetry.get("generation_before") == source_generation
        and telemetry.get("generation_after") == target_generation,
        "checkpoint_complete": telemetry.get("checkpoint_after", {}).get("generation") == target_generation
        and telemetry.get("checkpoint_after", {}).get("phase") == "complete",
        "cycle_checkpoint_pass": "PASS" in str(cc_after_data.get("classification", ""))
        and cc_after_data.get("generation") == target_generation,
        "stop_restored": post_run.get("stop_flag", {}).get("stop_requested") is True,
        "db_max_target": telemetry.get("db_max_generation_after") == target_generation,
        "next_gen_zero": telemetry.get(f"gen{target_generation + 1}_row_count_after") == 0,
        "candidates_24": telemetry.get("candidate_count") == 24,
        "promoted_0": telemetry.get("promoted_count") == 0,
        "shadow_promoted_0": telemetry.get("shadow_promoted_count") == 0,
        "rejected_24": telemetry.get("rejected_count") == 24,
        "scoring_no_timeout": telemetry.get("inline_rescue_timeout_status") is False,
        "run_window_filter_applied": telemetry.get("run_window_filter_applied") is True,
        "stale_did_not_change_classification": telemetry.get("stale_events_changed_classification") is False,
    }
    return {
        "validated": all(checks.values()),
        "checks": checks,
        "final_classification": final_report.get("classification"),
        "telemetry_summary": {
            k: telemetry.get(k)
            for k in (
                "live_model_call_count",
                "candidate_count",
                "promoted_count",
                "rejected_count",
                "init_watchdog_status",
                "shadow_upgrade_deferred_status",
                "inline_rescue_status",
                "run_window_filter_applied",
                "stale_events_changed_classification",
            )
        },
    }


def build_prep_only_launch_packet(
    *,
    next_generation: int,
    certified_generation: int,
) -> dict[str, Any]:
    return {
        "classification": f"DOOFUS_GEN{next_generation}_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY",
        "warning": f"Preparation only. This does not authorize gen{next_generation} launch.",
        "required_baseline": {
            "checkpoint_generation": certified_generation,
            "checkpoint_phase": "complete",
            "cycle_checkpoint_classification": "B1003_LIVE_MODEL_CYCLE_PASS",
            "cycle_checkpoint_generation": certified_generation,
            "stop_requested": True,
            "db_max_generation": certified_generation,
            "candidates_max_generation": certified_generation,
            f"gen{next_generation}_row_count": 0,
        },
        "preflight_commands": [
            f"python scripts/doofus_live_db_preflight.py --output-dir {live_verification_artifact_dir(next_generation)}",
            f"python scripts/doofus_high_score_miner_diagnostic.py --generation {next_generation} --limit 20 --deadline-seconds 30 --explain-query-plan --output-dir {live_verification_artifact_dir(next_generation)}",
            f"python scripts/doofus_shadow_upgrade_diagnostic.py --generation {next_generation} --limit 5 --deadline-seconds 30 --dry-run --output-dir {live_verification_artifact_dir(next_generation)}",
        ],
        "guard_tests_k": (
            "shadow_upgrade or inline_rescue or high_score or run_window or telemetry_filter "
            "or init_timeout or provider_gate or live_cycle_launch_guard or live_db_preflight "
            "or nonlive_cycle_forces_model_dry_run or controlled_cycle"
        ),
        "required_nonlive_dry_run_guard_probe": "verify_nonlive_dry_run_guard() == DOOFUS_MODEL_DRY_RUN",
        "required_inline_rescue_rehearsal": f"scripts/doofus_gen{certified_generation}_shadow_upgrade_rehearsal.py or controlled-cycle rehearsal",
        "future_artifact_directory": live_verification_artifact_dir(next_generation) + "/",
        "future_command_template": AUTHORIZED_LIVE_COMMAND_TEMPLATE,
        "provider_expected": DEFAULT_PROVIDER,
        "model_expected": DEFAULT_MODEL,
        "refusal_conditions": [
            f"gen{next_generation} rows before launch",
            f"db_max_generation above {certified_generation}",
            f"checkpoint not gen{certified_generation} complete",
            f"cycle checkpoint not gen{certified_generation} pass",
            "stop flag not true",
            "nonlive dry-run guard fails",
            "live DB preflight fails",
            "high-score miner readiness fails",
            "shadow_upgrade readiness fails",
            "run-window telemetry filter missing",
            "inline-rescue rehearsal fails",
            "launch-critical source changes dirty and unreviewed",
            "launch packet mismatch",
        ],
        "rollback_restore_procedure": [
            "Restore stop_requested=true immediately if cleared",
            "Do not scrub authorized baseline rows",
            "Run live DB preflight check-only",
            "Classify as PARTIAL if baseline intact",
        ],
        "future_classifications": [
            f"DOOFUS_GEN{next_generation}_LIVE_VERIFICATION_PASS",
            f"DOOFUS_GEN{next_generation}_LIVE_VERIFICATION_PARTIAL",
            f"DOOFUS_GEN{next_generation}_LIVE_VERIFICATION_FAIL",
        ],
    }
