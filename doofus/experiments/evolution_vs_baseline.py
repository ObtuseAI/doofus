"""Evolve a registered toy optimizer, then score it exactly once held out.

The evolution loop sees only deterministic training objectives.  The sealed
benchmark is imported only after evolution is complete, preventing fitness
feedback from leaking into candidate selection.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from doofus.core.doofus_events import utc_now
from doofus.evidence_contract import MetricEvidence, ResearchEvidence

_CANDIDATE_SOURCE = '''\
"""Generic random-restart local-search candidate evolved on public training tasks."""
from __future__ import annotations

import random

GLOBAL_FRACTION = 0.6
LOCAL_SCALE = 0.25


def solve(objective, dim, bounds, budget, rng):
    lo, hi = bounds
    global_budget = max(1, min(budget, int(budget * GLOBAL_FRACTION)))
    best = [rng.uniform(lo, hi) for _ in range(dim)]
    best_value = objective(best)
    for _ in range(global_budget - 1):
        point = [rng.uniform(lo, hi) for _ in range(dim)]
        value = objective(point)
        if value < best_value:
            best, best_value = point, value

    local_budget = max(0, budget - global_budget)
    span = hi - lo
    for index in range(local_budget):
        progress = index / max(1, local_budget - 1)
        sigma = span * LOCAL_SCALE * max(0.01, 1.0 - progress)
        point = [min(hi, max(lo, rng.gauss(value, sigma))) for value in best]
        value = objective(point)
        if value < best_value:
            best, best_value = point, value
    return best
'''

_FITNESS_SOURCE = '''\
import math
import random

from candidate import solve


def sphere(center):
    return lambda point: sum((value - target) ** 2 for value, target in zip(point, center))


def rastrigin(center):
    def objective(point):
        total = 10.0 * len(center)
        for value, target in zip(point, center):
            delta = value - target
            total += delta * delta - 10.0 * math.cos(2.0 * math.pi * delta)
        return total
    return objective


TASKS = (
    (sphere([-1.75, 2.25]), 2, (-5.0, 5.0), 220, 17),
    (sphere([2.0, -0.5, 1.25, -2.5]), 4, (-5.0, 5.0), 500, 29),
    (rastrigin([-2.0, 2.0]), 2, (-5.12, 5.12), 450, 41),
)

scores = []
for objective, dim, bounds, budget, seed in TASKS:
    point = solve(objective, dim, bounds, budget, random.Random(seed))
    scores.append(math.exp(-max(0.0, objective(point))))
print(sum(scores) / len(scores))
'''


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_solver(candidate_path: Path):
    spec = importlib.util.spec_from_file_location("doofus_evolved_candidate", candidate_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("candidate module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.solve


def _training_fitness(project: dict[str, Any]) -> float:
    from doofus.meta.codeevolve.project_registry import evaluate_project_fitness

    result = evaluate_project_fitness(project)
    if result.get("classification") != "EXTERNAL_FITNESS_OK":
        raise RuntimeError(f"training fitness failed: {result.get('classification')}")
    return float(result["fitness"])


def run_experiment(*, generations: int = 24, engine_ref: str = "working-tree") -> dict[str, Any]:
    """Run the registered-target evolution and return a held-out comparison."""
    if generations < 1:
        raise ValueError("generations must be positive")

    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="doofus-evolution-experiment-") as raw:
        workspace = Path(raw)
        candidate_path = workspace / "candidate.py"
        fitness_path = workspace / "fitness.py"
        candidate_path.write_text(_CANDIDATE_SOURCE, encoding="utf-8")
        fitness_path.write_text(_FITNESS_SOURCE, encoding="utf-8")

        # Bind the registry to the disposable experiment workspace.  This is a
        # normal registered external target with snapshot/rollback protection.
        from doofus.meta.codeevolve import project_registry
        from doofus.meta.codeevolve.external_evolver import evolve_project

        previous_registry = project_registry.PROJECTS_FILE
        project_registry.PROJECTS_FILE = workspace / "state" / "projects.json"
        try:
            registration = project_registry.register_project({
                "id": "heldout-toy-optimizer",
                "root": str(workspace),
                "enabled": True,
                "auto_apply": True,
                "fitness_command": [sys.executable, str(fitness_path)],
                "fitness_timeout_seconds": 60,
                "targets": [
                    {"id": "global-fraction", "module": "candidate.py", "param_key": "GLOBAL_FRACTION"},
                    {"id": "local-scale", "module": "candidate.py", "param_key": "LOCAL_SCALE"},
                ],
            })
            if registration.get("classification") != "PROJECT_REGISTERED":
                raise RuntimeError(f"toy target registration failed: {registration}")
            project = project_registry.get_project("heldout-toy-optimizer")
            if project is None:
                raise RuntimeError("registered toy target is unavailable")
            training_before = _training_fitness(project)
            evolution = evolve_project(
                "heldout-toy-optimizer",
                generations=generations,
                apply_override=True,
            )
            training_after = _training_fitness(project)
            candidate_hash = _sha256(candidate_path)
            solver = _load_solver(candidate_path)
            candidate_source = candidate_path.read_text(encoding="utf-8")
        finally:
            project_registry.PROJECTS_FILE = previous_registry

        # Deliberately import and execute the held-out suite only after the
        # candidate is frozen and hashed.  No held-out score drives evolution.
        from doofus.benchmarks.runner import report_to_dict, run_suite

        baseline = run_suite(engine_ref="committed-baseline")
        candidate = run_suite(
            candidate={"optimization": solver},
            engine_ref=engine_ref,
        )
        delta = round(candidate.overall_score - baseline.overall_score, 6)
        generated_at = utc_now()
        evidence = ResearchEvidence(
            evidence_id=f"doofus-evolution-{candidate_hash[:16]}",
            producer="ObtuseAI/doofus",
            domain="code_parameter_evolution",
            generated_at=generated_at,
            subject_ref=candidate_hash,
            evaluation_ref=f"heldout-suite:{candidate.suite_version}",
            isolation_verified=baseline.isolation_verified and candidate.isolation_verified,
            metrics=(MetricEvidence(
                name="heldout_overall_score",
                baseline=baseline.overall_score,
                candidate=candidate.overall_score,
                delta=delta,
            ),),
            notes={"registered_target": "heldout-toy-optimizer"},
        )
        return {
            "schema_version": "1.0.0",
            "experiment": "evolution-vs-baseline",
            "generated_at": generated_at,
            "engine_ref": engine_ref,
            "generations_per_target": generations,
            "registered_target": "heldout-toy-optimizer",
            "training_fitness": {
                "before": training_before,
                "after": training_after,
                "delta": round(training_after - training_before, 6),
            },
            "candidate": {
                "sha256": candidate_hash,
                "source": candidate_source,
                "frozen_before_heldout": True,
            },
            "evolution": evolution,
            "heldout": {
                "baseline": report_to_dict(baseline),
                "candidate": report_to_dict(candidate),
                "overall_delta": delta,
                "improved": delta > 0.0,
                "isolation_verified": baseline.isolation_verified and candidate.isolation_verified,
            },
            "duration_seconds": round(time.perf_counter() - started, 3),
            "evidence_contract": evidence.model_dump(),
        }


def write_report(path: Path, *, generations: int = 24, engine_ref: str = "working-tree") -> dict[str, Any]:
    report = run_experiment(generations=generations, engine_ref=engine_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report
