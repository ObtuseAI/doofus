"""Branch retirement — retire weak lineage branches."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.core.doofus_paths import STATE
from doofus.evolution.evolution_policy import branch_retirement_after_rejections

RETIRED = STATE / "retired_branches.json"


def _load() -> dict:
    if not RETIRED.exists():
        return {"retired": [], "rejection_counts": {}}
    return json.loads(RETIRED.read_text(encoding="utf-8"))


def _save(data: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    RETIRED.write_text(json.dumps(data, indent=2), encoding="utf-8")


def record_rejection(parent_id: str | None) -> dict:
    if not parent_id:
        return {"retired_branches": len(_load().get("retired", []))}
    data = _load()
    counts = data.setdefault("rejection_counts", {})
    counts[parent_id] = int(counts.get(parent_id, 0)) + 1
    if counts[parent_id] >= branch_retirement_after_rejections():
        retired = data.setdefault("retired", [])
        if parent_id not in retired:
            retired.append(parent_id)
    _save(data)
    return {"retired_branches": len(data.get("retired", [])), "retired": data.get("retired", [])[-5:]}


def is_branch_retired(parent_id: str | None) -> bool:
    if not parent_id:
        return False
    return parent_id in _load().get("retired", [])


def get_retired_summary() -> dict:
    data = _load()
    return {"retired_branch_count": len(data.get("retired", [])), "retired": data.get("retired", [])[:10]}
