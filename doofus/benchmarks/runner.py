"""Held-out benchmark runner.

Evaluates a candidate (or the built-in baselines) against the full held-out
suite and returns a scored, timestamped, machine-readable ``SuiteReport``. No
network, no API keys, fully deterministic.

Candidate shape (all keys optional; missing keys fall back to baselines)::

    {
        "optimization": solver_callable | {task_id: solver_callable},
        "code_repair":  {task_id: repaired_source_str},
        "calibration":  {record_id: probability_float},
    }
"""
from __future__ import annotations

from typing import Any

from doofus.benchmarks import isolation
from doofus.benchmarks.families import calibration, code_repair, optimization
from doofus.benchmarks.report_schema import SUITE_VERSION, SuiteReport, TaskResult
from doofus.core.doofus_events import utc_now


def _weighted_mean(pairs: list[tuple[float, float]]) -> float:
    total_w = sum(w for _, w in pairs)
    if total_w <= 0:
        return 0.0
    return sum(s * w for s, w in pairs) / total_w


def _optimization_results(candidate: dict[str, Any]) -> list[TaskResult]:
    spec = candidate.get("optimization")
    results: list[TaskResult] = []
    for task in optimization.load_tasks():
        solver = spec.get(task["task_id"]) if isinstance(spec, dict) else spec
        score, detail = optimization.score_task(task, solver)
        results.append(TaskResult(
            task_id=task["task_id"], family="optimization",
            score=score, weight=float(task.get("weight", 1.0)), detail=detail,
        ))
    return results


def _code_repair_results(candidate: dict[str, Any]) -> list[TaskResult]:
    sources = candidate.get("code_repair") or {}
    results: list[TaskResult] = []
    for task in code_repair.load_tasks():
        source = sources.get(task["task_id"]) if isinstance(sources, dict) else None
        score, detail = code_repair.score_task(task, source)
        results.append(TaskResult(
            task_id=task["task_id"], family="code_repair",
            score=score, weight=float(task.get("weight", 1.0)), detail=detail,
        ))
    return results


def _calibration_results(candidate: dict[str, Any]) -> list[TaskResult]:
    overrides = candidate.get("calibration") or {}
    results: list[TaskResult] = []
    for task in calibration.load_tasks():
        score, detail = calibration.score_task(task, overrides if isinstance(overrides, dict) else None)
        results.append(TaskResult(
            task_id=task["task_id"], family="calibration",
            score=score, weight=float(task.get("weight", 1.0)), detail=detail,
        ))
    return results


def run_suite(candidate: dict[str, Any] | None = None, *, engine_ref: str = "baseline") -> SuiteReport:
    candidate = candidate or {}
    tasks: list[TaskResult] = []
    tasks.extend(_optimization_results(candidate))
    tasks.extend(_code_repair_results(candidate))
    tasks.extend(_calibration_results(candidate))

    families: dict[str, list[tuple[float, float]]] = {}
    for t in tasks:
        families.setdefault(t.family, []).append((t.score, t.weight))
    family_scores = {fam: round(_weighted_mean(pairs), 6) for fam, pairs in families.items()}
    overall = round(_weighted_mean([(t.score, t.weight) for t in tasks]), 6)

    return SuiteReport(
        suite_version=SUITE_VERSION,
        generated_at=utc_now(),
        engine_ref=engine_ref,
        isolation_verified=isolation.verify_sealed_isolation()["isolated"],
        task_count=len(tasks),
        overall_score=overall,
        family_scores=family_scores,
        tasks=tuple(tasks),
    )


def report_to_dict(report: SuiteReport) -> dict:
    return report.model_dump()
