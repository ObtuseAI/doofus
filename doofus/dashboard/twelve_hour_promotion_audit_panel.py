"""12-hour promotion audit dashboard panel."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.core.doofus_paths import TWELVE_HOUR_RUN_DIR

AUDIT_JSON = TWELVE_HOUR_RUN_DIR / "b1094_promotion_shadow_audit.json"


def get_twelve_hour_promotion_audit_panel() -> dict:
    if not AUDIT_JSON.exists():
        return {"gate_verdict": "pending", "status": "pending"}
    a = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    return {
        "classification": a.get("classification"),
        "gate_verdict": a.get("gate_verdict"),
        "full_promotions_audited": a.get("full_promotions_audited"),
        "shadow_promotions_in_run": a.get("shadow_promotions_in_run"),
        "top_rejected_audited": a.get("top_rejected_audited"),
        "proof_density_failures_top20": a.get("proof_density_failures_top20"),
        "arena_support_failures_top20": a.get("arena_support_failures_top20"),
    }
