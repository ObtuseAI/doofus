"""Build 24/7 operation report."""
from __future__ import annotations
from doofus.dashboard.dashboard_data import summary
from doofus.model_router.model_environment_probe import probe_model_environment
from doofus.supervisor.windows_task_manifest import task_manifest
from doofus.core.doofus_events import utc_now

def build_24_7_report(ctx: dict | None = None) -> dict:
    ctx = ctx or {}
    return {
        "classification": "DOOFUS_24_7_FINAL_REPORT",
        "label": ctx.get("label", "doofus_24_7_local_operation_ready_with_notes"),
        "foundry_proven": False,
        "summary": summary(),
        "environment": probe_model_environment(),
        "tasks": task_manifest(),
        "bundles": ctx.get("bundles", {}),
        "generated_at": utc_now(),
    }
