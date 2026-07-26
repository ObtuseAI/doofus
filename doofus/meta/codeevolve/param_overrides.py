"""Runtime parameter overrides applied by CodeEvolve (safe — no source mutation)."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.core.doofus_paths import STATE

OVERRIDES_FILE = STATE / "codeevolve" / "overrides.json"

DEFAULT_SCORE_WEIGHTS = {
    "safety": 0.25,
    "replay": 0.20,
    "generalization": 0.15,
    "compounding": 0.15,
    "recursive_learning": 0.15,
    "proof": 0.10,
}

_OVERRIDES_CACHE: tuple[float | None, dict] | None = None


def load_overrides() -> dict:
    global _OVERRIDES_CACHE
    if not OVERRIDES_FILE.exists():
        _OVERRIDES_CACHE = None
        return {}
    try:
        mtime = OVERRIDES_FILE.stat().st_mtime
        if _OVERRIDES_CACHE and _OVERRIDES_CACHE[0] == mtime:
            return dict(_OVERRIDES_CACHE[1])
        data = json.loads(OVERRIDES_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            _OVERRIDES_CACHE = (mtime, dict(data))
            return data
        _OVERRIDES_CACHE = (mtime, {})
        return {}
    except Exception:
        _OVERRIDES_CACHE = None
        return {}


def load_score_weights(defaults: dict | None = None) -> dict:
    base = dict(defaults or DEFAULT_SCORE_WEIGHTS)
    ov = load_overrides().get("score_weights") or {}
    base.update({k: float(v) for k, v in ov.items() if k in base})
    total = sum(base.values())
    if total > 0 and abs(total - 1.0) > 0.01:
        base = {k: v / total for k, v in base.items()}
    return base


def load_promotion_threshold(*, default: float = 0.72) -> float:
    ov = load_overrides().get("promotion_threshold")
    if ov is None:
        return float(default)
    try:
        return max(0.5, min(0.95, float(ov)))
    except (TypeError, ValueError):
        return float(default)


def save_promotion_threshold(threshold: float, *, fitness: float, target_id: str) -> dict:
    OVERRIDES_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = load_overrides()
    data["promotion_threshold"] = max(0.5, min(0.95, float(threshold)))
    data["last_apply"] = {"fitness": fitness, "target_id": target_id}
    OVERRIDES_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    global _OVERRIDES_CACHE
    _OVERRIDES_CACHE = None
    return data


def save_score_weights(weights: dict, *, fitness: float, target_id: str) -> dict:
    OVERRIDES_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = load_overrides()
    data["score_weights"] = weights
    data["last_apply"] = {"fitness": fitness, "target_id": target_id}
    OVERRIDES_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    global _OVERRIDES_CACHE
    _OVERRIDES_CACHE = None
    return data
