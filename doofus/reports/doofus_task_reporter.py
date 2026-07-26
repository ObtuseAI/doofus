"""Scheduled task status for reports."""
from __future__ import annotations
from doofus.dashboard.dashboard_task_panel import task_panel

def build_task_report() -> dict:
    return {"classification": "DOOFUS_TASK_REPORT", "tasks": task_panel()}
