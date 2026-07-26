"""Provider router final report export."""
from __future__ import annotations

import json
from doofus.core.doofus_paths import SHARED
from doofus.model_router.provider_router import resolve_provider
from doofus.reports.doofus_report_builder import build_latest_run_report


def export_provider_reports(*, head_before: str, head_after: str, cycle: dict | None = None) -> dict:
    SHARED.mkdir(parents=True, exist_ok=True)
    route = resolve_provider()
    latest = build_latest_run_report()
    report = {
        "classification": "DOOFUS_PROVIDER_ROUTER_FINAL_REPORT",
        "head_before": head_before,
        "head_after": head_after,
        "route": {k: v for k, v in route.items() if k != "secret_value" or v == "REDACTED"},
        "cycle": cycle or {},
        "latest_summary": latest.get("summary", {}),
        "credentials_exposed": False,
    }
    files = {
        "DOOFUS-PROVIDER-ROUTER-FINAL-REPORT.json": report,
        "DOOFUS-LIVE-PROVIDER-CYCLE-REPORT.json": cycle or {},
    }
    for name, body in files.items():
        (SHARED / name).write_text(json.dumps(body, indent=2), encoding="utf-8")
        (SHARED / name.replace(".json", ".md")).write_text(f"# {name}\n\nSee JSON.\n", encoding="utf-8")
    (SHARED / "DOOFUS-LATEST-RUN-REPORT.json").write_text(json.dumps(latest, indent=2), encoding="utf-8")
    return {"path": str(SHARED), "report": report}
