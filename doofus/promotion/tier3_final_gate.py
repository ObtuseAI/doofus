# -*- coding: utf-8 -*-
"""Tier 3 final gate - optional high-score promotion finals (feature-flagged)."""
from __future__ import annotations

import json
import os

from doofus.core.atomic_json import load_json, save_json
from doofus.core.doofus_paths import STATE
from doofus.core.doofus_events import utc_now

TIER3_STATE = STATE / "tier3_finals.json"
TIER3_RESULTS = STATE / "tier3" / "results.jsonl"

VALID_VERDICTS = {
    "promotion_validated",
    "promotion_validated_with_notes",
}


def tier3_min_score() -> float:
    return float(os.environ.get("DOOFUS_TIER3_MIN_SCORE", "0.85"))


def tier3_enabled() -> bool:
    return os.environ.get("DOOFUS_TIER3_ENABLED", "0") == "1"


def tier3_agentbench_enabled() -> bool:
    return os.environ.get("DOOFUS_TIER3_AGENTBENCH_ENABLED", "0") == "1"


def tier3_gittask_enabled() -> bool:
    return os.environ.get("DOOFUS_TIER3_GITTASK_ENABLED", "0") == "1"


def tier3_agency_enabled() -> bool:
    return os.environ.get("DOOFUS_TIER3_AGENCY_ENABLED", "0") == "1"


def requires_tier3(score_total: float) -> bool:
    return float(score_total) >= tier3_min_score()


def _load_state() -> dict:
    data = load_json(TIER3_STATE, default={"pending": [], "completed": []})
    if not isinstance(data, dict):
        return {"pending": [], "completed": []}
    data.setdefault("pending", [])
    data.setdefault("completed", [])
    return data


def _save_state(state: dict) -> None:
    save_json(TIER3_STATE, state)


def _append_result(record: dict) -> None:
    TIER3_RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with TIER3_RESULTS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def _arena_wins(arena_results: list[dict] | None) -> int:
    return sum(
        1
        for a in (arena_results or [])
        if str(a.get("result", "")).lower() in ("win", "pass", "ok")
    )


def _inline_audit(
    candidate: dict,
    scores: dict,
    *,
    baseline: float = 0.5,
    arena_results: list[dict] | None = None,
    gate_checks: dict | None = None,
) -> dict:
    """Same-cycle audit using gate results already computed (candidate not in DB yet)."""
    gate_checks = gate_checks or {}
    score_total = float(scores.get("score_total") or 0)
    safety_ok = float(scores.get("score_safety") or 0) >= 0.99
    replay_ok = bool(gate_checks.get("replay_passed", scores.get("score_replay", 0) >= 0.45))
    proof_ok = bool(gate_checks.get("proof_density_passed", False))
    arena_ok = bool(gate_checks.get("arena_support_passed", False))
    wins = _arena_wins(arena_results)

    if not safety_ok or not replay_ok:
        verdict = "promotion_unreplayable"
    elif not proof_ok:
        verdict = "promotion_missing_proof"
    elif not arena_ok:
        verdict = "promotion_weak"
    elif score_total <= baseline:
        verdict = "promotion_weak"
    elif wins > 0:
        verdict = "promotion_validated"
    else:
        verdict = "promotion_validated_with_notes"

    return {
        "candidate_id": candidate.get("candidate_id"),
        "score_total": score_total,
        "verdict": verdict,
        "gate_would_promote": verdict in VALID_VERDICTS,
        "arena_support": arena_ok,
        "proof_exists": proof_ok,
        "replay_passed": replay_ok,
        "arena_wins": wins,
        "tier3_mode": "inline_gate_audit",
    }


def _db_audit(candidate: dict, scores: dict, *, baseline: float = 0.5) -> dict | None:
    """Post-hoc DB audit when candidate already persisted."""
    import sqlite3

    from doofus.core.doofus_paths import METRICS_DB
    from doofus.core.doofus_state import init_db
    from doofus.scoring.promotion_audit import audit_single_promotion

    init_db()
    conn = sqlite3.connect(METRICS_DB, timeout=5.0)
    try:
        row = conn.execute(
            "SELECT candidate_id FROM candidates WHERE candidate_id = ?",
            (candidate.get("candidate_id"),),
        ).fetchone()
        if not row:
            return None
        audit = audit_single_promotion(
            conn,
            {"candidate_id": candidate["candidate_id"], "created_at": utc_now()},
            baseline_score=baseline,
        )
    finally:
        conn.close()
    audit["score_total"] = float(scores.get("score_total") or 0)
    audit["tier3_mode"] = "db_replay_audit"
    return audit


def _external_harness_status() -> dict:
    enabled = (
        tier3_agentbench_enabled(),
        tier3_gittask_enabled(),
        tier3_agency_enabled(),
    )
    return {
        "agentbench": enabled[0],
        "gittask": enabled[1],
        "agency": enabled[2],
        "any_enabled": any(enabled),
    }


def run_tier3_final_gate(
    candidate: dict,
    scores: dict,
    *,
    arena_results: list[dict] | None = None,
    baseline: float = 0.5,
    gate_checks: dict | None = None,
) -> dict:
    """Evaluate Tier 3 final gate for high-score candidates."""
    score_total = float(scores.get("score_total") or 0)
    cid = candidate.get("candidate_id", "unknown")
    record = {
        "candidate_id": cid,
        "score_total": score_total,
        "evaluated_at": utc_now(),
        "tier3_enabled": tier3_enabled(),
        "harnesses": _external_harness_status(),
        "arena_count": len(arena_results or []),
    }

    if not requires_tier3(score_total):
        record.update({"passed": True, "classification": "TIER3_NOT_REQUIRED", "reason": "below_min_score"})
        _append_result(record)
        return record

    audit = _db_audit(candidate, scores, baseline=baseline) or _inline_audit(
        candidate, scores, baseline=baseline, arena_results=arena_results, gate_checks=gate_checks,
    )
    record["audit_verdict"] = audit.get("verdict")
    record["audit"] = {k: audit.get(k) for k in ("verdict", "gate_would_promote", "arena_support", "proof_exists")}
    record["audit_mode"] = audit.get("tier3_mode")

    if not tier3_enabled():
        record.update({
            "passed": True,
            "classification": "TIER3_AUDIT_ONLY",
            "reason": "tier3_disabled_high_score_logged",
        })
        _append_result(record)
        _record_completion(record)
        return record

    harnesses = _external_harness_status()
    if harnesses["any_enabled"]:
        record.update({
            "passed": False,
            "classification": "TIER3_HARNESS_PENDING",
            "reason": "external_harness_not_implemented",
            "recommendation": "Run AgentBench/GitTaskBench manually; see DOOFUS_TIER3_BENCHMARKS.md",
        })
        state = _load_state()
        if cid not in state["pending"]:
            state["pending"].append(cid)
        _save_state(state)
        _append_result(record)
        return record

    passed = audit.get("verdict") in VALID_VERDICTS
    record.update({
        "passed": passed,
        "classification": "TIER3_LOCAL_PASS" if passed else "TIER3_LOCAL_FAIL",
        "reason": audit.get("verdict") if not passed else "local_audit_passed",
    })
    _append_result(record)
    if passed:
        _record_completion(record)
    else:
        state = _load_state()
        if cid not in state["pending"]:
            state["pending"].append(cid)
        _save_state(state)
    return record


def _record_completion(record: dict) -> None:
    state = _load_state()
    cid = record["candidate_id"]
    state["pending"] = [x for x in state["pending"] if x != cid]
    state["completed"].append({
        "candidate_id": cid,
        "completed_at": utc_now(),
        "classification": record.get("classification"),
    })
    state["completed"] = state["completed"][-100:]
    _save_state(state)


def get_tier3_snapshot() -> dict:
    """Dashboard/report snapshot."""
    state = _load_state()
    return {
        "enabled": tier3_enabled(),
        "min_score": tier3_min_score(),
        "harnesses": _external_harness_status(),
        "pending_count": len(state.get("pending", [])),
        "completed_count": len(state.get("completed", [])),
        "pending": state.get("pending", [])[:20],
        "recent_completed": state.get("completed", [])[-10:],
        "results_file": str(TIER3_RESULTS),
    }
