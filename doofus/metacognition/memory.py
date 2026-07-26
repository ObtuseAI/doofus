"""Episodic, strategic, failure, and gene memory for metacognitive control."""
from __future__ import annotations

import hashlib
import json

from doofus.core.doofus_events import utc_now
from doofus.core.metrics_db import metrics_conn


def record_episode(
    target_id: str,
    generation: int,
    situation: str,
    control_action: str,
    strategy_id: str,
    confidence_before: float,
    confidence_after: float,
    actual_gain: float,
    context: dict[str, object],
) -> None:
    success = actual_gain > 0.0
    with metrics_conn() as conn:
        conn.execute(
            """INSERT INTO metacognitive_episodes (
                   target_id, generation, situation, control_action, strategy_id,
                   confidence_before, confidence_after, actual_gain, success, context, created_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                target_id,
                generation,
                situation,
                control_action,
                strategy_id,
                confidence_before,
                confidence_after,
                actual_gain,
                int(success),
                json.dumps(context, sort_keys=True, default=str),
                utc_now(),
            ),
        )


def record_failure(
    target_id: str,
    generation: int,
    failure_type: str,
    detail: dict[str, object],
    prediction_id: str,
) -> None:
    with metrics_conn() as conn:
        conn.execute(
            """INSERT INTO metacognitive_failures (
                   target_id, generation, failure_type, detail, prediction_id, created_at
               ) VALUES (?,?,?,?,?,?)""",
            (
                target_id,
                generation,
                failure_type,
                json.dumps(detail, sort_keys=True, default=str),
                prediction_id,
                utc_now(),
            ),
        )


def upsert_metacognitive_gene(
    gene_type: str,
    context_signature: str,
    policy_payload: dict[str, object],
    fitness: float,
    calibration_score: float,
    holdout_score: float,
    parent_gene_id: str,
) -> str:
    digest = hashlib.sha256(
        f"{gene_type}:{context_signature}:{json.dumps(policy_payload, sort_keys=True)}".encode("utf-8")
    ).hexdigest()[:16]
    gene_id = f"MCG_{digest}"
    now = utc_now()
    with metrics_conn() as conn:
        conn.execute(
            """INSERT INTO metacognitive_genes (
                   gene_id, gene_type, context_signature, policy_payload, fitness,
                   calibration_score, holdout_score, active, parent_gene_id, created_at, updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(gene_id) DO UPDATE SET
                   fitness=excluded.fitness,
                   calibration_score=excluded.calibration_score,
                   holdout_score=excluded.holdout_score,
                   updated_at=excluded.updated_at""",
            (
                gene_id,
                gene_type,
                context_signature,
                json.dumps(policy_payload, sort_keys=True, default=str),
                fitness,
                calibration_score,
                holdout_score,
                0,
                parent_gene_id or None,
                now,
                now,
            ),
        )
    return gene_id


def get_memory_snapshot(target_id: str) -> dict[str, object]:
    with metrics_conn() as conn:
        episode_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM metacognitive_episodes WHERE target_id = ?",
                (target_id,),
            ).fetchone()[0]
        )
        failure_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM metacognitive_failures WHERE target_id = ?",
                (target_id,),
            ).fetchone()[0]
        )
        strategy_rows = conn.execute(
            """SELECT strategy_id, COUNT(*) AS trials, SUM(success) AS successes,
                      AVG(actual_gain) AS avg_gain
               FROM metacognitive_episodes WHERE target_id = ?
               GROUP BY strategy_id ORDER BY avg_gain DESC""",
            (target_id,),
        ).fetchall()
        gene_rows = conn.execute(
            """SELECT gene_id, gene_type, context_signature, fitness, calibration_score,
                      holdout_score, active, parent_gene_id
               FROM metacognitive_genes ORDER BY fitness DESC LIMIT 20"""
        ).fetchall()
    return {
        "episodic_count": episode_count,
        "failure_count": failure_count,
        "strategic_memory": [
            {
                "strategy_id": str(row[0]),
                "trials": int(row[1]),
                "successes": int(row[2] or 0),
                "average_gain": float(row[3] or 0.0),
            }
            for row in strategy_rows
        ],
        "metacognitive_genes": [
            {
                "gene_id": str(row[0]),
                "gene_type": str(row[1]),
                "context_signature": str(row[2]),
                "fitness": float(row[3]),
                "calibration_score": float(row[4]),
                "holdout_score": float(row[5]),
                "active": bool(row[6]),
                "parent_gene_id": row[7],
            }
            for row in gene_rows
        ],
    }
