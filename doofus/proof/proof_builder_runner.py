"""Process proof-builder queue — build evidence and re-evaluate promotion."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time

from doofus.core.doofus_paths import METRICS_DB
from doofus.core.doofus_events import utc_now
from doofus.proof.proof_artifact_builder import build_proof_artifacts
from doofus.proof.proof_builder_queue import (
    pending_entries, update_entry, dequeue, record_success, record_failure, max_retries,
)
from doofus.scoring.promotion_gate import evaluate_promotion
from doofus.evolution.shadow_elite_promoter import try_shadow_elite
from doofus.evolution.shadow_elite_to_full_promotion import try_upgrade_to_full
from doofus.supervisor.metrics_writer import log_arena_results, log_score_components
from doofus.core.pipeline_log import pipeline_warn
from doofus.supervisor.supervisor_phase_watchdog import record_child_timeout


def _item_timeout_seconds() -> float:
    return float(os.environ.get("DOOFUS_PROOF_BUILDER_ITEM_TIMEOUT_SECONDS", "20"))


def _load_candidate(conn: sqlite3.Connection, candidate_id: str) -> tuple[dict | None, dict, list]:
    row = conn.execute(
        "SELECT candidate_id, parent_id, generation, traits, mutation_type, arena_targets, status, score_total FROM candidates WHERE candidate_id=?",
        (candidate_id,),
    ).fetchone()
    if not row:
        return None, {}, []
    c = {
        "candidate_id": row[0], "parent_id": row[1], "generation": row[2],
        "traits": row[3].split(",") if row[3] else [],
        "mutation_type": row[4], "arena_targets": row[5], "status": row[6],
        "score_total": row[7],
    }
    scores = {}
    for r in conn.execute("SELECT metric, value FROM scores WHERE candidate_id=?", (candidate_id,)):
        scores[r[0]] = r[1]
    if row[7] is not None:
        scores["score_total"] = max(float(scores.get("score_total") or 0), float(row[7]))
    arena = [{"candidate_id": r[0], "arena": r[1], "result": r[2]} for r in conn.execute(
        "SELECT candidate_id, arena, result FROM arena_results WHERE candidate_id=?", (candidate_id,)
    )]
    return c, scores, arena


def process_one(candidate_id: str, *, baseline: float = 0.5) -> dict:
    conn = sqlite3.connect(METRICS_DB, timeout=5.0)
    candidate, scores, arena = _load_candidate(conn, candidate_id)
    if not candidate:
        conn.close()
        update_entry(candidate_id, outcome="proof_blocked", last_error="not_found")
        return {"outcome": "proof_blocked"}
    entry = next((e for e in pending_entries(500) if e.get("candidate_id") == candidate_id), {})
    queued_generation = entry.get("generation")
    candidate_generation = candidate.get("generation")
    if queued_generation is not None and candidate_generation is not None and int(queued_generation) != int(candidate_generation):
        conn.close()
        update_entry(
            candidate_id,
            outcome="proof_blocked",
            last_error="generation_mismatch",
            queued_generation=queued_generation,
            candidate_generation=candidate_generation,
        )
        return {
            "candidate_id": candidate_id,
            "outcome": "proof_blocked",
            "error_type": "GenerationMismatch",
            "queued_generation": queued_generation,
            "candidate_generation": candidate_generation,
        }
    scores["_baseline"] = baseline
    built = build_proof_artifacts(candidate, scores, arena_results=arena)
    scores = built["updated_scores"]
    if candidate.get("score_total"):
        scores["score_total"] = max(float(scores.get("score_total") or 0), float(candidate["score_total"]))
    log_arena_results(conn, built["arena_results"])
    log_score_components(conn, candidate_id, scores)
    promo = evaluate_promotion(candidate, scores, baseline, arena_results=built["arena_results"])
    outcome = "proof_partial"
    gates_ok = (
        promo.get("proof_density_passed")
        and promo.get("arena_support_passed")
        and promo.get("replay_passed")
        and float(scores.get("score_safety") or 0) >= 0.99
        and float(scores.get("score_total") or 0) >= 0.72
        and float(scores.get("bloat_penalty") or 0) <= 0.20
    )
    if promo.get("promoted") or (gates_ok and float(scores.get("score_total") or 0) > baseline):
        upgrade = try_upgrade_to_full(candidate, scores, built["arena_results"], baseline=baseline, conn=conn)
        if upgrade.get("upgraded"):
            outcome = "proof_ready"
            record_success()
            dequeue(candidate_id)
        else:
            outcome = "proof_partial"
    elif gates_ok or promo.get("shadow_promoted") or float(scores.get("proof_density_score") or 0) >= 0.45:
        se = try_shadow_elite(candidate, scores, promo)
        if se.get("shadow_elite"):
            conn.execute(
                "UPDATE candidates SET status='shadow_promoted', promotion_status='shadow_promoted' WHERE candidate_id=?",
                (candidate_id,),
            )
            conn.execute(
                "INSERT INTO rejections (candidate_id, reason, created_at) VALUES (?,?,?)",
                (candidate_id, "shadow_elite_proof_builder", utc_now()),
            )
            outcome = "proof_ready"
            record_success()
            dequeue(candidate_id)
        else:
            outcome = "proof_partial"
    else:
        retries = int(entry.get("retries") or 0) + 1
        if retries >= max_retries():
            outcome = "proof_failed"
            record_failure()
            dequeue(candidate_id)
            conn.execute(
                "INSERT INTO rejections (candidate_id, reason, created_at) VALUES (?,?,?)",
                (candidate_id, "proof_builder_failed", utc_now()),
            )
        else:
            update_entry(candidate_id, retries=retries, outcome="proof_partial")
    update_entry(candidate_id, outcome=outcome, proof_density_score=scores.get("proof_density_score"))
    conn.commit()
    conn.close()
    return {"candidate_id": candidate_id, "outcome": outcome, "proof_density_score": scores.get("proof_density_score"), "promo": promo}


def run_process_one_guarded(
    candidate_id: str,
    *,
    baseline: float = 0.5,
    timeout_seconds: float | None = None,
    generation: int = 0,
    phase: str = "proof_builder_item",
) -> dict:
    timeout_seconds = float(timeout_seconds or _item_timeout_seconds())
    code = (
        "import json, sys; "
        "from doofus.proof.proof_builder_runner import process_one; "
        "print(json.dumps(process_one(sys.argv[1], baseline=float(sys.argv[2])), default=str))"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code, candidate_id, str(baseline)],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        update_entry(candidate_id, outcome="proof_timeout", last_error="child_timeout")
        record_child_timeout(
            generation=generation,
            phase=phase,
            timeout_seconds=timeout_seconds,
            detail=f"{candidate_id} timed out",
        )
        pipeline_warn("proof_builder_child", f"{candidate_id} timed out after {timeout_seconds:.1f}s")
        return {
            "candidate_id": candidate_id,
            "outcome": "proof_timeout",
            "error_type": "TimeoutExpired",
            "timeout_seconds": timeout_seconds,
        }
    if proc.returncode != 0:
        update_entry(candidate_id, outcome="proof_error", last_error=f"child_exit_{proc.returncode}")
        pipeline_warn("proof_builder_child", f"{candidate_id} exited with code {proc.returncode}")
        return {
            "candidate_id": candidate_id,
            "outcome": "proof_error",
            "error_type": "ChildExit",
            "returncode": proc.returncode,
        }
    try:
        lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
        payload = json.loads(lines[-1]) if lines else {}
    except (json.JSONDecodeError, IndexError):
        update_entry(candidate_id, outcome="proof_error", last_error="child_json_parse")
        pipeline_warn("proof_builder_child", f"{candidate_id} returned malformed JSON")
        return {
            "candidate_id": candidate_id,
            "outcome": "proof_error",
            "error_type": "ChildJsonParse",
        }
    return payload if isinstance(payload, dict) else {
        "candidate_id": candidate_id,
        "outcome": "proof_error",
        "error_type": "ChildPayloadType",
    }


def run_proof_builder_batch(*, limit: int = 10, baseline: float = 0.5, progress_callback=None, deadline_monotonic: float | None = None) -> dict:
    results = []
    max_item_duration_ms = 0.0
    slowest_item_id = ""
    for idx, entry in enumerate(pending_entries(limit), start=1):
        if deadline_monotonic is not None:
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 1.0:
                if progress_callback:
                    progress_callback(
                        "proof_builder_deadline",
                        {"completed": idx - 1, "total": limit},
                    )
                break
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            if progress_callback:
                progress_callback(
                    "proof_builder_deadline",
                    {"completed": idx - 1, "total": limit},
                )
            break
        timeout_seconds = None
        if deadline_monotonic is not None:
            timeout_seconds = max(0.1, deadline_monotonic - time.monotonic() - 1.0)
        started = time.monotonic()
        result = run_process_one_guarded(entry["candidate_id"], baseline=baseline, timeout_seconds=timeout_seconds)
        duration_ms = round((time.monotonic() - started) * 1000.0, 2)
        result["duration_ms"] = duration_ms
        results.append(result)
        if duration_ms >= max_item_duration_ms:
            max_item_duration_ms = duration_ms
            slowest_item_id = entry["candidate_id"]
        if progress_callback:
            progress_callback(
                "proof_builder_item",
                {
                    "completed": idx,
                    "candidate_id": entry["candidate_id"],
                    "outcome": result.get("outcome"),
                    "duration_ms": duration_ms,
                },
            )
    successes = sum(1 for r in results if r.get("outcome") == "proof_ready")
    failures = sum(1 for r in results if r.get("outcome") == "proof_failed")
    return {
        "processed": len(results),
        "successes": successes,
        "failures": failures,
        "results": results,
        "command_count": len(results),
        "max_item_duration_ms": max_item_duration_ms,
        "slowest_item_id": slowest_item_id,
        "slowest_item_type": "proof_builder_item" if slowest_item_id else "",
    }
