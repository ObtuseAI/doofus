"""Runtime manager dashboard panel."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.core.doofus_paths import STATE
from doofus.runtime.runtime_health import runtime_manager_health, get_runtime_health


def get_runtime_manager_panel() -> dict:
    return {"manager": runtime_manager_health(), "full": get_runtime_health()}
