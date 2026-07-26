"""MAP-Elites quality-diversity archive."""
from __future__ import annotations

import os
import sqlite3

from doofus.config.meta_evolution_config import map_elites_enabled
from doofus.core.atomic_json import load_json, save_json
from doofus.core.doofus_events import utc_now
from doofus.core.doofus_paths import STATE
from doofus.core.metrics_db import metrics_conn
from doofus.core.pipeline_log import pipeline_warn
from doofus.model_router.model_call_ledger import log_sqlite_health

ARCHIVE_JSON = STATE / "map_elites_archive.json"

SAFETY_BINS = 5
MUTATION_TYPES = (
    "trait_mutation", "local_trait_shuffle", "model_guided_mutation", "model_guided_pending",
    "gene_crossover", "map_elites_niche", "gepa_reflective", "unknown",
)
MUTATION_ALIASES = {"capsule_injected": "gene_crossover"}
ARENA_BINS = 5


def _load_json() -> list[dict]:
    data = load_json(ARCHIVE_JSON, default=[])
    return data if isinstance(data, list) else []


def _save_json(entries: list[dict]) -> None:
    save_json(ARCHIVE_JSON, entries)


def _safety_bin(score_safety: float) -> int:
    lo, hi = 0.85, 1.0
    clamped = max(lo, min(hi, score_safety))
    span = (hi - lo) / SAFETY_BINS
    return min(SAFETY_BINS - 1, int((clamped - lo) / span))


def _mutation_category(mutation_type: str | None) -> str:
    mt = mutation_type or "unknown"
    mt = MUTATION_ALIASES.get(mt, mt)
    return mt if mt in MUTATION_TYPES else "unknown"


def _arena_bin(pass_rate: float) -> int:
    return min(ARENA_BINS - 1, int(max(0.0, min(1.0, pass_rate)) * ARENA_BINS))


def cell_key(candidate: dict, scores: dict, arena_pass_rate: float) -> str:
    sb = _safety_bin(float(scores.get("score_safety") or 0.99))
    mc = _mutation_category(candidate.get("mutation_type"))
    ab = _arena_bin(arena_pass_rate)
    return f"s{sb}:m{mc}:a{ab}"


def _upsert_sql(
    conn: sqlite3.Connection,
    *,
    key: str,
    sb: int,
    mc: str,
    ab: int,
    fitness: float,
    candidate_id: str | None,
    generation: int | None,
) -> None:
    conn.execute(
        """INSERT INTO map_elites_cells (cell_key, measure_safety, measure_mutation, measure_arena,
           fitness, candidate_id, generation, updated_at)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(cell_key) DO UPDATE SET
           fitness=excluded.fitness, candidate_id=excluded.candidate_id,
           generation=excluded.generation, updated_at=excluded.updated_at
           WHERE excluded.fitness > map_elites_cells.fitness""",
        (key, sb, mc, ab, fitness, candidate_id, generation, utc_now()),
    )


def _error_result(*, key: str, fitness: float, archive_size: int, exc: Exception) -> dict:
    return {
        "cell_key": key,
        "fitness": fitness,
        "archive_size": archive_size,
        "sql_write_ok": False,
        "error_type": type(exc).__name__,
        "error_message_sanitized": str(exc)[:500],
    }


def insert(
    candidate: dict,
    scores: dict,
    *,
    arena_pass_rate: float = 0.0,
    conn: sqlite3.Connection | None = None,
) -> dict:
    if not map_elites_enabled():
        return {"skipped": True, "reason": "map_elites_disabled"}
    fitness = float(scores.get("score_total") or 0)
    key = cell_key(candidate, scores, arena_pass_rate)
    sb = _safety_bin(float(scores.get("score_safety") or 0.99))
    mc = _mutation_category(candidate.get("mutation_type"))
    ab = _arena_bin(arena_pass_rate)
    entry = {
        "cell_key": key,
        "candidate_id": candidate.get("candidate_id"),
        "fitness": fitness,
        "generation": candidate.get("generation"),
        "measure_safety": sb,
        "measure_mutation": mc,
        "measure_arena": ab,
        "traits": candidate.get("traits"),
        "mutation_type": candidate.get("mutation_type"),
        "updated_at": utc_now(),
    }
    try:
        entries = _load_json()
        for i, e in enumerate(entries):
            if e.get("cell_key") == key:
                if float(e.get("fitness") or 0) < fitness:
                    entries[i] = entry
                _save_json(entries)
                break
        else:
            entries.append(entry)
            _save_json(entries)
        if conn is not None:
            _upsert_sql(
                conn,
                key=key,
                sb=sb,
                mc=mc,
                ab=ab,
                fitness=fitness,
                candidate_id=candidate.get("candidate_id"),
                generation=candidate.get("generation"),
            )
        else:
            with metrics_conn() as owned_conn:
                _upsert_sql(
                    owned_conn,
                    key=key,
                    sb=sb,
                    mc=mc,
                    ab=ab,
                    fitness=fitness,
                    candidate_id=candidate.get("candidate_id"),
                    generation=candidate.get("generation"),
                )
    except Exception as exc:
        pipeline_warn("map_elites_db", f"cell insert failed key={key}", exc=exc)
        if conn is None:
            log_sqlite_health(
                event_type="map_elites_sql_write_failed",
                detail=f"{key}:{type(exc).__name__}:{str(exc)[:200]}",
            )
            try:
                from doofus.reports.sota_kpi_tracker import reconcile_map_elites_archive

                reconcile_map_elites_archive(auto_backfill=True)
            except Exception:
                pass
        return _error_result(key=key, fitness=fitness, archive_size=len(entries) if "entries" in locals() else 0, exc=exc)
    return {"cell_key": key, "fitness": fitness, "archive_size": len(entries), "sql_write_ok": True}


def load_all() -> list[dict]:
    return _load_json()


def occupancy_rate() -> float:
    entries = _load_json()
    max_cells = SAFETY_BINS * len(MUTATION_TYPES) * ARENA_BINS
    return round(len(entries) / max(max_cells, 1), 4)


def maintain() -> dict:
    cap = int(os.environ.get("DOOFUS_MAP_ELITES_ARCHIVE_CAP", "200"))
    entries = _load_json()
    entries.sort(key=lambda e: float(e.get("fitness") or 0), reverse=True)
    pruned = entries[:cap]
    _save_json(pruned)
    try:
        with metrics_conn() as conn:
            conn.execute("DELETE FROM map_elites_cells")
            for e in pruned:
                conn.execute(
                    """INSERT OR REPLACE INTO map_elites_cells
                       (cell_key, measure_safety, measure_mutation, measure_arena, fitness, candidate_id, generation, updated_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        e.get("cell_key"), e.get("measure_safety"), e.get("measure_mutation"),
                        e.get("measure_arena"), e.get("fitness"), e.get("candidate_id"),
                        e.get("generation"), e.get("updated_at", utc_now()),
                    ),
                )
    except Exception as exc:
        log_sqlite_health(event_type="map_elites_maintain_failed", detail=type(exc).__name__)
        pipeline_warn("map_elites_db", "maintain sync failed", exc=exc)
    try:
        from doofus.reports.sota_kpi_tracker import reconcile_map_elites_archive

        reconcile_map_elites_archive(auto_backfill=True)
    except Exception:
        pass
    return {
        "classification": "MAP_ELITES_MAINTAIN_OK",
        "occupancy": occupancy_rate(),
        "cells": len(pruned),
        "cap": cap,
    }


def get_snapshot() -> dict:
    entries = _load_json()
    return {
        "cell_count": len(entries),
        "occupancy_rate": occupancy_rate(),
        "top_cells": sorted(entries, key=lambda e: float(e.get("fitness") or 0), reverse=True)[:10],
    }
