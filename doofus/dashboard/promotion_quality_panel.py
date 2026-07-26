"""Promotion quality dashboard panel."""
from __future__ import annotations

import sqlite3

from doofus.core.doofus_paths import METRICS_DB
from doofus.core.doofus_state import init_db
from doofus.scoring.arena_support_gate import require_arena_support
from doofus.scoring.proof_density_gate import min_proof_density_score
from doofus.scoring.promotion_gate import PROMOTION_THRESHOLD
from doofus.scoring.promotion_quarantine import debt_summary


def get_promotion_quality_panel() -> dict:
    init_db()
    conn = sqlite3.connect(METRICS_DB, timeout=2.0)
    promoted = conn.execute("SELECT COUNT(*) FROM promotions").fetchone()[0]
    shadow = conn.execute("SELECT COUNT(*) FROM candidates WHERE promotion_status='shadow_promoted'").fetchone()[0]
    rejected = conn.execute("SELECT COUNT(*) FROM rejections").fetchone()[0]
    conn.close()
    debt = debt_summary()
    return {
        "promotion_threshold": PROMOTION_THRESHOLD,
        "proof_density_gate": {"min_score": min_proof_density_score(), "active": True},
        "arena_support_gate": {"required": require_arena_support(), "active": True},
        "replay_gate": {"active": True},
        "bloat_gate": {"active": True},
        "promoted_count": promoted,
        "shadow_promotions": shadow,
        "rejection_count": rejected,
        **debt,
    }
