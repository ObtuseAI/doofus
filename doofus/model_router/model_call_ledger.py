# -*- coding: utf-8 -*-
"""Record model call outcomes and events for KPI tracking."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from doofus.core.doofus_events import utc_now
from doofus.core.metrics_db import metrics_conn
from doofus.core.doofus_state import init_db
from doofus.model_router.model_secret_redactor import redact_secrets


def record_call(model: str, provider: str, output: str, tokens_est: int = 0, cost_est: float = 0.0) -> dict:
    init_db()
    h = hashlib.sha256(output.encode("utf-8")).hexdigest()[:16]
    with metrics_conn() as conn:
        conn.execute(
            "INSERT INTO model_calls (model, provider, tokens_est, cost_est, output_hash, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (model, provider, tokens_est, cost_est, h, utc_now()),
        )
    return {"output_hash": h, "recorded_at": utc_now()}


def record_model_event(
    *,
    generation: int,
    model_result: dict[str, Any],
    run_id: str | None = None,
    cycle_id: int | None = None,
    tournament_count: int | None = None,
    provider_requested: str = "",
    provider_resolved: str = "",
    model_requested: str = "",
    model_resolved: str = "",
    cursor_agent_cli_authenticated: bool = False,
    cursor_api_key_present: bool = False,
    prefer_cursor: bool = False,
    hybrid_fallback_enabled: bool = False,
    mutation_batch_size: int = 0,
    model_guided_weight: float = 0.0,
    attempted: bool = False,
    skipped: bool = False,
    skip_reason: str = "",
    live: bool = False,
    dry_run: bool = False,
    fallback_used: bool = False,
    fallback_provider: str = "",
    fallback_reason: str = "",
    proposals_requested: int = 0,
    proposals_returned: int = 0,
    proposals_applied: int = 0,
    proposal_valid: bool = False,
    duration_ms: float = 0.0,
    budget_gate_status: str = "",
    proof_gate_status: str = "",
    tier3_gate_status: str = "",
) -> dict:
    """Persist one model cycle outcome for Composer/fallback KPIs."""
    init_db()
    classification = str(model_result.get("classification") or "")
    transport = str(model_result.get("transport") or model_result.get("provider") or "")
    provider = str(model_result.get("provider") or model_result.get("provider_selected") or "")
    fallback_from = str(model_result.get("cursor_fallback_from") or "")
    cost_est = float(model_result.get("cost_est") or 0.0)
    mode = str(model_result.get("mode") or "")
    error_message = redact_secrets(str(model_result.get("error") or ""))[:500]
    error_type = ""
    if model_result.get("error"):
        error_type = str(model_result.get("classification") or "model_error")
    usable_response = bool(proposal_valid and proposals_returned > 0)
    success = int(
        classification == "DOOFUS_MODEL_LIVE"
        and (usable_response or proposals_applied > 0)
        and not fallback_from
    )
    detail = {
        "generation": generation,
        "run_id": run_id,
        "cycle_id": cycle_id,
        "tournament_count": tournament_count,
        "provider_requested": provider_requested,
        "provider_resolved": provider_resolved,
        "model_requested": model_requested,
        "model_resolved": model_resolved,
        "transport": transport,
        "cursor_agent_cli_authenticated": cursor_agent_cli_authenticated,
        "cursor_api_key_present": cursor_api_key_present,
        "prefer_cursor": prefer_cursor,
        "hybrid_fallback_enabled": hybrid_fallback_enabled,
        "mutation_batch_size": mutation_batch_size,
        "model_guided_weight": model_guided_weight,
        "attempted": attempted,
        "skipped": skipped,
        "skip_reason": skip_reason,
        "live": live,
        "dry_run": dry_run,
        "success": bool(success),
        "fallback_used": fallback_used or bool(fallback_from),
        "fallback_provider": fallback_provider,
        "fallback_reason": fallback_reason or fallback_from,
        "proposals_requested": proposals_requested,
        "proposals_returned": proposals_returned,
        "proposals_applied": proposals_applied,
        "proposal_valid": proposal_valid,
        "error_type": error_type,
        "error_message_sanitized": error_message,
        "duration_ms": round(duration_ms, 2),
        "estimated_cost": cost_est,
        "budget_gate_status": budget_gate_status,
        "proof_gate_status": proof_gate_status,
        "tier3_gate_status": tier3_gate_status,
        "classification": classification,
        "provider": provider,
        "mode": mode,
        "fallback_from": fallback_from,
        "timestamp_utc": utc_now(),
    }
    with metrics_conn() as conn:
        conn.execute(
            """
            INSERT INTO model_call_events (
              generation, classification, provider, transport, mode, fallback_from,
              proposals_applied, proposal_valid, cost_est, success, created_at,
              timestamp_utc, run_id, cycle_id, tournament_count,
              provider_requested, provider_resolved, model_requested, model_resolved,
              cursor_agent_cli_authenticated, cursor_api_key_present, prefer_cursor,
              hybrid_fallback_enabled, mutation_batch_size, model_guided_weight,
              attempted, skipped, skip_reason, live, dry_run, fallback_used,
              fallback_provider, fallback_reason, proposals_requested, proposals_returned,
              error_type, error_message_sanitized, duration_ms, estimated_cost,
              budget_gate_status, proof_gate_status, tier3_gate_status, detail_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                generation,
                classification,
                provider,
                transport,
                mode,
                fallback_from or None,
                proposals_applied,
                int(proposal_valid),
                cost_est,
                success,
                utc_now(),
                detail["timestamp_utc"],
                run_id,
                cycle_id,
                tournament_count,
                provider_requested,
                provider_resolved,
                model_requested,
                model_resolved,
                int(cursor_agent_cli_authenticated),
                int(cursor_api_key_present),
                int(prefer_cursor),
                int(hybrid_fallback_enabled),
                mutation_batch_size,
                model_guided_weight,
                int(attempted),
                int(skipped),
                skip_reason or None,
                int(live),
                int(dry_run),
                int(fallback_used or bool(fallback_from)),
                fallback_provider or None,
                (fallback_reason or fallback_from) or None,
                proposals_requested,
                proposals_returned,
                error_type or None,
                error_message or None,
                round(duration_ms, 2),
                cost_est,
                budget_gate_status or None,
                proof_gate_status or None,
                tier3_gate_status or None,
                json.dumps(detail, default=str),
            ),
        )
    return {
        "recorded_at": utc_now(),
        "generation": generation,
        "classification": classification,
        "success": bool(success),
        "fallback_from": fallback_from or None,
    }


def log_sqlite_health(*, event_type: str, retries: int = 0, latency_ms: float = 0.0, detail: str = "") -> None:
    init_db()
    with metrics_conn() as conn:
        conn.execute(
            "INSERT INTO db_health_events (event_type, retries, latency_ms, detail, created_at) VALUES (?,?,?,?,?)",
            (event_type, retries, latency_ms, detail[:500], utc_now()),
        )
