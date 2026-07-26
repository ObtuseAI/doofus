"""Arena support proof builder."""
from __future__ import annotations

from doofus.scoring.arena_runner import run_local_arenas


def build_arena_support(candidate: dict, scores: dict, existing: list[dict] | None = None) -> dict:
    arena = existing or []
    if not arena or not any(str(r.get("result", "")).lower().startswith("pass") for r in arena):
        arena = run_local_arenas(candidate, scores)
    wins = sum(1 for r in arena if str(r.get("result", "")).lower().startswith("pass"))
    return {"arena_results": arena, "arena_wins": wins, "arena_support": wins > 0}
