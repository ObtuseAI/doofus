# -*- coding: utf-8 -*-
"""Enable Cursor Composer 2.5 as Doofus mutation provider."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _set_user_env(name: str, value: str) -> None:
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"[Environment]::SetEnvironmentVariable('{name}', $env:DOOFUS_VAL_SYNC, 'User')"],
        env={**os.environ, "DOOFUS_VAL_SYNC": value},
        check=True,
    )
    os.environ[name] = value


def main() -> int:
    from doofus.config.aggressive_evolution_config import DEFAULTS as AGG
    from doofus.config.cursor_composer_config import DEFAULTS as CUR, apply_defaults, runtime_snapshot
    from doofus.config.evolution_runtime_config import DEFAULTS as EVO
    from doofus.config.meta_evolution_config import DEFAULTS as META, apply_defaults as apply_meta
    from doofus.config.proof_builder_runtime_config import DEFAULTS as PB, bootstrap_autonomous_runtime
    from doofus.core.doofus_paths import STATE
    from doofus.evolution.adaptive_mutation_pressure import boost_pressure_level
    from doofus.meta.aevolve.algorithm_registry import apply_env_weight_overrides, get_algorithm
    from doofus.reports.doofus_shared_folder_exporter import export_shared_folder
    from doofus.safety.on_off_switch import clear_emergency, start

    merged = {**EVO, **PB, **META, **AGG, **CUR}
    for name, value in merged.items():
        _set_user_env(name, value)

    apply_defaults(force=True)
    apply_meta(force=True)
    runtime = bootstrap_autonomous_runtime(force=True)
    weights = apply_env_weight_overrides()
    pressure = boost_pressure_level(level=3.0)
    clear_emergency()
    switch = start()

    STATE.mkdir(parents=True, exist_ok=True)
    marker = STATE / "cursor_composer_enabled.json"
    snapshot = runtime_snapshot()
    marker.write_text(json.dumps({
        "classification": "DOOFUS_CURSOR_COMPOSER_ENABLED",
        "model": snapshot.get("DOOFUS_CURSOR_MODEL", "composer-2.5"),
        "cursor_api_key_present": snapshot.get("cursor_api_key_present"),
        "pressure": pressure,
        "model_guided_weight": (get_algorithm("model_guided") or {}).get("weight"),
        "weights_applied": weights,
        "run_switch": switch,
    }, indent=2), encoding="utf-8")

    export_shared_folder()
    print(json.dumps({
        "classification": "DOOFUS_CURSOR_COMPOSER_ENABLED",
        "model": snapshot.get("DOOFUS_CURSOR_MODEL"),
        "cursor_api_key_present": snapshot.get("cursor_api_key_present"),
        "mutation_batch": snapshot.get("DOOFUS_CURSOR_MUTATION_BATCH"),
        "hybrid_fallback": snapshot.get("DOOFUS_CURSOR_HYBRID_FALLBACK"),
        "run_switch": switch,
        "pressure": pressure,
        "model_guided_weight": weights.get("model_guided"),
        "runtime": runtime,
        "marker": str(marker),
        "note": "Run once: agent login (uses local CLI, no Cloud API key). Or set CURSOR_API_KEY. Restart supervisor.",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
