"""Promotion audit report CLI."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.reports.burn_in_metrics_snapshot import AUDIT_DIR
from doofus.scoring.promotion_audit import audit_promotions

OUT_JSON = AUDIT_DIR / "b1073_promotion_audit.json"
OUT_MD = AUDIT_DIR / "B1073_PROMOTION_AUDIT.md"


def build_report(*, since: str | None = None) -> dict:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    burn_in_path = AUDIT_DIR / "b1071_2_5_hour_live_burn_in.json"
    if since is None and burn_in_path.exists():
        bi = json.loads(burn_in_path.read_text(encoding="utf-8"))
        since = bi.get("burn_in_start")

    result = audit_promotions(since=since, limit=10)
    s = result["summary"]

    if s.get("unsafe", 0) > 0:
        classification = "B1073_PROMOTION_AUDIT_ROLLBACK_RECOMMENDED"
    elif s.get("weak", 0) > s.get("validated", 0):
        classification = "B1073_PROMOTION_AUDIT_WEAK_PROMOTIONS_FOUND"
    elif s.get("validated", 0) == 0 and s.get("promotions_audited", 0) == 0:
        classification = "B1073_PROMOTION_AUDIT_PASS_WITH_NOTES"
    elif s.get("weak", 0) > 0 or s.get("missing_proof", 0) > 0:
        classification = "B1073_PROMOTION_AUDIT_PASS_WITH_NOTES"
    else:
        classification = "B1073_PROMOTION_AUDIT_PASS"

    report = {"classification": classification, **result}
    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# B1073 Promotion Audit",
        "",
        f"Classification: `{classification}`",
        "",
        f"- Audited: {s.get('promotions_audited', 0)}",
        f"- Validated: {s.get('validated', 0)}",
        f"- Weak: {s.get('weak', 0)}",
        f"- Unsafe: {s.get('unsafe', 0)}",
        f"- Unreplayable: {s.get('unreplayable', 0)}",
        f"- Rollback recommended: {s.get('rollback_recommended', 0)}",
        "",
    ]
    for p in result.get("promotions", [])[:10]:
        lines.append(f"- `{p.get('candidate_id')}` gen={p.get('generation')} verdict={p.get('verdict')} delta={p.get('delta_vs_baseline')}")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> None:
    r = build_report()
    print(json.dumps({"classification": r["classification"], "summary": r["summary"]}, indent=2))


if __name__ == "__main__":
    main()
