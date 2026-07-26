"""Supervisor health dashboard panel."""
from __future__ import annotations

from doofus.runtime.runtime_health import supervisor_health


def get_supervisor_health_panel() -> dict:
    return supervisor_health()
