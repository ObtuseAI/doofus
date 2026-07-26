"""Evolvable target module registry (builtin self-targets + external projects)."""
from __future__ import annotations

from pathlib import Path

from doofus.core.doofus_paths import ROOT

TARGETS = [
    {
        "id": "score_engine_weights",
        "project_id": "doofus",
        "module_path": ROOT / "doofus" / "scoring" / "score_engine.py",
        "param_key": "WEIGHTS",
        "description": "Score component weights",
        "source": "builtin",
    },
    {
        "id": "promotion_threshold",
        "project_id": "doofus",
        "module_path": ROOT / "doofus" / "scoring" / "promotion_gate.py",
        "param_key": "PROMOTION_THRESHOLD",
        "description": "Full promotion score threshold",
        "source": "builtin",
    },
    {
        "id": "evolution_pressure",
        "project_id": "doofus",
        "module_path": ROOT / "doofus" / "config" / "evolution_runtime_config.py",
        "param_key": "DOOFUS_BASE_CANDIDATES_PER_CYCLE",
        "description": "Base candidates per cycle",
        "source": "builtin",
    },
]

FORBIDDEN_MODULES = {
    "on_off_switch", "budget_guard", "doofus_safety_gate", "secret_guard",
}


def _merged_targets(include_external: bool | None = None) -> list[dict]:
    targets = [t for t in TARGETS if is_allowed(t["module_path"])]
    if include_external is None:
        from doofus.config.meta_evolution_config import external_targets_enabled
        include_external = external_targets_enabled()
    if include_external:
        from doofus.meta.codeevolve.project_registry import external_targets
        targets.extend(external_targets())
    return targets


def get_target(index: int = 0, *, include_external: bool | None = None) -> dict:
    targets = _merged_targets(include_external)
    return targets[index % len(targets)]


def is_allowed(path: Path) -> bool:
    name = path.stem
    return name not in FORBIDDEN_MODULES


def list_targets(*, include_external: bool | None = None) -> list[dict]:
    return _merged_targets(include_external)
