"""Build Doofus run reports."""
from __future__ import annotations
from doofus.dashboard.dashboard_data import summary, chart_series
from doofus.core.doofus_events import utc_now

def build_latest_run_report() -> dict:
    s = summary()
    return {
        "classification": "DOOFUS_LATEST_RUN_REPORT_READY",
        "label": "doofus_local_operation_ready_with_notes",
        "foundry_proven": False,
        "summary": s,
        "charts": chart_series(),
        "generated_at": utc_now(),
    }
