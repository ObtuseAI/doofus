"""Seeded black-box optimization tasks with sealed global optima.

A candidate supplies a *solver* callable; the harness hands it a black-box
objective (a closure over the sealed optimum) plus a fixed budget and a seeded
RNG, and scores the returned point by ``exp(-best_f)``. The solver never sees
the optimum, only objective values — so a better solver must genuinely search
better, not read the answer.
"""
from __future__ import annotations

import json
import math
import random
from typing import Callable

from doofus.benchmarks.isolation import TASKS_DIR, load_sealed

Point = list[float]
Objective = Callable[[Point], float]
Solver = Callable[[Objective, int, tuple[float, float], int, random.Random], Point]


def load_tasks() -> list[dict]:
    data = json.loads((TASKS_DIR / "optimization.json").read_text(encoding="utf-8"))
    return list(data["tasks"])


def _objective(kind: str, optimum: Point) -> Objective:
    if kind == "sphere":
        def f(x: Point) -> float:
            return sum((xi - ci) ** 2 for xi, ci in zip(x, optimum))
        return f
    if kind == "rastrigin":
        def f(x: Point) -> float:
            total = 10.0 * len(optimum)
            for xi, ci in zip(x, optimum):
                d = xi - ci
                total += d * d - 10.0 * math.cos(2.0 * math.pi * d)
            return total
        return f
    raise ValueError(f"unknown optimization kind: {kind}")


def default_solver(
    objective: Objective,
    dim: int,
    bounds: tuple[float, float],
    budget: int,
    rng: random.Random,
) -> Point:
    """Baseline: seeded uniform random search returning the best point seen."""
    lo, hi = bounds
    best_point = [rng.uniform(lo, hi) for _ in range(dim)]
    best_val = objective(best_point)
    for _ in range(max(0, budget - 1)):
        candidate = [rng.uniform(lo, hi) for _ in range(dim)]
        val = objective(candidate)
        if val < best_val:
            best_val, best_point = val, candidate
    return best_point


def score_task(task: dict, solver: Solver | None = None) -> tuple[float, dict]:
    solver = solver or default_solver
    optimum: Point = load_sealed("optimization")[task["task_id"]]["optimum"]
    objective = _objective(task["kind"], optimum)
    bounds = (float(task["bounds"][0]), float(task["bounds"][1]))
    rng = random.Random(int(task["seed"]))
    point = solver(objective, int(task["dim"]), bounds, int(task["budget"]), rng)
    if not isinstance(point, (list, tuple)) or len(point) != int(task["dim"]):
        return 0.0, {"error": "solver_returned_invalid_point"}
    best_f = objective([float(v) for v in point])
    score = math.exp(-max(0.0, best_f))
    return round(score, 6), {"best_f": round(best_f, 6), "kind": task["kind"], "dim": task["dim"]}
