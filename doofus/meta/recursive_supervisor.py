"""Meta-supervisor — orchestrates inner loop + outer meta-evolution."""
from __future__ import annotations

import json
import os
import time

from doofus.config.meta_evolution_config import (
    DEFAULTS,
    meta_evolution_enabled,
    runtime_snapshot as meta_runtime,
)
from doofus.config.evolution_runtime_config import apply_defaults as apply_evo_defaults
from doofus.config.meta_evolution_config import apply_defaults as apply_meta_defaults
from doofus.config.proof_builder_runtime_config import bootstrap_autonomous_runtime, proof_builder_mode
from doofus.config.metacognition_config import (
    apply_defaults as apply_metacognition_defaults,
    metacognition_enabled,
    target_id as metacognition_target_id,
)
from doofus.core.atomic_json import load_json, save_json
from doofus.core.doofus_events import utc_now
from doofus.core.doofus_paths import STATE
from doofus.core.metrics_db import metrics_conn
from doofus.core.pipeline_log import pipeline_warn
from doofus.evolution.adaptive_mutation_pressure import get_pressure_state
from doofus.evolution.map_elites_archive import maintain as maintain_map_elites
from doofus.meta.aevolve.stagnation_escalator import escalate as aevolve_escalate
from doofus.meta.codeevolve.openevolve_adapter import run_generation as run_codeevolve
from doofus.meta.gep.event_emitter import emit as emit_gep_event
from doofus.meta.gepa.prompt_evolver import run_batch as run_gepa_batch
from doofus.meta.meta_metacognition import run_meta_metacognitive_cycle
from doofus.metacognition.controller import (
    complete_metacognitive_cycle,
    deactivate_control,
    prepare_metacognitive_cycle,
    should_skip_cycle as should_skip_metacognitive_cycle,
)
from doofus.promotion.tier3_final_gate import get_tier3_snapshot
from doofus.safety.budget_guard import check_budget
from doofus.safety.on_off_switch import check_may_proceed
from doofus.supervisor.doofus_loop_runner import run_one_cycle
from doofus.supervisor.doofus_crash_recovery import load_checkpoint

META_STATE_FILE = STATE / "meta_evolution_state.json"
_DEFAULT_STATE = {
    "cycle_count": 0,
    "last_gepa_cycle": 0,
    "last_map_cycle": 0,
    "last_codeevolve_cycle": 0,
    "last_meta_metacognition_cycle": 0,
}


def load_meta_state() -> dict:
    return _load_meta_state()


def _load_meta_state() -> dict:
    data = load_json(META_STATE_FILE, default=dict(_DEFAULT_STATE))
    if not isinstance(data, dict):
        return dict(_DEFAULT_STATE)
    return {**_DEFAULT_STATE, **data}


def _save_meta_state(state: dict) -> None:
    save_json(META_STATE_FILE, state)


def _int_env(key: str) -> int:
    return int(os.environ.get(key, DEFAULTS.get(key, "5")))


def should_run_gepa(state: dict) -> bool:
    return state["cycle_count"] - state.get("last_gepa_cycle", 0) >= _int_env("DOOFUS_GEPA_BATCH_EVERY")


def should_run_map(state: dict) -> bool:
    return state["cycle_count"] - state.get("last_map_cycle", 0) >= _int_env("DOOFUS_MAP_ELITES_MAINTAIN_EVERY")


def should_run_codeevolve(state: dict) -> bool:
    return state["cycle_count"] - state.get("last_codeevolve_cycle", 0) >= _int_env("DOOFUS_CODEEVOLVE_EVERY")


def should_run_meta_metacognition(state: dict) -> bool:
    return state["cycle_count"] - state.get("last_meta_metacognition_cycle", 0) >= _int_env("DOOFUS_META_METACOGNITION_EVERY")


def _run_meta_task(name: str, fn, *args, **kwargs) -> dict:
    try:
        result = fn(*args, **kwargs)
        if isinstance(result, dict):
            result.setdefault("classification", f"{name.upper()}_OK")
            return result
        return {"classification": f"{name.upper()}_OK", "result": result}
    except Exception as exc:
        pipeline_warn(f"meta_{name}", "task failed", exc=exc)
        return {"classification": f"{name.upper()}_ERROR", "error": type(exc).__name__}


def _meta_result_classifications(meta_results: dict) -> dict:
    out = {}
    for k, v in meta_results.items():
        if isinstance(v, dict):
            out[k] = v.get("classification", k)
        else:
            out[k] = str(v)
    return out


def _record_codeevolve_event(
    *,
    generation: int,
    due: bool,
    attempted: bool,
    ran: bool,
    skipped: bool,
    skip_reason: str = "",
    blocked_by_gate: bool = False,
    gate_name: str = "",
    gate_details: dict | None = None,
    sandbox_enabled: bool = True,
    budget_status: dict | None = None,
    tier3_status: dict | None = None,
    proof_density_status: str = "",
    candidates_generated: int = 0,
    candidates_applied: int = 0,
    duration_ms: float = 0.0,
    error_type: str = "",
    error_message_sanitized: str = "",
) -> None:
    try:
        with metrics_conn() as conn:
            conn.execute(
                """
                INSERT INTO codeevolve_events (
                  timestamp_utc, generation, due, attempted, ran, skipped, skip_reason,
                  blocked_by_gate, gate_name, gate_details_sanitized, sandbox_enabled,
                  budget_status, tier3_status, proof_density_status, candidates_generated,
                  candidates_applied, duration_ms, error_type, error_message_sanitized, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    utc_now(),
                    generation,
                    int(due),
                    int(attempted),
                    int(ran),
                    int(skipped),
                    skip_reason or None,
                    int(blocked_by_gate),
                    gate_name or None,
                    json.dumps(gate_details or {}, default=str)[:500],
                    int(sandbox_enabled),
                    json.dumps(budget_status or {}, default=str)[:500],
                    json.dumps(tier3_status or {}, default=str)[:500],
                    proof_density_status or None,
                    candidates_generated,
                    candidates_applied,
                    round(duration_ms, 2),
                    error_type or None,
                    error_message_sanitized or None,
                    utc_now(),
                ),
            )
    except Exception as exc:
        pipeline_warn("codeevolve_event", "event insert failed", exc=exc)


def run_meta_cycle(*, dry_run: bool = False, live_model_if_available: bool = True) -> dict:
    from doofus.core.doofus_state import init_db

    bootstrap_autonomous_runtime()
    apply_evo_defaults()
    apply_meta_defaults()
    apply_metacognition_defaults()
    init_db()

    metacognitive_pre: dict = {}
    metacognitive_post: dict = {}
    if metacognition_enabled():
        deactivate_control("recursive_supervisor_preflight")
        metacognitive_pre = _run_meta_task(
            "metacognition_pre",
            prepare_metacognitive_cycle,
            metacognition_target_id(),
            True,
            dry_run,
        )

    from doofus.arenas.arena_router import reset_cycle_budget
    reset_cycle_budget()

    skip_cycle, skip_reason = should_skip_metacognitive_cycle()
    if skip_cycle:
        state_payload = metacognitive_pre.get("state") if isinstance(metacognitive_pre, dict) else {}
        generation = state_payload.get("generation", 0) if isinstance(state_payload, dict) else 0
        checkpoint = load_checkpoint()
        inner = {
            "classification": "DOOFUS_METACOGNITIVE_ABSTAIN",
            "reason": skip_reason,
            "generation": generation,
            "promoted": 0,
            "candidates": 0,
            "baseline_score": float(checkpoint.get("baseline_score", 0.5)),
        }
    else:
        inner = run_one_cycle(dry_run=dry_run, live_model_if_available=live_model_if_available)
    if metacognitive_pre.get("prediction_id"):
        metacognitive_post = _run_meta_task(
            "metacognition_post",
            complete_metacognitive_cycle,
            metacognitive_pre,
            inner,
        )
    if not meta_evolution_enabled():
        return {
            **inner,
            "metacognition": {"pre": metacognitive_pre, "post": metacognitive_post},
        }
    state = _load_meta_state()
    meta_results: dict = {}
    classification = inner.get("classification")
    completed_cycle = classification in {
        "DOOFUS_CYCLE_COMPLETE",
        "B1003_LIVE_MODEL_CYCLE_PASS",
        "B1003_LIVE_MODEL_CYCLE_DRY_RUN_FALLBACK",
        "B1003_LIVE_MODEL_CYCLE_PASS_WITH_NOTES",
        "DOOFUS_CYCLE_METACOGNITIVE_EARLY_TERMINATION",
    }
    state["last_inner"] = {
        "generation": inner.get("generation"),
        "promoted": inner.get("promoted"),
        "classification": classification,
    }
    if not completed_cycle:
        _save_meta_state(state)
        return {
            **inner,
            "metacognition": {"pre": metacognitive_pre, "post": metacognitive_post},
            "meta": {"state": state, "results": meta_results, "config": meta_runtime()},
        }

    state["cycle_count"] = state.get("cycle_count", 0) + 1

    ok, _reason = check_may_proceed()
    budget = check_budget()
    tier3 = get_tier3_snapshot()
    if ok or dry_run:
        if should_run_gepa(state):
            meta_results["gepa"] = _run_meta_task("gepa", run_gepa_batch)
            state["last_gepa_cycle"] = state["cycle_count"]
        if should_run_map(state):
            meta_results["map_elites"] = _run_meta_task("map_elites", maintain_map_elites)
            state["last_map_cycle"] = state["cycle_count"]
        if should_run_meta_metacognition(state):
            meta_results["meta_metacognition"] = _run_meta_task(
                "meta_metacognition",
                run_meta_metacognitive_cycle,
                metacognition_target_id(),
            )
            state["last_meta_metacognition_cycle"] = state["cycle_count"]
        code_due = should_run_codeevolve(state)
        code_gate_details = {
            "switch_allows_run": ok,
            "dry_run": dry_run,
            "budget_ok": budget.get("ok"),
            "tier3_enabled": tier3.get("enabled"),
            "proof_builder_mode": proof_builder_mode(),
        }
        if code_due and not dry_run and budget.get("ok"):
            started = time.perf_counter()
            result = _run_meta_task("codeevolve", run_codeevolve, state["cycle_count"])
            meta_results["codeevolve"] = result
            state["last_codeevolve_cycle"] = state["cycle_count"]
            _record_codeevolve_event(
                generation=int(inner.get("generation") or 0),
                due=True,
                attempted=True,
                ran=result.get("classification") == "CODEEVOLVE_GENERATION_COMPLETE",
                skipped=False,
                blocked_by_gate=False,
                gate_name="meta_due_check",
                gate_details=code_gate_details,
                sandbox_enabled=True,
                budget_status=budget,
                tier3_status=tier3,
                proof_density_status="preserved" if proof_builder_mode() else "disabled",
                candidates_generated=1,
                candidates_applied=int(bool(result.get("accepted"))),
                duration_ms=(time.perf_counter() - started) * 1000.0,
                error_type="" if result.get("classification") == "CODEEVOLVE_GENERATION_COMPLETE" else str(result.get("classification") or ""),
                error_message_sanitized=str(result.get("error") or "")[:500],
            )
        elif code_due:
            reason = "dry_run" if dry_run else ("budget_blocked" if not budget.get("ok") else "switch_blocked")
            gate_name = "budget_guard" if not budget.get("ok") else ("meta_cycle_dry_run" if dry_run else "run_switch")
            _record_codeevolve_event(
                generation=int(inner.get("generation") or 0),
                due=True,
                attempted=False,
                ran=False,
                skipped=True,
                skip_reason=reason,
                blocked_by_gate=True,
                gate_name=gate_name,
                gate_details={**code_gate_details, "reason": reason},
                sandbox_enabled=True,
                budget_status=budget,
                tier3_status=tier3,
                proof_density_status="preserved" if proof_builder_mode() else "disabled",
            )
        else:
            _record_codeevolve_event(
                generation=int(inner.get("generation") or 0),
                due=False,
                attempted=False,
                ran=False,
                skipped=True,
                skip_reason="not_due",
                blocked_by_gate=False,
                gate_name="cadence",
                gate_details={**code_gate_details, "state_cycle_count": state["cycle_count"]},
                sandbox_enabled=True,
                budget_status=budget,
                tier3_status=tier3,
                proof_density_status="preserved" if proof_builder_mode() else "disabled",
            )
    else:
        _record_codeevolve_event(
            generation=int(inner.get("generation") or 0),
            due=should_run_codeevolve(state),
            attempted=False,
            ran=False,
            skipped=True,
            skip_reason="run_switch_blocked",
            blocked_by_gate=True,
            gate_name="run_switch",
            gate_details={"switch_allows_run": ok},
            sandbox_enabled=True,
            budget_status=budget,
            tier3_status=tier3,
            proof_density_status="preserved" if proof_builder_mode() else "disabled",
        )

    ps = get_pressure_state()
    stagnation = int(ps.get("stagnation_cycles") or 0)
    escalation_at = int(os.environ.get("DOOFUS_AEVOLVE_ESCALATION_AT", "10"))
    if stagnation >= escalation_at:
        meta_results["aevolve_escalation"] = _run_meta_task("aevolve", aevolve_escalate, stagnation)

    emit_gep_event("meta_cycle_complete", {
        "generation": inner.get("generation"),
        "promoted": inner.get("promoted"),
        "meta_results": _meta_result_classifications(meta_results),
    })
    _save_meta_state(state)
    return {
        **inner,
        "metacognition": {"pre": metacognitive_pre, "post": metacognitive_post},
        "meta": {"state": state, "results": meta_results, "config": meta_runtime()},
    }


def get_meta_snapshot() -> dict:
    return {"state": _load_meta_state(), "config": meta_runtime()}
