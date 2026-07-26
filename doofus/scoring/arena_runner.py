"""Local arena dry-run scoring — persists to metrics DB."""
from __future__ import annotations
import hashlib
from doofus.core.doofus_events import utc_now

def run_local_arenas(candidate: dict, scores: dict) -> list[dict]:
    """Score candidate against local arena stubs. Not live game mutation."""
    targets = candidate.get("arena_targets") or ["agent_arcade", "dry_replay"]
    results = []
    base = scores.get("score_total", 0.5)
    for arena in targets:
        seed = int(hashlib.sha256(f"{candidate['candidate_id']}:{arena}".encode()).hexdigest()[:8], 16)
        jitter = (seed % 100) / 1000.0 - 0.05
        arena_score = round(max(0.0, min(1.0, base + jitter)), 4)
        outcome = "pass" if arena_score >= 0.55 else "fail"
        results.append({
            "candidate_id": candidate["candidate_id"],
            "arena": arena,
            "result": f"{outcome}:{arena_score}",
            "score": arena_score,
            "created_at": utc_now(),
        })
    return results
