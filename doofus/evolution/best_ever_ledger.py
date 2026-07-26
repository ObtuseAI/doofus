"""Best-ever candidate ledger."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.core.atomic_json import _assert_runtime_write_allowed
from doofus.core.doofus_paths import STATE

LEDGER = STATE / "best_ever_ledger.json"


def _load() -> dict:
    if not LEDGER.exists():
        return {"best_score": 0.0, "best_candidate_id": None, "history": []}
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def _save(data: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    _assert_runtime_write_allowed(LEDGER)
    LEDGER.write_text(json.dumps(data, indent=2), encoding="utf-8")


def update_best_ever(candidate_id: str, score: float, generation: int) -> dict:
    data = _load()
    if score > float(data.get("best_score", 0)):
        data["best_score"] = score
        data["best_candidate_id"] = candidate_id
        data["best_generation"] = generation
    data.setdefault("history", []).append({"candidate_id": candidate_id, "score": score, "generation": generation})
    data["history"] = data["history"][-100:]
    _save(data)
    return data


def get_best_ever() -> dict:
    data = _load()
    return {
        **data,
        "best_ever_score": data.get("best_score"),
        "best_ever_candidate_id": data.get("best_candidate_id"),
    }
