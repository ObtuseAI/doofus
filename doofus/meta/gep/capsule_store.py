"""GEP capsule persistence."""
from __future__ import annotations

import json
import random
import sqlite3
import uuid

from doofus.core.atomic_json import load_json, save_json
from doofus.core.doofus_events import utc_now
from doofus.core.doofus_paths import STATE
from doofus.core.metrics_db import connect_metrics_db
from doofus.core.pipeline_log import pipeline_warn
from doofus.meta.gep.gep_schema import Capsule
from doofus.meta.gep.gene_library import genes_to_traits, trait_to_gene

CAPSULES_FILE = STATE / "gep" / "capsules.json"


def _load() -> list[dict]:
    data = load_json(CAPSULES_FILE, default=[])
    return data if isinstance(data, list) else []


def _save(entries: list[dict]) -> None:
    save_json(CAPSULES_FILE, entries)


def create_capsule_from_candidate(
    candidate: dict,
    score: float,
    *,
    strategy_name: str = "",
    conn: sqlite3.Connection | None = None,
) -> Capsule:
    traits = candidate.get("traits") or []
    genes = [trait_to_gene(t) for t in traits[:4]]
    cap = Capsule(
        capsule_id=f"CAP_{uuid.uuid4().hex[:10]}",
        genes=genes,
        fitness=float(score),
        strategy_name=strategy_name or candidate.get("mutation_type", ""),
        created_at=utc_now(),
    )
    entries = _load()
    entries.append(cap.model_dump())
    entries.sort(key=lambda e: float(e.get("fitness") or 0), reverse=True)
    _save(entries[:100])
    try:
        payload = (
            cap.capsule_id,
            json.dumps([g.model_dump() for g in genes]),
            cap.fitness,
            0,
            cap.created_at,
            cap.created_at,
        )
        if conn is not None:
            conn.execute(
                """INSERT OR REPLACE INTO gep_capsules (capsule_id, genes, fitness, reuse_count, created_at, updated_at)
                   VALUES (?,?,?,?,?,?)""",
                payload,
            )
        else:
            owned_conn = connect_metrics_db()
            owned_conn.execute(
                """INSERT OR REPLACE INTO gep_capsules (capsule_id, genes, fitness, reuse_count, created_at, updated_at)
                   VALUES (?,?,?,?,?,?)""",
                payload,
            )
            owned_conn.commit()
            owned_conn.close()
    except Exception as exc:
        pipeline_warn("gep_capsule_db", f"insert failed {cap.capsule_id}", exc=exc)
    return cap


def sample_capsule() -> Capsule | None:
    entries = _load()
    if not entries:
        return None
    entries.sort(key=lambda e: float(e.get("fitness") or 0), reverse=True)
    top = entries[:5]
    try:
        return Capsule.model_validate(random.choice(top))
    except Exception as exc:
        pipeline_warn("gep_capsule", "sample validation failed", exc=exc)
        return None


def inject_capsule_traits(candidate: dict, capsule: Capsule) -> dict:
    traits = list(candidate.get("traits") or [])
    for t in genes_to_traits(capsule.genes):
        if t not in traits:
            traits.append(t)
    child = dict(candidate)
    child["traits"] = sorted(set(traits))[:6]
    child["capsule_id"] = capsule.capsule_id
    return child


def record_reuse(capsule_id: str) -> None:
    entries = _load()
    reuse = 0
    for e in entries:
        if e.get("capsule_id") == capsule_id:
            reuse = int(e.get("reuse_count") or 0) + 1
            e["reuse_count"] = reuse
            break
    _save(entries)
    try:
        conn = connect_metrics_db()
        conn.execute(
            "UPDATE gep_capsules SET reuse_count = ?, updated_at = ? WHERE capsule_id = ?",
            (reuse, utc_now(), capsule_id),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        pipeline_warn("gep_capsule_db", f"reuse update failed {capsule_id}", exc=exc)


def get_snapshot() -> dict:
    entries = _load()
    return {
        "capsule_count": len(entries),
        "top_capsules": entries[:5],
        "total_reuses": sum(int(e.get("reuse_count") or 0) for e in entries),
    }
