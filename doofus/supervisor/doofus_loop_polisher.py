"""Loop polish metadata."""
from __future__ import annotations

POLISH_CHECKS = (
    "switch_before_model", "budget_before_model", "rate_before_model",
    "secret_redaction", "proposal_only", "local_validation", "safety_gate",
    "replay_before_promotion", "no_forced_promotion", "checkpoint", "heartbeat",
)
