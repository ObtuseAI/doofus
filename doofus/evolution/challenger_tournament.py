"""Challenger tournament — compare top candidates."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.core.doofus_paths import STATE
from doofus.evolution.evolution_policy import challenger_tournament_size

TOURNAMENT = STATE / "challenger_tournaments.json"


def _load() -> dict:
    if not TOURNAMENT.exists():
        return {"tournament_count": 0, "last_winner": None, "history": []}
    return json.loads(TOURNAMENT.read_text(encoding="utf-8"))


def _save(data: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    TOURNAMENT.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_tournament(candidates: list[dict]) -> dict:
    if not candidates:
        return {"tournament_count": _load().get("tournament_count", 0), "winner": None}
    ranked = sorted(candidates, key=lambda c: float(c.get("score_total") or 0), reverse=True)
    pool = ranked[: challenger_tournament_size()]
    winner = pool[0] if pool else None
    data = _load()
    data["tournament_count"] = int(data.get("tournament_count", 0)) + 1
    data["last_winner"] = winner.get("candidate_id") if winner else None
    data.setdefault("history", []).append({
        "winner": winner.get("candidate_id") if winner else None,
        "score": winner.get("score_total") if winner else 0,
        "pool_size": len(pool),
    })
    data["history"] = data["history"][-50:]
    _save(data)
    return {"tournament_count": data["tournament_count"], "winner": data["last_winner"]}


def get_tournament_summary() -> dict:
    data = _load()
    return {
        "challenger_tournament_count": data.get("tournament_count", 0),
        "last_winner": data.get("last_winner"),
    }
