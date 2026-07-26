"""Provider-aware live model cycle."""
from __future__ import annotations

import argparse
import json

from doofus.core.doofus_config import DoofusConfig
from doofus.model_router.openai_live_smoke import run_smoke as openai_smoke
from doofus.model_router.provider_result_classifier import classify_cycle
from doofus.model_router.provider_router import resolve_provider
from doofus.safety.budget_guard import check_budget
from doofus.safety.on_off_switch import check_may_prepare_one_cycle, check_may_proceed
from doofus.supervisor.doofus_loop_runner import run_one_cycle
from doofus.supervisor.live_cycle_launch_guard import guarded_live_cycle_launch
from doofus.supervisor.provider_model_gate import may_call_live_provider

_ONE_CYCLE_WRAPPER_CONSUMED = False


def run_provider_aware_cycle(
    *,
    max_model_calls: int = 2,
    max_cost_usd: float = 0.05,
    operator_approved_one_cycle: bool = False,
) -> dict:
    global _ONE_CYCLE_WRAPPER_CONSUMED

    if operator_approved_one_cycle:
        if _ONE_CYCLE_WRAPPER_CONSUMED:
            return {
                "classification": "B1053_PROVIDER_AWARE_LIVE_CYCLE_BLOCKED",
                "reason": "repeated_operator_approved_one_cycle",
            }
        may, reason = check_may_prepare_one_cycle()
    else:
        may, reason = check_may_proceed()
    if not may:
        return {"classification": "B1053_PROVIDER_AWARE_LIVE_CYCLE_BLOCKED", "reason": reason}

    budget = check_budget(DoofusConfig.from_env())
    if not budget.get("ok"):
        return {"classification": "B1053_PROVIDER_AWARE_LIVE_CYCLE_BLOCKED", "reason": "budget"}

    route = resolve_provider()
    provider = route.get("provider_selected", "dry_run")

    if operator_approved_one_cycle:
        cfg = DoofusConfig.from_env()
        if not route.get("live_provider_ready"):
            return {
                "classification": "B1053_PROVIDER_AWARE_LIVE_CYCLE_AUTH_BLOCKED",
                "provider_selected": provider,
                "gate_reason": "no_live_provider",
            }
        if route.get("provider_selected") == "blocked":
            return {
                "classification": "B1053_PROVIDER_AWARE_LIVE_CYCLE_AUTH_BLOCKED",
                "provider_selected": provider,
                "gate_reason": route.get("provider_reason"),
            }
        if cfg.model_mode != "live":
            return {
                "classification": "B1053_PROVIDER_AWARE_LIVE_CYCLE_AUTH_BLOCKED",
                "provider_selected": provider,
                "gate_reason": "model_mode_not_live",
            }
        gate = {
            "allowed": True,
            "provider": provider,
            "model_name": route.get("model_name"),
            "reason": "operator_approved_one_cycle_prepare",
        }
    else:
        gate = may_call_live_provider(live_requested=True)

    smoke = None
    if provider == "openai" and route.get("live_provider_ready"):
        smoke = openai_smoke(max_tokens=120, temperature=0.2)
        if smoke.get("classification", "").endswith("AUTH_BLOCKED"):
            return {
                "classification": "B1053_PROVIDER_AWARE_LIVE_CYCLE_AUTH_BLOCKED",
                "provider_selected": provider,
                "live_provider_ready": False,
                "deepseek_openrouter_ready": False,
            }

    if not gate.get("allowed") and provider not in ("openai", "openrouter"):
        return {
            "classification": "B1053_PROVIDER_AWARE_LIVE_CYCLE_AUTH_BLOCKED",
            "provider_selected": provider,
            "gate_reason": gate.get("reason"),
        }

    if operator_approved_one_cycle:
        _ONE_CYCLE_WRAPPER_CONSUMED = True

    launch = guarded_live_cycle_launch(
        requested_live_mode=True,
        one_cycle_only=True,
        run_cycle=run_one_cycle,
        operator_approved_one_cycle=operator_approved_one_cycle,
    )
    if launch.get("classification") == "DOOFUS_LIVE_CYCLE_LAUNCH_GUARD_REFUSED":
        return {
            "classification": "B1053_PROVIDER_AWARE_LIVE_CYCLE_BLOCKED",
            "reason": launch.get("reason"),
            "provider_selected": provider,
            "live_provider_ready": route.get("live_provider_ready"),
            "deepseek_openrouter_ready": route.get("deepseek_openrouter_ready"),
        }
    cycle = launch.get("result", {})
    cls = classify_cycle(
        provider,
        bool(route.get("live_provider_ready")),
        bool(route.get("deepseek_openrouter_ready")),
        cycle,
    )
    return {
        "classification": cls,
        "provider_selected": provider,
        "model_name": route.get("model_name"),
        "live_provider_ready": route.get("live_provider_ready"),
        "deepseek_openrouter_ready": route.get("deepseek_openrouter_ready"),
        "deepseek_lane_status": route.get("deepseek_lane_status"),
        "cycle_classification": cycle.get("classification"),
        "generation": cycle.get("generation"),
        "promoted": cycle.get("promoted"),
        "rejected": cycle.get("rejected"),
        "smoke_classification": smoke.get("classification") if smoke else None,
        "max_model_calls_cap": max_model_calls,
        "max_cost_usd_cap": max_cost_usd,
        "operator_approved_one_cycle": operator_approved_one_cycle,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--max-model-calls", type=int, default=2)
    p.add_argument("--max-cost-usd", type=float, default=0.05)
    p.add_argument(
        "--operator-approved-one-cycle",
        action="store_true",
        help="Explicit operator approval for exactly one guarded live cycle from stop_requested=true.",
    )
    args = p.parse_args()
    doc = run_provider_aware_cycle(
        max_model_calls=args.max_model_calls,
        max_cost_usd=args.max_cost_usd,
        operator_approved_one_cycle=args.operator_approved_one_cycle,
    )
    print(json.dumps(doc, indent=2))
    return 0 if "PASS" in doc.get("classification", "") else 1


if __name__ == "__main__":
    raise SystemExit(main())
