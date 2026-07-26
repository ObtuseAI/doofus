"""Promotion gate recommendation report."""
from __future__ import annotations

import json

from doofus.reports.burn_in_metrics_snapshot import AUDIT_DIR
from doofus.reports.promotion_audit_report import build_report as build_promotion_audit
from doofus.scoring.promotion_gate_recommendation import recommend_gate

OUT_JSON = AUDIT_DIR / "b1074_promotion_gate_recommendation.json"
OUT_MD = AUDIT_DIR / "B1074_PROMOTION_GATE_RECOMMENDATION.md"


def build_report() -> dict:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    audit = build_promotion_audit()
    rec = recommend_gate(audit)

    if rec["recommendation"] != "keep_gate_current":
        classification = "B1074_PROMOTION_GATE_RECOMMENDATION_CHANGE_RECOMMENDED"
    elif audit["summary"].get("weak", 0) > 0:
        classification = "B1074_PROMOTION_GATE_RECOMMENDATION_PASS_WITH_NOTES"
    else:
        classification = "B1074_PROMOTION_GATE_RECOMMENDATION_PASS"

    report = {"classification": classification, "recommendation": rec, "audit_summary": audit["summary"]}
    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    OUT_MD.write_text(
        f"# B1074 Promotion Gate Recommendation\n\n"
        f"Classification: `{classification}`\n\n"
        f"Recommendation: **{rec['recommendation']}**\n\n"
        f"Current threshold: {rec['current_threshold']}\n"
        f"Recommended threshold: {rec['recommended_threshold']}\n\n"
        f"Why: {rec['why']}\n\n"
        f"Risk: {rec['risk']}\n\n"
        f"Rollback plan: {rec['rollback_plan']}\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    r = build_report()
    print(json.dumps({"classification": r["classification"], "recommendation": r["recommendation"]["recommendation"]}, indent=2))


if __name__ == "__main__":
    main()
