# -*- coding: utf-8 -*-
"""Enable aggressive high-throughput evolution profile (user-scope env)."""
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
    from doofus.config.evolution_runtime_config import DEFAULTS as EVO
    from doofus.config.meta_evolution_config import DEFAULTS as META, apply_defaults as apply_meta
    from doofus.config.proof_builder_runtime_config import DEFAULTS as PB, bootstrap_autonomous_runtime
    from doofus.core.doofus_paths import STATE
    from doofus.evolution.adaptive_mutation_pressure import boost_pressure_level, get_pressure_state
    from doofus.reports.doofus_shared_folder_exporter import export_shared_folder
    from doofus.safety.on_off_switch import clear_emergency, start

    budget = {
        "DOOFUS_MAX_MODEL_CALLS_PER_HOUR": "120",
        "DOOFUS_MAX_DAILY_COST_USD": "15",
        "DOOFUS_MODEL_TEMPERATURE": "0.75",
    }
    merged = {**EVO, **PB, **META, **AGG, **budget}
    for name, value in merged.items():
        _set_user_env(name, value)

    apply_meta(force=True)
    runtime = bootstrap_autonomous_runtime(force=True)
    pressure = boost_pressure_level(level=2.5)
    clear_emergency()
    switch = start()

    STATE.mkdir(parents=True, exist_ok=True)
    marker = STATE / "aggressive_evolution_enabled.json"
    marker.write_text(json.dumps({
        "classification": "DOOFUS_AGGRESSIVE_EVOLUTION_ENABLED",
        "pressure": pressure,
        "candidate_count_next": pressure.get("candidate_count_next"),
        "run_switch": switch,
        "profile": AGG,
    }, indent=2), encoding="utf-8")

    export_shared_folder()
    print(json.dumps({
        "classification": "DOOFUS_AGGRESSIVE_EVOLUTION_ENABLED",
        "run_switch": switch,
        "pressure": pressure,
        "highlights": {
            "base_candidates": merged["DOOFUS_BASE_CANDIDATES_PER_CYCLE"],
            "max_candidates": merged["DOOFUS_MAX_CANDIDATES_PER_CYCLE"],
            "capsule_injection": merged["DOOFUS_CAPSULE_INJECTION_RATE"],
            "gepa_every": merged["DOOFUS_GEPA_BATCH_EVERY"],
            "cycle_sleep_s": merged["DOOFUS_CYCLE_SLEEP_SECONDS"],
            "max_calls_per_hour": budget["DOOFUS_MAX_MODEL_CALLS_PER_HOUR"],
        },
        "runtime": runtime,
        "marker": str(marker),
        "note": "Restart supervisor to pick up user env in scheduled task processes.",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
