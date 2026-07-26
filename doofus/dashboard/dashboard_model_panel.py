"""Model panel data."""
from __future__ import annotations
from doofus.model_router.model_environment_probe import probe_model_environment
from doofus.safety.budget_guard import check_budget
from doofus.core.doofus_config import DoofusConfig

def model_panel() -> dict:
    return {"environment": probe_model_environment(), "budget": check_budget(DoofusConfig.from_env())}
