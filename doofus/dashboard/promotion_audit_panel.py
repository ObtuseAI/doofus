"""Promotion audit panel for dashboard."""
from __future__ import annotations

import json

from doofus.core.doofus_paths import BURN_IN_AUDIT_DIR

AUDIT_DIR = BURN_IN_AUDIT_DIR

AUDIT_JSON = AUDIT_DIR / "b1073_promotion_audit.json"
GATE_JSON = AUDIT_DIR / "b1074_promotion_gate_recommendation.json"


def get_promotion_audit_status() -> dict:
    audit = gate = {}
    if AUDIT_JSON.exists():
        audit = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    if GATE_JSON.exists():
        gate = json.loads(GATE_JSON.read_text(encoding="utf-8"))
    summary = audit.get("summary", {})
    rec = gate.get("recommendation", {})
    return {
        "status": audit.get("classification", "pending"),
        "promotions_audited": summary.get("promotions_audited", 0),
        "validated_promotions": summary.get("validated", 0),
        "weak_promotion_count": summary.get("weak", 0),
        "unsafe_promotion_count": summary.get("unsafe", 0),
        "unreplayable_count": summary.get("unreplayable", 0),
        "rollback_recommendation_count": summary.get("rollback_recommended", 0),
        "gate_recommendation": rec.get("recommendation", "pending"),
        "gate_current_threshold": rec.get("current_threshold"),
        "gate_recommended_threshold": rec.get("recommended_threshold"),
        "audit_report_path": str(AUDIT_JSON) if AUDIT_JSON.exists() else None,
        "gate_report_path": str(GATE_JSON) if GATE_JSON.exists() else None,
        "verdicts": [p.get("verdict") for p in audit.get("promotions", [])[:10]],
    }
