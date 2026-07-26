"""Elite archive — preserve top proof-backed promoted candidates."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from doofus.core.doofus_paths import STATE
from doofus.evolution.evolution_policy import elite_archive_size
from doofus.evolution.best_ever_ledger import get_best_ever

ARCHIVE = STATE / "elite_archive.json"
USAGE = STATE / "elite_archive_usage.json"


def _load() -> list:
    if not ARCHIVE.exists():
        return []
    return json.loads(ARCHIVE.read_text(encoding="utf-8"))


def _save(entries: list) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    ARCHIVE.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _lineage_key(entry: dict) -> str:
    parent = entry.get("parent_id") or "none"
    mut = entry.get("mutation_type") or "unknown"
    return f"{parent}:{mut}"


def _is_clone(existing: dict, candidate: dict) -> bool:
    if existing.get("candidate_id") == candidate.get("candidate_id"):
        return False
    if existing.get("parent_id") != candidate.get("parent_id"):
        return False
    existing_traits = set(existing.get("traits") or [])
    new_traits = set(candidate.get("traits") or [])
    if existing_traits and new_traits and existing_traits == new_traits:
        return True
    return _lineage_key(existing) == _lineage_key(candidate)


def pin_best_ever() -> None:
    best = get_best_ever()
    cid = best.get("best_candidate_id") or best.get("best_ever_candidate_id")
    score = float(best.get("best_score") or best.get("best_ever_score") or 0)
    if not cid or score <= 0:
        return
    entries = _load()
    entries = [e for e in entries if e.get("candidate_id") != cid]
    entries.append({
        "candidate_id": cid,
        "score": score,
        "generation": best.get("best_generation"),
        "parent_id": "best_ever",
        "source": "best_ever_pin",
    })
    entries.sort(key=lambda e: e.get("score", 0), reverse=True)
    _save(entries[: elite_archive_size()])


def add_elite(
    candidate: dict,
    score: float,
    *,
    skip_dedupe: bool = False,
    conn: sqlite3.Connection | None = None,
) -> dict:
    entries = _load()
    cid = candidate.get("candidate_id")
    entries = [e for e in entries if e.get("candidate_id") != cid]
    if not skip_dedupe:
        for e in entries:
            if _is_clone(e, candidate) and float(e.get("score") or 0) >= score * 0.98:
                return {"elite_archive_count": len(entries), "skipped": "clone", "entries": entries[:5]}
    entries.append({
        "candidate_id": cid,
        "score": score,
        "generation": candidate.get("generation"),
        "parent_id": candidate.get("parent_id"),
        "mutation_type": candidate.get("mutation_type"),
        "traits": candidate.get("traits"),
        "source": candidate.get("source", "full_promotion"),
    })
    entries.sort(key=lambda e: e.get("score", 0), reverse=True)
    cap = elite_archive_size()
    diverse: list[dict] = []
    seen_lineages: set[str] = set()
    for e in entries:
        lk = _lineage_key(e)
        if lk in seen_lineages and e.get("source") != "best_ever_pin":
            continue
        seen_lineages.add(lk)
        diverse.append(e)
        if len(diverse) >= cap:
            break
    if len(diverse) < cap:
        for e in entries:
            if e not in diverse:
                diverse.append(e)
            if len(diverse) >= cap:
                break
    _save(diverse[:cap])
    try:
        from doofus.evolution.map_elites_archive import insert as map_insert
        map_insert(
            candidate,
            {"score_total": score, "score_safety": float(candidate.get("score_safety") or 0.99)},
            arena_pass_rate=0.5,
            conn=conn,
        )
    except Exception:
        pass
    return {"elite_archive_count": len(_load()), "entries": _load()[:5]}


def load_elite_parents(*, limit: int = 25) -> list[dict]:
    entries = _load()
    return [
        {"candidate_id": e["candidate_id"], "score_total": e.get("score"), "parent_id": e.get("parent_id"), "source": "elite_archive"}
        for e in entries[:limit]
        if e.get("candidate_id")
    ]


def record_parent_usage(sources: list[str]) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    data = {"total_cycles": 0, "elite_hits": 0, "best_ever_hits": 0, "shadow_hits": 0, "novelty_hits": 0}
    if USAGE.exists():
        data = json.loads(USAGE.read_text(encoding="utf-8"))
    data["total_cycles"] = int(data.get("total_cycles", 0)) + 1
    for s in sources:
        key = f"{s}_hits" if s in ("elite", "best_ever", "shadow", "novelty") else None
        if key:
            data[key] = int(data.get(key, 0)) + 1
    USAGE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_elite_archive() -> dict:
    entries = _load()
    usage = json.loads(USAGE.read_text(encoding="utf-8")) if USAGE.exists() else {}
    return {
        "elite_archive_count": len(entries),
        "size_cap": elite_archive_size(),
        "entries": entries[:elite_archive_size()],
        "usage": usage,
    }
