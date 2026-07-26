"""Tests for the held-out benchmark harness.

Deterministic, no network, no credentials, CI-safe on windows-latest.
"""
from __future__ import annotations

import json
from pathlib import Path

from doofus.benchmarks import runner
from doofus.benchmarks.isolation import (
    SEALED_DIR,
    TASKS_DIR,
    load_sealed,
    verify_sealed_isolation,
)
from doofus.meta.codeevolve import project_registry

BASELINE = Path(runner.__file__).resolve().parent / "baseline" / "baseline_report.json"

# Correct repairs for each buggy fixture (used to prove the harness reaches 1.0).
CORRECT_SOURCES = {
    "repair_median": (
        "def median(xs):\n"
        "    ys = sorted(xs)\n"
        "    n = len(ys)\n"
        "    mid = n // 2\n"
        "    if n % 2:\n"
        "        return ys[mid]\n"
        "    return (ys[mid - 1] + ys[mid]) / 2\n"
    ),
    "repair_word_count": "def word_count(s):\n    return len(s.split())\n",
    "repair_clamp": "def clamp(x, lo, hi):\n    return max(lo, min(x, hi))\n",
}


def test_suite_runs_and_scores_bounded():
    report = runner.run_suite(engine_ref="test")
    assert report.task_count == 7
    assert set(report.family_scores) == {"optimization", "code_repair", "calibration"}
    assert 0.0 <= report.overall_score <= 1.0
    for t in report.tasks:
        assert 0.0 <= t.score <= 1.0
    assert report.isolation_verified is True


def test_deterministic_across_runs():
    a = runner.run_suite(engine_ref="a")
    b = runner.run_suite(engine_ref="b")
    assert a.overall_score == b.overall_score
    assert {t.task_id: t.score for t in a.tasks} == {t.task_id: t.score for t in b.tasks}


def test_baseline_report_is_reproducible():
    """The committed baseline scores must be reproducible from a fresh run."""
    committed = json.loads(BASELINE.read_text(encoding="utf-8"))
    report = runner.run_suite(engine_ref=committed["engine_ref"])
    fresh = {t.task_id: t.score for t in report.tasks}
    for task in committed["tasks"]:
        assert fresh[task["task_id"]] == task["score"], task["task_id"]
    assert report.overall_score == committed["overall_score"]


def test_sealed_answers_are_isolated_from_engine():
    """The engine's own protected-root containment excludes the sealed dir."""
    assert project_registry.is_protected_path(SEALED_DIR) is True
    assert SEALED_DIR in project_registry._STATIC_PROTECTED_ROOTS
    # A project rooted at the sealed dir is rejected as a protected root.
    ok, reason = project_registry.validate_project(
        {"id": "benchtarget", "root": str(SEALED_DIR), "fitness_command": ["python", "-c", "print(1)"]}
    )
    assert ok is False
    assert reason == "protected_root"
    ev = verify_sealed_isolation()
    assert ev["isolated"] is True


def test_hidden_answers_are_hashed_not_plaintext():
    raw = (SEALED_DIR / "code_repair.json").read_text(encoding="utf-8")
    sealed = json.loads(raw)
    for cases in sealed.values():
        for case in cases:
            assert "expected_hash" in case
            assert "expected" not in case
            assert len(case["expected_hash"]) == 64  # sha256 hex


def test_code_repair_reaches_perfect_with_correct_source():
    report = runner.run_suite(candidate={"code_repair": CORRECT_SOURCES})
    repair = {t.task_id: t.score for t in report.tasks if t.family == "code_repair"}
    assert repair == {tid: 1.0 for tid in CORRECT_SOURCES}


def test_optimization_reaches_perfect_with_oracle_solver():
    sealed = load_sealed("optimization")

    def make_oracle(task_id):
        optimum = list(sealed[task_id]["optimum"])
        return lambda objective, dim, bounds, budget, rng: optimum

    solvers = {tid: make_oracle(tid) for tid in sealed}
    report = runner.run_suite(candidate={"optimization": solvers})
    for t in report.tasks:
        if t.family == "optimization":
            assert t.score == 1.0
            assert t.detail["best_f"] == 0.0


def test_calibration_reaches_perfect_with_true_predictor():
    truth = load_sealed("calibration")
    overrides = {rid: (1.0 if truth[rid]["actual_outcome"] else 0.0) for rid in truth}
    report = runner.run_suite(candidate={"calibration": overrides})
    calib = [t for t in report.tasks if t.family == "calibration"]
    assert calib and all(t.score == 1.0 for t in calib)
    assert all(t.detail["brier_score"] == 0.0 for t in calib)


def test_baseline_underperforms_a_perfect_candidate():
    """Held-out honesty: the shipped baseline must not already be maxed out."""
    baseline = runner.run_suite()
    assert baseline.overall_score < 1.0
    assert baseline.family_scores["code_repair"] < 1.0


def test_public_tasks_do_not_leak_answers():
    """Public task inputs must not contain sealed answer material."""
    # The sealed answer keys/values must not appear in the public task inputs.
    opt_text = (TASKS_DIR / "optimization.json").read_text(encoding="utf-8")
    for task_id, ans in load_sealed("optimization").items():
        assert json.dumps(ans["optimum"]) not in opt_text, task_id
    calib_text = (TASKS_DIR / "calibration.json").read_text(encoding="utf-8")
    assert "actual_outcome" not in calib_text
