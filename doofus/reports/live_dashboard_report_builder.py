"""Build live dashboard Shared Folder reports."""
from __future__ import annotations
import json
from doofus.core.doofus_paths import SHARED
from doofus.dashboard.live_data_api import get_dashboard_snapshot
from doofus.core.doofus_events import utc_now

def build_live_dashboard_report(label: str = "doofus_live_dashboard_ready_with_notes") -> dict:
    snap = get_dashboard_snapshot()
    return {
        "classification": "DOOFUS_LIVE_DASHBOARD_FINAL_REPORT",
        "label": label,
        "foundry_proven": False,
        "snapshot": snap,
        "generated_at": utc_now(),
    }

def export_live_dashboard_shared_folder(label: str = "doofus_live_dashboard_ready_with_notes") -> dict:
    SHARED.mkdir(parents=True, exist_ok=True)
    report = build_live_dashboard_report(label)
    files = {
        "DOOFUS-LIVE-DASHBOARD-README.md": "# Doofus Live Dashboard\n\nNiceGUI localhost-only live charts.\n",
        "DOOFUS-LIVE-DASHBOARD-CHARTS.md": "# Charts\n\nMutation, candidate, score, compounding, recursive learning.\n",
        "DOOFUS-LIVE-DASHBOARD-CONTROL.md": "# Control\n\nSwitch files only. No safety bypass.\n",
        "DOOFUS-LIVE-DASHBOARD-MODEL-COST-SAFETY.md": "# Model/Cost/Safety\n\nAuth status redacted.\n",
        "DOOFUS-LIVE-DASHBOARD-CANDIDATE-LINEAGE.md": "# Lineage\n\nParent-child candidate table.\n",
        "DOOFUS-LIVE-DASHBOARD-FINAL-REPORT.md": f"# Final Report\n\nLabel: {label}\n",
    }
    for name, body in files.items():
        (SHARED / name).write_text(body, encoding="utf-8")
    (SHARED / "DOOFUS-LIVE-DASHBOARD-FINAL-REPORT.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return {"classification": "B1018_SHARED_FOLDER_LIVE_DASHBOARD_REPORT_REFRESH_PASS", "path": str(SHARED)}
