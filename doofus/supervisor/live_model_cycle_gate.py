"""Gate model calls on switch, budget, rate."""
from __future__ import annotations

import os

from doofus.safety.on_off_switch import check_may_prepare_one_cycle, check_may_proceed
from doofus.safety.budget_guard import check_budget
from doofus.core.doofus_config import DoofusConfig


def may_call_model(*, live_requested: bool = False) -> dict:
    if os.environ.get("DOOFUS_OPERATOR_APPROVED_PROVIDER_SMOKE") == "1":
        ok, reason = check_may_prepare_one_cycle()
    else:
        ok, reason = check_may_proceed()
    cfg = DoofusConfig.from_env()
    budget = check_budget(cfg)
    if not ok:
        return {"allowed": False, "reason": reason, "mode": "blocked"}
    if not budget["ok"]:
        return {"allowed": False, "reason": "budget_or_rate", "mode": "blocked", "budget": budget}
    if live_requested and cfg.model_mode != "live":
        return {"allowed": False, "reason": "no_credentials", "mode": "dry_run"}
    return {"allowed": True, "mode": cfg.model_mode, "budget": budget}
