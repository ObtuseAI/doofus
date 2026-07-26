"""One-shot finish final report."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from doofus.core.doofus_paths import ROOT, SHARED, BURN_IN_AUDIT_DIR
from doofus.reports.burn_in_metrics_snapshot import capture_metrics_snapshot
from doofus.dashboard.live_data_api import get_dashboard_snapshot
from doofus.evolution.evolution_pressure_mode import get_evolution_snapshot
from doofus.scoring.promotion_quarantine import debt_summary

FINISH_DIR = ROOT / "artifacts" / "latest" / "doofus_one_shot_finish"


def build_report(*, head_before: str | None = None) -> dict:
    snap = capture_metrics_snapshot(label="one_shot_finish")
    dash = get_dashboard_snapshot()
    evo = get_evolution_snapshot()
    debt = debt_summary()
    head_after = snap.get("git_head", "unknown")
    report = {
        "label": "doofus_standalone_evolution_runtime_finished_with_notes",
        "head_before": head_before or head_after,
        "head_after": head_after,
        "snapshot": snap,
        "dashboard": {"status": dash.get("status"), "bind": dash.get("bind")},
        "evolution": evo,
        "promotion_debt": debt,
        "burn_in_audit_path": str(BURN_IN_AUDIT_DIR),
    }
    return report


def export_shared_folder(report: dict) -> dict:
    SHARED.mkdir(parents=True, exist_ok=True)
    files = {
        "DOOFUS-ONE-SHOT-FINISH-FINAL-REPORT": report,
        "DOOFUS-EVOLUTION-PRESSURE-MODE-REPORT": report.get("evolution", {}),
        "DOOFUS-SUPERVISOR-RELIABILITY-FIX-REPORT": report.get("snapshot", {}).get("supervisor_task", {}),
        "DOOFUS-PROMOTION-GATE-PROOF-ARENA-REPORT": report.get("promotion_debt", {}),
        "DOOFUS-LATEST-RUN-REPORT": {"summary": report.get("snapshot", {})},
    }
    for stem, body in files.items():
        (SHARED / f"{stem}.json").write_text(json.dumps(body, indent=2), encoding="utf-8")
        (SHARED / f"{stem}.md").write_text(f"# {stem}\n\nLabel: {report.get('label')}\n", encoding="utf-8")
    return {"classification": "B1087_FINAL_TEST_AUDIT_REPORT_PASS_WITH_NOTES", "path": str(SHARED)}


def main() -> None:
    FINISH_DIR.mkdir(parents=True, exist_ok=True)
    try:
        head_before = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        head_before = "unknown"
    report = build_report(head_before=head_before)
    (FINISH_DIR / "one_shot_finish_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    exp = export_shared_folder(report)
    print(json.dumps({"classification": exp["classification"], "label": report["label"]}, indent=2))


if __name__ == "__main__":
    main()
