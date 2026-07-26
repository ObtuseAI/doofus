"""Threshold tuning dashboard panel."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.core.doofus_paths import PROOF_BUILDER_TUNING_DIR
from doofus.scoring.proof_density_gate import min_proof_density_score


def get_threshold_tuning_panel() -> dict:
    sweep = {}
    p = PROOF_BUILDER_TUNING_DIR / "b1104_threshold_sweep_tuning.json"
    if p.exists():
        sweep = json.loads(p.read_text(encoding="utf-8"))
    return {
        "active_proof_density_threshold": min_proof_density_score(),
        "sweep_recommendation": sweep.get("recommendation"),
        "recommended_threshold": sweep.get("recommended_threshold"),
        "current_threshold": sweep.get("current_threshold", 0.55),
    }
