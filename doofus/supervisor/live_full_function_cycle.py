"""Full live model function cycle with guards."""
from __future__ import annotations

import argparse
import json

from doofus.model_router.deepseek_v4_flash_live_proof import run_live_proof
from doofus.supervisor.live_cycle_launch_guard import guarded_live_cycle_launch
from doofus.supervisor.doofus_loop_runner import run_one_cycle
from doofus.safety.on_off_switch import check_may_prepare_one_cycle, check_may_proceed
from doofus.safety.budget_guard import check_budget
from doofus.core.doofus_config import DoofusConfig


def run_full_live_cycle(
    *,
    max_model_calls: int = 2,
    max_cost_usd: float = 0.05,
    operator_approved_one_cycle: bool = False,
) -> dict:
    if operator_approved_one_cycle:
        may, reason = check_may_prepare_one_cycle()
    else:
        may, reason = check_may_proceed()
    budget = check_budget(DoofusConfig.from_env())
    if not may:
        return {"classification": "B1045_FULL_LIVE_CYCLE_BLOCKED", "reason": reason}
    if not budget.get("ok"):
        return {"classification": "B1045_FULL_LIVE_CYCLE_BLOCKED", "reason": "budget"}

    proof = run_live_proof(max_tokens=120, temperature=0.2)
    if proof.get("provider_auth") != "ok":
        return {
            "classification": "B1045_FULL_LIVE_CYCLE_AUTH_BLOCKED",
            "proof": proof.get("classification"),
        }

    launch = guarded_live_cycle_launch(
        requested_live_mode=True,
        one_cycle_only=True,
        run_cycle=run_one_cycle,
        operator_approved_one_cycle=operator_approved_one_cycle,
    )
    if launch.get("classification") == "DOOFUS_LIVE_CYCLE_LAUNCH_GUARD_REFUSED":
        return {
            "classification": "B1045_FULL_LIVE_CYCLE_BLOCKED",
            "reason": launch.get("reason"),
            "proof": proof.get("classification"),
        }
    cycle = launch.get("result", {})
    cls = "B1045_FULL_LIVE_CYCLE_PASS"
    if cycle.get("classification", "").endswith("_WITH_NOTES"):
        cls = "B1045_FULL_LIVE_CYCLE_PASS_WITH_NOTES"
    return {
        "classification": cls,
        "proof": proof.get("classification"),
        "cycle_classification": cycle.get("classification"),
        "generation": cycle.get("generation"),
        "promoted": cycle.get("promoted"),
        "rejected": cycle.get("rejected"),
        "max_model_calls_cap": max_model_calls,
        "max_cost_usd_cap": max_cost_usd,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--max-model-calls", type=int, default=2)
    p.add_argument("--max-cost-usd", type=float, default=0.05)
    args = p.parse_args()
    doc = run_full_live_cycle(max_model_calls=args.max_model_calls, max_cost_usd=args.max_cost_usd)
    print(json.dumps(doc, indent=2))
    return 0 if doc.get("classification", "").startswith("B1045_FULL_LIVE_CYCLE_PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
