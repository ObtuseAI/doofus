"""Route arena targets to live adapters or legacy stubs."""
from __future__ import annotations

import os

from doofus.config.meta_evolution_config import DEFAULTS, arena_mode
from doofus.scoring.arena_runner import run_local_arenas
from doofus.arenas.agent_arcade_adapter import run_agent_arcade
from doofus.arenas.arena_result_schema import normalize_arena_result
from doofus.safety.on_off_switch import check_may_proceed
from doofus.metacognition.runtime_control import active_arena_limit

KNOWN_ARENAS = frozenset({"agent_arcade", "dry_replay", "veloren_bridge", "minetest_stub"})
_live_calls_this_cycle = 0


def reset_cycle_budget() -> None:
    global _live_calls_this_cycle
    _live_calls_this_cycle = 0


def _max_live_per_cycle() -> int:
    configured = int(os.environ.get("DOOFUS_ARENA_LIVE_MAX_PER_CYCLE", DEFAULTS["DOOFUS_ARENA_LIVE_MAX_PER_CYCLE"]))
    return active_arena_limit(configured)


def _should_run_live(dry_run: bool) -> tuple[bool, str]:
    global _live_calls_this_cycle
    mode = arena_mode()
    if dry_run or mode == "stub":
        return False, "stub_mode"
    ok, reason = check_may_proceed()
    if not ok:
        return False, reason
    if _live_calls_this_cycle >= _max_live_per_cycle():
        return False, "live_budget_exhausted"
    if mode in ("live", "hybrid"):
        _live_calls_this_cycle += 1
        return True, "live"
    return False, "mode_off"


def run_arenas(candidate: dict, scores: dict, *, dry_run: bool = False) -> list[dict]:
    targets = candidate.get("arena_targets") or ["agent_arcade", "dry_replay"]
    results: list[dict] = []
    for arena in targets:
        if arena not in KNOWN_ARENAS:
            results.append(normalize_arena_result({
                "candidate_id": candidate["candidate_id"],
                "arena": arena,
                "score": 0.0,
                "passed": False,
                "result": "fail:0.0",
                "trace_ref": "unknown_arena",
                "mode": "rejected",
            }))
            continue
        if arena == "agent_arcade":
            live, live_reason = _should_run_live(dry_run)
            raw = run_agent_arcade(candidate, scores, live=live)
            raw["mode"] = "live" if live else f"stub:{live_reason}"
            results.append(raw)
        else:
            stub_results = run_local_arenas({**candidate, "arena_targets": [arena]}, scores)
            for r in stub_results:
                nr = normalize_arena_result(r)
                nr["mode"] = "stub"
                results.append(nr)
    return results
