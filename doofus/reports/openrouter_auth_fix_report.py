"""Build OpenRouter auth fix reports — REDACTED only."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.core.doofus_paths import SHARED
from doofus.model_router.desktop_secret_loader import safe_report, load_desktop_secret
from doofus.reports.doofus_report_builder import build_latest_run_report


def build_auth_fix_report(*, head_before: str, head_after: str, probe: dict, proof: dict | None = None) -> dict:
    desk = safe_report(load_desktop_secret())
    latest = build_latest_run_report()
    return {
        "classification": "DOOFUS_OPENROUTER_AUTH_FIX_REPORT",
        "head_before": head_before,
        "head_after": head_after,
        "desktop_secret": desk,
        "repair_probe": probe,
        "live_proof": proof or {"classification": "not_run"},
        "latest_summary": latest.get("summary", {}),
        "credentials_exposed": False,
    }


def export_auth_fix_reports(report: dict) -> dict:
    SHARED.mkdir(parents=True, exist_ok=True)
    files = {
        "DOOFUS-OPENROUTER-AUTH-FIX-REPORT.json": report,
        "DOOFUS-DEEPSEEK-LIVE-PROOF-REPORT.json": report.get("live_proof", {}),
        "DOOFUS-LIVE-CYCLE-REPORT.json": report.get("live_cycle", {}),
    }
    for name, body in files.items():
        (SHARED / name).write_text(json.dumps(body, indent=2), encoding="utf-8")
        (SHARED / name.replace(".json", ".md")).write_text(
            f"# {name}\n\n```json\n{json.dumps(body, indent=2)}\n```\n", encoding="utf-8"
        )
    latest = build_latest_run_report()
    (SHARED / "DOOFUS-LATEST-RUN-REPORT.json").write_text(json.dumps(latest, indent=2), encoding="utf-8")
    return {"path": str(SHARED), "files": list(files)}
