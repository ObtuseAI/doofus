# -*- coding: utf-8 -*-
"""Runtime heal - clear conflicting switches, repair checkpoint, init DB."""
from __future__ import annotations

import json
import sys

from doofus.core.atomic_json import load_json, save_json
from doofus.core.doofus_state import init_db
from doofus.meta.recursive_supervisor import META_STATE_FILE, _DEFAULT_STATE
from doofus.safety.on_off_switch import start, status
from doofus.supervisor.doofus_crash_recovery import load_checkpoint, save_checkpoint


def heal_checkpoint() -> dict:
    cp = load_checkpoint()
    if cp.get("phase") == "started":
        cp["phase"] = "complete"
        cp["healed"] = True
        save_checkpoint(cp)
        return {"healed": True, "checkpoint": cp}
    return {"healed": False, "checkpoint": cp}


def sync_meta_cycle_count() -> dict:
    """Align meta_evolution_state cycle_count with generation for scheduling."""
    cp = load_checkpoint()
    gen = int(cp.get("generation") or 0)
    data = load_json(META_STATE_FILE, default=dict(_DEFAULT_STATE))
    if not isinstance(data, dict):
        data = dict(_DEFAULT_STATE)
    old = int(data.get("cycle_count") or 0)
    if gen > old:
        data["cycle_count"] = gen
        save_json(META_STATE_FILE, data)
        return {"synced": True, "old_cycle_count": old, "new_cycle_count": gen}
    return {"synced": False, "cycle_count": old, "generation": gen}


def heal_switches(*, force_start: bool = False) -> dict:
    s = status()
    if force_start or (s["run_enabled"] and (s["stop_requested"] or s["emergency_stop"])):
        start()
        s = status()
        return {"action": "cleared_stop_flags", "status": s}
    if not s["run_enabled"] and force_start:
        start()
        return {"action": "enabled_run", "status": status()}
    return {"action": "none", "status": s}


def main() -> int:
    force = "--force-start" in sys.argv
    bootstrap_meta = "--meta-bootstrap" in sys.argv
    init_db()
    results = {
        "switches": heal_switches(force_start=force),
        "checkpoint": heal_checkpoint(),
        "meta_sync": sync_meta_cycle_count(),
        "db": "initialized",
    }
    if bootstrap_meta:
        from doofus.meta.meta_bootstrap import bootstrap_meta as run_meta_bootstrap
        results["meta_bootstrap"] = run_meta_bootstrap(force_gepa=True, run_codeevolve_gen=False)
    print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
