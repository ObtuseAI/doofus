"""Calibration and control charts for the experimental metacognitive cortex."""
from __future__ import annotations

from doofus.dashboard import live_metric_queries as mq
from doofus.dashboard.live_chart_helpers import assert_plot_chart, plot_from_rows, plot_multi_from_rows


def _reliability_rows(rows: list[dict]) -> list[dict]:
    buckets: list[dict] = []
    resolved = [row for row in rows if row.get("actual_non_regression") is not None]
    for index in range(10):
        low = index / 10.0
        high = (index + 1) / 10.0
        bucket = [
            row for row in resolved
            if low <= float(row.get("probability_non_regression") or 0.0) < high
            or (index == 9 and float(row.get("probability_non_regression") or 0.0) == 1.0)
        ]
        if not bucket:
            continue
        buckets.append(
            {
                "predicted_probability": sum(float(row["probability_non_regression"]) for row in bucket) / len(bucket),
                "actual_frequency": sum(float(bool(row["actual_non_regression"])) for row in bucket) / len(bucket),
                "count": len(bucket),
            }
        )
    return buckets


def build_metacognition_charts() -> dict[str, object]:
    rows = mq.metacognitive_predictions()
    resolved = [row for row in rows if row.get("actual_fitness") is not None]
    reliability = _reliability_rows(rows)
    error_rows = [
        {
            "generation": int(row.get("generation") or 0),
            "calibration_error": abs(
                float(row.get("probability_non_regression") or 0.0)
                - float(bool(row.get("actual_non_regression")))
            ),
        }
        for row in resolved
    ]
    charts = {
        "reliability": plot_multi_from_rows(
            "Predicted improvement probability vs actual frequency",
            reliability,
            "predicted_probability",
            (("actual frequency", "actual_frequency"), ("perfect calibration", "predicted_probability")),
        ),
        "predicted_actual_fitness": plot_multi_from_rows(
            "Predicted vs actual fitness",
            resolved,
            "generation",
            (("predicted", "predicted_fitness"), ("actual", "actual_fitness")),
        ),
        "calibration_error": plot_from_rows(
            "Per-generation calibration error",
            error_rows,
            "generation",
            "calibration_error",
        ),
        "difficulty": plot_from_rows(
            "Estimated task difficulty",
            rows,
            "generation",
            "task_difficulty",
        ),
        "resource_allocation": plot_from_rows(
            "Metacognitive candidate allocation",
            rows,
            "generation",
            "recommended_candidates",
        ),
        "search_saturation": plot_from_rows(
            "Search saturation",
            rows,
            "generation",
            "search_saturation",
        ),
    }
    for name, figure in charts.items():
        assert_plot_chart(figure, name)
    return charts
