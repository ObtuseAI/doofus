"""Burn-in status panel for dashboard."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.core.doofus_paths import BURN_IN_AUDIT_DIR

AUDIT_DIR = BURN_IN_AUDIT_DIR

BURN_IN_JSON = AUDIT_DIR / "b1071_2_5_hour_live_burn_in.json"
DELTA_JSON = AUDIT_DIR / "b1072_post_burn_in_metrics_delta.json"


def get_burn_in_status() -> dict:
    status = "not_started"
    data: dict = {}
    if BURN_IN_JSON.exists():
        data = json.loads(BURN_IN_JSON.read_text(encoding="utf-8"))
        status = data.get("status", "unknown")
    deltas = {}
    if DELTA_JSON.exists():
        deltas = json.loads(DELTA_JSON.read_text(encoding="utf-8")).get("deltas", {})
    return {
        "status": status,
        "burn_in_duration_seconds": data.get("burn_in_duration_seconds", 9000),
        "burn_in_start": data.get("burn_in_start"),
        "burn_in_end": data.get("burn_in_end"),
        "classification": data.get("classification"),
        "checkpoints": data.get("checkpoints", []),
        "live_call_count_delta": deltas.get("successful_live_calls"),
        "provider_failures": data.get("provider_failures", 0),
        "rate_limit_events": deltas.get("rate_limit_events", data.get("rate_limit_events", 0)),
        "cooldown_events": deltas.get("cooldown_events", data.get("cooldown_events", 0)),
        "candidate_delta": deltas.get("candidate_delta"),
        "promotion_delta": deltas.get("promotion_delta"),
        "rejection_delta": deltas.get("rejection_delta"),
        "report_path": str(BURN_IN_JSON) if BURN_IN_JSON.exists() else None,
        "delta_report_path": str(DELTA_JSON) if DELTA_JSON.exists() else None,
    }
