"""Artifact-only next-cycle seed context plan (no runtime injection)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from doofus.self_improvement.improvement_catalog import ImprovementCatalog
from doofus.self_improvement.next_cycle_seed_builder import build_seed_recommendations


def build_next_cycle_seed_context_plan(
    *,
    certified_generation: int,
    next_generation: int,
    catalog_dir: Path | None = None,
) -> dict[str, Any]:
    workspace = Path(__file__).resolve().parents[2]
    cat_dir = catalog_dir or workspace / "artifacts" / "doofus" / "self-improvement-kernel-gen1640-readiness-v1"
    catalog_path = cat_dir / "improvement_catalog.json"
    items: list = []
    if catalog_path.exists():
        catalog = ImprovementCatalog.load(catalog_path)
        seed_payload = build_seed_recommendations(catalog, cat_dir)
        items = seed_payload.get("seeds") or []

    return {
        "classification": "DOOFUS_NEXT_CYCLE_SEED_CONTEXT_PLAN",
        "warning": f"Preparation only. Does not authorize gen{next_generation} launch.",
        "certified_generation": certified_generation,
        "next_generation": next_generation,
        "safe_injection_mechanism_exists": False,
        "seed_context_used_in_live_cycle": False,
        "decision": "staged_as_artifact_only_context",
        "refusal_reason": "no safe runtime seed injection mechanism",
        "runtime_mutation_risk": "none",
        "seed_count": len(items),
        "p0_count": sum(1 for s in items if s.get("priority") == "P0"),
        "p1_count": sum(1 for s in items if s.get("priority") == "P1"),
        "deferred_count": sum(1 for s in items if s.get("priority") == "DEFERRED"),
        "catalog_path": str(catalog_path) if catalog_path.exists() else None,
        "recommendations_preview": items[:5],
    }
