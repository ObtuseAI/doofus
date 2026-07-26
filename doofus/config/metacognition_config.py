"""Runtime configuration for the experimental metacognitive evolution layer."""
from __future__ import annotations

import os


DEFAULTS: dict[str, str] = {
    "DOOFUS_METACOGNITION_MODE": "shadow",
    "DOOFUS_METACOGNITION_TARGET_ID": "doofus",
    "DOOFUS_METACOGNITION_CALIBRATION_WINDOW": "200",
    "DOOFUS_METACOGNITION_MIN_ONLINE_SAMPLES": "8",
    "DOOFUS_METACOGNITION_MAX_CANDIDATES": "48",
    "DOOFUS_METACOGNITION_MIN_CANDIDATES": "8",
    "DOOFUS_METACOGNITION_MAX_ARENA_REPETITIONS": "4",
    "DOOFUS_METACOGNITION_MAX_REPLAY_DEPTH": "5",
    "DOOFUS_METACOGNITION_POLICY_VERSION": "metacognitive_cortex_v1",
}

VALID_MODES = frozenset({"off", "shadow", "advisory", "bounded"})


def apply_defaults(*, force: bool = False) -> dict[str, str]:
    applied: dict[str, str] = {}
    for key, value in DEFAULTS.items():
        if force or key not in os.environ:
            os.environ[key] = value
            applied[key] = value
    return applied


def metacognition_mode() -> str:
    mode = os.environ.get("DOOFUS_METACOGNITION_MODE", DEFAULTS["DOOFUS_METACOGNITION_MODE"]).strip().lower()
    if mode not in VALID_MODES:
        raise ValueError(
            "DOOFUS_METACOGNITION_MODE must be one of "
            f"{sorted(VALID_MODES)}, received {mode!r}"
        )
    return mode


def metacognition_enabled() -> bool:
    return metacognition_mode() != "off"


def bounded_control_enabled() -> bool:
    return metacognition_mode() == "bounded"


def int_setting(key: str) -> int:
    if key not in DEFAULTS:
        raise KeyError(f"Unknown metacognition integer setting: {key}")
    return int(os.environ.get(key, DEFAULTS[key]))


def target_id() -> str:
    value = os.environ.get("DOOFUS_METACOGNITION_TARGET_ID", DEFAULTS["DOOFUS_METACOGNITION_TARGET_ID"]).strip()
    if not value:
        raise ValueError("DOOFUS_METACOGNITION_TARGET_ID must not be empty")
    return value


def policy_version() -> str:
    return os.environ.get(
        "DOOFUS_METACOGNITION_POLICY_VERSION",
        DEFAULTS["DOOFUS_METACOGNITION_POLICY_VERSION"],
    ).strip()


def runtime_snapshot() -> dict[str, str]:
    return {key: os.environ.get(key, value) for key, value in DEFAULTS.items()}
