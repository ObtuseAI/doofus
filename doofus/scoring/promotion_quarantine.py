"""Quarantine and proof-debt tracking for weak promotions."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.core.doofus_paths import STATE

DEBT_FILE = STATE / "promotion_debt.json"


def _load() -> dict:
    if not DEBT_FILE.exists():
        return {"proof_debt": [], "arena_debt": [], "quarantined": []}
    return json.loads(DEBT_FILE.read_text(encoding="utf-8"))


def _save(data: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    DEBT_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def record_debt(candidate_id: str, *, proof_debt: bool = False, arena_debt: bool = False) -> None:
    data = _load()
    if proof_debt and candidate_id not in data["proof_debt"]:
        data["proof_debt"].append(candidate_id)
    if arena_debt and candidate_id not in data["arena_debt"]:
        data["arena_debt"].append(candidate_id)
    _save(data)


def quarantine_candidate(candidate_id: str, reason: str) -> None:
    data = _load()
    data["quarantined"].append({"candidate_id": candidate_id, "reason": reason})
    _save(data)


def debt_summary() -> dict:
    data = _load()
    return {
        "proof_debt_count": len(data.get("proof_debt", [])),
        "arena_debt_count": len(data.get("arena_debt", [])),
        "quarantined_count": len(data.get("quarantined", [])),
        "proof_debt": data.get("proof_debt", [])[:20],
        "arena_debt": data.get("arena_debt", [])[:20],
    }
