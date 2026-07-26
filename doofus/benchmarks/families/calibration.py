"""Held-out calibration task scoring a prediction ledger against sealed outcomes.

This reuses the production ``doofus.metacognition.calibration`` machinery, so a
good score here means the actual cortex scoring code is well-calibrated on
unseen outcomes. A candidate may override the predicted probability per record
(an evolved cortex's re-calibrated output); the default uses the baseline
predictor shipped in the public task. Score = ``1 - brier_score``.
"""
from __future__ import annotations

import json

from doofus.benchmarks.isolation import TASKS_DIR, load_sealed
from doofus.metacognition.calibration import CalibrationObservation, summarize_calibration


def load_tasks() -> list[dict]:
    data = json.loads((TASKS_DIR / "calibration.json").read_text(encoding="utf-8"))
    return list(data["tasks"])


def score_task(task: dict, probability_overrides: dict[str, float] | None = None) -> tuple[float, dict]:
    overrides = probability_overrides or {}
    truth = load_sealed("calibration")
    observations: list[CalibrationObservation] = []
    for rec in task["records"]:
        rid = rec["record_id"]
        gt = truth.get(rid)
        if gt is None:
            continue
        prob = float(overrides.get(rid, rec["predicted_probability"]))
        prob = min(1.0, max(0.0, prob))
        observations.append(
            CalibrationObservation(
                predicted_probability=prob,
                actual_outcome=bool(gt["actual_outcome"]),
                predicted_fitness=float(rec["predicted_fitness"]),
                actual_fitness=float(gt["actual_fitness"]),
                interval_low=float(rec["interval_low"]),
                interval_high=float(rec["interval_high"]),
                recommended_action=str(rec["recommended_action"]),
            )
        )
    if not observations:
        return 0.0, {"error": "no_observations"}
    summary = summarize_calibration(observations)
    score = 1.0 - summary.brier_score
    return round(score, 6), {
        "brier_score": round(summary.brier_score, 6),
        "expected_calibration_error": round(summary.expected_calibration_error, 6),
        "prediction_interval_coverage": round(summary.prediction_interval_coverage, 6),
        "false_confidence_rate": round(summary.false_confidence_rate, 6),
        "sample_count": summary.sample_count,
    }
