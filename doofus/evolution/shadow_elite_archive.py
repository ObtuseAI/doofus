"""Shadow elite archive — high-scoring under-proven candidates preserved safely."""
from __future__ import annotations

import json
import os
from pathlib import Path

from doofus.core.doofus_paths import STATE

ARCHIVE = STATE / "shadow_elite_archive.json"


def shadow_elite_enabled() -> bool:
    return os.environ.get("DOOFUS_SHADOW_ELITE_MODE", "1") == "1"


def archive_size() -> int:
    return int(os.environ.get("DOOFUS_SHADOW_ELITE_ARCHIVE_SIZE", "50"))


def _load() -> list:
    if not ARCHIVE.exists():
        return []
    return json.loads(ARCHIVE.read_text(encoding="utf-8"))


def _save(entries: list) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    ARCHIVE.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def add_shadow_elite(candidate: dict, *, proof_density: float, reason: str = "under_proven") -> dict:
    entries = _load()
    cid = candidate.get("candidate_id")
    entries = [e for e in entries if e.get("candidate_id") != cid]
    entries.append({
        "candidate_id": cid,
        "score": float(candidate.get("score_total") or 0),
        "generation": candidate.get("generation"),
        "parent_id": candidate.get("parent_id"),
        "proof_density_score": proof_density,
        "reason": reason,
        "status": "shadow_elite",
        "upgraded": False,
    })
    entries.sort(key=lambda e: e.get("score", 0), reverse=True)
    entries = entries[: archive_size()]
    _save(entries)
    return {"shadow_elite_count": len(entries)}


def retire_shadow_elite(candidate_id: str, reason: str = "proof_failed") -> None:
    entries = _load()
    entries = [e for e in entries if e.get("candidate_id") != candidate_id]
    _save(entries)


def mark_upgraded(candidate_id: str) -> None:
    entries = _load()
    for e in entries:
        if e.get("candidate_id") == candidate_id:
            e["upgraded"] = True
            e["status"] = "upgraded_to_full"
    _save(entries)


def increment_failed_attempts(candidate_id: str) -> int:
    entries = _load()
    count = 0
    for e in entries:
        if e.get("candidate_id") == candidate_id:
            count = int(e.get("failed_attempts") or 0) + 1
            e["failed_attempts"] = count
    _save(entries)
    return count


def get_shadow_elite_archive() -> dict:
    entries = _load()
    return {
        "enabled": shadow_elite_enabled(),
        "shadow_elite_count": len(entries),
        "upgraded_count": sum(1 for e in entries if e.get("upgraded")),
        "entries": entries[:20],
    }
