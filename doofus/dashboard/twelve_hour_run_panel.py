"""12-hour run dashboard panel."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.core.doofus_paths import TWELVE_HOUR_RUN_DIR

RUN_JSON = TWELVE_HOUR_RUN_DIR / "b1091_12_hour_unattended_run.json"
DELTA_JSON = TWELVE_HOUR_RUN_DIR / "b1092_post_run_metrics_delta.json"
QUALITY_JSON = TWELVE_HOUR_RUN_DIR / "b1093_evolution_quality_analysis.json"


def get_twelve_hour_run_panel() -> dict:
    run = delta = quality = {}
    if RUN_JSON.exists():
        run = json.loads(RUN_JSON.read_text(encoding="utf-8"))
    if DELTA_JSON.exists():
        delta = json.loads(DELTA_JSON.read_text(encoding="utf-8"))
    if QUALITY_JSON.exists():
        quality = json.loads(QUALITY_JSON.read_text(encoding="utf-8"))
    return {
        "status": run.get("status", "not_started"),
        "classification": run.get("classification"),
        "run_start": run.get("run_start"),
        "run_end": run.get("run_end"),
        "duration_seconds": run.get("duration_seconds", 43200),
        "checkpoint_count": len(run.get("checkpoints", [])),
        "deltas": delta.get("deltas", {}),
        "evolution_quality_verdict": quality.get("verdict"),
        "report_path": str(RUN_JSON) if RUN_JSON.exists() else None,
    }
