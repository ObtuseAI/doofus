"""Adaptive evolution of external project targets (hill-climbing numeric params, snapshot + rollback)."""
from __future__ import annotations

import ast
import re

from doofus.core.atomic_json import load_json, save_json
from doofus.core.doofus_events import utc_now
from doofus.meta.codeevolve.project_registry import (
    evaluate_project_fitness,
    external_targets,
    get_project,
    project_workspace,
)
from doofus.meta.gep.event_emitter import emit

# Adaptive step-size hill-climbing (1/5-success-rule flavored):
# accepted candidates grow the step and keep direction; rejections flip
# direction, and two consecutive rejections shrink the step.
STEP_INITIAL = 0.05
STEP_MIN = 0.005
STEP_MAX = 0.25
STEP_GROW = 1.3
STEP_SHRINK = 0.5
HISTORY_CAP = 50

_ASSIGN_LINE_RE_TEMPLATE = r"^(?P<indent>\s*){key}\s*=\s*(?P<value>-?\d+(?:\.\d+)?)\s*(?P<comment>#.*)?$"


def find_numeric_param(source: str, param_key: str) -> tuple[int, float] | None:
    """Locate a top-level `PARAM = <number>` assignment; return (lineno, value)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id != param_key:
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, (int, float)) and not isinstance(value.value, bool):
            return node.lineno, float(value.value)
        if (
            isinstance(value, ast.UnaryOp)
            and isinstance(value.op, ast.USub)
            and isinstance(value.operand, ast.Constant)
            and isinstance(value.operand.value, (int, float))
        ):
            return node.lineno, -float(value.operand.value)
    return None


def perturb_numeric_param(source: str, param_key: str, factor: float) -> tuple[str | None, str]:
    """Rewrite `PARAM = <number>` scaled by (1 + factor). Line must hold only that assignment."""
    found = find_numeric_param(source, param_key)
    if found is None:
        return None, "param_not_found"
    lineno, value = found
    lines = source.splitlines(keepends=True)
    line = lines[lineno - 1]
    m = re.match(_ASSIGN_LINE_RE_TEMPLATE.format(key=re.escape(param_key)), line.rstrip("\r\n"))
    if not m:
        return None, "assignment_line_not_simple"
    new_value = value * (1.0 + factor)
    is_int = value.is_integer() and "." not in m.group("value")
    if is_int:
        stepped = round(new_value)
        if stepped == round(value):  # guarantee a minimum step of 1 for small ints
            stepped = int(value) + (1 if factor > 0 else -1)
        if value >= 1:
            stepped = max(1, stepped)
        rendered = str(stepped)
    else:
        rendered = f"{new_value:.6g}"
    comment = f"  {m.group('comment')}" if m.group("comment") else ""
    eol = "\r\n" if line.endswith("\r\n") else ("\n" if line.endswith("\n") else "")
    lines[lineno - 1] = f"{m.group('indent')}{param_key} = {rendered}{comment}{eol}"
    return "".join(lines), "ok"


def _state_file(project_id: str):
    return project_workspace(project_id) / "evolve_state.json"


def load_evolve_state(project_id: str) -> dict:
    state = load_json(_state_file(project_id), default={"targets": {}})
    if not isinstance(state, dict) or not isinstance(state.get("targets"), dict):
        return {"targets": {}}
    return state


def _save_evolve_state(project_id: str, state: dict) -> None:
    save_json(_state_file(project_id), state)


def _target_state(state: dict, target_id: str) -> dict:
    return state["targets"].setdefault(target_id, {
        "step": STEP_INITIAL,
        "direction": 1,
        "consecutive_rejects": 0,
        "accepted_count": 0,
        "rejected_count": 0,
        "best_fitness": None,
        "best_value": None,
        "history": [],
    })


def _adapt_on_accept(ts: dict) -> None:
    ts["step"] = min(round(ts["step"] * STEP_GROW, 6), STEP_MAX)
    ts["consecutive_rejects"] = 0
    ts["accepted_count"] = ts.get("accepted_count", 0) + 1


def _adapt_on_reject(ts: dict) -> None:
    ts["direction"] = -ts.get("direction", 1)
    ts["rejected_count"] = ts.get("rejected_count", 0) + 1
    ts["consecutive_rejects"] = ts.get("consecutive_rejects", 0) + 1
    if ts["consecutive_rejects"] >= 2:
        ts["step"] = max(round(ts["step"] * STEP_SHRINK, 6), STEP_MIN)
        ts["consecutive_rejects"] = 0


def _note_best(ts: dict, fitness: float, value: float | None) -> None:
    if ts.get("best_fitness") is None or fitness > float(ts["best_fitness"]):
        ts["best_fitness"] = round(fitness, 6)
        if value is not None:
            ts["best_value"] = value


def _append_history(ts: dict, row: dict) -> None:
    ts.setdefault("history", []).append(row)
    ts["history"] = ts["history"][-HISTORY_CAP:]


def _write_report(project_id: str, report: dict) -> None:
    ws = project_workspace(project_id)
    save_json(ws / "last_generation.json", report)


def run_external_generation(target: dict, generation_index: int = 0, *, apply_override: bool | None = None) -> dict:
    """Evaluate (and, when explicitly opted in, evolve) one external target.

    apply_override forces evolution on (True) or measure-only (False); None
    defers to DOOFUS_CODEEVOLVE_AUTO_APPLY plus the project's auto_apply flag.
    """
    from doofus.config.meta_evolution_config import codeevolve_auto_apply

    project = get_project(target["project_id"])
    if project is None or not project.get("enabled"):
        return {"classification": "CODEEVOLVE_EXTERNAL_SKIPPED", "reason": "project_missing_or_disabled", "target": target["id"]}

    module_path = target["module_path"]
    baseline = evaluate_project_fitness(project)
    baseline_fitness = float(baseline.get("fitness") or 0.0)
    report = {
        "target": target["id"],
        "generation": generation_index,
        "baseline": baseline,
        "created_at": utc_now(),
    }

    state = load_evolve_state(project["id"])
    ts = _target_state(state, target["id"])

    if apply_override is None:
        apply_allowed = codeevolve_auto_apply() and bool(project.get("auto_apply"))
    else:
        apply_allowed = apply_override
    param_key = target.get("param_key")
    if not apply_allowed or not param_key or baseline["classification"] != "EXTERNAL_FITNESS_OK":
        _note_best(ts, baseline_fitness, None)
        ts["last_measured"] = {"fitness": baseline_fitness, "at": utc_now()}
        _save_evolve_state(project["id"], state)
        report["mode"] = "measure_only"
        _write_report(project["id"], report)
        emit("codeevolve_external_measured", {"target": target["id"], "fitness": baseline_fitness})
        return {
            "classification": "CODEEVOLVE_EXTERNAL_MEASURED",
            "target": target["id"],
            "fitness": baseline_fitness,
            "accepted": False,
            "summary": f"Measured {target['id']} fitness={baseline_fitness:.4f} (measure-only)",
        }

    original_source = module_path.read_text(encoding="utf-8")
    factor = ts.get("direction", 1) * float(ts.get("step", STEP_INITIAL))
    mutated, reason = perturb_numeric_param(original_source, param_key, factor)
    if mutated is None:
        report["mode"] = f"mutation_skipped:{reason}"
        _write_report(project["id"], report)
        return {
            "classification": "CODEEVOLVE_EXTERNAL_MEASURED",
            "target": target["id"],
            "fitness": baseline_fitness,
            "accepted": False,
            "summary": f"Measured {target['id']} fitness={baseline_fitness:.4f} ({reason})",
        }

    snapshot = project_workspace(project["id"]) / f"gen{generation_index}_{module_path.name}"
    snapshot.write_text(original_source, encoding="utf-8")
    module_path.write_text(mutated, encoding="utf-8")
    candidate = evaluate_project_fitness(project)
    candidate_fitness = float(candidate.get("fitness") or 0.0)
    accepted = candidate["classification"] == "EXTERNAL_FITNESS_OK" and candidate_fitness >= baseline_fitness
    if not accepted:
        module_path.write_text(original_source, encoding="utf-8")

    new_value = (find_numeric_param(mutated, param_key) or (None, None))[1]
    if accepted:
        _adapt_on_accept(ts)
        _note_best(ts, candidate_fitness, new_value)
    else:
        _adapt_on_reject(ts)
        _note_best(ts, baseline_fitness, (find_numeric_param(original_source, param_key) or (None, None))[1])
    _append_history(ts, {
        "generation": generation_index,
        "factor": round(factor, 6),
        "baseline_fitness": baseline_fitness,
        "candidate_fitness": candidate_fitness,
        "accepted": accepted,
        "at": utc_now(),
    })
    _save_evolve_state(project["id"], state)

    report.update({
        "mode": "evolve",
        "candidate": candidate,
        "param_key": param_key,
        "factor": factor,
        "accepted": accepted,
        "snapshot": str(snapshot),
        "optimizer": {"step": ts["step"], "direction": ts["direction"], "best_fitness": ts["best_fitness"]},
    })
    _write_report(project["id"], report)
    emit("codeevolve_external_generation", {
        "target": target["id"],
        "baseline_fitness": baseline_fitness,
        "candidate_fitness": candidate_fitness,
        "accepted": accepted,
    })
    action = "applied" if accepted else "rolled back"
    return {
        "classification": "CODEEVOLVE_EXTERNAL_GENERATION_COMPLETE",
        "target": target["id"],
        "fitness": candidate_fitness if accepted else baseline_fitness,
        "accepted": accepted,
        "summary": (
            f"External {target['id']} {param_key} x{1.0 + factor:.3f} "
            f"baseline={baseline_fitness:.4f} candidate={candidate_fitness:.4f} — {action}"
        ),
    }


def evolve_project(
    project_id: str,
    *,
    generations: int = 5,
    target_filter: str | None = None,
    apply_override: bool | None = None,
) -> dict:
    """Run N hill-climbing generations against one registered project's targets."""
    targets = [
        t for t in external_targets()
        if t["project_id"] == project_id
        and (target_filter is None or t["target_id"] == target_filter or t["id"] == target_filter)
    ]
    if not targets:
        return {
            "classification": "EVOLVE_PROJECT_NO_TARGETS",
            "project": project_id,
            "reason": "project disabled, unregistered, or no resolvable targets",
        }
    results = []
    for generation in range(max(1, generations)):
        for target in targets:
            results.append(run_external_generation(target, generation, apply_override=apply_override))
    accepted = sum(1 for r in results if r.get("accepted"))
    best_fitness = max((float(r.get("fitness") or 0.0) for r in results), default=0.0)
    state = load_evolve_state(project_id)
    return {
        "classification": "EVOLVE_PROJECT_COMPLETE",
        "project": project_id,
        "generations": max(1, generations),
        "targets": [t["id"] for t in targets],
        "runs": len(results),
        "accepted": accepted,
        "best_fitness": round(best_fitness, 4),
        "optimizer_state": {tid: {k: ts.get(k) for k in ("step", "direction", "best_fitness", "best_value")}
                            for tid, ts in state.get("targets", {}).items()},
        "results": results,
    }
