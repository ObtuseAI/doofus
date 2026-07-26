"""Arena support gate for promotion."""
from __future__ import annotations

import os


def require_arena_support() -> bool:
    return os.environ.get("DOOFUS_REQUIRE_ARENA_SUPPORT_FOR_PROMOTION", "1") == "1"


def check_arena_support(arena_results: list[dict]) -> dict:
    if not arena_results:
        if require_arena_support():
            return {"arena_support_passed": False, "arena_count": 0, "arena_wins": 0, "arena_debt": True, "arena_unavailable": True}
        return {"arena_support_passed": True, "arena_count": 0, "arena_wins": 0, "arena_debt": False, "arena_unavailable": True}
    wins = sum(1 for r in arena_results if str(r.get("result", "")).lower().startswith("pass"))
    passed = wins > 0 if require_arena_support() else True
    return {
        "arena_support_passed": passed,
        "arena_count": len(arena_results),
        "arena_wins": wins,
        "arena_debt": require_arena_support() and not passed,
        "arena_unavailable": False,
    }
