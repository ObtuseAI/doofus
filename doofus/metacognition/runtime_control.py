"""Dependency-light reader for the currently authorized bounded control."""
from __future__ import annotations

from pathlib import Path

from doofus.config.metacognition_config import bounded_control_enabled
from doofus.core import doofus_paths
from doofus.core.atomic_json import load_json


def state_dir() -> Path:
    return doofus_paths.STATE / "metacognition"


def active_control_file() -> Path:
    return state_dir() / "active_control.json"


def latest_state_file() -> Path:
    return state_dir() / "latest_state.json"


def latest_bundle_file() -> Path:
    return state_dir() / "latest_bundle.json"


def get_active_control() -> dict[str, object] | None:
    if not bounded_control_enabled():
        return None
    payload = load_json(active_control_file(), default={})
    if not isinstance(payload, dict) or not payload.get("active"):
        return None
    decision = payload.get("decision")
    if not isinstance(decision, dict) or not decision.get("authorized"):
        return None
    return payload


def active_candidate_count() -> int | None:
    payload = get_active_control()
    if payload is None:
        return None
    decision = payload["decision"]
    allocation = decision["authorized_allocation"]
    return int(allocation["candidates"])


def active_algorithm_portfolio() -> dict[str, float]:
    payload = get_active_control()
    if payload is None:
        return {}
    portfolio = payload["decision"].get("algorithm_portfolio", {})
    return {str(key): float(value) for key, value in portfolio.items()}


def active_arena_limit(configured_limit: int) -> int:
    payload = get_active_control()
    if payload is None:
        return configured_limit
    allocation = payload["decision"]["authorized_allocation"]
    return min(configured_limit, int(allocation["arena_repetitions"]))


def should_skip_cycle() -> tuple[bool, str]:
    payload = get_active_control()
    if payload is None:
        return False, "no_authorized_metacognitive_skip"
    action = str(payload["decision"].get("recommendation", ""))
    if action in {"abstain", "terminate", "research"}:
        return True, f"metacognitive_{action}"
    return False, "authorized_control_requires_cycle"
