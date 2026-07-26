"""Deterministic next-cycle seed context from Doofus artifacts (no live calls)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from doofus.evaluation.candidate_quality import analyze_generations
from doofus.evolution.next_cycle_seed_context import build_next_cycle_seed_context_plan
from doofus.reports.proof_builder_handoff_report import handoff_report


def build_seed_context(
    *,
    certified_generation: int,
    next_generation: int,
    artifact_root: Path | None = None,
    max_items: int = 25,
) -> dict[str, Any]:
    workspace = Path(__file__).resolve().parents[2]
    root = artifact_root or workspace / "artifacts" / "doofus" / "full-completion-master-v1"

    quality = analyze_generations(start_generation=max(1637, certified_generation - 6), end_generation=certified_generation)
    handoff = handoff_report(generation=certified_generation)
    seed_plan = build_next_cycle_seed_context_plan(
        certified_generation=certified_generation,
        next_generation=next_generation,
    )

    best_near_miss = None
    try:
        import sqlite3
        from doofus.core.doofus_paths import METRICS_DB
        from doofus.scoring.promotion_gate import PROMOTION_THRESHOLD

        conn = sqlite3.connect(METRICS_DB, timeout=15)
        row = conn.execute(
            """
            SELECT candidate_id, score_total FROM candidates
            WHERE generation=? AND status='rejected' AND score_total >= ?
            ORDER BY score_total DESC LIMIT 1
            """,
            (certified_generation, float(PROMOTION_THRESHOLD)),
        ).fetchone()
        conn.close()
        best_near_miss = row[0] if row else None
    except Exception:
        best_near_miss = None

    dominant = quality.get("aggregate_dominant_rejection_reason")
    provenance = []
    for name in ("ZERO_PROMOTION_DIAGNOSIS.json", "candidate_quality_report.json", "promotion_near_miss_report.json"):
        p = root / name
        if p.exists():
            provenance.append(str(p.relative_to(workspace)))

    context_items = [
        {"type": "dominant_rejection", "value": dominant},
        {"type": "best_near_miss", "value": best_near_miss},
        {"type": "proof_backlog_pending", "value": handoff.get("queue_summary", {}).get("pending")},
        {"type": "seed_plan_decision", "value": seed_plan.get("decision")},
    ][:max_items]

    return {
        "classification": "DOOFUS_NEXT_CYCLE_SEED_CONTEXT",
        "certified_generation": certified_generation,
        "next_generation": next_generation,
        "dominant_rejection_reason": dominant,
        "best_near_miss_candidate": best_near_miss,
        "proof_builder_pending": handoff.get("queue_summary", {}).get("pending"),
        "seed_plan": seed_plan,
        "quality_summary": {
            "zero_promotion_pattern": quality.get("zero_promotion_pattern"),
            "aggregate_histogram": quality.get("aggregate_rejection_histogram"),
        },
        "context_items": context_items,
        "provenance_artifacts": provenance,
        "safe_injection_mechanism_exists": False,
        "runtime_injection": False,
        "capped_size": max_items,
    }
