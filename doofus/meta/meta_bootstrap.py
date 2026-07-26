# -*- coding: utf-8 -*-
"""Bootstrap meta-evolution subsystems (GEPA, MAP-Elites, CodeEvolve catch-up)."""
from __future__ import annotations

from doofus.config.meta_evolution_config import apply_defaults
from doofus.config.proof_builder_runtime_config import bootstrap_autonomous_runtime
from doofus.core.atomic_json import save_json
from doofus.core.doofus_state import init_db
from doofus.evolution.map_elites_archive import maintain as maintain_map_elites
from doofus.meta.codeevolve.openevolve_adapter import run_generation as run_codeevolve
from doofus.meta.gepa.prompt_evolver import run_batch as run_gepa_batch
from doofus.meta.recursive_supervisor import META_STATE_FILE, load_meta_state


def bootstrap_meta(*, force_gepa: bool = False, run_codeevolve_gen: bool = False) -> dict:
    bootstrap_autonomous_runtime()
    apply_defaults()
    init_db()
    state = load_meta_state()
    results: dict = {"state_before": dict(state)}

    results["gepa"] = run_gepa_batch(force=force_gepa)
    state["last_gepa_cycle"] = state.get("cycle_count", 0)

    results["map_elites"] = maintain_map_elites()
    state["last_map_cycle"] = state.get("cycle_count", 0)

    if run_codeevolve_gen:
        results["codeevolve"] = run_codeevolve(state.get("cycle_count", 0))
        state["last_codeevolve_cycle"] = state.get("cycle_count", 0)
    else:
        results["codeevolve"] = {"classification": "CODEEVOLVE_SKIPPED", "reason": "bootstrap_no_codeevolve"}

    save_json(META_STATE_FILE, state)
    results["state_after"] = state
    results["classification"] = "META_BOOTSTRAP_COMPLETE"
    return results
