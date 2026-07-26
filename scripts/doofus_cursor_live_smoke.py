"""Bounded Cursor Composer live smoke using local agent CLI."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(r"C:\sai-auth-doofus")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from doofus.config.cursor_composer_config import cursor_model_id
from doofus.core.doofus_config import DoofusConfig
from doofus.core.doofus_env_loader import load_doofus_env
from doofus.core.doofus_paths import METRICS_DB
from doofus.core.doofus_state import init_db
from doofus.evolution.best_ever_ledger import get_best_ever
from doofus.model_router.cursor_agent_cli import probe_agent_auth, propose_via_agent_cli
from doofus.model_router.model_call_ledger import record_model_event
from doofus.model_router.openrouter_adapter import propose_mutations as openrouter_propose
from doofus.model_router.provider_router import resolve_provider
from doofus.scoring.live_candidate_validator import validate_proposal
from doofus.safety.budget_guard import check_budget
from doofus.supervisor.doofus_crash_recovery import load_checkpoint
from doofus.supervisor.live_model_cycle_gate import may_call_model


def _proposal_count(validation: dict) -> int:
    proposal = validation.get("proposal")
    if isinstance(proposal, dict):
        proposals = proposal.get("proposals")
        if isinstance(proposals, list):
            return len(proposals)
        if proposal:
            return 1
    return 0


def _skip_reason(result: dict, called_agent: bool, used_fallback: bool) -> str:
    if used_fallback:
        return ""
    if called_agent:
        return ""
    if result.get("classification") == "DOOFUS_MODEL_DRY_RUN":
        return "live_smoke_degraded_to_dry_run"
    if result.get("classification") == "DOOFUS_MODEL_GATE_BLOCKED":
        return str(result.get("reason") or "model_gate_blocked")
    if result.get("classification") == "DOOFUS_MODEL_BUDGET_BLOCKED":
        return "budget_blocked"
    if result.get("classification"):
        return str(result.get("classification"))
    return "agent_cli_not_called"


def _record_smoke_event(
    *,
    generation: int,
    route: dict,
    gate: dict,
    auth: dict,
    result: dict,
    validation: dict,
    budget: dict,
    timeout_seconds: int,
) -> dict:
    fallback_reason = str(result.get("cursor_fallback_from") or "")
    used_fallback = bool(fallback_reason)
    called_agent = result.get("transport") == "agent_cli" and result.get("mode") == "live"
    proposals_returned = _proposal_count(validation)
    record = record_model_event(
        generation=generation,
        model_result=result,
        run_id=f"cursor-live-smoke-{generation}",
        provider_requested="cursor",
        provider_resolved=str(route.get("provider_selected") or result.get("provider") or ""),
        model_requested=os.environ.get("DOOFUS_CURSOR_MODEL", cursor_model_id()),
        model_resolved=str(result.get("cursor_model") or route.get("model_name") or cursor_model_id()),
        cursor_agent_cli_authenticated=bool(auth.get("logged_in")),
        cursor_api_key_present=bool(os.environ.get("CURSOR_API_KEY", "").strip()),
        prefer_cursor=os.environ.get("DOOFUS_PREFER_CURSOR", "0") == "1",
        hybrid_fallback_enabled=os.environ.get("DOOFUS_CURSOR_HYBRID_FALLBACK", "1") == "1",
        mutation_batch_size=1,
        model_guided_weight=float(os.environ.get("DOOFUS_MODEL_GUIDED_WEIGHT", "0") or 0.0),
        attempted=called_agent or used_fallback or result.get("classification", "").startswith("DOOFUS_CURSOR"),
        skipped=not called_agent and not used_fallback,
        skip_reason=_skip_reason(result, called_agent, used_fallback),
        live=called_agent,
        dry_run=False,
        fallback_used=used_fallback,
        fallback_provider="openrouter" if used_fallback else "",
        fallback_reason=fallback_reason,
        proposals_requested=1,
        proposals_returned=proposals_returned,
        proposals_applied=0,
        proposal_valid=bool(validation.get("valid")),
        duration_ms=float(result.get("duration_ms") or 0.0),
        budget_gate_status="allowed" if budget.get("ok") else "blocked:budget",
        proof_gate_status="not_applicable_smoke",
        tier3_gate_status="not_applicable_smoke",
    )
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="cursor")
    parser.add_argument("--model", default="composer-2.5")
    parser.add_argument("--transport", default="agent_cli")
    parser.add_argument("--record-event", action="store_true")
    parser.add_argument("--no-promotion", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=90)
    args = parser.parse_args()

    load_doofus_env()
    os.environ["DOOFUS_MODEL_PROVIDER"] = args.provider
    os.environ["DOOFUS_PREFER_CURSOR"] = "1"
    os.environ["DOOFUS_CURSOR_PREFER_AGENT_CLI"] = "1"
    os.environ["DOOFUS_CURSOR_USE_AGENT_CLI"] = "1"
    os.environ["DOOFUS_CURSOR_MODEL"] = args.model
    os.environ["DOOFUS_CURSOR_TIMEOUT_SECONDS"] = str(args.timeout_seconds)

    init_db()
    checkpoint = load_checkpoint()
    best = get_best_ever()
    generation = int(checkpoint.get("generation") or 0)
    route = resolve_provider()
    gate = may_call_model(live_requested=True)
    budget = check_budget(DoofusConfig.from_env())
    auth = probe_agent_auth()
    before_count = sqlite3.connect(METRICS_DB).execute("SELECT COUNT(*) FROM model_call_events").fetchone()[0]

    context = {
        "generation": generation,
        "baseline": float(checkpoint.get("baseline_score") or 0.0),
        "best_ever_score": float(best.get("best_score") or 0.0),
        "stagnation_cycles": 0,
        "pressure_level": 1.0,
        "candidate_count": 1,
        "parent_traits": [],
        "requested_proposals": 1,
        "diagnostic_mode": "cursor_live_smoke",
    }

    started = time.perf_counter()
    raw_result = propose_via_agent_cli(context)
    result: dict
    if raw_result.get("ok"):
        result = {
            "classification": "DOOFUS_MODEL_LIVE",
            "mode": "live",
            "provider": "cursor",
            "transport": "agent_cli",
            "cursor_model": raw_result.get("model", args.model),
            "raw": str(raw_result.get("text") or ""),
        }
    else:
        result = {
            "classification": "DOOFUS_CURSOR_ERROR",
            "mode": "live",
            "provider": "cursor",
            "transport": "agent_cli",
            "cursor_model": raw_result.get("model", args.model),
            "error": str(raw_result.get("error") or "agent_cli_failed"),
            "hint": raw_result.get("hint"),
        }
        if os.environ.get("DOOFUS_CURSOR_HYBRID_FALLBACK", "1") == "1":
            fallback = openrouter_propose(context)
            fallback["cursor_fallback_from"] = result["classification"]
            result = fallback
    result["duration_ms"] = round((time.perf_counter() - started) * 1000.0, 2)

    raw = str(result.get("raw") or json.dumps({"proposals": result.get("proposals") or []}))
    validation = validate_proposal(raw)
    if validation.get("valid"):
        result["proposal_validation"] = validation

    record = None
    if args.record_event:
        record = _record_smoke_event(
            generation=generation,
            route=route,
            gate=gate,
            auth=auth,
            result=result,
            validation=validation,
            budget=budget,
            timeout_seconds=args.timeout_seconds,
        )

    conn = sqlite3.connect(METRICS_DB)
    try:
        after_count = conn.execute("SELECT COUNT(*) FROM model_call_events").fetchone()[0]
        last_row = conn.execute(
            """
            SELECT id, generation, classification, provider, transport, attempted, live, dry_run,
                   success, fallback_used, skip_reason, proposals_returned, proposals_applied,
                   provider_resolved, model_resolved
            FROM model_call_events
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()

    out = {
        "classification": "DOOFUS_CURSOR_LIVE_SMOKE",
        "provider_selected": route.get("provider_selected"),
        "model_selected": route.get("model_name"),
        "agent_auth": {"logged_in": bool(auth.get("logged_in")), "agent_bin": auth.get("agent_bin")},
        "gate": gate,
        "budget": budget,
        "result": {
            "classification": result.get("classification"),
            "provider": result.get("provider"),
            "transport": result.get("transport"),
            "cursor_model": result.get("cursor_model"),
            "fallback_from": result.get("cursor_fallback_from"),
            "error": result.get("error"),
            "duration_ms": result.get("duration_ms"),
            "proposal_valid": bool(validation.get("valid")),
            "proposals_returned": _proposal_count(validation),
        },
        "event_recorded": bool(args.record_event),
        "model_call_events_before": before_count,
        "model_call_events_after": after_count,
        "model_call_event_delta": after_count - before_count,
        "last_event_row": list(last_row) if last_row else None,
        "record_summary": record,
    }
    print(json.dumps(out, indent=2))
    live_success = (
        result.get("classification") == "DOOFUS_MODEL_LIVE"
        and result.get("provider") == "cursor"
        and bool(validation.get("valid"))
        and _proposal_count(validation) >= 1
    )
    return 0 if live_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
