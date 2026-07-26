"""OpenEvolve-style island GA adapter for policy modules."""
from __future__ import annotations

import json
import os

from doofus.config.meta_evolution_config import codeevolve_enabled, codeevolve_auto_apply
from doofus.core.doofus_events import utc_now
from doofus.core.metrics_db import metrics_conn
from doofus.meta.codeevolve.param_overrides import (
    DEFAULT_SCORE_WEIGHTS,
    load_promotion_threshold,
    load_score_weights,
    save_promotion_threshold,
    save_score_weights,
)
from doofus.meta.codeevolve.rollback_manager import (
    get_snapshot,
    record_baseline_promotion_rate,
    save_pending_diff,
    should_rollback,
    snapshot_module,
)
from doofus.meta.codeevolve.sandbox_runner import evaluate_dry_run_cycles
from doofus.meta.codeevolve.target_registry import get_target
from doofus.meta.gep.event_emitter import emit


def _perturb_weights(current: dict, fitness: float, baseline_fitness: float) -> dict:
    """Small safe weight shift toward compounding/replay when fitness improves."""
    out = dict(current)
    delta = 0.01 if fitness > baseline_fitness else -0.005
    out["compounding"] = max(0.05, min(0.35, out.get("compounding", 0.15) + delta))
    out["replay"] = max(0.05, min(0.35, out.get("replay", 0.20) + delta * 0.5))
    total = sum(out.values())
    return {k: round(v / total, 4) for k, v in out.items()}


def _perturb_threshold(current: float, fitness: float, baseline_fitness: float) -> float:
    delta = 0.01 if fitness > baseline_fitness else -0.005
    return max(0.65, min(0.88, current + delta))


def _record_generation(target_id: str, generation_index: int, fitness: float, accepted: bool, summary: str) -> None:
    try:
        with metrics_conn() as conn:
            conn.execute(
                """INSERT INTO codeevolve_generations (target_module, generation, fitness, accepted, diff_summary, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (target_id, generation_index, fitness, 1 if accepted else 0, summary[:500], utc_now()),
            )
    except Exception as exc:
        from doofus.core.pipeline_log import pipeline_warn
        pipeline_warn("codeevolve_db", f"generation insert failed target={target_id}", exc=exc)


def run_generation(generation_index: int = 0) -> dict:
    if not codeevolve_enabled():
        return {"classification": "CODEEVOLVE_SKIPPED", "reason": "disabled"}
    target = get_target(generation_index)
    if target.get("source") == "external":
        from doofus.meta.codeevolve.external_evolver import run_external_generation

        result = run_external_generation(target, generation_index)
        _record_generation(
            target["id"],
            generation_index,
            float(result.get("fitness") or 0.0),
            bool(result.get("accepted")),
            str(result.get("summary") or result.get("classification") or "")[:500],
        )
        return result
    module_path = target["module_path"]
    label = f"gen{generation_index}"
    snapshot_module(module_path, label)
    baseline = evaluate_dry_run_cycles(n=1)
    baseline_rate = float(baseline.get("promotion_rate") or 0)
    baseline_fitness = float(baseline.get("fitness") or 0)
    record_baseline_promotion_rate(baseline_rate)
    fitness_result = evaluate_dry_run_cycles(n=3)
    fitness = float(fitness_result.get("fitness") or 0)
    accepted = False
    summary = f"Evaluated {target['id']} fitness={fitness:.4f}"

    if codeevolve_auto_apply() and target["id"] == "score_engine_weights":
        if fitness >= baseline_fitness and not should_rollback(
            float(fitness_result.get("promotion_rate") or 0), baseline_rate
        ):
            new_weights = _perturb_weights(load_score_weights(), fitness, baseline_fitness)
            save_score_weights(new_weights, fitness=fitness, target_id=target["id"])
            accepted = True
            summary = f"Auto-applied score_weights fitness={fitness:.4f} weights={new_weights}"
            emit("codeevolve_accept", {"target": target["id"], "fitness": fitness, "weights": new_weights})
        else:
            summary += " (rollback threshold or fitness drop — not applied)"
    elif codeevolve_auto_apply() and target["id"] == "promotion_threshold":
        if fitness >= baseline_fitness and not should_rollback(
            float(fitness_result.get("promotion_rate") or 0), baseline_rate
        ):
            current = load_promotion_threshold(default=0.72)
            new_threshold = _perturb_threshold(current, fitness, baseline_fitness)
            save_promotion_threshold(new_threshold, fitness=fitness, target_id=target["id"])
            accepted = True
            summary = f"Auto-applied promotion_threshold fitness={fitness:.4f} threshold={new_threshold:.3f}"
            emit("codeevolve_accept", {"target": target["id"], "fitness": fitness, "threshold": new_threshold})
        else:
            summary += " (rollback threshold or fitness drop — not applied)"
    elif not codeevolve_auto_apply():
        summary += " (auto_apply disabled)"

    save_pending_diff(target["id"], summary, fitness)
    _record_generation(target["id"], generation_index, fitness, accepted, summary)
    emit("codeevolve_generation", {"target": target["id"], "fitness": fitness, "accepted": accepted})
    return {
        "classification": "CODEEVOLVE_GENERATION_COMPLETE",
        "target": target["id"],
        "fitness": fitness,
        "accepted": accepted,
        "auto_apply": codeevolve_auto_apply(),
        "summary": summary,
        "rollback": get_snapshot(),
    }
