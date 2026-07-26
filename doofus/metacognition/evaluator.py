"""Resolve predictions, score critiques, and update metacognitive memory."""
from __future__ import annotations

from doofus.config.metacognition_config import policy_version
from doofus.core.doofus_events import utc_now
from doofus.metacognition.calibration import get_calibration_summary
from doofus.metacognition.causal_monitor import assess_causal_gain
from doofus.metacognition.event_schema import MetacognitiveEvent, MetacognitiveEventType
from doofus.metacognition.memory import record_episode, record_failure, upsert_metacognitive_gene
from doofus.metacognition.predictions import prediction_row, record_event, resolve_prediction


def _failure_type(row: dict[str, object], actual_gain: float) -> str:
    confidence = float(row["control_confidence"])
    predicted_gain = float(row["predicted_fitness"]) - float(row["baseline_fitness"])
    action = str(row["recommended_action"])
    if confidence >= 0.70 and actual_gain < 0.0:
        return "false_confidence"
    if predicted_gain > 0.0 and actual_gain <= 0.0:
        return "predicted_gain_not_realized"
    if action in {"abstain", "terminate"} and actual_gain > 0.0:
        return "false_abstention"
    return ""


def evaluate_cycle_outcome(prediction_id: str, cycle_result: dict[str, object]) -> dict[str, object]:
    row = prediction_row(prediction_id)
    baseline = float(row["baseline_fitness"])
    actual_fitness = float(cycle_result.get("baseline_score") or baseline)
    observed_gain = actual_fitness - baseline
    causal = assess_causal_gain(observed_gain, [observed_gain], True, True)
    resolved = resolve_prediction(
        prediction_id,
        actual_fitness,
        causal.causal_confidence,
        causal.noise_adjusted_gain,
    )
    actual_non_regression = bool(resolved["actual_non_regression"])
    predicted_probability = float(row["probability_non_regression"])
    confidence_after = 1.0 - abs(predicted_probability - float(actual_non_regression))
    situation = (
        "saturated_search"
        if str(row["recommended_action"]) in {"diversify", "terminate"}
        else f"boundary_{row['knowledge_boundary']}"
    )
    record_episode(
        str(row["target_id"]),
        int(row["generation"]),
        situation,
        str(row["recommended_action"]),
        str(row["strategy_id"]),
        float(row["control_confidence"]),
        confidence_after,
        causal.noise_adjusted_gain,
        {
            "prediction_id": prediction_id,
            "classification": cycle_result.get("classification"),
            "causal_confidence": causal.causal_confidence,
            "replication_count": causal.replication_count,
        },
    )
    failure_type = _failure_type(row, observed_gain)
    if failure_type:
        record_failure(
            str(row["target_id"]),
            int(row["generation"]),
            failure_type,
            {
                "predicted_probability": predicted_probability,
                "observed_gain": observed_gain,
                "strategy_id": row["strategy_id"],
            },
            prediction_id,
        )
    calibration = get_calibration_summary(str(row["target_id"]))
    if causal.noise_adjusted_gain > 0.0 and confidence_after >= 0.60:
        upsert_metacognitive_gene(
            "control_episode",
            f"{row['knowledge_boundary']}:{row['recommended_action']}",
            {
                "strategy_id": row["strategy_id"],
                "recommended_candidates": row["recommended_candidates"],
            },
            causal.noise_adjusted_gain,
            1.0 - calibration.brier_score,
            0.0,
            "",
        )
    payload = {
        "prediction_id": prediction_id,
        "observed_gain": observed_gain,
        "causal": causal.model_dump(),
        "calibration": calibration.model_dump(),
        "failure_type": failure_type or None,
    }
    record_event(
        MetacognitiveEvent(
            event_type=MetacognitiveEventType.OUTCOME_EVALUATED,
            target_id=str(row["target_id"]),
            generation=int(row["generation"]),
            policy_version=policy_version(),
            payload=payload,
            created_at=utc_now(),
        )
    )
    return {
        "classification": "METACOGNITIVE_OUTCOME_EVALUATED",
        **payload,
    }
