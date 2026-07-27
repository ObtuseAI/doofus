"""Build gen1640 seed recommendations from self-improvement catalog."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from doofus.self_improvement.improvement_catalog import ImprovementCatalog, write_pair
from doofus.self_improvement.improvement_item import ImprovementItem


def _seed_from_item(item: ImprovementItem, priority: str) -> dict[str, Any]:
    return {
        "seed_id": f"seed-{item.dedupe_key}",
        "source_improvement_id": item.id,
        "priority": priority,
        "title": item.title,
        "why_it_matters": item.problem or item.summary,
        "how_to_implement": item.implementation_hint or item.recommendation,
        "risk": item.risk_level,
        "required_validation": item.validation_method,
        "affected_subsystems": item.affected_subsystems,
        "rollback_strategy": "Revert config/code change; checkpoint unchanged; no DB scrub without backup.",
        "non_live_first": item.type not in ("operator_packet_improvement",),
        "operator_review_required": priority in ("P0", "DEFERRED"),
    }


def build_seed_recommendations(catalog: ImprovementCatalog, output_dir: Path) -> dict[str, Any]:
    p0 = [i for i in catalog.items if i.score >= 85][:5]
    p1 = [i for i in catalog.items if 70 <= i.score < 85][:10]
    selected = {item.dedupe_key for item in (*p0, *p1)}
    deferred = [
        i
        for i in catalog.items
        if (
            i.dedupe_key not in selected
            and (i.status == "deferred" or i.score < 55)
        )
    ][:5]
    selected.update(item.dedupe_key for item in deferred)
    p2 = [
        i
        for i in catalog.items
        if i.dedupe_key not in selected
    ][: max(0, 20 - len(selected))]

    seeds = [_seed_from_item(i, "P0") for i in p0]
    seeds += [_seed_from_item(i, "P1") for i in p1]
    seeds += [_seed_from_item(i, "P2") for i in p2]
    seeds += [_seed_from_item(i, "DEFERRED") for i in deferred]

    excluded = [
        {"reason": "gen1640 live launch not authorized in this bundle", "item": "live_provider_cycle"},
        {"reason": "requires operator packet approval", "item": "unclear baseline launch"},
        {"reason": "DB mutation without backup-first evidence", "item": "live_db_scrub"},
    ]

    payload = {
        "classification": "DOOFUS_GEN1640_SEED_RECOMMENDATIONS",
        "warning": "Preparation only. Does not authorize gen1640 launch.",
        "seed_count": len(seeds),
        "p0_count": len(p0),
        "p1_count": len(p1),
        "p2_count": len(p2),
        "deferred_count": len([s for s in seeds if s["priority"] == "DEFERRED"]),
        "seeds": seeds,
        "excluded_from_gen1640": excluded,
        "operator_review_required": [s["seed_id"] for s in seeds if s["operator_review_required"]],
    }
    write_pair(output_dir, "next_cycle_seed_recommendations", payload)
    write_pair(output_dir, "GEN1640_SEED_RECOMMENDATIONS", payload)
    return payload
