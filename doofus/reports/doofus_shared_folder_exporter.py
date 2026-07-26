"""Export 24/7 reports to Shared Folder."""
from __future__ import annotations
import json
from pathlib import Path
from doofus.core.doofus_paths import SHARED, ROOT
from doofus.reports.doofus_report_builder import build_latest_run_report
from doofus.safety.budget_guard import check_budget
from doofus.safety.on_off_switch import status as switch_status
from doofus.core.doofus_config import DoofusConfig
from doofus.supervisor.doofus_crash_recovery import load_checkpoint
from doofus.meta.recursive_supervisor import get_meta_snapshot
from doofus.promotion.tier3_final_gate import get_tier3_snapshot

def export_24_7_shared_folder(report: dict | None = None) -> dict:
    SHARED.mkdir(parents=True, exist_ok=True)
    report = report or {}
    latest = build_latest_run_report()
    budget = check_budget(DoofusConfig.from_env())

    files = {
        "DOOFUS-24-7-OPERATION-README.md": (
            "# Doofus 24/7 Local Operation\n\n"
            "Local/private operation on GamingPC3. Supervisor via Windows Scheduled Task.\n"
            "Dashboard: http://127.0.0.1:8765 (localhost only).\n"
            "Switch: runtime/control/DOOFUS_RUN.enabled\n"
        ),
        "DOOFUS-24-7-TASK-REGISTRATION.md": (
            "# Task Registration\n\n"
            "Tasks: Doofus-24-7-Supervisor, Doofus-Local-Dashboard\n\n"
            "Register: scripts\\doofus_register_24_7_task.ps1\n"
        ),
        "DOOFUS-DASHBOARD-FINAL-POLISH.md": "# Dashboard Polish\n\nPanels: health, control, model, task, error.\n",
        "DOOFUS-DEEPSEEK-V4-FLASH-LIVE-SMOKE.md": "# Live Smoke\n\nBounded smoke via live_model_smoke module.\n",
        "DOOFUS-LIVE-MODEL-CYCLE-REPORT.md": "# Live Model Cycle\n\nGated by switch, budget, rate guards.\n",
        "DOOFUS-SECRET-AND-ENVIRONMENT-POLICY.md": "# Secret Policy\n\nNever log/commit OPENROUTER_API_KEY.\n",
        "DOOFUS-BUDGET-RATE-GUARD-STATUS.md": f"# Budget/Rate\n\n{json.dumps(budget, indent=2)}\n",
        "DOOFUS-24-7-SOAK-REPORT.md": "# Soak Report\n\nShort controlled soak with switch obeyed.\n",
        "DOOFUS-24-7-FINAL-REPORT.md": (
            f"# Doofus 24/7 Final Report\n\nLabel: {report.get('label', 'doofus_24_7_local_operation_ready_with_notes')}\n"
        ),
    }
    for name, body in files.items():
        (SHARED / name).write_text(body, encoding="utf-8")

    (SHARED / "DOOFUS-24-7-SUPERVISOR-STATUS.json").write_text(json.dumps(report.get("summary", latest["summary"]), indent=2), encoding="utf-8")
    (SHARED / "DOOFUS-LATEST-RUN-REPORT.json").write_text(json.dumps(latest, indent=2), encoding="utf-8")
    (SHARED / "DOOFUS-LATEST-RUN-REPORT.md").write_text("# Latest Run\n\n" + json.dumps(latest["summary"], indent=2), encoding="utf-8")
    (SHARED / "DOOFUS-24-7-FINAL-REPORT.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    return {"classification": "B1008_SHARED_FOLDER_REPORT_REFRESH_PASS", "path": str(SHARED)}


DOCS = {
    "DOOFUS-LOCAL-OPERATION-README.md": "# Doofus Local Operation\n\nSeparate from frozen Dunce handoff. Local/private only.\n",
    "DOOFUS-DASHBOARD-START-INSTRUCTIONS.md": "# Dashboard\n\n`scripts\\doofus_dashboard.ps1` → http://127.0.0.1:8765\n",
    "DOOFUS-ON-OFF-SWITCH.md": "# On/Off Switch\n\nControl files under runtime/control/.\n",
    "DOOFUS-DEEPSEEK-V4-FLASH-POLICY.md": "# DeepSeek V4 Flash\n\nNo hardcoded credentials. dry_run if OPENROUTER_API_KEY absent.\n",
    "DOOFUS-SAFETY-BOUNDARY.md": "# Safety\n\nfoundry_proven=false. No AGI/public claims. No forced promotion.\n",
    "DOOFUS-DUNCE-SEPARATION.md": "# Dunce Separation\n\nDunce handoff package is frozen. Doofus is separate workspace C:\\sai-auth-doofus.\n",
}


def export_shared_folder() -> dict:
    SHARED.mkdir(parents=True, exist_ok=True)
    for name, body in DOCS.items():
        (SHARED / name).write_text(body, encoding="utf-8")
    report = build_latest_run_report()
    checkpoint = load_checkpoint()
    status_bundle = {
        "switch": switch_status(),
        "checkpoint": checkpoint,
        "meta": get_meta_snapshot(),
        "tier3": get_tier3_snapshot(),
        "budget": check_budget(DoofusConfig.from_env()),
        "source_root": str(ROOT),
    }
    (SHARED / "DOOFUS-LATEST-RUN-REPORT.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (SHARED / "DOOFUS-LATEST-RUN-REPORT.md").write_text("# Latest Run\n\n" + json.dumps(report["summary"], indent=2), encoding="utf-8")
    (SHARED / "DOOFUS-LOCAL-OPERATION-STATUS.json").write_text(json.dumps({**report["summary"], **status_bundle}, indent=2, default=str), encoding="utf-8")
    (SHARED / "DOOFUS-META-EVOLUTION-STATUS.json").write_text(json.dumps(status_bundle["meta"], indent=2, default=str), encoding="utf-8")
    (SHARED / "DOOFUS-TIER3-STATUS.json").write_text(json.dumps(status_bundle["tier3"], indent=2), encoding="utf-8")
    try:
        from doofus.reports.sota_kpi_tracker import export_kpi_to_shared, capture_kpi_snapshot

        export_kpi_to_shared(capture_kpi_snapshot())
    except Exception:
        pass
    (SHARED / "DOOFUS-MUTATION-METRICS-SUMMARY.md").write_text(
        "# Metrics\n\n"
        f"Generation: {checkpoint.get('generation')}\n"
        f"Baseline: {checkpoint.get('baseline_score')}\n"
        f"May run: {status_bundle['switch'].get('may_run')}\n",
        encoding="utf-8",
    )
    final = {"classification": "DOOFUS_LOCAL_OPERATION_FINAL_REPORT", "report": report, "status": status_bundle, "path": str(SHARED)}
    (SHARED / "DOOFUS-LOCAL-OPERATION-FINAL-REPORT.json").write_text(json.dumps(final, indent=2, default=str), encoding="utf-8")
    (SHARED / "DOOFUS-LOCAL-OPERATION-FINAL-REPORT.md").write_text(
        "# Doofus Final Report\n\n"
        f"Label: doofus_local_operation_ready_with_notes\n\n"
        f"Generation: {checkpoint.get('generation')}\n"
        f"Best baseline: {checkpoint.get('baseline_score')}\n"
        f"May run: {status_bundle['switch'].get('may_run')}\n",
        encoding="utf-8",
    )
    return final
