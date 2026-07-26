# Held-out benchmark suite

Doofus claims self-improvement across GEPA prompt evolution, the MAP-Elites
archive, the A-Evolve bandit, CodeEvolve policy tuning, and the metacognitive
cortex. Those loops score candidates with *self-reported* fitness. A held-out
benchmark exists so those claims carry independent, verifiable evidence: a
fixed, versioned set of tasks the evolution loops never see during
optimization.

- Suite version: **1.0.0** (`doofus.benchmarks.SUITE_VERSION`)
- Runner: `python -m doofus.benchmarks [--out PATH] [--engine-ref REF]`
- Deterministic, no network, no API keys.

## Task inventory

| Family | Task id | What it measures |
| --- | --- | --- |
| optimization | `opt_sphere_2d` | Black-box min of a sealed-shift sphere (2-D) |
| optimization | `opt_sphere_5d` | Black-box min of a sealed-shift sphere (5-D) |
| optimization | `opt_rastrigin_2d` | Black-box min of a sealed-shift Rastrigin (2-D) |
| code_repair | `repair_median` | Repair median-of-list; hidden unsorted inputs |
| code_repair | `repair_word_count` | Repair whitespace tokenisation; hidden tabs/newlines |
| code_repair | `repair_clamp` | Repair upper-bound clamping; hidden over-range inputs |
| calibration | `calib_ledger_v1` | Score a prediction ledger vs. sealed outcomes |

Public task inputs live in `doofus/benchmarks/tasks/`. The engine may see these.

### Scoring

- **optimization** — a candidate supplies a `solver(objective, dim, bounds,
  budget, rng)` callable. The harness hands it a black-box objective (a closure
  over the sealed optimum) and scores the returned point by `exp(-best_f)`
  (global minimum value `0.0` → score `1.0`). The solver only ever sees
  objective values, never the optimum. Baseline solver = seeded random search.
- **code_repair** — a candidate supplies replacement source per task id. The
  harness executes it in a restricted namespace and runs hidden tests; score =
  fraction passed. Baseline candidate = the shipped buggy source (passes the
  visible public tests, fails hidden edge cases).
- **calibration** — reuses the production
  `doofus.metacognition.calibration.summarize_calibration`. A candidate may
  override the predicted probability per record; score = `1 - brier_score`.
  Baseline = the mildly overconfident predictor shipped in the public task.

The overall score is the weighted mean across all tasks; family scores are the
weighted mean within each family. The report (`SuiteReport`) is timestamped and
machine-readable (JSON).

## Honesty / isolation mechanism

The answers live in `doofus/benchmarks/_sealed/` and are kept away from the
evolution loops by **two independent mechanisms**:

1. **Protected-root containment (the codebase's existing mechanism).** The
   sealed directory is registered in
   `doofus.meta.codeevolve.project_registry._STATIC_PROTECTED_ROOTS`, so
   `is_protected_path(SEALED_DIR)` returns `True`. This is the same guard that
   keeps CodeEvolve out of `C:\sai-auth` and the Doofus runtime root. As a
   result:
   - `validate_project` rejects any project rooted at (or overlapping) the
     sealed dir with reason `protected_root`.
   - `resolve_target_module` rejects any target module resolving into it with
     reason `protected_path`.
   The engine therefore can never register, resolve, read, or mutate an
   evolution target that overlaps the sealed answers.

2. **Hashed answers (defence in depth).** Code-repair hidden expected outputs
   are stored only as SHA-256 digests, never plaintext. Even a candidate that
   somehow read the sealed file cannot echo the answer — it must actually
   compute the result, which the runner hashes and compares.

The runner is the only component that opens the sealed directory, and only at
scoring time (after a candidate already exists). `verify_sealed_isolation()`
returns evidence that the containment holds, and the runner records the result
as `isolation_verified` in every report.

## Baseline

`doofus/benchmarks/baseline/baseline_report.json` is the committed reference
point captured against `master@2535a4a`:

| Metric | Score |
| --- | --- |
| overall | 0.3007 |
| optimization | 0.3611 |
| code_repair | 0.0833 |
| calibration | 0.7712 |

Future self-improvement claims should be substantiated by re-running the suite
against the new engine state and showing a genuine, held-out gain over this
baseline. `test_baseline_report_is_reproducible` guards that the baseline is
deterministically reproducible.

## Evolution-vs-baseline campaign

`python scripts/doofus_evolution_vs_baseline.py --generations 24` exercises the
production registered-target CodeEvolve path against a disposable toy optimizer.
The fitness loop sees only three deterministic training objectives. After the
last generation, the candidate source is hashed and frozen; only then is the
held-out runner imported and executed. The JSON report records training fitness,
the complete evolution ledger, baseline and candidate held-out reports, delta,
isolation status, and a portable `ResearchEvidence` envelope.

This command is the short, reproducible qualification run. A 24–48 hour campaign
uses the same command with an operator-selected generation budget and should
commit its resulting JSON only after reviewing duration, isolation, and the
held-out delta. Duration is evidence, not simulated by the harness.

## Opt-in CI

`.github/workflows/heldout-benchmarks.yml` runs on Windows when a pull request has
the `run-heldout` label or when manually dispatched. It reproduces the committed
baseline, emits a fresh report for the exact commit SHA, and uploads that JSON as
a workflow artifact.

## Regenerating sealed answers

The sealed files are authored artifacts; they contain plaintext optima /
outcomes (isolation-protected) and hashed code-repair outputs. They are not
regenerated at runtime. To rotate the suite, bump `SUITE_VERSION`, add new
tasks, and re-seal — never commit plaintext code-repair expected outputs.
