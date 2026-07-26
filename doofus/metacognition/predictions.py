"""Prediction-before-outcome persistence and metacognitive event logging."""
from __future__ import annotations

import json
import sqlite3
import uuid

from doofus.core.doofus_events import utc_now
from doofus.core.metrics_db import metrics_conn
from doofus.metacognition.event_schema import MetacognitiveEvent
from doofus.metacognition.state import ControlAction, MetacognitiveState


def record_event(event: MetacognitiveEvent) -> None:
    with metrics_conn() as conn:
        conn.execute(
            """INSERT INTO metacognitive_events (
                   event_type, target_id, generation, policy_version, payload, created_at
               ) VALUES (?,?,?,?,?,?)""",
            (
                event.event_type.value,
                event.target_id,
                event.generation,
                event.policy_version,
                json.dumps(event.payload, sort_keys=True, default=str),
                event.created_at,
            ),
        )


def record_prediction(
    state: MetacognitiveState,
    baseline_fitness: float,
    recommended_action: ControlAction,
    recommended_candidates: int,
) -> str:
    prediction_id = f"MCP_{uuid.uuid4().hex[:16]}"
    prediction = state.fitness_prediction
    confidence = state.confidence
    with metrics_conn() as conn:
        conn.execute(
            """INSERT INTO metacognitive_predictions (
                   prediction_id, target_id, generation, strategy_id, predicted_fitness,
                   interval_low, interval_high, probability_non_regression,
                   model_confidence, behavioral_confidence, evidential_confidence,
                   control_confidence, task_difficulty, knowledge_boundary,
                   recommended_action, recommended_candidates, search_saturation,
                   fitness_noise, progress_velocity, regression_rate, baseline_fitness, created_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                prediction_id,
                state.target_id,
                state.generation,
                state.selected_strategy.strategy_id,
                prediction.mean,
                prediction.interval_low,
                prediction.interval_high,
                prediction.probability_of_non_regression,
                confidence.model,
                confidence.behavioral,
                confidence.evidential,
                confidence.final_control,
                state.task_difficulty,
                state.knowledge_boundary.value,
                recommended_action.value,
                recommended_candidates,
                state.search_saturation,
                state.uncertainty.aleatoric,
                state.progress.velocity,
                state.progress.regression_rate,
                max(0.0, min(1.0, float(baseline_fitness))),
                state.created_at,
            ),
        )
    return prediction_id


def prediction_row(prediction_id: str) -> dict[str, object]:
    with metrics_conn() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM metacognitive_predictions WHERE prediction_id = ?",
            (prediction_id,),
        ).fetchone()
    if row is None:
        raise LookupError(f"Metacognitive prediction not found: {prediction_id}")
    return dict(row)


def resolve_prediction(
    prediction_id: str,
    actual_fitness: float,
    causal_confidence: float,
    noise_adjusted_gain: float,
) -> dict[str, object]:
    row = prediction_row(prediction_id)
    baseline = float(row["baseline_fitness"])
    actual = max(0.0, min(1.0, float(actual_fitness)))
    actual_gain = actual - baseline
    resolved_at = utc_now()
    with metrics_conn() as conn:
        conn.execute(
            """UPDATE metacognitive_predictions
               SET actual_fitness = ?, actual_gain = ?, actual_non_regression = ?,
                   causal_confidence = ?, noise_adjusted_gain = ?, resolved_at = ?
               WHERE prediction_id = ? AND resolved_at IS NULL""",
            (
                actual,
                actual_gain,
                int(actual_gain >= 0.0),
                max(0.0, min(1.0, causal_confidence)),
                noise_adjusted_gain,
                resolved_at,
                prediction_id,
            ),
        )
    return {
        **row,
        "actual_fitness": actual,
        "actual_gain": actual_gain,
        "actual_non_regression": actual_gain >= 0.0,
        "causal_confidence": causal_confidence,
        "noise_adjusted_gain": noise_adjusted_gain,
        "resolved_at": resolved_at,
    }
