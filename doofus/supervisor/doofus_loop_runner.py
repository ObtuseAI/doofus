"""Single Doofus cycle runner — hardened autonomous evolution pipeline."""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import time
import uuid

from doofus.arenas.arena_router import run_arenas
from doofus.config.proof_builder_runtime_config import (
    bootstrap_autonomous_runtime,
    high_score_rescue_mode,
    proof_builder_mode,
)
from doofus.core import doofus_paths
from doofus.core.doofus_config import DoofusConfig
from doofus.core.doofus_events import utc_now
from doofus.core.doofus_state import init_db
from doofus.core.metrics_db import connect_metrics_db
from doofus.core.pipeline_log import pipeline_warn
from doofus.evolution.autonomous_compounding_loop import after_compounding_cycle
from doofus.evolution.best_ever_ledger import get_best_ever
from doofus.evolution.elite_parent_selector import select_parents
from doofus.evolution.evolution_pressure_mode import (
    after_candidate_scored,
    after_cycle,
    apply_pre_promotion_scores,
    filter_retired_parents,
    prepare_cycle,
)
from doofus.evolution.shadow_elite_promoter import try_shadow_elite
from doofus.meta.gepa.gepa_hooks import on_candidate_scored
from doofus.meta.gepa.prompt_evolver import build_mutation_context
from doofus.model_router.live_model_adapter import propose_mutations as provider_propose_mutations
from doofus.model_router.model_secret_redactor import redact_secrets
from doofus.model_router.provider_router import resolve_provider
from doofus.mutation.candidate_generator import generate_cycle_candidates, record_candidate_outcome
from doofus.mutation.model_proposal_applier import apply_proposal_to_candidate
from doofus.mutation.mutation_lineage import build_lineage
from doofus.metacognition.controller import online_termination_reason, record_online_observation
from doofus.config.metacognition_config import target_id as metacognition_target_id
from doofus.proof.high_score_rescue_loop import run_inline_rescue
from doofus.reports.live_cycle_reporter import build_live_cycle_report
from doofus.safety.doofus_safety_gate import check_candidate_safety
from doofus.safety.on_off_switch import check_may_proceed
from doofus.scoring.arena_runner import run_local_arenas  # noqa: F401 — re-export compat
from doofus.scoring.candidate_scorecard import build_scorecard
from doofus.scoring.live_candidate_validator import validate_proposal
from doofus.scoring.promotion_gate import evaluate_promotion, prequalify_candidate
from doofus.scoring.promotion_quarantine import record_debt
from doofus.scoring.rejection_classifier import classify_rejection
from doofus.scoring.score_engine import score_candidate
from doofus.scoring.scoring_telemetry import (
    bind_candidate,
    bind_cycle,
    record_progress as record_scoring_progress,
    record_scoring_event,
    record_timeout as record_scoring_timeout,
    reset_candidate,
    reset_cycle,
    scoring_step,
)
from doofus.supervisor.doofus_crash_recovery import finalize_checkpoint, load_checkpoint, save_checkpoint
from doofus.supervisor.doofus_cycle_checkpoint import write_checkpoint
from doofus.supervisor.doofus_heartbeat import emit_heartbeat
from doofus.supervisor.live_model_cycle_gate import may_call_model
from doofus.supervisor.metrics_writer import (
    log_arena_results,
    log_mutation,
    log_safety_event,
    log_score_components,
    upsert_candidate,
)
from doofus.supervisor.supervisor_phase_watchdog import (
    SupervisorPhaseTimeout,
    finalize_phase_or_raise,
    phase_timeout_seconds,
    record_phase_event,
)
from doofus.supervisor.cycle_init_watchdog import CycleInitContext, CycleInitTimeout, run_bounded_init_call

_DB_INITIALIZED = False
_CYCLE_HEARTBEAT_SECONDS = float(os.environ.get("DOOFUS_CYCLE_HEARTBEAT_SECONDS", "30"))


def _ensure_db() -> None:
    global _DB_INITIALIZED
    if not _DB_INITIALIZED:
        init_db()
        _DB_INITIALIZED = True


def _arena_pass_rate(arena: list[dict]) -> float:
    if not arena:
        return 0.0
    passed = sum(1 for a in arena if a.get("passed") or str(a.get("result", "")).startswith("pass"))
    return passed / len(arena)


def _score_metric_count(scores: dict) -> int:
    return sum(
        1
        for metric in scores
        if metric.startswith("score_")
        or metric in ("proof_density_score", "bloat_penalty", "replay_stability_score")
    )


def _emit_cycle_progress(
    *,
    generation: int,
    stage: str,
    last_heartbeat_at: float,
    force: bool = False,
    **detail,
) -> float:
    now = time.perf_counter()
    if force or now - last_heartbeat_at >= _CYCLE_HEARTBEAT_SECONDS:
        emit_heartbeat(
            "cycle_progress",
            {
                "generation": generation,
                "stage": stage,
                **detail,
            },
        )
        return now
    return last_heartbeat_at


def _apply_model_proposal(
    model_result: dict,
    candidates: list[dict],
    generation: int,
) -> tuple[dict, list[dict]]:
    batch = int(os.environ.get("DOOFUS_CURSOR_MUTATION_BATCH", "1"))
    model_result.setdefault("mutation_batch_size", batch)
    model_guided_indices = [
        i for i, c in enumerate(candidates) if c.get("algorithm_id") == "model_guided"
    ]
    requested_slots = len(model_guided_indices) or len(candidates)
    model_result.setdefault("proposals_requested", max(1, min(batch, requested_slots or 1)))
    raw = model_result.get("raw", "")
    if not raw and model_result.get("proposals"):
        raw = json.dumps({"proposals": model_result.get("proposals")})
    if not raw or not candidates:
        if not raw:
            model_result.setdefault("skip_reason", "no_raw_model_output")
        return model_result, candidates
    try:
        validation = validate_proposal(raw)
        model_result["proposal_validation"] = validation
        if validation.get("valid") and validation.get("proposal"):
            proposal_root = validation["proposal"]
            proposals = proposal_root.get("proposals") if isinstance(proposal_root, dict) else None
            if not isinstance(proposals, list) or not proposals:
                proposals = [proposal_root]
            model_result["proposals_returned"] = len(proposals)
            if not model_guided_indices:
                model_guided_indices = list(range(min(batch, len(candidates))))
                model_result.setdefault("skip_reason", "no_model_guided_candidates")

            applied_ids: list[str] = []
            for n, idx in enumerate(model_guided_indices[: max(1, batch)]):
                if idx >= len(candidates):
                    break
                prop = proposals[n % len(proposals)]
                wrap = {"proposals": [prop]} if isinstance(prop, dict) and "traits" in prop else prop
                if isinstance(wrap, dict) and "proposals" not in wrap and wrap.get("traits"):
                    wrap = {"proposals": [wrap]}
                updated = apply_proposal_to_candidate(
                    candidates[idx], wrap if isinstance(wrap, dict) else {"proposals": proposals},
                    rng=random.Random(generation + n),
                )
                candidates[idx] = updated
                if updated.get("mutation_type") == "model_guided_mutation":
                    applied_ids.append(updated["candidate_id"])

            if applied_ids:
                model_result["proposal_applied"] = applied_ids[0]
                model_result["proposals_applied_count"] = len(applied_ids)
                model_result["proposals_applied_ids"] = applied_ids
                model_result.pop("proposal_only", None)
            else:
                model_result["proposal_only"] = True
                model_result.setdefault("skip_reason", "zero_usable_proposals")
        else:
            model_result["proposals_returned"] = 0
            model_result.setdefault("skip_reason", "proposal_invalid")
    except Exception as exc:
        model_result["proposal_error"] = type(exc).__name__
        model_result.setdefault("skip_reason", "proposal_apply_error")
        pipeline_warn("model_proposal", "apply failed", exc=exc)
    return model_result, candidates


def _resolve_model_context(generation: int, baseline: float, pressure: dict, candidate_count: int) -> dict:
    best = get_best_ever()
    return build_mutation_context({
        "generation": generation,
        "baseline": baseline,
        "best_ever_score": best.get("best_score"),
        "stagnation_cycles": pressure.get("stagnation_cycles", 0),
        "pressure_level": pressure.get("pressure_level", 1.0),
        "candidate_count": candidate_count,
        "parent_traits": [p.get("traits") for p in select_parents(limit=3)],
    })


def _provider_propose_mutations_for_cycle(context: dict, *, force_dry_run: bool) -> dict:
    if not force_dry_run:
        return provider_propose_mutations(context)
    previous = os.environ.get("DOOFUS_FORCE_MODEL_DRY_RUN")
    os.environ["DOOFUS_FORCE_MODEL_DRY_RUN"] = "1"
    try:
        return provider_propose_mutations(context)
    finally:
        if previous is None:
            os.environ.pop("DOOFUS_FORCE_MODEL_DRY_RUN", None)
        else:
            os.environ["DOOFUS_FORCE_MODEL_DRY_RUN"] = previous


def _failure_cycle_result(
    *,
    classification: str,
    generation: int,
    run_id: str,
    baseline: float,
    phase: str,
    error_type: str,
    error_message: str,
    model_result: dict,
    gate: dict,
    model_context: dict,
    cfg: DoofusConfig,
    inline_rescue_result: dict,
    dry_run: bool,
    live_model_if_available: bool,
) -> dict:
    return build_live_cycle_report({
        "classification": classification,
        "run_id": run_id,
        "generation": generation,
        "candidates": 0,
        "promoted": 0,
        "shadow_promoted": 0,
        "rejected": 0,
        "partial": False,
        "evolution": {},
        "compounding": {},
        "inline_rescue": inline_rescue_result,
        "baseline_score": baseline,
        "lineage": [],
        "lineage_parents": 0,
        "model_mode": cfg.model_mode,
        "model_result": {
            **{
                k: redact_secrets(str(v)) if isinstance(v, str) else v
                for k, v in model_result.items()
            },
            "failure_phase": phase,
            "error_type": error_type,
            "error_message_sanitized": redact_secrets(error_message)[:500],
        },
        "dry_run": dry_run,
        "live_model_if_available": live_model_if_available,
        "gate": gate if live_model_if_available else {},
        "generated_at": utc_now(),
        "phase": phase,
    })["cycle"]


def _score_one_candidate(
    conn: sqlite3.Connection,
    c: dict,
    *,
    generation: int,
    baseline: float,
    dry_run: bool,
    traits_before: list,
) -> tuple[dict, dict, int, int, int, float]:
    """Returns (candidate, promo, promoted_delta, shadow_delta, rejected_delta, new_baseline)."""
    promoted_d = shadow_d = rejected_d = 0
    new_baseline = baseline
    with scoring_step(
        scorer_name="candidate_scoring",
        scorer_module="doofus.supervisor.doofus_loop_runner",
        substep="candidate_total",
        input_size=len(c.get("traits") or []),
    ) as candidate_step:
        safety = check_candidate_safety(c)
        if not safety["passes"]:
            rejected_d = 1
            reason_s = "safety_violation:" + ",".join(safety["violations"])
            with scoring_step(
                scorer_name="safety_gate",
                scorer_module="doofus.safety.doofus_safety_gate",
                substep="forbidden_trait_block",
                input_size=len(safety.get("violations") or []),
            ) as safety_step:
                log_safety_event(conn, "forbidden_trait_block", reason_s)
                conn.execute(
                    "INSERT INTO rejections (candidate_id, reason, created_at) VALUES (?,?,?)",
                    (c["candidate_id"], reason_s, utc_now()),
                )
                safety_step.sqlite_write_count = 2
            c["status"] = "rejected"
            c["rejection_reason"] = reason_s
            zero = {
                "score_total": 0,
                "score_safety": 0,
                "score_replay": 0,
                "score_generalization": 0,
                "score_compounding": 0,
                "score_recursive_learning": 0,
            }
            with scoring_step(
                scorer_name="candidate_persist",
                scorer_module="doofus.supervisor.metrics_writer",
                substep="upsert_candidate",
                input_size=1,
            ) as persist_step:
                upsert_candidate(conn, c, zero, {"promotion_status": "rejected"})
                persist_step.sqlite_write_count = 1
            candidate_step.output_size = len(zero)
            c["metacognitive_score_total"] = 0.0
            return c, {"promotion_status": "rejected"}, promoted_d, shadow_d, rejected_d, new_baseline

        with scoring_step(
            scorer_name="score_candidate",
            scorer_module="doofus.scoring.score_engine",
            substep="base_scores",
            input_size=len(c.get("traits") or []),
        ) as step:
            scores = score_candidate(c, generation, baseline)
            step.output_size = len(scores)
        with scoring_step(
            scorer_name="score_adjustment",
            scorer_module="doofus.evolution.evolution_pressure_mode",
            substep="apply_pre_promotion_scores",
            input_size=len(scores),
        ) as step:
            scores = apply_pre_promotion_scores(c, scores)
            step.output_size = len(scores)
        c.update(scores)

        prequal = prequalify_candidate(scores, baseline)
        arena: list[dict] = []
        card: dict | None = None
        if prequal["eligible_for_expensive_scoring"]:
            with scoring_step(
                scorer_name="arena_scoring",
                scorer_module="doofus.arenas.arena_router",
                substep="run_arenas",
                input_size=len(c.get("arena_targets") or []),
            ) as step:
                arena = run_arenas(c, scores, dry_run=dry_run)
                step.output_size = len(arena)

            with scoring_step(
                scorer_name="arena_scoring",
                scorer_module="doofus.supervisor.metrics_writer",
                substep="log_arena_results",
                input_size=len(arena),
            ) as step:
                log_arena_results(conn, arena)
                step.sqlite_write_count = len(arena)

            pass_rate = _arena_pass_rate(arena)
            with scoring_step(
                scorer_name="map_elites",
                scorer_module="doofus.evolution.map_elites_archive",
                substep="insert_archive_cell",
                input_size=len(arena),
            ) as step:
                from doofus.evolution.map_elites_archive import insert as map_insert

                result = map_insert(c, scores, arena_pass_rate=pass_rate, conn=conn)
                if result.get("sql_write_ok", True):
                    step.sqlite_write_count = 1
                    step.artifact_write_count = 1
                    step.output_size = 1
                else:
                    step.status = "suppressed_error"
                    step.error_type = result.get("error_type", "")
                    step.error_message_sanitized = result.get("error_message_sanitized", "")

            with scoring_step(
                scorer_name="proof_density",
                scorer_module="doofus.scoring.candidate_scorecard",
                substep="build_scorecard",
                input_size=len(arena),
            ) as step:
                card = build_scorecard(c, scores, arena_results=arena)
                scores = card["scores"]
                step.output_size = len(scores)
            c.update(scores)
        else:
            record_scoring_event(
                scorer_name="arena_scoring",
                scorer_module="doofus.arenas.arena_router",
                substep="run_arenas",
                event_type="skipped",
                input_size=len(c.get("arena_targets") or []),
                status="suppressed",
                error_type="CandidatePrequalifiedOut",
                error_message_sanitized=prequal["prequal_reason"],
            )
            record_scoring_event(
                scorer_name="map_elites",
                scorer_module="doofus.evolution.map_elites_archive",
                substep="insert_archive_cell",
                event_type="skipped",
                status="deferred",
                error_type="CandidatePrequalifiedOut",
                error_message_sanitized=prequal["prequal_reason"],
            )
            record_scoring_event(
                scorer_name="proof_density",
                scorer_module="doofus.scoring.candidate_scorecard",
                substep="build_scorecard",
                event_type="skipped",
                status="suppressed",
                error_type="CandidatePrequalifiedOut",
                error_message_sanitized=prequal["prequal_reason"],
            )

        with scoring_step(
            scorer_name="score_persist",
            scorer_module="doofus.supervisor.metrics_writer",
            substep="log_score_components",
            input_size=_score_metric_count(scores),
        ) as step:
            log_score_components(conn, c["candidate_id"], scores)
            step.sqlite_write_count = _score_metric_count(scores)

        with scoring_step(
            scorer_name="rejection_classifier",
            scorer_module="doofus.scoring.rejection_classifier",
            substep="classify_rejection",
            input_size=len(scores),
        ) as step:
            rej = classify_rejection(c, scores)
            step.output_size = 1 if rej else 0

        with scoring_step(
            scorer_name="promotion_gate",
            scorer_module="doofus.scoring.promotion_gate",
            substep="evaluate_promotion",
            input_size=len(arena),
        ) as step:
            if prequal["eligible_for_expensive_scoring"]:
                promo = evaluate_promotion(
                    c,
                    scores,
                    baseline,
                    arena_results=arena,
                    precomputed_card=card,
                )
                step.output_size = len(promo)
            else:
                promo = {
                    "promoted": False,
                    "shadow_promoted": False,
                    "promotion_status": "rejected",
                    "baseline_retained": True,
                    "proof_density_passed": False,
                    "arena_support_passed": False,
                    "proof_debt": False,
                    "arena_debt": False,
                    "replay_passed": prequal["replay_passed"],
                    "promotion_threshold": prequal["promotion_threshold"],
                    "promotion_baseline": prequal["promotion_baseline"],
                    "tier3_result": None,
                    "tier3_debt": False,
                }
                step.status = "suppressed"
                step.output_size = len(promo)

        with scoring_step(
            scorer_name="post_score_side_effects",
            scorer_module="doofus.evolution.evolution_pressure_mode",
            substep="after_candidate_scored",
            input_size=len(scores),
        ) as step:
            scores = after_candidate_scored(
                c,
                scores,
                promoted=promo.get("promoted", False),
                shadow=promo.get("shadow_promoted", False),
                conn=conn,
            )
            step.output_size = len(scores)
        c.update(scores)

        with scoring_step(
            scorer_name="promotion_outcome",
            scorer_module="doofus.supervisor.doofus_loop_runner",
            substep="finalize_candidate_status",
            input_size=1,
        ) as step:
            if promo.get("promoted"):
                promoted_d = 1
                new_baseline = max(baseline, float(scores.get("score_total") or 0))
                conn.execute(
                    "INSERT INTO promotions (candidate_id, created_at) VALUES (?,?)",
                    (c["candidate_id"], utc_now()),
                )
                c["status"] = "promoted"
                step.sqlite_write_count = 1
                try:
                    from doofus.meta.gep.capsule_store import create_capsule_from_candidate
                    from doofus.meta.gep.event_emitter import emit as gep_emit

                    create_capsule_from_candidate(c, float(scores["score_total"]), conn=conn)
                    gep_emit(
                        "full_promotion",
                        {"candidate_id": c["candidate_id"], "score": scores["score_total"]},
                        conn=conn,
                    )
                    step.sqlite_write_count += 2
                    step.artifact_write_count += 2
                except Exception as exc:
                    pipeline_warn("gep", "promotion capsule/event failed", exc=exc)
            elif promo.get("shadow_promoted"):
                shadow_d = 1
                c["status"] = "shadow_promoted"
                record_debt(
                    c["candidate_id"],
                    proof_debt=promo.get("proof_debt", False),
                    arena_debt=promo.get("arena_debt", False),
                )
                try_shadow_elite(c, scores, promo)
                conn.execute(
                    "INSERT INTO rejections (candidate_id, reason, created_at) VALUES (?,?,?)",
                    (c["candidate_id"], "shadow_promoted_pending_proof", utc_now()),
                )
                c["rejection_reason"] = "shadow_promoted_pending_proof"
                step.sqlite_write_count = 1
                step.artifact_write_count = 2
            else:
                rejected_d = 1
                reason_r = rej or promo.get("promotion_status", "below_threshold")
                if promo.get("proof_debt"):
                    reason_r = "proof_density_gate"
                elif promo.get("arena_debt"):
                    reason_r = "arena_support_gate"
                score_total = float(scores.get("score_total") or 0)
                if high_score_rescue_mode() and score_total >= 0.72 and float(scores.get("score_safety") or 0) >= 0.99:
                    from doofus.proof.proof_builder_queue import enqueue

                    enqueue(
                        c["candidate_id"],
                        score=score_total,
                        reason=reason_r,
                        generation=int(c.get("generation") or generation),
                    )
                    c["status"] = "rejected"
                    c["rejection_reason"] = reason_r + "_queued_for_proof_builder"
                    step.artifact_write_count = 2
                else:
                    conn.execute(
                        "INSERT INTO rejections (candidate_id, reason, created_at) VALUES (?,?,?)",
                        (c["candidate_id"], reason_r, utc_now()),
                    )
                    c["status"] = "rejected"
                    c["rejection_reason"] = reason_r
                    step.sqlite_write_count = 1
            step.output_size = 1

        with scoring_step(
            scorer_name="candidate_persist",
            scorer_module="doofus.supervisor.metrics_writer",
            substep="upsert_candidate",
            input_size=1,
        ) as step:
            upsert_candidate(conn, c, scores, promo)
            step.sqlite_write_count = 1

        with scoring_step(
            scorer_name="aevolve_feedback",
            scorer_module="doofus.mutation.candidate_generator",
            substep="record_candidate_outcome",
            input_size=1,
        ) as step:
            record_candidate_outcome(
                c,
                promoted=bool(promo.get("promoted")),
                shadow=bool(promo.get("shadow_promoted")),
            )
            step.artifact_write_count = 1

        with scoring_step(
            scorer_name="gepa_trace",
            scorer_module="doofus.meta.gepa.gepa_hooks",
            substep="on_candidate_scored",
            input_size=len(scores),
        ) as step:
            on_candidate_scored(
                generation=generation,
                candidate=c,
                scores=scores,
                baseline=new_baseline,
                rejection_reason=c.get("rejection_reason") or "",
                arena_results=arena,
                traits_before=traits_before,
                conn=conn,
            )
            step.sqlite_write_count = 1
            step.artifact_write_count = 1
        candidate_step.output_size = len(scores)
        c["metacognitive_score_total"] = float(scores.get("score_total") or 0.0)
        return c, promo, promoted_d, shadow_d, rejected_d, new_baseline


def run_one_cycle(*, dry_run: bool = False, live_model_if_available: bool = False) -> dict:
    bootstrap_autonomous_runtime()
    ok, reason = check_may_proceed()
    if not ok and not dry_run:
        return {"classification": "DOOFUS_CYCLE_SKIPPED", "reason": reason}

    _ensure_db()
    cfg = DoofusConfig.from_env()
    cp = load_checkpoint()
    baseline_checkpoint = dict(cp)
    generation = int(cp.get("generation", 0)) + 1
    baseline = float(cp.get("baseline_score", 0.5))
    cycle_start_baseline = baseline
    run_id = cp.get("run_id") or str(uuid.uuid4())[:12]

    init_ctx = CycleInitContext(
        generation=generation,
        baseline_checkpoint=baseline_checkpoint,
        run_id=run_id,
        dry_run=dry_run,
        live_model_if_available=live_model_if_available,
        model_mode=cfg.model_mode,
        one_cycle_approved=bool(os.environ.get("DOOFUS_OPERATOR_APPROVED_ONE_CYCLE") == "1"),
    )
    init_ctx.__enter__()

    init_ctx.step_start("cycle_init_checkpoint_start")
    finalize_checkpoint(
        generation=generation,
        baseline_score=baseline,
        run_id=run_id,
        phase="started",
    )
    write_checkpoint("init", {"generation": generation, "run_id": run_id})
    init_ctx.step_end("cycle_init_checkpoint_end")
    emit_heartbeat("cycle_start", {"generation": generation})
    last_progress_heartbeat = time.perf_counter()
    current_phase = "init"
    phase_started_perf = time.perf_counter()
    phase_started_at = utc_now()
    phase_checkpoint_before = load_checkpoint()

    def begin_phase(name: str) -> None:
        nonlocal current_phase, phase_started_perf, phase_started_at, phase_checkpoint_before
        init_ctx.check(name)
        current_phase = name
        phase_started_perf = time.perf_counter()
        phase_started_at = utc_now()
        phase_checkpoint_before = load_checkpoint()

    def finish_phase() -> None:
        checkpoint_after = load_checkpoint()
        finalize_phase_or_raise(
            generation=generation,
            phase=current_phase,
            phase_started_at=phase_started_at,
            phase_ended_at=utc_now(),
            duration_ms=(time.perf_counter() - phase_started_perf) * 1000.0,
            checkpoint_before=phase_checkpoint_before,
            checkpoint_after=checkpoint_after,
            heartbeat_age_ms=(time.perf_counter() - last_progress_heartbeat) * 1000.0,
        )

    def enforce_phase_timeout() -> None:
        init_ctx.check(current_phase)
        duration_ms = (time.perf_counter() - phase_started_perf) * 1000.0
        limit_seconds = phase_timeout_seconds(current_phase)
        if duration_ms <= limit_seconds * 1000.0:
            return
        if current_phase == "scoring":
            record_scoring_timeout(
                error_type="SupervisorPhaseTimeout",
                error_message_sanitized=f"{current_phase} exceeded {limit_seconds:.1f}s",
            )
        record_phase_event(
            generation=generation,
            phase=current_phase,
            status="timeout",
            timeout=True,
            phase_started_at=phase_started_at,
            phase_ended_at=utc_now(),
            duration_ms=duration_ms,
            checkpoint_before=phase_checkpoint_before,
            checkpoint_after=load_checkpoint(),
            heartbeat_age_ms=(time.perf_counter() - last_progress_heartbeat) * 1000.0,
            error_type="SupervisorPhaseTimeout",
            error_message_sanitized=f"{current_phase} exceeded {limit_seconds:.1f}s",
        )
        raise SupervisorPhaseTimeout(
            phase=current_phase,
            duration_ms=duration_ms,
            limit_seconds=limit_seconds,
        )

    def report_inline_rescue_progress(stage: str, detail: dict) -> None:
        nonlocal last_progress_heartbeat
        init_ctx.check(f"inline_rescue_{stage}")
        write_checkpoint("inline_rescue_progress", {"stage": stage, **detail})
        last_progress_heartbeat = _emit_cycle_progress(
            generation=generation,
            stage=f"inline_rescue_{stage}",
            last_heartbeat_at=last_progress_heartbeat,
            force=True,
            **detail,
        )

    init_ctx.step_start("cycle_init_provider_gate_start")
    init_ctx.step_start("cycle_init_provider_readiness_start")
    model_result: dict = {}
    gate: dict = {}
    model_context: dict = {}
    inline_rescue_result: dict = {}
    pressure: dict = {}
    candidate_count = 0
    candidates: list[dict] = []
    promoted = shadow = rejected = 0
    scored: list[dict] = []
    partial_cycle = False
    metacognitive_early_termination_reason = ""
    evolution_snap: dict = {}
    compounding: dict = {}
    route: dict = {"provider_selected": "unknown"}
    try:
        route = run_bounded_init_call(
            init_ctx,
            step="cycle_init_provider_readiness",
            func=resolve_provider,
        )
        init_ctx.provider = str(route.get("provider_selected") or "")
        init_ctx.model_name = str(route.get("model_name") or "")
        init_ctx.step_end(
            "cycle_init_provider_readiness_end",
            decision=str(route.get("auth_status") or ""),
        )
        init_ctx.step_end(
            "cycle_init_provider_gate_end",
            provider=init_ctx.provider,
            model=init_ctx.model_name,
        )
        model_result = {
            "classification": "DOOFUS_MODEL_SKIPPED",
            "mode": cfg.model_mode,
            "provider": route.get("provider_selected"),
        }
        if not dry_run and proof_builder_mode():
            init_ctx.step_start("cycle_init_champion_defense_start")
            init_ctx.step_end(
                "cycle_init_champion_defense_end",
                decision="inline_rescue_only_no_kpi_snapshot",
            )
            begin_phase("inline_rescue")
            try:
                inline_rescue_result = run_bounded_init_call(
                    init_ctx,
                    step="inline_rescue",
                    func=lambda: run_inline_rescue(
                        baseline=baseline,
                        generation=generation,
                        progress_callback=report_inline_rescue_progress,
                        init_phase=True,
                    ),
                )
            except Exception as exc:
                inline_rescue_result = {"classification": "INLINE_RESCUE_ERROR", "error": type(exc).__name__}
                pipeline_warn("inline_rescue", "failed", exc=exc)
                raise
            write_checkpoint("inline_rescue", inline_rescue_result)
            last_progress_heartbeat = _emit_cycle_progress(
                generation=generation,
                stage="inline_rescue_timeout" if inline_rescue_result.get("timed_out") else "inline_rescue_complete",
                last_heartbeat_at=last_progress_heartbeat,
                force=True,
                classification=inline_rescue_result.get("classification"),
                elapsed_seconds=inline_rescue_result.get("elapsed_seconds"),
                active=inline_rescue_result.get("active"),
            )
            try:
                finish_phase()
            except SupervisorPhaseTimeout as exc:
                inline_rescue_result = {
                    **inline_rescue_result,
                    "classification": "INLINE_RESCUE_TIMEOUT",
                    "timeout": True,
                    "error_message_sanitized": str(exc),
                }
                write_checkpoint("inline_rescue_timeout", inline_rescue_result)
                last_progress_heartbeat = _emit_cycle_progress(
                    generation=generation,
                    stage="inline_rescue_timeout",
                    last_heartbeat_at=last_progress_heartbeat,
                    force=True,
                    error=str(exc),
                )

        init_ctx.step_start("cycle_init_db_prepare_start")
        begin_phase("candidate_generation")
        pressure = run_bounded_init_call(init_ctx, step="cycle_init_db_prepare", func=prepare_cycle)
        init_ctx.step_end("cycle_init_db_prepare_end")
        init_ctx.mark_candidate_generation_started()
        if pressure.get("candidate_count_next") is not None:
            candidate_count = int(pressure["candidate_count_next"])
        elif pressure.get("candidate_count") is not None:
            candidate_count = int(pressure["candidate_count"])
        else:
            candidate_count = 3
        candidates = filter_retired_parents(
            generate_cycle_candidates(generation, count=candidate_count)
        )
        init_ctx.mark_candidates_created()
        write_checkpoint("candidates_generated", {
            "count": len(candidates),
            "pressure": pressure,
            "with_lineage": sum(1 for c in candidates if c.get("parent_id")),
        })
        last_progress_heartbeat = _emit_cycle_progress(
            generation=generation,
            stage="candidates_generated",
            last_heartbeat_at=last_progress_heartbeat,
            force=True,
            candidate_count=len(candidates),
        )
        finish_phase()

        begin_phase("model_call")
        model_context = _resolve_model_context(generation, baseline, pressure, candidate_count)
        gate = may_call_model(live_requested=live_model_if_available and not dry_run)
        model_started = time.perf_counter()
        try:
            if dry_run or not live_model_if_available or cfg.model_mode == "dry_run":
                model_result = _provider_propose_mutations_for_cycle(
                    model_context,
                    force_dry_run=not live_model_if_available,
                )
                model_result["attempted"] = True
                write_checkpoint("model_dry_run", {
                    "classification": model_result.get("classification"),
                    "provider": route.get("provider_selected"),
                })
                model_result, candidates = _apply_model_proposal(model_result, candidates, generation)
                last_progress_heartbeat = _emit_cycle_progress(
                    generation=generation,
                    stage="model_dry_run_complete",
                    last_heartbeat_at=last_progress_heartbeat,
                    force=True,
                    classification=model_result.get("classification"),
                    proposals_returned=model_result.get("proposals_returned"),
                )
            elif gate["allowed"] and not dry_run:
                model_result = provider_propose_mutations(model_context)
                model_result["attempted"] = True
                model_result["provider_selected"] = route.get("provider_selected")
                write_checkpoint("model_call", {
                    "classification": model_result.get("classification"),
                    "mode": model_result.get("mode"),
                    "provider": route.get("provider_selected"),
                })
                if model_result.get("error"):
                    write_checkpoint("model_error", {"error": redact_secrets(str(model_result["error"]))[:200]})
                model_result, candidates = _apply_model_proposal(model_result, candidates, generation)
                last_progress_heartbeat = _emit_cycle_progress(
                    generation=generation,
                    stage="model_call_complete",
                    last_heartbeat_at=last_progress_heartbeat,
                    force=True,
                    classification=model_result.get("classification"),
                    proposals_returned=model_result.get("proposals_returned"),
                )
            elif live_model_if_available and not dry_run:
                model_result = {
                    "classification": "DOOFUS_MODEL_GATE_BLOCKED",
                    "reason": gate.get("reason"),
                    "mode": gate.get("mode", "dry_run"),
                    "attempted": False,
                    "skipped": True,
                    "skip_reason": gate.get("reason"),
                }
                write_checkpoint("model_call_blocked", model_result)
                last_progress_heartbeat = _emit_cycle_progress(
                    generation=generation,
                    stage="model_call_blocked",
                    last_heartbeat_at=last_progress_heartbeat,
                    force=True,
                    reason=model_result.get("reason"),
                )
        except Exception as exc:
            model_result = {
                "classification": "DOOFUS_MODEL_ERROR",
                "error": type(exc).__name__,
                "attempted": True,
                "skip_reason": "provider_exception",
            }
            pipeline_warn("model_call", "provider failed", exc=exc)
            write_checkpoint("model_error", model_result)
            raise
        model_result["duration_ms"] = round((time.perf_counter() - model_started) * 1000.0, 2)
        finish_phase()

        begin_phase("scoring")
        conn = connect_metrics_db()
        scoring_cycle_token = bind_cycle(
            generation=generation,
            cycle_id=run_id,
            candidate_count=len(candidates),
            batch_id="scoring",
        )
        record_scoring_event(
            scorer_name="scoring_loop",
            scorer_module="doofus.supervisor.doofus_loop_runner",
            substep="scoring_phase",
            event_type="start",
            candidate_count=len(candidates),
        )
        try:
            may_run, _ = check_may_proceed()
            total_candidates = len(candidates)
            for idx, c in enumerate(candidates, start=1):
                enforce_phase_timeout()
                if not dry_run and not may_run:
                    partial_cycle = True
                    break
                traits_before = list(c.get("traits") or [])
                candidate_token = bind_candidate(
                    candidate_id=c["candidate_id"],
                    candidate_index=idx,
                    candidate_count=total_candidates,
                )
                if c.get("parent_id"):
                    log_mutation(conn, c["candidate_id"], c.get("mutation_type", "trait_mutation"))
                try:
                    c, _promo, p_d, s_d, r_d, baseline = _score_one_candidate(
                        conn, c,
                        generation=generation,
                        baseline=baseline,
                        dry_run=dry_run,
                        traits_before=traits_before,
                    )
                    promoted += p_d
                    shadow += s_d
                    rejected += r_d
                    scored.append(c)
                    metacognitive_early_termination_reason = online_termination_reason(
                        [float(item.get("metacognitive_score_total") or 0.0) for item in scored],
                        cycle_start_baseline,
                    )
                except Exception as exc:
                    rejected += 1
                    pipeline_warn("candidate_score", f"{c.get('candidate_id')} failed", exc=exc)
                    c["status"] = "error"
                    c["rejection_reason"] = f"pipeline_error:{type(exc).__name__}"
                    upsert_candidate(conn, c, {"score_total": 0}, {"promotion_status": "rejected"})
                    scored.append(c)
                heartbeat_before = last_progress_heartbeat
                last_progress_heartbeat = _emit_cycle_progress(
                    generation=generation,
                    stage="scoring",
                    last_heartbeat_at=last_progress_heartbeat,
                    completed=idx,
                    total=total_candidates,
                    promoted=promoted,
                    rejected=rejected,
                    partial=partial_cycle,
                )
                record_scoring_progress(
                    scorer_name="scoring_loop",
                    scorer_module="doofus.supervisor.doofus_loop_runner",
                    substep="candidate_progress",
                    heartbeat_written=last_progress_heartbeat != heartbeat_before,
                    input_size=idx,
                    output_size=total_candidates,
                )
                reset_candidate(candidate_token)
                enforce_phase_timeout()
                if metacognitive_early_termination_reason:
                    write_checkpoint(
                        "metacognitive_early_termination",
                        {
                            "generation": generation,
                            "completed": idx,
                            "total": total_candidates,
                            "reason": metacognitive_early_termination_reason,
                        },
                    )
                    break

            enforce_phase_timeout()
            record_scoring_progress(
                scorer_name="scoring_loop",
                scorer_module="doofus.supervisor.doofus_loop_runner",
                substep="pre_checkpoint_finalization",
                heartbeat_written=False,
                input_size=len(scored),
                output_size=promoted + shadow + rejected,
            )
            write_checkpoint("scoring_complete", {"promoted": promoted, "shadow": shadow, "rejected": rejected, "partial": partial_cycle})
            last_progress_heartbeat = _emit_cycle_progress(
                generation=generation,
                stage="scoring_complete",
                last_heartbeat_at=last_progress_heartbeat,
                force=True,
                promoted=promoted,
                shadow=shadow,
                rejected=rejected,
                partial=partial_cycle,
            )
            enforce_phase_timeout()
            evolution_snap = after_cycle(generation=generation, promoted=promoted, scored=scored, partial=partial_cycle)
            compounding = after_compounding_cycle(promoted=promoted, generation=generation)
            write_checkpoint("evolution_pressure", evolution_snap)
            write_checkpoint("autonomous_compounding", compounding)
            conn.execute(
                "INSERT INTO cycles (run_id, generation, created_at) VALUES (?,?,?)",
                (run_id, generation, utc_now()),
            )
            conn.commit()
            record_scoring_event(
                scorer_name="scoring_loop",
                scorer_module="doofus.supervisor.doofus_loop_runner",
                substep="scoring_phase",
                event_type="end",
                candidate_count=total_candidates,
                output_size=len(scored),
            )
        except Exception as exc:
            conn.rollback()
            pipeline_warn("cycle_db", "transaction rolled back", exc=exc)
            raise
        finally:
            reset_cycle(scoring_cycle_token)
            conn.close()
        record_online_observation(
            metacognition_target_id(),
            generation,
            [float(item.get("metacognitive_score_total") or 0.0) for item in scored],
            metacognitive_early_termination_reason,
        )
        finish_phase()

        finalize_checkpoint(
            generation=generation,
            baseline_score=baseline,
            run_id=run_id,
            phase="complete",
        )
        doofus_paths.ARTIFACTS.mkdir(parents=True, exist_ok=True)

        cls = "DOOFUS_CYCLE_COMPLETE"
        if metacognitive_early_termination_reason:
            cls = "DOOFUS_CYCLE_METACOGNITIVE_EARLY_TERMINATION"
        elif partial_cycle:
            cls = "DOOFUS_CYCLE_PARTIAL"
        elif live_model_if_available and model_result.get("classification") == "DOOFUS_MODEL_LIVE":
            cls = "B1003_LIVE_MODEL_CYCLE_PASS"
        elif live_model_if_available and model_result.get("classification") in (
            "DOOFUS_MODEL_DRY_RUN", "DOOFUS_MODEL_GATE_BLOCKED",
        ):
            cls = "B1003_LIVE_MODEL_CYCLE_DRY_RUN_FALLBACK"
        elif live_model_if_available and model_result.get("classification") == "DOOFUS_MODEL_ERROR":
            cls = "B1003_LIVE_MODEL_CYCLE_PASS_WITH_NOTES"

        from doofus.proof.proof_builder_queue import queue_summary

        queued_pb = 0
        try:
            qs = queue_summary()
            by_gen = qs.get("by_generation") or {}
            queued_pb = int(by_gen.get(str(generation), 0))
            queued_pb += sum(
                1
                for c in scored
                if c.get("rejection_reason") and "queued_for_proof_builder" in str(c.get("rejection_reason"))
            )
        except Exception:
            queued_pb = sum(
                1
                for c in scored
                if c.get("rejection_reason") and "queued_for_proof_builder" in str(c.get("rejection_reason"))
            )

        result = build_live_cycle_report({
            "classification": cls,
            "run_id": run_id,
            "generation": generation,
            "candidates": len(scored),
            "promoted": promoted,
            "shadow_promoted": shadow,
            "rejected": rejected,
            "queued_for_proof_builder": queued_pb,
            "queued_for_proof_builder_count": queued_pb,
            "partial": partial_cycle,
            "metacognitive_early_termination_reason": metacognitive_early_termination_reason,
            "evolution": evolution_snap,
            "compounding": compounding,
            "inline_rescue": inline_rescue_result,
            "baseline_score": baseline,
            "lineage": build_lineage(scored),
            "lineage_parents": sum(1 for c in scored if c.get("parent_id")),
            "model_mode": cfg.model_mode,
            "model_result": {
                k: redact_secrets(str(v)) if isinstance(v, str) else v
                for k, v in model_result.items()
            },
            "dry_run": dry_run,
            "live_model_if_available": live_model_if_available,
            "gate": gate if live_model_if_available else {},
            "generated_at": utc_now(),
        })["cycle"]
        write_checkpoint("cycle_complete", {"classification": cls, "generation": generation})
        emit_heartbeat("cycle_complete", {
            "generation": generation, "promoted": promoted, "shadow": shadow, "rejected": rejected,
        })

        begin_phase("kpi_refresh")
        try:
            from doofus.reports.sota_kpi_tracker import maybe_refresh_kpi_snapshot, record_cycle_model_event

            record_scoring_progress(
                scorer_name="kpi_refresh",
                scorer_module="doofus.reports.sota_kpi_tracker",
                substep="before_kpi_export",
                heartbeat_written=False,
                input_size=len(scored),
                output_size=promoted,
            )
            record_cycle_model_event(
                generation,
                model_result,
                run_id=run_id,
                route=route,
                gate=gate,
                model_context=model_context,
                cfg=cfg,
                candidates=candidates,
                scored=scored,
            )
            maybe_refresh_kpi_snapshot(every_n_cycles=3, generation=generation)
        except Exception as exc:
            record_phase_event(
                generation=generation,
                phase="kpi_refresh",
                status="error",
                phase_started_at=phase_started_at,
                phase_ended_at=utc_now(),
                duration_ms=(time.perf_counter() - phase_started_perf) * 1000.0,
                checkpoint_before=phase_checkpoint_before,
                checkpoint_after=load_checkpoint(),
                heartbeat_age_ms=(time.perf_counter() - last_progress_heartbeat) * 1000.0,
                error_type=type(exc).__name__,
                error_message_sanitized=str(exc),
            )
        else:
            finish_phase()
        return result

    except SupervisorPhaseTimeout as exc:
        finalize_checkpoint(
            generation=generation,
            baseline_score=baseline,
            run_id=run_id,
            phase="timeout_with_reason",
            timeout_phase=exc.phase,
            error_type="SupervisorPhaseTimeout",
            error_message_sanitized=str(exc),
        )
        write_checkpoint("cycle_timeout", {"generation": generation, "phase": exc.phase, "error": str(exc)})
        emit_heartbeat("cycle_timeout", {"generation": generation, "phase": exc.phase})
        return _failure_cycle_result(
            classification="DOOFUS_CYCLE_TIMEOUT",
            generation=generation,
            run_id=run_id,
            baseline=baseline,
            phase=exc.phase,
            error_type="SupervisorPhaseTimeout",
            error_message=str(exc),
            model_result=model_result,
            gate=gate,
            model_context=model_context,
            cfg=cfg,
            inline_rescue_result=inline_rescue_result,
            dry_run=dry_run,
            live_model_if_available=live_model_if_available,
        )
    except CycleInitTimeout as exc:
        emit_heartbeat("cycle_init_timeout", {"generation": generation, "step": exc.step})
        return init_ctx.build_timeout_result(exc, inline_rescue_result=inline_rescue_result)
    except KeyboardInterrupt as exc:
        finalize_checkpoint(
            generation=generation,
            baseline_score=baseline,
            run_id=run_id,
            phase="interrupted_with_reason",
            failure_phase=current_phase,
            error_type="KeyboardInterrupt",
            error_message_sanitized=str(exc),
        )
        write_checkpoint("cycle_interrupted", {"generation": generation, "phase": current_phase})
        emit_heartbeat("cycle_interrupted", {"generation": generation, "phase": current_phase})
        return _failure_cycle_result(
            classification="DOOFUS_CYCLE_INTERRUPTED",
            generation=generation,
            run_id=run_id,
            baseline=baseline,
            phase=current_phase,
            error_type="KeyboardInterrupt",
            error_message=str(exc),
            model_result=model_result,
            gate=gate,
            model_context=model_context,
            cfg=cfg,
            inline_rescue_result=inline_rescue_result,
            dry_run=dry_run,
            live_model_if_available=live_model_if_available,
        )
    except Exception as exc:
        record_phase_event(
            generation=generation,
            phase=current_phase,
            status="error",
            phase_started_at=phase_started_at,
            phase_ended_at=utc_now(),
            duration_ms=(time.perf_counter() - phase_started_perf) * 1000.0,
            checkpoint_before=phase_checkpoint_before,
            checkpoint_after=load_checkpoint(),
            heartbeat_age_ms=(time.perf_counter() - last_progress_heartbeat) * 1000.0,
            error_type=type(exc).__name__,
            error_message_sanitized=str(exc),
        )
        finalize_checkpoint(
            generation=generation,
            baseline_score=baseline,
            run_id=run_id,
            phase="failed_with_reason",
            failure_phase=current_phase,
            error_type=type(exc).__name__,
            error_message_sanitized=str(exc),
        )
        write_checkpoint("cycle_failed", {"generation": generation, "phase": current_phase, "error": type(exc).__name__})
        emit_heartbeat("cycle_failed", {"generation": generation, "phase": current_phase, "error": type(exc).__name__})
        return _failure_cycle_result(
            classification="DOOFUS_CYCLE_FAILED",
            generation=generation,
            run_id=run_id,
            baseline=baseline,
            phase=current_phase,
            error_type=type(exc).__name__,
            error_message=str(exc),
            model_result=model_result,
            gate=gate,
            model_context=model_context,
            cfg=cfg,
            inline_rescue_result=inline_rescue_result,
            dry_run=dry_run,
            live_model_if_available=live_model_if_available,
        )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--live-model-if-available", action="store_true")
    args = p.parse_args()
    doc = run_one_cycle(dry_run=args.dry_run, live_model_if_available=args.live_model_if_available)
    print(doc["classification"], doc.get("generation"), doc.get("promoted"), doc.get("rejected"))
    skipped = doc.get("classification") in ("DOOFUS_CYCLE_SKIPPED",)
    failed = doc.get("classification") in (
        "DOOFUS_CYCLE_TIMEOUT",
        "DOOFUS_CYCLE_FAILED",
        "DOOFUS_CYCLE_INTERRUPTED",
        "DOOFUS_CYCLE_INIT_TIMEOUT_ABORTED",
    )
    if skipped:
        return 1
    if failed:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
