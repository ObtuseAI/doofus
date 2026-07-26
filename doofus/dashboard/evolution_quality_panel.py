"""Evolution quality dashboard panel."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.core.doofus_paths import TWELVE_HOUR_RUN_DIR

QUALITY_JSON = TWELVE_HOUR_RUN_DIR / "b1093_evolution_quality_analysis.json"


def get_evolution_quality_panel() -> dict:
    if not QUALITY_JSON.exists():
        return {"verdict": "pending", "status": "pending"}
    q = json.loads(QUALITY_JSON.read_text(encoding="utf-8"))
    return {
        "verdict": q.get("verdict"),
        "avg_score": q.get("avg_score"),
        "best_score_in_window": q.get("best_score_in_window"),
        "best_ever_delta": q.get("best_ever_delta"),
        "shadow_promotions_in_window": q.get("shadow_promotions_in_window"),
        "full_promotions_in_window": q.get("full_promotions_in_window"),
        "proof_density_rejections": q.get("proof_density_rejections"),
        "arena_support_rejections": q.get("arena_support_rejections"),
    }
