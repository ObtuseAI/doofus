"""Select shadow elite candidates as cautious mutation parents."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.core.doofus_paths import STATE
from doofus.config.proof_builder_runtime_config import shadow_elite_mode

ARCHIVE = STATE / "shadow_elite_archive.json"


def load_shadow_elite_parents(limit: int = 10) -> list[dict]:
    if not shadow_elite_mode() or not ARCHIVE.exists():
        return []
    entries = json.loads(ARCHIVE.read_text(encoding="utf-8"))
    out = []
    for e in entries:
        if e.get("upgraded") or e.get("status") == "retired":
            continue
        out.append({
            "candidate_id": e.get("candidate_id"),
            "score_total": e.get("score"),
            "generation": e.get("generation"),
            "parent_id": e.get("parent_id"),
            "traits": [],
            "source": "shadow_elite",
        })
    return out[:limit]
