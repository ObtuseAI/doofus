"""Full autonomy dashboard panel."""
from __future__ import annotations

from doofus.config.proof_builder_runtime_config import runtime_snapshot


def get_full_autonomy_panel() -> dict:
    r = runtime_snapshot()
    return {
        "enabled": r.get("proof_builder_mode") and r.get("high_score_rescue_mode"),
        "proof_builder_mode": r.get("proof_builder_mode"),
        "shadow_elite_mode": r.get("shadow_elite_mode"),
        "high_score_rescue_mode": r.get("high_score_rescue_mode"),
        "evidence_based_proof_density": r.get("evidence_based_proof_density"),
        "batch_runner_required": False,
    }
