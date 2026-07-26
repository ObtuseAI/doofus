# Doofus SOTA Validation Checklist (45–60 min)

Run after implementing SOTA recursive evolution platform.

## Pre-flight

- [ ] `pip install -e ".[dev]"` from `C:\sai-auth-doofus`
- [ ] `python scripts/doofus_install_evolution_env.py` (installs meta env vars)
- [ ] `CONTROL/DOOFUS_RUN.enabled` exists
- [ ] Dashboard on `http://127.0.0.1:8766`

## Unit tests

```powershell
cd C:\sai-auth-doofus
python -m pytest tests/test_agent_arcade_adapter.py tests/test_map_elites_archive.py tests/test_gepa_trace_collector.py tests/test_gep_schema.py tests/test_aevolve_registry.py tests/test_codeevolve_sandbox.py tests/test_recursive_supervisor.py tests/test_doofus_sota_dashboard.py tests/test_doofus_compound_acceleration.py -q
```

## 45–60 min live validation

1. Start supervisor: `python -m doofus.supervisor.doofus_24_7_supervisor --max-cycles 8`
2. Confirm logs show `DOOFUS_CYCLE_COMPLETE` with 8–24 candidates/cycle
3. Dashboard **Meta Evolution** tab shows:
   - `map_elites.cell_count` > 0 after ~5 cycles
   - `gepa.mutation_versions` ≥ 0 (GEPA batch after 5 cycles if traces accumulate)
   - `gep.capsule_count` increases on promotions
   - `aevolve.stats` records algorithm trials
4. Dashboard **Arenas** tab shows `arena_avg_scores` (not just counts)
5. SQLite `arena_results` has `score`, `steps`, `trace_ref` populated
6. No safety events for forbidden traits
7. `runtime/state/meta_evolution_state.json` increments `cycle_count`

## Pipeline health

- [ ] `runtime/logs/pipeline.log` has no repeated errors during run
- [ ] Partial cycles (`DOOFUS_CYCLE_PARTIAL`) only when run switch flipped mid-cycle
- [ ] Generation increments without duplicates after simulated restart (checkpoint at cycle start)

- Real/trait-sensitive arena scores (not identical hash jitter for all candidates)
- MAP-Elites occupancy > 0 within 20 cycles
- GEP events in `runtime/state/gep/events.jsonl`
- Meta supervisor runs GEPA/MAP maintenance on schedule
- Zero regressions in compound acceleration tests
