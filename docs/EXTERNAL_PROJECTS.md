# Evolving external projects with Doofus

Doofus's CodeEvolve loop can optimize **any codebase on this machine**, not just
itself. You declare *what may change* (numeric params in specific modules) and
*what "better" means* (a fitness command); Doofus hill-climbs the params with
snapshot/rollback safety.

## 1. The fitness contract

Doofus runs your command in the project root with `shell=False`:

- **Exit code 0** = the project is healthy (fitness `1.0` unless a score is printed).
- **Last stdout line parses as a float in `[0, 1]`** = fine-grained fitness.
  Higher is better. Anything else on the last line → plain pass/fail.
- Non-zero exit = fitness `0.0`; the candidate is rejected and rolled back.
- Timeout (default 300 s, clamp 10–1800 via `fitness_timeout_seconds`) = rejected.
- `DOOFUS_*` env vars and provider API keys are **stripped** from the subprocess.

Examples:

| Project type | Fitness command |
|---|---|
| pytest suite | `python -m pytest -q` |
| pytest + score | `python scripts/bench.py` (prints e.g. `0.87` last) |
| Node | `npm test --silent` |
| Arbitrary benchmark | any script that exits 0 and prints a 0–1 score |

A good score line compresses what you care about: accuracy, latency budget,
win-rate — anything, as long as higher = better and it's reproducible.

## 2. Register and run

```powershell
python scripts\doofus_register_project.py --add --id myproj --root C:\path\to\proj `
    --fitness "python -m pytest -q" `
    --target "src\config.py:LEARNING_RATE:optimizer LR" `
    --target "src\config.py:BATCH_SIZE:training batch"
python scripts\doofus_register_project.py --enable myproj

# Measure first (no writes) — sanity-check the fitness signal:
python scripts\doofus_evolve_project.py myproj --generations 2 --measure-only

# Then let it optimize:
python scripts\doofus_evolve_project.py myproj --generations 10 --apply
```

Target spec is `module[:param_key[:description]]`, module path relative to the
project root. The param must be a top-level `NAME = <number>` assignment on its
own line (an inline `# comment` is fine).

## 3. What the optimizer does

Per generation and target:

1. Snapshot the module into `runtime/state/codeevolve/projects/<id>/`.
2. Perturb the param by `direction × step` (step starts at 5%).
3. Re-run fitness. **Accept** (fitness didn't drop) → keep the change, grow step
   ×1.3 (cap ±25%). **Reject** → restore the snapshot, flip direction; two
   consecutive rejections halve the step (floor 0.5%).
4. Persist optimizer state (`evolve_state.json`): step, direction, best-ever
   fitness and value, capped history — repeated runs resume, not restart.

Integers move by whole steps (minimum 1). Results also land in the shared
`codeevolve_generations` metrics table, so dashboard KPI queries see them.

## 4. Safety model

- **Measure-only by default.** Writes require `--apply` on the one-shot runner,
  or (in the 24/7 loop) the project's `auto_apply` flag **and**
  `DOOFUS_CODEEVOLVE_AUTO_APPLY=1` **and** `DOOFUS_EXTERNAL_TARGETS_MODE=1`.
- **Containment.** Target modules must resolve inside the declared project root;
  `..` escapes and symlink escapes are rejected at resolution time.
- **Protected roots.** Operator-protected paths and Doofus's own workspace can
  never be registered as external projects.
- **Every rejected candidate is rolled back** from its snapshot; accepted ones
  keep the snapshot for manual rollback.
- The registry (`runtime/state/codeevolve/projects.json`) is machine-local and
  gitignored — commit your *project's* accepted param changes from the project's
  own repo, where its tests already passed.

## 5. Troubleshooting

- `EVOLVE_PROJECT_NO_TARGETS` — project unregistered, disabled, or its target
  modules didn't resolve (check `--list`, path spelling, protected roots).
- `EXTERNAL_FITNESS_ERROR: root_missing` — the declared root doesn't exist.
- `mutation_skipped:param_not_found` — the param isn't a simple top-level
  numeric assignment.
- Fitness always `1.0`/`0.0` — your command isn't printing a score line; that's
  fine for pass/fail gates but gives the climber no gradient. Print a score.
- Everything rejected — your fitness may be noisy; make the command
  deterministic (fixed seeds, no network) or coarsen to pass/fail.
